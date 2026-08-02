#!/usr/bin/env python
"""Setup must not reorganise a vault somebody already curated.

The defect this covers shipped in the first version: setup assumed a fresh vault,
proposed a taxonomy from the user's answers alone, and the next merge then deleted
every existing hub and rewrote every note's `Up:` line. Nothing was lost, but
nobody asked for it, and the summary line gave no hint it had happened.

So: inspection must SEE an organised vault, derive rules from the notes rather
than from a guess, and — the part that matters — check its own derivation against
the real notes instead of asserting it worked.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from harness import FixtureCase, note  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class InspectVault(FixtureCase):

    def place(self, title, ntype, tags, hubs, sub="01 Notes"):
        d = self.vault / sub
        d.mkdir(parents=True, exist_ok=True)
        body = note(title, "a quote that does not matter here", source_session="s1",
                    ntype=ntype, tags="[%s]" % ", ".join(tags))
        body += "\n\nUp: " + ", ".join("[[%s]]" % h for h in hubs) + "\n"
        (d / (title + ".md")).write_text(body, encoding="utf-8")

    def hub(self, title):
        d = self.vault / "02 Topics"
        d.mkdir(parents=True, exist_ok=True)
        (d / (title + ".md")).write_text(
            "---\ntitle: %s\ntype: moc\n---\n\nhub\n" % title, encoding="utf-8")

    def organised_vault(self):
        """Three hubs with a clean signal, mirroring how merge lays one out."""
        for h in ("MOC — Money", "MOC — People", "MOC — Everything Else"):
            self.hub(h)
        for i in range(4):
            self.place("Cost note %d" % i, "insight", ["cost"], ["MOC — Money"])
        for i in range(3):
            self.place("Team note %d" % i, "employment", ["team"], ["MOC — People"])
        for i in range(3):
            self.place("Other note %d" % i, "idea", ["misc"], ["MOC — Everything Else"])

    def inspect(self, *args):
        p = subprocess.run([sys.executable, str(SCRIPTS / "inspect_vault.py"),
                            str(self.vault), *args],
                           capture_output=True, text=True, env=self.env)
        return p.returncode, p.stdout + p.stderr

    def inspect_json(self):
        rc, out = self.inspect("--json")
        self.assertEqual(rc, 0, out)
        return json.loads(out)

    # ---- the empty case --------------------------------------------------
    def test_empty_vault_is_reported_as_safe_to_propose_over(self):
        rc, out = self.inspect()
        self.assertEqual(rc, 0, out)
        self.assertIn("no notes", out)
        self.assertIn("Safe to propose", out)

    def test_empty_vault_has_no_derived_topics(self):
        res = self.inspect_json()
        self.assertFalse(res["populated"])
        self.assertNotIn("derived_topics", res)

    # ---- the case that shipped broken ------------------------------------
    def test_populated_vault_is_detected(self):
        self.organised_vault()
        res = self.inspect_json()
        self.assertTrue(res["populated"])
        self.assertEqual(res["note_count"], 10)

    def test_existing_hubs_are_reported(self):
        self.organised_vault()
        res = self.inspect_json()
        self.assertEqual(sorted(res["existing_hubs"]),
                         ["MOC — Everything Else", "MOC — Money", "MOC — People"])

    def test_output_warns_that_a_new_taxonomy_would_delete_them(self):
        self.organised_vault()
        rc, out = self.inspect()
        self.assertIn("ALREADY ORGANISED", out)
        self.assertIn("would delete every hub", out)
        self.assertIn("Ask before doing that", out)

    def test_derived_topics_keep_the_existing_hub_names(self):
        """The whole point: adopt what is there, do not invent replacements."""
        self.organised_vault()
        res = self.inspect_json()
        titles = {t["title"] for t in res["derived_topics"]}
        self.assertEqual(titles, set(res["existing_hubs"]))

    def test_derived_topics_reproduce_the_existing_grouping(self):
        self.organised_vault()
        res = self.inspect_json()
        self.assertEqual(res["reproduction"]["percent"], 100.0,
                         res["reproduction"]["moved"])

    def test_exactly_one_fallback_is_derived(self):
        self.organised_vault()
        res = self.inspect_json()
        fb = [t for t in res["derived_topics"] if t.get("fallback")]
        self.assertEqual(len(fb), 1, res["derived_topics"])

    def test_derived_topics_are_a_valid_config(self):
        """Derivation is worthless if the result will not load."""
        import config
        self.organised_vault()
        res = self.inspect_json()
        raw = json.loads((self.home / "config.json").read_text())
        raw["vaults"][0]["topics"] = res["derived_topics"]
        self.assertEqual(config.validate(raw), [])

    def test_reproduction_gap_is_reported_rather_than_hidden(self):
        """A vault with contradictory grouping cannot be reproduced exactly. Say so
        with the specific notes, instead of claiming success."""
        self.organised_vault()
        # Same type and tags as the Money notes, but filed elsewhere by hand.
        self.place("Contradictory", "insight", ["cost"], ["MOC — People"])
        res = self.inspect_json()
        rep = res["reproduction"]
        self.assertLess(rep["percent"], 100.0)
        self.assertTrue(rep["moved"])
        self.assertIn("from", rep["moved"][0])
        self.assertIn("to", rep["moved"][0])

    def test_private_notes_are_included_in_the_analysis(self):
        self.organised_vault()
        self.place("Secret", "employment", ["team"], ["MOC — People"], sub="05 Private")
        res = self.inspect_json()
        self.assertEqual(res["note_count"], 11)

    def test_user_authored_notes_are_ignored(self):
        """A note without our frontmatter is the user's own and says nothing about
        how the plugin organised anything."""
        self.organised_vault()
        d = self.vault / "01 Notes"
        (d / "Mine.md").write_text("# Just my own note\n", encoding="utf-8")
        res = self.inspect_json()
        self.assertEqual(res["note_count"], 10)

    def test_derived_and_generated_hubs_do_not_collide_with_entity_notes(self):
        self.organised_vault()
        (self.vault / "03 People").mkdir(parents=True, exist_ok=True)
        (self.vault / "03 People" / "Someone.md").write_text(
            "---\ntitle: Someone\ntype: person\n---\n", encoding="utf-8")
        res = self.inspect_json()
        self.assertEqual(res["note_count"], 10)
        self.assertNotIn("Someone", res["existing_hubs"])


class MergeWarnsWhenHubsDisappear(FixtureCase):
    """Even with a hand-edited config, losing a hub must not pass silently."""

    def setUp(self):
        super().setUp()
        self.sid = self.add_transcript(
            [("user", "we decided to drop the vendor for cost reasons")],
            title="A decision")
        self.scan()
        self.stage("main", "A Decision.md",
                   note("A Decision", "we decided to drop the vendor for cost reasons",
                        source_session=self.sid, ntype="decision", tags="[cost]"))
        self.merge()

    def test_removing_a_topic_from_config_is_reported_by_name(self):
        self.assertIn("MOC — Decisions.md", self.vault_files("02 Topics"))
        # Drop that hub from the config, as a careless edit would.
        self.write_config(vaults=[{
            "id": "main", "path": str(self.vault), "watch": [str(self.proj)],
            "documents": [str(self.docs)],
            "topics": [{"title": "MOC — Everything Else", "fallback": True}]}])
        rc, out = self.merge()
        self.assertEqual(rc, 0, out)
        self.assertIn("topic hub(s) no longer exist", out)
        self.assertIn("MOC — Decisions", out)
        self.assertIn("has been regrouped", out)


if __name__ == "__main__":
    unittest.main()
