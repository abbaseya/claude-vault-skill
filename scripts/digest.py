#!/usr/bin/env python
"""Condense a Claude Code transcript into a triage-able digest.

Keeps only your own turns plus the assistant's prose. Drops tool calls, tool
results, file dumps, thinking blocks, subagent sidechains and harness wrappers.
Typically reduces a transcript to ~2% of its raw size — on one real corpus,
379.8 MB of transcripts became 6.5 MB of actual conversation.

Importable (digest_session) and runnable standalone.
"""
import json
import re
import sys
from pathlib import Path

BLOCK_RE = [
    re.compile(r"<system-reminder>.*?</system-reminder>", re.S),
    re.compile(r"<local-command-stdout>.*?</local-command-stdout>", re.S),
    re.compile(r"<local-command-caveat>.*?</local-command-caveat>", re.S),
    re.compile(r"<command-message>.*?</command-message>", re.S),
    re.compile(r"<command-args>.*?</command-args>", re.S),
    re.compile(r"<command-contents>.*?</command-contents>", re.S),
    re.compile(r"<user-prompt-submit-hook>.*?</user-prompt-submit-hook>", re.S),
    re.compile(r"<task-notification>.*?</task-notification>", re.S),
    re.compile(r"<function_results>.*?</function_results>", re.S),
    re.compile(r"<bash-(?:input|stdout|stderr)>.*?</bash-[a-z]+>", re.S),
]
CMDNAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.S)
FENCE_RE = re.compile(r"```.*?```", re.S)
WS_RE = re.compile(r"\n{3,}")

ASSISTANT_CAP = 4000
USER_CAP = 12000


def clean(text):
    if not text:
        return ""
    cmds = CMDNAME_RE.findall(text)
    for rx in BLOCK_RE:
        text = rx.sub("", text)
    text = CMDNAME_RE.sub("", text)
    text = WS_RE.sub("\n\n", text).strip()
    if cmds:
        marker = " ".join("[" + c.strip() + "]" for c in cmds)
        text = (marker + "\n" + text).strip() if text else marker
    return text


def strip_code(text, max_fence_lines=12):
    def repl(m):
        body = m.group(0)
        n = body.count("\n")
        return body if n <= max_fence_lines else "[code block omitted: %d lines]" % n
    return FENCE_RE.sub(repl, text)


def cap(text, limit):
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n\n[... %d chars elided ...]\n\n" % (len(text) - limit) + text[-half:]


def blocks_text(content, want):
    if isinstance(content, str):
        return content if want == "user" else ""
    if not isinstance(content, list):
        return ""
    return "\n".join(b.get("text") or "" for b in content
                     if isinstance(b, dict) and b.get("type") == "text")


def digest_session(path, outdir):
    """Write <session-id>.md into outdir. Returns a metadata dict, or None."""
    path, outdir = Path(path), Path(outdir)
    sid = path.stem
    meta = {"cwd": "", "branch": "", "title": "", "first": "", "last": ""}
    turns, n_user, n_asst = [], 0, 0

    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            t = rec.get("type")
            if t == "custom-title":
                meta["title"] = rec.get("title") or rec.get("customTitle") or meta["title"]
                continue
            if t == "summary" and not meta["title"]:
                meta["title"] = rec.get("summary") or ""
                continue
            ts = rec.get("timestamp") or ""
            if ts:
                if not meta["first"]:
                    meta["first"] = ts
                meta["last"] = ts
            if t not in ("user", "assistant") or rec.get("isSidechain") or rec.get("isMeta"):
                continue
            meta["cwd"] = rec.get("cwd") or meta["cwd"]
            meta["branch"] = rec.get("gitBranch") or meta["branch"]
            body = blocks_text((rec.get("message") or {}).get("content"), t)
            if t == "user":
                body = clean(body)
                if body:
                    n_user += 1
                    turns.append(("USER", ts[11:16], cap(body, USER_CAP)))
            else:
                body = strip_code(body).strip()
                if body:
                    n_asst += 1
                    turns.append(("CLAUDE", ts[11:16], cap(body, ASSISTANT_CAP)))

    if not turns:
        return None

    head = ["---", "session_id: %s" % sid, "project: %s" % path.parent.name,
            "cwd: %s" % meta["cwd"], "branch: %s" % meta["branch"],
            "title: %s" % (meta["title"] or "<untitled>").replace("\n", " "),
            "start: %s" % meta["first"][:19], "end: %s" % meta["last"][:19],
            "user_turns: %d" % n_user, "assistant_turns: %d" % n_asst, "---", ""]
    body = []
    for who, hhmm, text in turns:
        body += ["### %s %s" % (who, hhmm), text, ""]
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / (sid + ".md")).write_text("\n".join(head + body), encoding="utf-8")
    return {"sid": sid, "project": path.parent.name, "title": meta["title"] or "<untitled>",
            "start": meta["first"][:10], "end": meta["last"], "user_turns": n_user,
            # cwd is what routes a session to a vault, so triage needs to see it.
            "cwd": meta["cwd"]}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import config as cfg

    out = Path(sys.argv[1])
    n = 0
    for p in sorted(cfg.projects_dir().glob("*/*.jsonl")):
        if digest_session(p, out):
            n += 1
    print("digested %d sessions -> %s" % (n, out))
