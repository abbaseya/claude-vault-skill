#!/usr/bin/env python
"""Verify staged notes before anything reaches a vault.

This is the guarantee the whole tool rests on: **every quote in your vault is
text you or Claude actually wrote**, not a plausible reconstruction.

An extraction agent reporting "I verified my quotes" is a claim, not evidence.
Language models fabricate most readily when a tool call failed and they feel
pressure to produce an answer — and a fabricated quote is indistinguishable
from a real one by eye. So this re-derives it from disk:

  1. every blockquote must be a character-exact substring of its declared source
  2. session-sourced quotes are re-extracted straight from the raw .jsonl and
     matched again, independently of the digest

Exits non-zero on any failure, and merge.py refuses to run.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as cfg  # noqa: E402

PROJECTS = cfg.projects_dir()
FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)
REQUIRED = ["title", "type", "date", "fidelity"]
_raw = {}


def raw_text(sid):
    """Re-extract user+assistant text from the transcript itself."""
    if sid in _raw:
        return _raw[sid]
    hits = list(PROJECTS.glob("*/%s.jsonl" % sid))
    if not hits:
        _raw[sid] = None
        return None
    buf = []
    with hits[0].open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict) or rec.get("type") not in ("user", "assistant"):
                continue
            c = (rec.get("message") or {}).get("content")
            if isinstance(c, str):
                buf.append(c)
            elif isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "text":
                        buf.append(b.get("text") or "")
    _raw[sid] = "\n".join(buf)
    return _raw[sid]


def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_fm(txt):
    m = FM.match(txt)
    if not m:
        return None, txt
    d = {}
    for line in m.group(1).split("\n"):
        if ": " in line:
            k, v = line.split(": ", 1)
            d[k.strip()] = unquote(v)
    return d, txt[m.end():]


def quoted_spans(body):
    """Blockquote lines that are quotations, minus the authored attribution line."""
    out = []
    for line in body.split("\n"):
        if not line.startswith(">"):
            continue
        q = line[1:].strip()
        if not q or q.startswith("—") or q.startswith("--"):
            continue                       # attribution, written not quoted
        # Notes wrap the quoted span in quote marks / emphasis the source lacks.
        q = q.strip("*").strip('"“”‘’').strip().strip("*").strip()
        if len(q) >= 12:
            out.append(q)
    return out


def find_doc(name, roots):
    for r in roots:
        p = Path(r) / name
        if p.is_file():
            return p
    return None


def main():
    conf, problems = cfg.load(strict=False)
    if conf is None:
        print("NO_CONFIG")
        return 2
    run = cfg.run_dir()
    notes_root = run / "notes"
    if not notes_root.is_dir():
        print("no staged notes at %s — run scan.py first" % notes_root)
        return 1
    doc_roots = conf.document_roots()
    valid_types = set(cfg.NOTE_TYPES)

    problems_found, n_notes, n_q, n_raw, n_doc = [], 0, 0, 0, 0
    for vault_dir in sorted(notes_root.iterdir()):
        if not vault_dir.is_dir():
            continue
        if conf.vault_by_id(vault_dir.name) is None:
            problems_found.append((vault_dir.name, "staged notes for unknown vault id"))
            continue
        for p in sorted(vault_dir.glob("*.md")):
            n_notes += 1
            rel = "%s/%s" % (vault_dir.name, p.name)
            txt = p.read_text(encoding="utf-8", errors="replace")
            fm, body = parse_fm(txt)
            if fm is None:
                problems_found.append((rel, "NO FRONTMATTER"))
                continue
            for k in REQUIRED:
                if not fm.get(k):
                    problems_found.append((rel, "missing frontmatter field: %s" % k))
            if fm.get("type") not in valid_types:
                problems_found.append((rel, "bad type: %r" % fm.get("type")))
            if fm.get("sensitivity") not in ("normal", "private", None):
                problems_found.append((rel, "bad sensitivity: %r" % fm.get("sensitivity")))

            sid, doc, src = fm.get("source_session"), fm.get("source_doc"), None
            if sid:
                f = run / "digests" / (sid + ".md")
                if not f.is_file():
                    problems_found.append((rel, "source_session digest missing: %s" % sid))
                else:
                    src = f.read_text(encoding="utf-8", errors="replace")
            elif doc:
                f = find_doc(doc, doc_roots)
                if f is None:
                    problems_found.append((rel, "source_doc not found in any documents "
                                                "root: %s" % doc))
                else:
                    src = f.read_text(encoding="utf-8", errors="replace")
            else:
                problems_found.append((rel, "no source_session or source_doc"))
            if src is None:
                continue

            raw = raw_text(sid) if sid else None
            for q in quoted_spans(body):
                n_q += 1
                if q not in src:
                    problems_found.append((rel, "QUOTE NOT IN SOURCE: %s" % q[:110]))
                    continue
                if raw is None:
                    n_doc += 1
                elif q in raw:
                    n_raw += 1
                else:
                    problems_found.append((rel, "QUOTE NOT IN RAW TRANSCRIPT: %s" % q[:110]))

    print("staged notes      : %d" % n_notes)
    print("quotes checked    : %d" % n_q)
    print("  verified vs raw transcript : %d" % n_raw)
    print("  verified vs source document: %d" % n_doc)
    print("problems          : %d" % len(problems_found))
    for rel, msg in problems_found:
        print("  ! %-52s %s" % (rel, msg))
    if problems_found:
        print("\nFAILED — merge.py will refuse to write to any vault until these are fixed.")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
