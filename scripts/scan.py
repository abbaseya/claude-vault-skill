#!/usr/bin/env python
"""Find sessions that have not been captured yet, digest them, build a triage sheet.

The transcripts ARE the queue. There is no hook writing to a queue file and no
watermark timestamp to get subtly wrong — state records each session's last
timestamp, so a session that gets resumed and grows is picked up again instead
of being silently skipped.

    python scan.py [--all] [--since YYYY-MM-DD] [--vault <id>]
"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as cfg  # noqa: E402
from digest import digest_session  # noqa: E402

PROJECTS = cfg.projects_dir()

# A hint for triage, never a verdict. Deliberately generic: names and jargon
# specific to one person do not belong in a tool other people install.
FAMILIES = {
    "DECISION": r"\b(decid\w*|decision|chose|choos\w*|opted|trade.?off|instead of|"
                r"rather than|we should|let's go with|agreed|conclusion)\b",
    "BUSINESS": r"\b(pitch|acquisi\w*|investor|revenue|pricing|deal|negotiat\w*|budget|"
                r"partnership|market\w*|competitor|positioning|strateg\w*|roadmap|"
                r"customer|contract|proposal|cost)\b",
    "PEOPLE": r"\b(team|hiring|onboard\w*|training|coaching|stakeholder|manager|"
              r"1:1|feedback|escalat\w*|colleague|meeting)\b",
    "IDEA": r"\b(idea|thesis|hypothes\w*|what if|concept|draft a post|article|blog|"
            r"announce\w*|publish|narrative)\b",
    "TECH": r"\b(function|const |import |npm |yarn |PR #|commit|merge|rebase|branch|"
            r"unit test|lint|refactor|stack trace|endpoint|typescript|schema|CI|"
            r"deploy|async|await|regex|null|undefined|traceback)\b",
}
RX = {k: re.compile(v, re.I) for k, v in FAMILIES.items()}
FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)
TURN = re.compile(r"^### (USER|CLAUDE) (\d\d:\d\d)$", re.M)


def session_end(path):
    """Last timestamp in the transcript, read without parsing every line as JSON."""
    last = ""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                i = line.rfind('"timestamp":"')
                if i != -1:
                    last = line[i + 13:i + 37]
    except OSError:
        pass
    return last


def render_brief(conf, run):
    """Fill the generic brief template with this user's scope and vocabulary.

    Extraction agents get a concrete brief rather than a template full of
    placeholders — a placeholder that reaches an agent becomes a note that says
    "{{USER_NAME}}".
    """
    tpl = Path(__file__).resolve().parents[1] / "templates" / "EXTRACTION_BRIEF.md"
    text = tpl.read_text(encoding="utf-8")
    private = "\n".join("  - %s" % x for x in conf.private_when) or "  - (none configured)"
    for key, val in (
        ("{{USER_NAME}}", conf.user_name),
        ("{{PRONOUNS}}", conf.pronouns),
        ("{{SCOPE_INCLUDE}}", conf.scope_include),
        ("{{SCOPE_EXCLUDE}}", conf.scope_exclude or "(nothing explicitly excluded)"),
        ("{{PRIVATE_WHEN}}", private),
        ("{{NOTE_TYPES}}", " ".join("`%s`" % t for t in cfg.NOTE_TYPES)),
    ):
        text = text.replace(key, val)
    out = run / "EXTRACTION_BRIEF.md"
    out.write_text(text, encoding="utf-8")
    return out


def user_turns(body):
    parts = TURN.split(body)
    out = []
    for i in range(1, len(parts) - 2, 3):
        if parts[i] == "USER":
            out.append(parts[i + 2].strip())
    return out


def main():
    argv = sys.argv[1:]
    force = "--all" in argv
    since = argv[argv.index("--since") + 1] if "--since" in argv else None
    only_vault = argv[argv.index("--vault") + 1] if "--vault" in argv else None

    conf, problems = cfg.load(strict=False)
    if conf is None:
        print("NO_CONFIG")
        for p in problems:
            print("  %s" % p)
        print("\nRun /my-vault:setup first.")
        return 2
    for p in problems:
        print("WARN %s" % p)

    if not PROJECTS.is_dir():
        print("No Claude Code transcripts found at %s" % PROJECTS)
        return 1

    state = cfg.load_state()
    done = {} if force else state.get("processed", {})

    todo = []
    for p in sorted(PROJECTS.glob("*/*.jsonl")):
        end = session_end(p)
        if since and end[:10] < since:
            continue
        if done.get(p.stem) == end:
            continue
        todo.append((p, end))

    run = cfg.run_dir()
    if run.exists():
        shutil.rmtree(run)
    (run / "digests").mkdir(parents=True)
    for v in conf.vaults:
        if only_vault and v.id != only_vault:
            continue
        (run / "notes" / v.id).mkdir(parents=True)

    rows = []
    for p, end in todo:
        m = digest_session(p, run / "digests")
        if m:
            m["end_raw"] = end
            rows.append(m)

    # merge.py commits these to state only after the notes actually land.
    (run / "pending.json").write_text(
        json.dumps({r["sid"]: r["end_raw"] for r in rows}, indent=1), encoding="utf-8")

    sheet = run / "triage_sheet.txt"
    with sheet.open("w", encoding="utf-8") as fh:
        fh.write("# Triage sheet — %d session(s) not yet captured\n" % len(rows))
        fh.write("# Vaults: %s\n" % ", ".join(
            "%s -> %s" % (v.id, v.path) for v in conf.vaults))
        for r in sorted(rows, key=lambda x: x["start"]):
            d = run / "digests" / (r["sid"] + ".md")
            txt = d.read_text(encoding="utf-8", errors="replace")
            m = FM.match(txt)
            body = txt[m.end():] if m else txt
            prof = {k: len(rx.findall(body)) for k, rx in RX.items()}
            users = user_turns(body)
            fh.write("\n" + "=" * 78 + "\n")
            fh.write("%s | %s user turns | %s KB\n"
                     % (r["start"], r["user_turns"], d.stat().st_size // 1024))
            fh.write("TITLE : %s\n" % r["title"])
            fh.write("ID    : %s\n" % r["sid"])
            fh.write("CWD   : %s\n" % (r.get("cwd") or "?"))
            fh.write("SIGNAL: decision=%d business=%d people=%d idea=%d | tech=%d\n"
                     % (prof["DECISION"], prof["BUSINESS"], prof["PEOPLE"],
                        prof["IDEA"], prof["TECH"]))
            for label, idx in (("OPEN", 0), ("OPEN", 1), ("LAST", -1)):
                try:
                    fh.write("%s  : %s\n" % (label, " ".join(users[idx].split())[:340]))
                except IndexError:
                    pass

    brief = render_brief(conf, run)

    print("sessions not yet captured : %d" % len(rows))
    print("digests                   : %s" % (run / "digests"))
    print("triage sheet              : %s" % sheet)
    print("extraction brief          : %s" % brief)
    print("stage notes into          : %s/<vault-id>/" % (run / "notes"))
    print("vault ids                 : %s" % ", ".join(v.id for v in conf.vaults))
    if not rows:
        print("\nNothing new. Your vault is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
