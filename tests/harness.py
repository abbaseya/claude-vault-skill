#!/usr/bin/env python
"""Fixture harness: a throwaway world with a vault, a config and fake transcripts.

Every test runs against MY_VAULT_HOME and CLAUDE_PROJECTS_DIR pointed at a temp
directory. Nothing here can touch the real vault, the real config, or the user's
actual Claude Code history — which matters, because a test suite that writes to
someone's notes is worse than no test suite.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def transcript(turns, session_id="s0000000-0000-4000-8000-000000000001",
               cwd="/tmp/proj", title=None, start="2026-01-15T09:00:00.000Z"):
    """Build a Claude Code .jsonl transcript from (role, text) pairs.

    Mirrors the real shape closely enough to exercise the digester: string and
    block content, tool_use / tool_result noise, a sidechain turn, and a meta turn.
    """
    lines = []
    if title:
        lines.append({"type": "custom-title", "title": title, "sessionId": session_id})
    hh = 0
    for role, text in turns:
        ts = start[:11] + "%02d:%02d:00.000Z" % (9 + hh // 60, hh % 60)
        hh += 1
        if role == "user":
            content = text
        elif role == "assistant":
            content = [{"type": "text", "text": text}]
        elif role == "tool":                     # noise that must be stripped
            lines.append({"type": "assistant", "timestamp": ts, "cwd": cwd,
                          "isSidechain": False,
                          "message": {"role": "assistant", "content": [
                              {"type": "tool_use", "id": "t1", "name": "Bash",
                               "input": {"command": text}}]}})
            lines.append({"type": "user", "timestamp": ts, "cwd": cwd,
                          "message": {"role": "user", "content": [
                              {"type": "tool_result", "tool_use_id": "t1",
                               "content": "SECRET_TOOL_OUTPUT " + text}]}})
            continue
        elif role == "sidechain":                # subagent turn, must be stripped
            lines.append({"type": "assistant", "timestamp": ts, "cwd": cwd,
                          "isSidechain": True,
                          "message": {"role": "assistant",
                                      "content": [{"type": "text", "text": text}]}})
            continue
        elif role == "meta":                     # harness-injected, must be stripped
            lines.append({"type": "user", "timestamp": ts, "cwd": cwd, "isMeta": True,
                          "message": {"role": "user", "content": text}})
            continue
        else:
            raise ValueError(role)
        lines.append({"type": role, "timestamp": ts, "cwd": cwd, "isSidechain": False,
                      "message": {"role": role, "content": content}})
    return "\n".join(json.dumps(x) for x in lines) + "\n", session_id


def note(title, quote, source_session=None, source_doc=None, ntype="decision",
         sensitivity="normal", date="2026-01-15", tags="[alpha, beta]",
         source_title="A session", extra_links=""):
    src = ("source_session: %s" % source_session if source_session
           else "source_doc: %s" % source_doc)
    return (
        "---\n"
        "title: %s\n"
        "type: %s\n"
        "date: %s\n"
        "tags: %s\n"
        "sensitivity: %s\n"
        "%s\n"
        "source_title: %s\n"
        "fidelity: verbatim\n"
        "---\n\n"
        "A one-line synthesis of the claim.\n\n"
        "> \"%s\"\n"
        "> — Someone, %s, %s\n\n"
        "Some context about why it matters.\n"
        "%s"
    ) % (title, ntype, date, tags, sensitivity, src, source_title, quote, date,
         source_title, extra_links)


class FixtureCase(unittest.TestCase):
    """Base class giving each test an isolated world."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="my-vault-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.projects = self.tmp / "projects" / "-tmp-proj"
        self.vault = self.tmp / "vault"
        self.proj = self.tmp / "proj"
        self.docs = self.tmp / "docs"
        for d in (self.home, self.projects, self.vault, self.proj, self.docs):
            d.mkdir(parents=True, exist_ok=True)
        self.env = dict(os.environ)
        self.env["MY_VAULT_HOME"] = str(self.home)
        self.env["CLAUDE_PROJECTS_DIR"] = str(self.tmp / "projects")
        self.write_config()

    # ---- fixture builders ------------------------------------------------
    def write_config(self, **overrides):
        conf = {
            "version": 1,
            "user": {"name": "Test User", "pronouns": "they/them"},
            "vaults": [{
                "id": "main", "name": "Test Vault", "path": str(self.vault),
                "watch": [str(self.proj)], "documents": [str(self.docs)],
                "topics": [
                    {"title": "MOC — Decisions", "types": ["decision"], "tags": []},
                    {"title": "MOC — Money", "types": [], "tags": ["cost"]},
                    {"title": "MOC — Everything Else", "fallback": True},
                ],
            }],
            "scope": {"preset": "everything-except-technical"},
            "sensitivity": {"private_when": ["pay"]},
        }
        conf.update(overrides)
        (self.home / "config.json").write_text(json.dumps(conf, indent=1),
                                               encoding="utf-8")
        return conf

    def add_transcript(self, turns, **kw):
        text, sid = transcript(turns, cwd=str(self.proj), **kw)
        (self.projects / (sid + ".jsonl")).write_text(text, encoding="utf-8")
        return sid

    def stage(self, vault_id, filename, body):
        d = self.home / "run" / "notes" / vault_id
        d.mkdir(parents=True, exist_ok=True)
        (d / filename).write_text(body, encoding="utf-8")
        return d / filename

    # ---- runners ---------------------------------------------------------
    def run_script(self, name, *args):
        p = subprocess.run([sys.executable, str(SCRIPTS / name), *args],
                           capture_output=True, text=True, env=self.env)
        return p.returncode, p.stdout + p.stderr

    def scan(self, *args):
        return self.run_script("scan.py", *args)

    def verify(self, *args):
        return self.run_script("verify.py", *args)

    def merge(self, *args):
        return self.run_script("merge.py", *args)

    # ---- assertions ------------------------------------------------------
    def vault_files(self, sub=None):
        base = self.vault / sub if sub else self.vault
        if not base.is_dir():
            return []
        return sorted(p.name for p in base.glob("*.md"))

    def snapshot(self):
        return {str(p.relative_to(self.vault)): p.read_bytes()
                for p in sorted(self.vault.rglob("*.md"))}
