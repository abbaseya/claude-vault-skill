#!/usr/bin/env python
"""Find the user's Obsidian vaults and their likely project directories.

Knowing your own vault path is the single hardest step in setting this up for
someone who does not live in a terminal. So we do not ask — we look.

Obsidian keeps its own registry of every vault it has opened. That is the
authoritative source and it is a plain JSON file. Filesystem scanning is only a
fallback for a vault that exists on disk but has never been opened.

    python detect.py            # human-readable
    python detect.py --json     # machine-readable, for the setup skill
"""
import json
import os
import sys
from pathlib import Path

HOME = Path.home()

# Obsidian's own registry, per platform.
REGISTRIES = [
    HOME / "Library" / "Application Support" / "obsidian" / "obsidian.json",   # macOS
    Path(os.environ.get("APPDATA", "/nonexistent")) / "obsidian" / "obsidian.json",  # Windows
    HOME / ".config" / "obsidian" / "obsidian.json",                            # Linux
]

# Only used when the registry yields nothing. Deliberately shallow: a deep scan of
# $HOME on a large disk is slow enough that people assume it hung.
SCAN_ROOTS = [
    HOME / "Documents",
    HOME / "Obsidian",
    HOME / "Notes",
    HOME / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents",
    HOME / "iCloud Drive" / "Obsidian",
    HOME,
]
SCAN_DEPTH = 3

# Where people keep code. Used to suggest which folders map to which vault.
PROJECT_ROOTS = ["Sites", "Projects", "projects", "code", "Code", "dev", "Developer",
                 "src", "repos", "work", "workspace", "git"]


def from_registry():
    """Vaults Obsidian itself knows about. Most reliable source."""
    found = []
    for reg in REGISTRIES:
        try:
            if not reg.is_file():
                continue
            data = json.loads(reg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for meta in (data.get("vaults") or {}).values():
            p = meta.get("path")
            if not p:
                continue
            path = Path(p)
            if path.is_dir():
                found.append({"path": str(path), "name": path.name,
                              "source": "obsidian-registry",
                              "open": bool(meta.get("open"))})
    return found


def from_scan():
    """Any directory containing a .obsidian folder. Fallback only."""
    found, seen = [], set()
    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, _ in os.walk(root):
            d = Path(dirpath)
            if len(d.parts) - base_depth >= SCAN_DEPTH:
                dirnames[:] = []
                continue
            # Never descend into noise.
            dirnames[:] = [x for x in dirnames
                           if not x.startswith(".") or x == ".obsidian"]
            if ".obsidian" in dirnames:
                key = str(d.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append({"path": str(d), "name": d.name,
                                  "source": "filesystem-scan", "open": False})
                dirnames[:] = [x for x in dirnames if x != ".obsidian"]
    return found


def vaults():
    found = from_registry()
    if found:
        return found
    return from_scan()


def project_dirs(limit=40):
    """Plausible `watch` directories: git repos, and the folders that hold them."""
    out = []
    for name in PROJECT_ROOTS:
        root = HOME / name
        if not root.is_dir():
            continue
        entry = {"path": str(root), "name": name, "repos": []}
        try:
            for child in sorted(root.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                if (child / ".git").exists():
                    entry["repos"].append(child.name)
                if len(entry["repos"]) >= limit:
                    break
        except OSError:
            pass
        out.append(entry)
    return out


def main():
    vs = vaults()
    ps = project_dirs()
    if "--json" in sys.argv:
        json.dump({"vaults": vs, "project_dirs": ps}, sys.stdout, indent=1)
        print()
        return 0 if vs else 1

    if not vs:
        print("No Obsidian vaults found.")
        print()
        print("If you have not created one yet: open Obsidian, choose 'Create new vault',")
        print("pick a name and a folder, then run setup again.")
        print("If you have one already, tell me its folder path and I will use that.")
        return 1

    print("Obsidian vaults found:")
    for i, v in enumerate(vs, 1):
        mark = "  (currently open)" if v.get("open") else ""
        print("  %d. %-28s %s%s" % (i, v["name"], v["path"], mark))
    print()
    if ps:
        print("Folders that look like they hold your projects:")
        for p in ps:
            repos = ", ".join(p["repos"][:8]) or "(no git repos directly inside)"
            more = " +%d more" % (len(p["repos"]) - 8) if len(p["repos"]) > 8 else ""
            print("  %-22s %s%s" % (p["path"], repos, more))
    return 0


if __name__ == "__main__":
    sys.exit(main())
