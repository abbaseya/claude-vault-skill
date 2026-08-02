#!/usr/bin/env python
"""SessionStart — tell Claude which vault belongs to this working directory.

Without this, Claude has no idea a vault exists and you would have to say so in
every session. With it, the mapping is automatic and works from nested
directories, which is where most sessions actually start.

It deliberately also says *do not write unprompted*. Capturing a session is the
user's call, made by running /my-vault:sync — never a side effect of a session
happening to touch a watched folder.

Always exits 0 and prints nothing on any error. A session must never fail to
start because this had a bad day.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def session_cwd():
    """Prefer the cwd the harness reports; fall back to the process cwd."""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("cwd"):
                return Path(data["cwd"])
    except Exception:
        pass
    return Path(os.getcwd())


def main():
    import config as cfg

    conf, _ = cfg.load(strict=False)
    if conf is None:
        return
    vault = conf.vault_for_cwd(session_cwd())
    if vault is None or not (vault.path / "Home.md").is_file():
        return                              # not a watched dir, or vault not built yet

    def count(key):
        d = vault.dir(key)
        return len(list(d.glob("*.md"))) if d.is_dir() else 0

    private = count("private")
    notes = count("notes") + private
    if notes == 0:
        return

    ctx = (
        "Obsidian vault for this working directory: {path}\n"
        "{n} note{s} ({p} marked `sensitivity: private`). Entry point: Home.md — "
        "`{topics}/` holds topic hubs, `{notes}/` and `{priv}/` hold the notes, "
        "`{sources}/` maps each note back to the session or document it came from.\n"
        "READ from it whenever earlier decisions, reasoning or context would help "
        "answer something. Grep the frontmatter (`type:`, `tags:`, `sensitivity:`) "
        "to find notes.\n"
        "Do NOT write to the vault unprompted. Capturing a session into it is the "
        "user's call — they run /my-vault:sync when they want it."
    ).format(path=vault.path, n=notes, s="" if notes == 1 else "s", p=private,
             topics=vault.folders["topics"], notes=vault.folders["notes"],
             priv=vault.folders["private"], sources=vault.folders["sources"])

    json.dump({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": ctx,
    }}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
