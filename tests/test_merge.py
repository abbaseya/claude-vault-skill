#!/usr/bin/env python
"""Merge must be safe to run repeatedly, and must never damage what it did not write.

The failure modes that matter here are quiet ones: a second run silently
rewriting notes, a private note landing in the open folder, a user's own note
being clobbered by a regeneration pass, or a link that resolves to nothing.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FixtureCase, note  # noqa: E402

Q1 = "we should drop the vendor and build it ourselves"
Q2 = "the pay band for this role is the blocker"
Q3 = "hosting cost doubled after the migration"
TURNS = [
    ("user", "I think %s, the licence cost is absurd." % Q1),
    ("assistant", "Noted."),
    ("user", "Also %s." % Q2),
    ("user", "And %s." % Q3),
]


class MergeBehaviour(FixtureCase):

    def setUp(self):
        super().setUp()
        self.sid = self.add_transcript(TURNS, title="Vendor decision")
        self.scan()

    def stage_three(self):
        self.stage("main", "Drop The Vendor.md",
                   note("Drop The Vendor", Q1, source_session=self.sid,
                        ntype="decision", tags="[vendor]"))
        self.stage("main", "Pay Band Is The Blocker.md",
                   note("Pay Band Is The Blocker", Q2, source_session=self.sid,
                        ntype="employment", sensitivity="private", tags="[hiring]"))
        self.stage("main", "Hosting Cost Doubled.md",
                   note("Hosting Cost Doubled", Q3, source_session=self.sid,
                        ntype="insight", tags="[cost]"))

    def test_merge_files_notes_by_sensitivity(self):
        self.stage_three()
        rc, out = self.merge()
        self.assertEqual(rc, 0, out)
        self.assertIn("Drop The Vendor.md", self.vault_files("01 Notes"))
        self.assertIn("Hosting Cost Doubled.md", self.vault_files("01 Notes"))
        # The private one must NOT be sitting in the open folder.
        self.assertIn("Pay Band Is The Blocker.md", self.vault_files("05 Private"))
        self.assertNotIn("Pay Band Is The Blocker.md", self.vault_files("01 Notes"))

    def test_topics_come_from_config_not_from_code(self):
        self.stage_three()
        self.merge()
        topics = self.vault_files("02 Topics")
        self.assertIn("MOC — Decisions.md", topics)
        self.assertIn("MOC — Money.md", topics)          # matched by the `cost` tag
        self.assertIn("MOC — Everything Else.md", topics)  # fallback caught `employment`

    def test_fallback_topic_catches_orphans(self):
        """A note matching no topic rule must still be reachable."""
        self.stage("main", "Orphan.md",
                   note("Orphan", Q1, source_session=self.sid,
                        ntype="pitch", tags="[nothing-matches-this]"))
        self.merge()
        text = (self.vault / "02 Topics" / "MOC — Everything Else.md").read_text()
        self.assertIn("[[Orphan]]", text)

    def test_merge_is_idempotent(self):
        self.stage_three()
        self.merge()
        before = self.snapshot()
        rc, out = self.merge()                # nothing newly staged
        self.assertEqual(rc, 0, out)
        after = self.snapshot()
        self.assertEqual(before, after, "second merge changed the vault")

    def test_rerun_does_not_duplicate_notes(self):
        self.stage_three()
        self.merge()
        self.stage_three()                    # same filenames staged again
        rc, out = self.merge()
        self.assertEqual(rc, 0, out)
        self.assertIn("skip (already in vault)", out)
        self.assertEqual(len(self.vault_files("01 Notes")), 2)

    def test_user_authored_notes_are_never_touched(self):
        self.stage_three()
        self.merge()
        mine = self.vault / "01 Notes" / "My Own Thoughts.md"
        mine.write_text("# Mine\n\nI wrote this by hand.\n", encoding="utf-8")
        inbox = self.vault / "00 Inbox" / "Scratch.md"
        inbox.parent.mkdir(parents=True, exist_ok=True)
        inbox.write_text("scratch\n", encoding="utf-8")
        self.merge()
        self.assertEqual(mine.read_text(), "# Mine\n\nI wrote this by hand.\n")
        self.assertEqual(inbox.read_text(), "scratch\n")

    def test_moved_notes_are_not_moved_back(self):
        """If the user reorganises, merge must respect it."""
        self.stage_three()
        self.merge()
        src = self.vault / "01 Notes" / "Drop The Vendor.md"
        dst = self.vault / "01 Notes" / "Archive"
        dst.mkdir(parents=True, exist_ok=True)
        moved = dst / "Drop The Vendor.md"
        moved.write_text(src.read_text(), encoding="utf-8")
        src.unlink()
        self.merge()
        self.assertTrue(moved.is_file(), "merge lost a note the user had moved")
        self.assertFalse(src.exists(), "merge moved the note back")

    def test_entities_are_learned_not_shipped(self):
        self.stage("main", "With Entities.md",
                   note("With Entities", Q1, source_session=self.sid,
                        extra_links="\nRelated: [[Acme Corp]], [[Dana Fields]]\n"))
        rc, out = self.merge()
        self.assertEqual(rc, 0, out)
        ents = json.loads((self.home / "entities.json").read_text())
        self.assertIn("Acme Corp", ents)
        self.assertIn("Dana Fields", ents)
        self.assertEqual(ents["Acme Corp"]["kind"], "unknown")
        # Unclassified entities get a note so the link resolves, but are not
        # guessed into People or Companies.
        self.assertIn("Acme Corp.md", self.vault_files("07 Entities"))
        self.assertIn("2 new entities", out)

    def test_classified_entities_move_to_their_folder(self):
        self.stage("main", "With Entities.md",
                   note("With Entities", Q1, source_session=self.sid,
                        extra_links="\nRelated: [[Acme Corp]], [[Dana Fields]]\n"))
        self.merge()
        ents = json.loads((self.home / "entities.json").read_text())
        ents["Acme Corp"] = {"kind": "org", "description": "A supplier."}
        ents["Dana Fields"] = {"kind": "person", "description": "Procurement lead."}
        (self.home / "entities.json").write_text(json.dumps(ents), encoding="utf-8")
        self.merge()
        self.assertIn("Acme Corp.md", self.vault_files("04 Companies"))
        self.assertIn("Dana Fields.md", self.vault_files("03 People"))
        self.assertEqual(self.vault_files("07 Entities"), [])

    def test_user_files_in_the_meta_folder_survive(self):
        """We regenerate the index into 99 Meta, but users keep their own docs
        there. Reconciling that folder would delete them."""
        self.stage_three()
        self.merge()
        mine = self.vault / "99 Meta" / "My Reading List.md"
        mine.write_text("# Reading list\n", encoding="utf-8")
        self.merge()
        self.assertTrue(mine.is_file(), "merge deleted a user's file from 99 Meta")

    def test_no_dangling_links_after_merge(self):
        self.stage("main", "With Entities.md",
                   note("With Entities", Q1, source_session=self.sid,
                        extra_links="\nRelated: [[Acme Corp]]\n"))
        self.merge()
        stems = {p.stem for p in self.vault.rglob("*.md")}
        import re
        dangling = set()
        for p in self.vault.rglob("*.md"):
            for t in re.findall(r"\[\[([^\]|#]+)", p.read_text(encoding="utf-8")):
                if t.strip() not in stems:
                    dangling.add(t.strip())
        self.assertEqual(dangling, set(), "vault has unresolved links")

    def test_provenance_stub_links_back_to_its_notes(self):
        self.stage_three()
        self.merge()
        stubs = self.vault_files("06 Sessions")
        self.assertEqual(len(stubs), 1)
        text = (self.vault / "06 Sessions" / stubs[0]).read_text()
        self.assertIn("[[Drop The Vendor]]", text)
        self.assertIn(self.sid, text)
        self.assertTrue(stubs[0].startswith("2026-01-15 — "), stubs[0])

    def test_titles_with_colons_do_not_mangle_filenames(self):
        """A YAML value containing a colon is legally quoted; the quotes are not
        part of the value and must not become dashes in the filename."""
        body = note("Colon Case", Q1, source_session=self.sid,
                    source_title='"Vendor: the decision"')
        self.stage("main", "Colon Case.md", body)
        self.merge()
        stubs = self.vault_files("06 Sessions")
        self.assertTrue(stubs, "no provenance stub written")
        for s in stubs:
            self.assertFalse(s.startswith("-"), s)
            self.assertNotIn("--", s)
            self.assertFalse(s.endswith("-.md"), s)

    def test_state_records_the_session_only_after_a_successful_merge(self):
        self.stage_three()
        self.merge()
        state = json.loads((self.home / "state.json").read_text())
        self.assertIn(self.sid, state["processed"])

    def test_merge_refuses_when_verification_fails(self):
        self.stage("main", "Fabricated.md",
                   note("Fabricated", "a sentence nobody ever typed anywhere",
                        source_session=self.sid))
        rc, out = self.merge()
        self.assertNotEqual(rc, 0)
        self.assertIn("Aborted", out)
        self.assertEqual(self.vault_files("01 Notes"), [],
                         "a note reached the vault despite verification failing")
        self.assertFalse((self.home / "state.json").is_file(),
                         "state was advanced despite an aborted merge")

    def test_merge_refuses_on_invalid_config(self):
        self.write_config(vaults=[])
        rc, out = self.merge()
        self.assertEqual(rc, 2)
        self.assertIn("NO_CONFIG / INVALID CONFIG", out)


if __name__ == "__main__":
    unittest.main()
