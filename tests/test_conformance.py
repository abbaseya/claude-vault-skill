#!/usr/bin/env python
"""The plugin must be structurally sound and free of personal references.

These are the failures that do not show up when you run the tool yourself: a
skill pointing at a script that was renamed, a hook path that only resolves on
the author's machine, or a colleague's name surviving into a public repo.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class PluginManifest(unittest.TestCase):

    def setUp(self):
        self.manifest = json.loads(
            (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))

    def test_manifest_is_at_the_repo_root(self):
        """The marketplace references this repo with a `github` source, so the
        manifest must be at the root — not under plugins/<name>/."""
        self.assertTrue((ROOT / ".claude-plugin" / "plugin.json").is_file())

    def test_name_is_kebab_case(self):
        self.assertTrue(KEBAB.match(self.manifest["name"]), self.manifest["name"])

    def test_required_fields_present(self):
        for k in ("name", "description", "version"):
            self.assertTrue(self.manifest.get(k), k)

    def test_version_is_semver(self):
        self.assertRegex(str(self.manifest["version"]), r"^\d+\.\d+\.\d+")


class Skills(unittest.TestCase):

    def skill_files(self):
        return sorted((ROOT / "skills").glob("*/SKILL.md"))

    def test_skills_exist(self):
        names = {p.parent.name for p in self.skill_files()}
        self.assertEqual(names, {"sync", "setup"})

    def test_every_skill_has_required_frontmatter(self):
        for p in self.skill_files():
            head = p.read_text(encoding="utf-8").split("---")[1]
            self.assertIn("name:", head, p)
            self.assertIn("description:", head, p)

    def test_skills_are_user_invoked_only(self):
        """Capturing a session is the user's call. If the model can invoke these
        on its own, it will eventually write to a vault unasked."""
        for p in self.skill_files():
            head = p.read_text(encoding="utf-8").split("---")[1]
            self.assertIn("disable-model-invocation: true", head, p)

    def test_skill_name_matches_its_directory(self):
        for p in self.skill_files():
            head = p.read_text(encoding="utf-8").split("---")[1]
            declared = re.search(r"^name:\s*(\S+)", head, re.M).group(1)
            self.assertEqual(declared, p.parent.name, p)

    def test_every_script_referenced_by_a_skill_exists(self):
        """A skill naming a script that was renamed fails at runtime, silently,
        for the user — never for the author."""
        rx = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)")
        checked = 0
        for p in self.skill_files():
            for rel in rx.findall(p.read_text(encoding="utf-8")):
                self.assertTrue((ROOT / rel).exists(),
                                "%s references missing %s" % (p.name, rel))
                checked += 1
        self.assertGreater(checked, 0, "no script references found to check")

    def test_skills_do_not_hardcode_a_home_directory(self):
        for p in self.skill_files():
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("/Users/", text, p)
            self.assertNotRegex(text, r"~/\.claude/skills/", p.name)


class Hooks(unittest.TestCase):

    def setUp(self):
        self.hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))

    def test_hooks_json_is_valid_and_registers_sessionstart(self):
        self.assertIn("SessionStart", self.hooks["hooks"])

    def test_hook_commands_use_the_plugin_root_placeholder(self):
        for group in self.hooks["hooks"].values():
            for entry in group:
                for h in entry["hooks"]:
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}", h["command"], h)

    def test_hook_scripts_exist(self):
        rx = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)")
        for group in self.hooks["hooks"].values():
            for entry in group:
                for h in entry["hooks"]:
                    for rel in rx.findall(h["command"]):
                        self.assertTrue((ROOT / rel).is_file(), rel)

    def test_hook_never_fails_a_session(self):
        """A hook that can exit non-zero can stop a session from starting. This
        one must swallow everything."""
        src = (ROOT / "hooks" / "vault-context.py").read_text(encoding="utf-8")
        self.assertIn("sys.exit(0)", src)
        self.assertIn("except Exception", src)


class LeakGate(unittest.TestCase):
    """The leak checker must actually catch a leak, or its green run means nothing.

    The sample leaks below are assembled at runtime rather than written as
    literals. Adding this file to the checker's exemption list would have been
    easier, but it would also mean a genuine leak introduced here later would
    never be caught — the one file guaranteed to be exempt is the worst place to
    have a blind spot.
    """

    LEAK_NAME = "Clau" + "diu"
    LEAK_ORG = "OGG" + "EH"
    LEAK_PATH = "~/Si" + "tes/thing"

    def run_checker(self, cwd):
        p = subprocess.run([sys.executable, str(cwd / "bin" / "check-leaks.py")],
                           capture_output=True, text=True, cwd=str(cwd))
        return p.returncode, p.stdout + p.stderr

    def test_repo_is_clean(self):
        rc, out = self.run_checker(ROOT)
        self.assertEqual(rc, 0, out)

    def test_a_planted_leak_is_caught(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "bin").mkdir()
            (td / "bin" / "check-leaks.py").write_text(
                (ROOT / "bin" / "check-leaks.py").read_text(encoding="utf-8"),
                encoding="utf-8")
            (td / "templates").mkdir()
            (td / "templates" / "example.md").write_text(
                "Ask %s about the %s migration.\n" % (self.LEAK_NAME, self.LEAK_ORG),
                encoding="utf-8")
            rc, out = self.run_checker(td)
            self.assertEqual(rc, 1, out)
            self.assertIn(self.LEAK_NAME, out)

    def test_a_planted_local_path_is_caught(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "bin").mkdir()
            (td / "bin" / "check-leaks.py").write_text(
                (ROOT / "bin" / "check-leaks.py").read_text(encoding="utf-8"),
                encoding="utf-8")
            (td / "notes.md").write_text("see %s\n" % self.LEAK_PATH, encoding="utf-8")
            rc, out = self.run_checker(td)
            self.assertEqual(rc, 1, out)


class SetupSkillIsGeneric(unittest.TestCase):
    """Nothing from the author's own vault may reach a shipped prompt.

    The first version of the existing-vault guidance illustrated the wording with
    the author's real note count and hub names. It is only an example, but it ships
    to everyone and gives the model concrete taxonomy to echo at people whose work
    looks nothing like his. The leak gate could not catch it — "Competitive
    Positioning" is not a distinctive enough phrase to blocklist — so it is
    asserted here instead.
    """

    def setUp(self):
        self.text = (ROOT / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")

    def test_no_hub_names_from_the_authors_vault(self):
        # Assembled at runtime: two of these contain a term the leak gate blocks,
        # and exempting this file would blind the gate exactly where the sample
        # data lives.
        org = "OGG" + "EH"
        for hub in ("AI-Driven Development", "Business & M&A", "Competitive Positioning",
                    "My Role & Employment", "Org & Team Dynamics", "Product Decisions",
                    "%s Product & Positioning" % org, "Client Delivery"):
            self.assertNotIn(hub, self.text, "author's hub name %r in a shipped prompt" % hub)

    def test_no_concrete_note_counts_or_percentages(self):
        """An example with real figures invites the model to reuse them verbatim."""
        self.assertNotRegex(self.text, r"\b\d{2,}\s+notes\b")
        self.assertNotRegex(self.text, r"\b\d{2,}%")

    def test_the_example_uses_placeholders(self):
        self.assertIn("&lt;N&gt;", self.text)
        self.assertIn("&lt;PERCENT&gt;", self.text)

    def test_setup_asks_about_documents(self):
        """`documents` defaults to empty and an empty value is silent — nothing
        tells you your written notes are being ignored. So setup has to ask."""
        self.assertIn("documents", self.text)
        self.assertIn("do not skip this", self.text.lower())

    def test_setup_inspects_before_proposing_topics(self):
        self.assertIn("inspect_vault.py", self.text)
        self.assertIn("ALREADY ORGANISED", self.text)


class Templates(unittest.TestCase):

    def test_extraction_brief_placeholders_are_all_rendered(self):
        """A placeholder that survives into an agent's brief becomes a note that
        literally says {{USER_NAME}}."""
        sys.path.insert(0, str(SCRIPTS))
        tpl = (ROOT / "templates" / "EXTRACTION_BRIEF.md").read_text(encoding="utf-8")
        found = set(re.findall(r"\{\{([A-Z_]+)\}\}", tpl))
        rendered_by = set(re.findall(
            r'\("\{\{([A-Z_]+)\}\}"', (SCRIPTS / "scan.py").read_text(encoding="utf-8")))
        self.assertEqual(found - rendered_by, set(),
                         "template placeholders nothing renders")

    def test_brief_forbids_inventing_quotes(self):
        tpl = (ROOT / "templates" / "EXTRACTION_BRIEF.md").read_text(encoding="utf-8")
        self.assertIn("NEVER invent a quote", tpl)
        self.assertIn("character-exact", tpl)


if __name__ == "__main__":
    unittest.main()
