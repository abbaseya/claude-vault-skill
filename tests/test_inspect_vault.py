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


class DerivationUnits(FixtureCase):
    """Direct tests for the derivation functions.

    The cases above drive everything through the CLI, which proves the whole path
    works but says nothing about the edges — a hub with one note, a tag that
    appears once, a note filed under nothing. Those are cheap to reach here and
    awkward to reach through a subprocess.
    """

    def setUp(self):
        super().setUp()
        import inspect_vault
        self.iv = inspect_vault
        self.folders = __import__("config").DEFAULT_FOLDERS

    # ---- unquote ---------------------------------------------------------
    def test_unquote_strips_a_quoted_yaml_value(self):
        self.assertEqual(self.iv.unquote('"Vendor: the decision"'),
                         "Vendor: the decision")

    def test_unquote_leaves_a_bare_value_alone(self):
        self.assertEqual(self.iv.unquote("  plain value  "), "plain value")

    def test_unquote_does_not_strip_mismatched_quotes(self):
        self.assertEqual(self.iv.unquote('"unbalanced'), '"unbalanced')

    # ---- read_notes ------------------------------------------------------
    def write_note(self, sub, title, ntype, tags, hubs, ours=True):
        d = self.vault / sub
        d.mkdir(parents=True, exist_ok=True)
        if ours:
            body = note(title, "quote text here", source_session="s1",
                        ntype=ntype, tags="[%s]" % ", ".join(tags))
        else:
            body = "---\ntitle: %s\n---\n\nmine\n" % title
        if hubs:
            body += "\n\nUp: " + ", ".join("[[%s]]" % h for h in hubs) + "\n"
        (d / (title + ".md")).write_text(body, encoding="utf-8")

    def test_read_notes_extracts_type_tags_and_hubs(self):
        self.write_note("01 Notes", "A", "decision", ["cost", "vendor"], ["MOC — X"])
        got = self.iv.read_notes(self.vault, self.folders)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["type"], "decision")
        self.assertEqual(got[0]["tags"], ["cost", "vendor"])
        self.assertEqual(got[0]["hubs"], ["MOC — X"])

    def test_read_notes_skips_notes_without_our_frontmatter(self):
        self.write_note("01 Notes", "Mine", "decision", [], [], ours=False)
        self.assertEqual(self.iv.read_notes(self.vault, self.folders), [])

    def test_read_notes_skips_the_derived_folders(self):
        self.write_note("02 Topics", "A Hub", "decision", ["x"], [])
        self.write_note("03 People", "Someone", "decision", ["x"], [])
        self.assertEqual(self.iv.read_notes(self.vault, self.folders), [])

    def test_read_notes_handles_a_note_in_no_hub(self):
        self.write_note("01 Notes", "Orphan", "idea", ["x"], [])
        got = self.iv.read_notes(self.vault, self.folders)
        self.assertEqual(got[0]["hubs"], [])

    # ---- derive_topics ---------------------------------------------------
    def notes(self, spec):
        return [{"title": t, "type": ty, "tags": tg, "hubs": h}
                for t, ty, tg, h in spec]

    def test_derive_topics_promotes_a_dominant_tag_to_a_rule(self):
        ns = self.notes([("a", "insight", ["cost"], ["Money"]),
                         ("b", "insight", ["cost"], ["Money"]),
                         ("c", "idea", ["misc"], ["Other"])])
        topics = self.iv.derive_topics(ns, ["Money", "Other"])
        money = next(t for t in topics if t["title"] == "Money")
        self.assertIn("cost", money["tags"])

    def test_derive_topics_ignores_a_tag_seen_only_once(self):
        """One occurrence is not evidence of a rule."""
        ns = self.notes([("a", "insight", ["oneoff"], ["Money"]),
                         ("b", "idea", ["misc"], ["Other"]),
                         ("c", "idea", ["misc"], ["Other"])])
        topics = self.iv.derive_topics(ns, ["Money", "Other"])
        money = next(t for t in topics if t["title"] == "Money")
        self.assertNotIn("oneoff", money["tags"])

    def test_derive_topics_marks_exactly_one_fallback(self):
        ns = self.notes([("a", "insight", ["cost"], ["Money"]),
                         ("b", "idea", ["misc"], ["Other"]),
                         ("c", "idea", ["misc"], ["Other"])])
        topics = self.iv.derive_topics(ns, ["Money", "Other"])
        self.assertEqual(sum(1 for t in topics if t.get("fallback")), 1)

    def test_derive_topics_keeps_only_hubs_that_have_members(self):
        ns = self.notes([("a", "insight", ["cost"], ["Money"])])
        topics = self.iv.derive_topics(ns, ["Money", "AbandonedEmptyHub"])
        self.assertEqual([t["title"] for t in topics], ["Money"])

    def test_derive_topics_returns_empty_for_no_notes(self):
        self.assertEqual(self.iv.derive_topics([], []), [])

    # ---- simulate --------------------------------------------------------
    def test_simulate_reports_full_reproduction_when_rules_match(self):
        ns = self.notes([("a", "insight", ["cost"], ["Money"]),
                         ("b", "idea", ["misc"], ["Other"])])
        topics = [{"title": "Money", "types": [], "tags": ["cost"]},
                  {"title": "Other", "types": [], "tags": [], "fallback": True}]
        rep = self.iv.simulate(ns, topics, self.folders)
        self.assertEqual(rep["percent"], 100.0)
        self.assertEqual(rep["moved"], [])

    def test_simulate_names_the_notes_that_would_move(self):
        ns = self.notes([("a", "insight", ["cost"], ["Money"]),
                         ("b", "insight", ["cost"], ["Other"])])
        topics = [{"title": "Money", "types": [], "tags": ["cost"]},
                  {"title": "Other", "types": [], "tags": [], "fallback": True}]
        rep = self.iv.simulate(ns, topics, self.folders)
        self.assertEqual(rep["reproduced"], 1)
        self.assertEqual(rep["moved"][0]["title"], "b")
        self.assertEqual(rep["moved"][0]["from"], ["Other"])
        self.assertEqual(rep["moved"][0]["to"], ["Money"])

    def test_simulate_on_no_notes_does_not_divide_by_zero(self):
        rep = self.iv.simulate([], [], self.folders)
        self.assertEqual(rep["percent"], 100.0)
        self.assertEqual(rep["total"], 0)

    def test_derivation_round_trips_through_simulate(self):
        """Derive from observed grouping, then check the derivation reproduces it."""
        ns = self.notes([("a", "insight", ["cost"], ["Money"]),
                         ("b", "insight", ["cost"], ["Money"]),
                         ("c", "employment", ["team"], ["People"]),
                         ("d", "employment", ["team"], ["People"]),
                         ("e", "idea", ["misc"], ["Other"]),
                         ("f", "idea", ["misc"], ["Other"])])
        topics = self.iv.derive_topics(ns, ["Money", "People", "Other"])
        rep = self.iv.simulate(ns, topics, self.folders)
        self.assertEqual(rep["percent"], 100.0, rep["moved"])


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
