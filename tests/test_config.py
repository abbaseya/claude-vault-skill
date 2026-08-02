#!/usr/bin/env python
"""Configuration must fail loudly, never silently half-work.

A config that loads but is subtly wrong is the worst outcome: notes go to the
wrong vault, or nowhere, and nothing says so. Every case here plants one defect
and asserts it is reported in words a non-technical user could act on.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from harness import FixtureCase  # noqa: E402


def fresh_config_module(home, projects=None):
    """Import config.py with MY_VAULT_HOME pointed at a temp dir."""
    import importlib
    import os
    os.environ["MY_VAULT_HOME"] = str(home)
    if projects:
        os.environ["CLAUDE_PROJECTS_DIR"] = str(projects)
    import config
    importlib.reload(config)
    return config


class ConfigValidation(FixtureCase):

    def cfg(self):
        return fresh_config_module(self.home)

    def load_with(self, **overrides):
        self.write_config(**overrides)
        c = self.cfg()
        return c.load(strict=True)

    def test_valid_config_loads(self):
        conf, problems = self.load_with()
        self.assertEqual(problems, [])
        self.assertIsNotNone(conf)
        self.assertEqual(conf.user_name, "Test User")
        self.assertEqual(len(conf.vaults), 1)

    def test_missing_config_is_reported_not_crashed(self):
        (self.home / "config.json").unlink()
        conf, problems = self.cfg().load(strict=True)
        self.assertIsNone(conf)
        self.assertTrue(any("setup" in p for p in problems), problems)

    def test_malformed_json_is_reported(self):
        (self.home / "config.json").write_text("{oops", encoding="utf-8")
        conf, problems = self.cfg().load(strict=True)
        self.assertIsNone(conf)
        self.assertTrue(any("not valid JSON" in p for p in problems), problems)

    def test_no_vaults_is_reported(self):
        conf, problems = self.load_with(vaults=[])
        self.assertIsNone(conf)
        self.assertTrue(any("no vaults" in p for p in problems), problems)

    def test_nonexistent_vault_path_is_reported(self):
        conf, problems = self.load_with(vaults=[{
            "id": "main", "path": str(self.tmp / "nope"), "watch": [str(self.proj)],
            "topics": [{"title": "T", "fallback": True}]}])
        self.assertTrue(any("does not exist" in p for p in problems), problems)

    def test_nonexistent_watch_path_is_reported(self):
        conf, problems = self.load_with(vaults=[{
            "id": "main", "path": str(self.vault), "watch": [str(self.tmp / "nope")],
            "topics": [{"title": "T", "fallback": True}]}])
        self.assertTrue(any("watch path does not exist" in p for p in problems), problems)

    def test_duplicate_vault_ids_are_reported(self):
        v = {"id": "main", "path": str(self.vault), "watch": [str(self.proj)],
             "topics": [{"title": "T", "fallback": True}]}
        conf, problems = self.load_with(vaults=[v, dict(v)])
        self.assertTrue(any("duplicate vault id" in p for p in problems), problems)

    def test_non_slug_vault_id_is_reported(self):
        conf, problems = self.load_with(vaults=[{
            "id": "My Vault", "path": str(self.vault), "watch": [str(self.proj)],
            "topics": [{"title": "T", "fallback": True}]}])
        self.assertTrue(any("lowercase-with-hyphens" in p for p in problems), problems)

    def test_missing_fallback_topic_is_reported(self):
        """Without a fallback, notes matching no rule vanish from every hub."""
        conf, problems = self.load_with(vaults=[{
            "id": "main", "path": str(self.vault), "watch": [str(self.proj)],
            "topics": [{"title": "Only", "types": ["decision"]}]}])
        self.assertTrue(any("fallback" in p for p in problems), problems)

    def test_two_fallback_topics_are_reported(self):
        conf, problems = self.load_with(vaults=[{
            "id": "main", "path": str(self.vault), "watch": [str(self.proj)],
            "topics": [{"title": "A", "fallback": True},
                       {"title": "B", "fallback": True}]}])
        self.assertTrue(any("more than one" in p for p in problems), problems)

    def test_unknown_note_type_in_a_topic_is_reported(self):
        conf, problems = self.load_with(vaults=[{
            "id": "main", "path": str(self.vault), "watch": [str(self.proj)],
            "topics": [{"title": "A", "types": ["ruminations"]},
                       {"title": "B", "fallback": True}]}])
        self.assertTrue(any("unknown note type" in p for p in problems), problems)

    def test_unknown_scope_preset_is_reported(self):
        conf, problems = self.load_with(scope={"preset": "vibes"})
        self.assertTrue(any("unknown scope preset" in p for p in problems), problems)

    def test_every_shipped_preset_resolves(self):
        c = self.cfg()
        for name in c.SCOPE_PRESETS:
            self.write_config(scope={"preset": name})
            conf, problems = c.load(strict=True)
            self.assertEqual(problems, [], "%s: %s" % (name, problems))
            self.assertTrue(conf.scope_include)
            self.assertTrue(conf.scope_exclude)


class CwdRouting(FixtureCase):

    def test_nested_directory_resolves_to_its_vault(self):
        c = fresh_config_module(self.home)
        conf, _ = c.load()
        deep = self.proj / "a" / "b" / "c"
        deep.mkdir(parents=True)
        self.assertEqual(conf.vault_for_cwd(deep).id, "main")

    def test_unwatched_directory_resolves_to_nothing(self):
        c = fresh_config_module(self.home)
        conf, _ = c.load()
        self.assertIsNone(conf.vault_for_cwd(self.tmp))

    def test_longest_matching_watch_wins(self):
        inner = self.proj / "inner"
        inner.mkdir()
        other = self.tmp / "vault2"
        other.mkdir()
        self.write_config(vaults=[
            {"id": "outer", "path": str(self.vault), "watch": [str(self.proj)],
             "topics": [{"title": "T", "fallback": True}]},
            {"id": "inner", "path": str(other), "watch": [str(inner)],
             "topics": [{"title": "T", "fallback": True}]},
        ])
        c = fresh_config_module(self.home)
        conf, problems = c.load()
        self.assertEqual(problems, [])
        self.assertEqual(conf.vault_for_cwd(inner / "deep").id, "inner")
        self.assertEqual(conf.vault_for_cwd(self.proj / "elsewhere").id, "outer")


class TopicRouting(FixtureCase):

    def routes(self, ntype, tags):
        c = fresh_config_module(self.home)
        conf, _ = c.load()
        return conf.vaults[0].topics_for(ntype, tags)

    def test_type_match(self):
        self.assertIn("MOC — Decisions", self.routes("decision", []))

    def test_tag_match(self):
        self.assertIn("MOC — Money", self.routes("insight", ["cost"]))

    def test_tag_match_is_case_insensitive(self):
        self.assertIn("MOC — Money", self.routes("insight", ["COST"]))

    def test_no_match_falls_back(self):
        self.assertEqual(self.routes("pitch", ["nothing"]), ["MOC — Everything Else"])

    def test_a_note_can_belong_to_several_topics(self):
        r = self.routes("decision", ["cost"])
        self.assertIn("MOC — Decisions", r)
        self.assertIn("MOC — Money", r)

    def test_fallback_not_added_when_something_matched(self):
        self.assertNotIn("MOC — Everything Else", self.routes("decision", []))


class FallbackTypes(FixtureCase):
    """`fallback_types` gives a note type a home WITHOUT pulling every note of
    that type into that hub. Using plain `types` for this silently inflates the
    hub, because `types` matches unconditionally."""

    def setUp(self):
        super().setUp()
        self.write_config(vaults=[{
            "id": "main", "path": str(self.vault), "watch": [str(self.proj)],
            "topics": [
                {"title": "Money", "types": [], "tags": ["cost"]},
                {"title": "Thinking", "fallback_types": ["insight"]},
                {"title": "Everything Else", "fallback": True},
            ]}])

    def routes(self, ntype, tags):
        c = fresh_config_module(self.home)
        conf, problems = c.load()
        self.assertEqual(problems, [])
        return conf.vaults[0].topics_for(ntype, tags)

    def test_type_fallback_applies_when_nothing_else_matched(self):
        self.assertEqual(self.routes("insight", ["unrelated"]), ["Thinking"])

    def test_type_fallback_does_NOT_apply_when_something_matched(self):
        """The regression this exists to prevent: an insight note that already
        belongs to Money must not also be dragged into Thinking."""
        self.assertEqual(self.routes("insight", ["cost"]), ["Money"])

    def test_final_fallback_still_catches_unclaimed_types(self):
        self.assertEqual(self.routes("pitch", ["unrelated"]), ["Everything Else"])

    def test_two_topics_claiming_the_same_fallback_type_is_reported(self):
        conf, problems = self.load_with_topics([
            {"title": "A", "fallback_types": ["insight"]},
            {"title": "B", "fallback_types": ["insight"]},
            {"title": "C", "fallback": True},
        ])
        self.assertTrue(any("claimed as a fallback by both" in p for p in problems),
                        problems)

    def test_unknown_type_in_fallback_types_is_reported(self):
        conf, problems = self.load_with_topics([
            {"title": "A", "fallback_types": ["daydreams"]},
            {"title": "C", "fallback": True},
        ])
        self.assertTrue(any("unknown note type" in p for p in problems), problems)

    def load_with_topics(self, topics):
        self.write_config(vaults=[{
            "id": "main", "path": str(self.vault), "watch": [str(self.proj)],
            "topics": topics}])
        return fresh_config_module(self.home).load(strict=True)


class DataPaths(FixtureCase):

    def test_all_state_lives_outside_the_plugin(self):
        """A plugin update replaces the plugin directory. Anything the user owns
        that lived inside it would be deleted by the first update."""
        c = fresh_config_module(self.home)
        plugin_root = Path(__file__).resolve().parents[1]
        for p in (c.config_path(), c.state_path(), c.entities_path(), c.run_dir()):
            self.assertFalse(str(p).startswith(str(plugin_root)),
                             "%s is inside the plugin directory" % p)

    def test_entities_round_trip(self):
        c = fresh_config_module(self.home)
        c.save_entities({"Acme": {"kind": "org", "description": "x"}})
        self.assertEqual(c.load_entities()["Acme"]["kind"], "org")

    def test_corrupt_state_does_not_crash(self):
        c = fresh_config_module(self.home)
        c.state_path().parent.mkdir(parents=True, exist_ok=True)
        c.state_path().write_text("{broken", encoding="utf-8")
        self.assertEqual(c.load_state()["processed"], {})

    def test_corrupt_entities_do_not_crash(self):
        c = fresh_config_module(self.home)
        c.entities_path().parent.mkdir(parents=True, exist_ok=True)
        c.entities_path().write_text("nope", encoding="utf-8")
        self.assertEqual(c.load_entities(), {})


class DefaultTemplate(unittest.TestCase):

    def test_shipped_default_config_is_structurally_valid(self):
        """The template users start from must not itself be broken. Paths in it
        are placeholders, so only structural problems are checked here."""
        import config
        tpl = Path(__file__).resolve().parents[1] / "templates" / "config.default.json"
        raw = json.loads(tpl.read_text(encoding="utf-8"))
        problems = [p for p in config.validate(raw) if "does not exist" not in p]
        self.assertEqual(problems, [], problems)

    def test_default_template_has_exactly_one_fallback_topic(self):
        tpl = Path(__file__).resolve().parents[1] / "templates" / "config.default.json"
        raw = json.loads(tpl.read_text(encoding="utf-8"))
        for v in raw["vaults"]:
            fb = [t for t in v["topics"] if t.get("fallback")]
            self.assertEqual(len(fb), 1, v["id"])


if __name__ == "__main__":
    unittest.main()
