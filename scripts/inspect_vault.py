#!/usr/bin/env python
"""Read an existing vault and work out how it is already organised.

Setup used to assume a fresh vault. That is the wrong default — most people who
want this already keep notes, and several will have run an earlier version of it.
Proposing a fresh topic taxonomy over an organised vault silently reorganises
every note the next time merge runs: the old hubs are deleted, new ones appear,
and every note's `Up:` line is rewritten. Nothing is lost, but nobody asked for it.

So before proposing anything, look. This reports what the vault already contains
and derives a `topics` array from the notes themselves, then **simulates that
array against the real notes and reports exactly how much of the current grouping
it reproduces**. A derivation that claims to preserve your organisation without
checking is just a different way of guessing.

    python inspect_vault.py <vault-path> [--json]
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as cfg  # noqa: E402

FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)
UP = re.compile(r"^Up: (.+)$", re.M)
WIKI = re.compile(r"\[\[([^\]|#]+)\]\]")

# A tag or type has to be this dominant within a hub before it is treated as the
# rule that puts notes there. Lower and unrelated notes get dragged in; higher and
# almost nothing qualifies, so everything collapses into the fallback.
DOMINANCE = 0.8


def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def read_notes(vault_path, folders):
    """Every note we manage, with its type, tags and the hubs it currently sits in."""
    notes = []
    derived = {folders[k] for k in ("topics", "people", "orgs", "sources", "meta",
                                    "unsorted") if k in folders}
    for p in sorted(Path(vault_path).rglob("*.md")):
        if ".obsidian" in p.parts or p.parent == Path(vault_path):
            continue
        if any(part in derived for part in p.parts):
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        m = FM.match(txt)
        if not m:
            continue
        fm = {}
        for line in m.group(1).split("\n"):
            if ": " in line:
                k, v = line.split(": ", 1)
                fm[k.strip()] = unquote(v)
        if not (fm.get("source_session") or fm.get("source_doc")):
            continue                       # the user's own note, not ours
        up = UP.search(txt)
        hubs = [h.strip() for h in WIKI.findall(up.group(1))] if up else []
        notes.append({
            "title": fm.get("title", p.stem),
            "type": fm.get("type", "insight"),
            "tags": sorted(set(re.findall(r"[\w.&-]+", fm.get("tags", "")))),
            "hubs": hubs,
        })
    return notes


def derive_topics(notes, existing_hubs):
    """Turn observed grouping back into rules that would reproduce it."""
    by_hub = defaultdict(list)
    for n in notes:
        for h in n["hubs"]:
            by_hub[h].append(n)

    type_total, tag_total = Counter(), Counter()
    for n in notes:
        type_total[n["type"]] += 1
        for t in n["tags"]:
            tag_total[t] += 1

    hubs = [h for h in existing_hubs if h in by_hub] or list(by_hub)
    # The fallback is the hub that most often carries a note on its own.
    solo = Counter(n["hubs"][0] for n in notes if len(n["hubs"]) == 1)
    fallback = solo.most_common(1)[0][0] if solo else (hubs[-1] if hubs else None)

    claimed_fallback_types = set()
    topics = []
    for h in hubs:
        members = by_hub[h]
        mt, mtag = Counter(), Counter()
        for n in members:
            mt[n["type"]] += 1
            for t in n["tags"]:
                mtag[t] += 1
        types = sorted(ty for ty, c in mt.items()
                       if type_total[ty] and c / type_total[ty] >= DOMINANCE)
        tags = sorted(t for t, c in mtag.items()
                      if tag_total[t] >= 2 and c / tag_total[t] >= DOMINANCE)
        entry = {"title": h, "types": types, "tags": tags}
        if h == fallback:
            entry = {"title": h, "types": types, "tags": tags, "fallback": True}
        topics.append(entry)

    # A type that lands almost entirely in one hub but is not dominant enough to be
    # an unconditional match is a fallback_types candidate — it gives the type a home
    # without dragging every note of that type into that hub.
    for entry in topics:
        if entry.get("fallback"):
            continue
        members = by_hub[entry["title"]]
        mt = Counter(n["type"] for n in members)
        extra = []
        for ty, c in mt.items():
            if ty in entry["types"] or ty in claimed_fallback_types:
                continue
            if type_total[ty] and 0.5 <= c / type_total[ty] < DOMINANCE:
                extra.append(ty)
                claimed_fallback_types.add(ty)
        if extra:
            entry["fallback_types"] = sorted(extra)
    return topics


def simulate(notes, topics, folders):
    """Would these rules actually reproduce the grouping? Check, do not assume."""
    vault = cfg.Vault({"id": "sim", "path": "/", "topics": topics}, folders)
    same = 0
    moved = []
    for n in notes:
        got = vault.topics_for(n["type"], n["tags"])
        if set(got) == set(n["hubs"]):
            same += 1
        else:
            moved.append({"title": n["title"], "from": n["hubs"], "to": got})
    pct = round(100.0 * same / len(notes), 1) if notes else 100.0
    return {"reproduced": same, "total": len(notes), "percent": pct, "moved": moved}


def inspect(vault_path, folders=None):
    folders = folders or cfg.DEFAULT_FOLDERS
    vp = Path(vault_path).expanduser()
    topics_dir = vp / folders["topics"]
    existing_hubs = sorted(p.stem for p in topics_dir.glob("*.md")) \
        if topics_dir.is_dir() else []
    notes = read_notes(vp, folders)
    out = {
        "path": str(vp),
        "exists": vp.is_dir(),
        "populated": bool(notes),
        "note_count": len(notes),
        "existing_hubs": existing_hubs,
        "types": dict(Counter(n["type"] for n in notes)),
        "top_tags": Counter(t for n in notes for t in n["tags"]).most_common(15),
    }
    if notes:
        topics = derive_topics(notes, existing_hubs)
        out["derived_topics"] = topics
        out["reproduction"] = simulate(notes, topics, folders)
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: inspect_vault.py <vault-path> [--json]")
        return 2
    res = inspect(args[0])
    if "--json" in sys.argv:
        json.dump(res, sys.stdout, indent=1, ensure_ascii=False)
        print()
        return 0

    if not res["exists"]:
        print("No vault at %s" % res["path"])
        return 1
    if not res["populated"]:
        print("Vault at %s has no notes from this plugin yet." % res["path"])
        print("Safe to propose a fresh topic taxonomy.")
        return 0

    print("Vault: %s" % res["path"])
    print("  %d note(s) already captured — this vault is ALREADY ORGANISED." % res["note_count"])
    print("  Existing hubs: %s" % ", ".join(res["existing_hubs"]))
    print()
    rep = res["reproduction"]
    print("  Rules derived from those notes reproduce %s%% of the current grouping "
          "(%d/%d)." % (rep["percent"], rep["reproduced"], rep["total"]))
    if rep["moved"]:
        print("  %d note(s) would still shift:" % len(rep["moved"]))
        for m in rep["moved"][:8]:
            print("    - %s" % m["title"][:60])
            print("        now: %s" % ", ".join(m["from"] or ["(none)"]))
            print("        new: %s" % ", ".join(m["to"] or ["(none)"]))
        if len(rep["moved"]) > 8:
            print("    ... and %d more" % (len(rep["moved"]) - 8))
    print()
    print("  Proposing a different taxonomy would delete every hub above and rewrite")
    print("  every note's `Up:` line on the next sync. Ask before doing that.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
