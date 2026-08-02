#!/usr/bin/env python
"""Merge verified notes into your vaults and regenerate everything derived.

Runs verify.py first and refuses to touch a vault if it fails.

  Source of truth : the atomic notes themselves.
  Regenerated     : topic hubs, entity notes, source provenance, index, Home.
  Never touched   : notes already in the vault (including ones you moved or
                    edited by hand), the inbox, and any note without our
                    frontmatter. Your own writing is yours.

New notes are placed by sensitivity. A staged note whose filename already
exists anywhere in the vault is skipped rather than overwritten.
"""
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as cfg  # noqa: E402

FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)
WIKI = re.compile(r"\[\[([^\]|#]+)")
UP = re.compile(r"\n+Up: \[\[.*?\]\](?:, \[\[.*?\]\])*\s*\Z", re.S)

# Folders whose entire contents this script owns and regenerates. Anything not
# re-emitted in a run is deleted from them. `meta` and the note folders are
# excluded on purpose — users keep their own files there.
PRUNED_FOLDERS = ("topics", "people", "orgs", "unsorted", "sources")


def unquote(v):
    """A YAML value containing a colon is legally quoted. Strip the wrapper —
    leaving it in mangles filenames, because " is also an illegal path char."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def safe_name(t, limit=70):
    t = re.sub(r'[/\\:*?"<>|]', "-", unquote(str(t)))
    t = re.sub(r"-{2,}", "-", t).strip(" -")
    return t[:limit].strip(" -") or "Untitled"


def parse(p):
    t = p.read_text(encoding="utf-8", errors="replace")
    m = FM.match(t)
    if not m:
        return None, t
    d = {}
    for line in m.group(1).split("\n"):
        if ": " in line:
            k, v = line.split(": ", 1)
            d[k.strip()] = unquote(v)
    return d, t


def content_notes(vault):
    """Atomic notes anywhere in the vault except the folders we regenerate."""
    derived = {vault.folders[k] for k in ("topics", "people", "orgs", "sources",
                                          "meta", "unsorted") if k in vault.folders}
    for p in sorted(vault.path.rglob("*.md")):
        if ".obsidian" in p.parts or p.parent == vault.path:
            continue
        if any(part in derived for part in p.parts):
            continue
        yield p


def main():
    conf, problems = cfg.load(strict=True)
    if conf is None:
        print("NO_CONFIG / INVALID CONFIG")
        for p in problems:
            print("  %s" % p)
        return 2

    here = Path(__file__).resolve().parent
    rc = subprocess.call([sys.executable, str(here / "verify.py")])
    if rc != 0:
        print("\nAborted: verification failed. Nothing was written to any vault.")
        return rc

    run = cfg.run_dir()
    entities = cfg.load_entities()
    report, new_entities = {}, []

    for vault in conf.vaults:
        if not vault.path.is_dir():
            print("skip %s: vault path missing (%s)" % (vault.id, vault.path))
            continue
        for key in vault.folders.values():
            (vault.path / key).mkdir(parents=True, exist_ok=True)

        # ---- place newly staged notes -------------------------------------
        stage = run / "notes" / vault.id
        existing = {p.name for p in vault.path.rglob("*.md")}
        added = 0
        if stage.is_dir():
            for p in sorted(stage.glob("*.md")):
                if p.name in existing:
                    print("  skip (already in vault): %s/%s" % (vault.id, p.name))
                    continue
                fm, txt = parse(p)
                sub = "private" if (fm or {}).get("sensitivity") == "private" else "notes"
                (vault.dir(sub)).mkdir(parents=True, exist_ok=True)
                (vault.dir(sub) / p.name).write_text(txt, encoding="utf-8")
                added += 1

        # ---- read every note, collect what the derived layer needs --------
        topic_members = defaultdict(list)
        sess_members, doc_members = defaultdict(list), defaultdict(list)
        sess_title, sess_date, rows, ents = {}, {}, [], Counter()

        for p in content_notes(vault):
            fm, txt = parse(p)
            if not fm or not (fm.get("source_session") or fm.get("source_doc")):
                continue                       # the user's own note — leave it alone
            tags = set(re.findall(r"[\w.&-]+", fm.get("tags", "")))
            ty = fm.get("type", "insight")
            priv = fm.get("sensitivity") == "private"
            ms = vault.topics_for(ty, tags)
            body = UP.sub("", txt.rstrip())
            if ms:
                body += "\n\nUp: " + ", ".join("[[%s]]" % m for m in ms) + "\n"
            else:
                body += "\n"
            if body != txt:
                p.write_text(body, encoding="utf-8")
            title = fm.get("title", p.stem)
            for m in ms:
                topic_members[m].append((title, ty, priv))
            if fm.get("source_session"):
                sid = fm["source_session"]
                sess_members[sid].append(title)
                sess_title[sid] = fm.get("source_title", "")
                d = fm.get("date", "")
                if d and (sid not in sess_date or d < sess_date[sid]):
                    sess_date[sid] = d
            else:
                doc_members[fm["source_doc"]].append(title)
            for e in WIKI.findall(body):
                ents[e.strip()] += 1
            rows.append((fm.get("date", ""), title, ty,
                         fm.get("sensitivity", "normal"),
                         fm.get("source_title", fm.get("source_doc", ""))))

        titles = {r[1] for r in rows}
        topic_titles = {t.get("title") for t in vault.topics}

        # Reconcile rather than delete-then-recreate. Obsidian watches these
        # folders live; deleting a file it has open makes it fork a "Name 2.md"
        # copy the instant we write the replacement.
        # Seed every purely-derived folder, so one is still reconciled in a round
        # where it happens to receive nothing. Without this an entity reclassified
        # from unknown to person leaves its old copy behind in the unsorted folder
        # forever, and the vault ends up with two notes for one entity.
        #
        # `meta` is deliberately NOT in this list. We emit the index into it, but
        # users keep their own documents there too, and pruning would delete them.
        expected = defaultdict(set)
        for key in PRUNED_FOLDERS:
            expected[key] = set()

        # `vault` and `expected` are bound as defaults rather than closed over.
        # emit is only called inside this iteration today, but a closure over a
        # loop variable is a trap: defer one call and every vault writes to the
        # last one silently.
        def emit(folder_key, name, text, vault=vault, expected=expected):
            d = vault.dir(folder_key)
            d.mkdir(parents=True, exist_ok=True)
            expected[folder_key].add(name + ".md")
            f = d / (name + ".md")
            if not f.is_file() or f.read_text(encoding="utf-8", errors="replace") != text:
                f.write_text(text, encoding="utf-8")

        # ---- entity notes, learned rather than shipped --------------------
        for name, cnt in sorted(ents.items()):
            if name in titles or name in topic_titles:
                continue
            rec = entities.get(name)
            if rec is None:
                rec = {"kind": "unknown", "description": "", "first_seen": vault.id}
                entities[name] = rec
                new_entities.append(name)
            kind = rec.get("kind", "unknown")
            folder = {"person": "people", "org": "orgs"}.get(kind, "unsorted")
            lines = ["---", "title: %s" % name,
                     "type: %s" % ("person" if kind == "person" else
                                   "org" if kind == "org" else "entity"),
                     "tags: [entity, %s]" % kind, "---", ""]
            if rec.get("description"):
                lines += [rec["description"], ""]
            elif kind == "unknown":
                lines += ["_Not yet classified. Ask Claude to classify the entities in "
                          "this vault, or edit `%s`._" % cfg.entities_path(), ""]
            lines += ["Referenced by %d note%s in this vault. Open the backlinks pane "
                      "to see them." % (cnt, "" if cnt == 1 else "s"), ""]
            emit(folder, safe_name(name), "\n".join(lines))

        # ---- topic hubs ---------------------------------------------------
        for m, members in sorted(topic_members.items()):
            members.sort(key=lambda x: x[0])
            lines = ["---", "title: %s" % m, "type: moc", "tags: [moc]", "---", "",
                     "%d note%s.\n" % (len(members), "" if len(members) == 1 else "s")]
            for ty in cfg.NOTE_TYPES:
                grp = [x for x in members if x[1] == ty]
                if grp:
                    lines.append("## %s\n" % ty.title())
                    lines += ["- [[%s]]%s" % (t, "  🔒" if pv else "") for t, _, pv in grp]
                    lines.append("")
            emit("topics", safe_name(m), "\n".join(lines))

        # ---- source provenance -------------------------------------------
        for sid, members in sorted(sess_members.items()):
            safe = safe_name(sess_title.get(sid) or "Untitled session")
            start = sess_date.get(sid, "")
            fn = ("%s — %s" % (start, safe)) if start else safe
            lines = ["---", "title: %s" % fn, "type: source", "tags: [source, session]",
                     "session_id: %s" % sid, "---", "",
                     "Claude Code session. Raw transcript lives under "
                     "`~/.claude/projects/`.", "",
                     "## Notes captured from this session\n"]
            lines += ["- [[%s]]" % x for x in sorted(members)]
            emit("sources", fn, "\n".join(lines) + "\n")

        for doc, members in sorted(doc_members.items()):
            fn = "Doc — %s" % safe_name(str(doc).rsplit(".md", 1)[0])
            lines = ["---", "title: %s" % fn, "type: source", "tags: [source, document]",
                     "source_doc: %s" % doc, "---", "",
                     "Source document: `%s`" % doc, "",
                     "## Notes captured from this document\n"]
            lines += ["- [[%s]]" % x for x in sorted(members)]
            emit("sources", fn, "\n".join(lines) + "\n")

        pruned, dropped_topics = 0, []
        for folder_key, keep in expected.items():
            if folder_key not in PRUNED_FOLDERS:
                continue                       # never prune a folder users write into
            d = vault.dir(folder_key)
            if not d.is_dir():
                continue
            for f in d.glob("*.md"):
                if f.name not in keep:
                    # Losing a topic hub means the config no longer describes how this
                    # vault is organised. Every note that lived under it has been
                    # regrouped. That is legitimate after a deliberate config change and
                    # alarming after an accidental one, and the two look identical in a
                    # summary line — so name them.
                    if folder_key == "topics":
                        dropped_topics.append(f.stem)
                    f.unlink()
                    pruned += 1

        # ---- index + home -------------------------------------------------
        rows.sort()
        idx = ["---", "title: Index — All Notes", "tags: [meta]", "---", "",
               "%d note%s, sorted by date.\n" % (len(rows), "" if len(rows) == 1 else "s"),
               "| date | note | type | sensitivity | source |", "|--|--|--|--|--|"]
        idx += ["| %s | [[%s]] | %s | %s | %s |" %
                (d, t, ty, "🔒 private" if se == "private" else "normal", src)
                for d, t, ty, se, src in rows]
        emit("meta", "Index — All Notes", "\n".join(idx) + "\n")

        home = ["---", "title: Home", "tags: [moc]", "---", "",
                "# %s\n" % vault.name,
                "%d note%s captured from Claude Code sessions and source documents.\n"
                % (len(rows), "" if len(rows) == 1 else "s"),
                "## Topics\n"]
        home += ["- [[%s]]" % m for m in sorted(topic_members)] or ["_No notes yet._"]
        home += ["", "## Reference\n",
                 "- [[Index — All Notes]] — every note in one table", "",
                 "## How this works\n",
                 "- Every note quotes its source **verbatim**. The summary above the "
                 "quote is written; the quote is not.",
                 "- Notes in `%s/` are marked `sensitivity: private`."
                 % vault.folders["private"],
                 "- `%s/` maps each note back to the session or document it came from."
                 % vault.folders["sources"],
                 "- Run `/my-vault:sync` to capture new sessions. Nothing is written "
                 "here on its own.", ""]
        # Home lives at the vault root, outside any reconciled folder.
        (vault.path / "Home.md").write_text("\n".join(home) + "\n", encoding="utf-8")

        dangling = Counter()
        allmd = [q for q in vault.path.rglob("*.md") if ".obsidian" not in q.parts]
        stems = {q.stem for q in allmd}
        for q in allmd:
            for t in WIKI.findall(q.read_text(encoding="utf-8", errors="replace")):
                if t.strip() and t.strip() not in stems:
                    dangling[t.strip()] += 1

        report[vault.id] = {"added": added, "total": len(rows),
                            "topics": len(topic_members), "stale_pruned": pruned,
                            "topics_removed": dropped_topics,
                            "dangling": dict(dangling)}

    cfg.save_entities(entities)

    pend = run / "pending.json"
    if pend.is_file():
        state = cfg.load_state()
        state["processed"].update(json.loads(pend.read_text(encoding="utf-8")))
        state["last_sync"] = max((v for v in state["processed"].values() if v),
                                 default=None)
        cfg.save_state(state)
        print("\nstate: %d session(s) recorded as captured" % len(state["processed"]))

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if new_entities:
        print("\n%d new entit%s discovered and left unclassified:"
              % (len(new_entities), "y" if len(new_entities) == 1 else "ies"))
        for n in new_entities[:20]:
            print("  - %s" % n)
        if len(new_entities) > 20:
            print("  ... and %d more" % (len(new_entities) - 20))
        print("Ask Claude to classify them, or edit %s" % cfg.entities_path())
    for v, r in report.items():
        if r.get("topics_removed"):
            print("\nWARNING  %s: %d topic hub(s) no longer exist in your config and "
                  "were removed:" % (v, len(r["topics_removed"])))
            for t_ in r["topics_removed"]:
                print("           - %s" % t_)
            print("         Every note that lived under them has been regrouped. If you "
                  "did not\n         intend that, restore the topics in "
                  "%s and re-run." % cfg.config_path())
        if r["dangling"]:
            print("WARNING %s has dangling links: %s" % (v, r["dangling"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
