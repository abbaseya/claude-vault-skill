#!/usr/bin/env python
"""The verification gate must actually reject fabricated quotes.

This is the load-bearing test in the repo. Everything my-vault promises reduces
to one claim: a quote in your vault is text that was really written. A verifier
that passes a fabricated quote turns the whole tool into a confident liar, and a
green test run would say it was fine.

So each case plants one specific defect and asserts verification FAILS.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FixtureCase, note  # noqa: E402

REAL = "we should drop the vendor and build it ourselves"
TURNS = [
    ("user", "I think %s, the licence cost is absurd." % REAL),
    ("assistant", "That trade-off holds if the build is under two weeks."),
    ("tool", "ls -la"),
    ("sidechain", "A subagent said something that is not in the conversation."),
    ("meta", "Injected harness noise."),
]


class VerifyGate(FixtureCase):

    def setUp(self):
        super().setUp()
        self.sid = self.add_transcript(TURNS, title="Vendor decision")
        self.scan()                       # produces the digest verify reads

    def test_exact_quote_passes(self):
        self.stage("main", "Drop The Vendor.md",
                   note("Drop The Vendor", REAL, source_session=self.sid))
        rc, out = self.verify()
        self.assertEqual(rc, 0, out)
        self.assertIn("PASS", out)

    def test_fabricated_quote_fails(self):
        self.stage("main", "Fabricated.md",
                   note("Fabricated", "we should absolutely drop this vendor immediately",
                        source_session=self.sid))
        rc, out = self.verify()
        self.assertEqual(rc, 1, out)
        self.assertIn("QUOTE NOT IN SOURCE", out)

    def test_subtly_altered_quote_fails(self):
        """One changed word. This is what a 'helpful' tidy-up looks like."""
        altered = REAL.replace("drop", "dropping")
        self.stage("main", "Altered.md",
                   note("Altered", altered, source_session=self.sid))
        rc, out = self.verify()
        self.assertEqual(rc, 1, out)
        self.assertIn("QUOTE NOT IN SOURCE", out)

    def test_quote_from_stripped_tool_output_fails(self):
        """Tool output is not conversation. Quoting it must not pass."""
        self.stage("main", "FromTool.md",
                   note("FromTool", "SECRET_TOOL_OUTPUT ls -la", source_session=self.sid))
        rc, out = self.verify()
        self.assertEqual(rc, 1, out)

    def test_quote_from_sidechain_fails(self):
        """Subagent chatter is not the user's session and must not be quotable."""
        self.stage("main", "FromSidechain.md",
                   note("FromSidechain",
                        "A subagent said something that is not in the conversation.",
                        source_session=self.sid))
        rc, out = self.verify()
        self.assertEqual(rc, 1, out)

    def test_unknown_session_fails(self):
        self.stage("main", "Ghost.md",
                   note("Ghost", REAL,
                        source_session="s9999999-0000-4000-8000-999999999999"))
        rc, out = self.verify()
        self.assertEqual(rc, 1, out)
        self.assertIn("digest missing", out)

    def test_missing_frontmatter_fails(self):
        self.stage("main", "Bare.md", "Just a body with no frontmatter.\n")
        rc, out = self.verify()
        self.assertEqual(rc, 1, out)
        self.assertIn("NO FRONTMATTER", out)

    def test_unknown_note_type_fails(self):
        self.stage("main", "BadType.md",
                   note("BadType", REAL, source_session=self.sid, ntype="musings"))
        rc, out = self.verify()
        self.assertEqual(rc, 1, out)
        self.assertIn("bad type", out)

    def test_unknown_sensitivity_fails(self):
        self.stage("main", "BadSens.md",
                   note("BadSens", REAL, source_session=self.sid, sensitivity="secret"))
        rc, out = self.verify()
        self.assertEqual(rc, 1, out)
        self.assertIn("bad sensitivity", out)

    def test_notes_staged_for_unknown_vault_fail(self):
        self.stage("nosuchvault", "Stray.md",
                   note("Stray", REAL, source_session=self.sid))
        rc, out = self.verify()
        self.assertEqual(rc, 1, out)
        self.assertIn("unknown vault id", out)

    def test_document_sourced_quote_verifies_against_the_document(self):
        (self.docs / "PLAN.md").write_text(
            "# Plan\n\nWe agreed to ship the smaller version first.\n", encoding="utf-8")
        self.stage("main", "Ship Smaller.md",
                   note("Ship Smaller", "We agreed to ship the smaller version first.",
                        source_doc="PLAN.md"))
        rc, out = self.verify()
        self.assertEqual(rc, 0, out)

    def test_document_quote_not_in_document_fails(self):
        (self.docs / "PLAN.md").write_text("# Plan\n\nSomething else.\n", encoding="utf-8")
        self.stage("main", "Wrong.md",
                   note("Wrong", "We agreed to ship the smaller version first.",
                        source_doc="PLAN.md"))
        rc, out = self.verify()
        self.assertEqual(rc, 1, out)

    def test_missing_document_fails(self):
        self.stage("main", "NoDoc.md",
                   note("NoDoc", "anything at all here", source_doc="ABSENT.md"))
        rc, out = self.verify()
        self.assertEqual(rc, 1, out)
        self.assertIn("source_doc not found", out)

    def test_quote_wrapped_in_markdown_emphasis_still_matches(self):
        """Notes wrap quotes in punctuation the source lacks. That must not
        be mistaken for fabrication — a false positive here is as bad as a miss."""
        body = note("Emphasised", REAL, source_session=self.sid)
        body = body.replace('> "%s"' % REAL, '> **"%s"**' % REAL)
        self.stage("main", "Emphasised.md", body)
        rc, out = self.verify()
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
