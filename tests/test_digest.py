#!/usr/bin/env python
"""The digest must keep the conversation and drop everything else.

Two failure directions, both bad. Keeping too much means tool output, file dumps
and subagent chatter become quotable — so a note could "quote" something the
user never said. Keeping too little means real turns disappear and the extraction
never sees them.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from digest import digest_session  # noqa: E402
from harness import FixtureCase, transcript  # noqa: E402


class Digest(FixtureCase):

    def digest_of(self, turns, **kw):
        text, sid = transcript(turns, cwd=str(self.proj), **kw)
        src = self.projects / (sid + ".jsonl")
        src.write_text(text, encoding="utf-8")
        out = self.tmp / "digests"
        meta = digest_session(src, out)
        return meta, (out / (sid + ".md")).read_text(encoding="utf-8")

    def test_user_text_is_preserved_byte_exact(self):
        odd = "we shouldn't  ship — the cost is 2×, and \"maybe\" isn't a plan"
        _, d = self.digest_of([("user", odd)])
        self.assertIn(odd, d)

    def test_assistant_prose_is_kept(self):
        _, d = self.digest_of([("assistant", "That trade-off only holds under load.")])
        self.assertIn("That trade-off only holds under load.", d)

    def test_tool_calls_and_results_are_dropped(self):
        _, d = self.digest_of([("user", "run it"), ("tool", "cat /etc/passwd")])
        self.assertNotIn("SECRET_TOOL_OUTPUT", d)
        self.assertNotIn("/etc/passwd", d)

    def test_subagent_sidechains_are_dropped(self):
        _, d = self.digest_of([("user", "go"),
                               ("sidechain", "SUBAGENT_CHATTER should not survive")])
        self.assertNotIn("SUBAGENT_CHATTER", d)

    def test_meta_turns_are_dropped(self):
        _, d = self.digest_of([("user", "go"), ("meta", "HARNESS_NOISE")])
        self.assertNotIn("HARNESS_NOISE", d)

    def test_system_reminders_are_stripped(self):
        _, d = self.digest_of([
            ("user", "real question\n<system-reminder>INJECTED</system-reminder>")])
        self.assertIn("real question", d)
        self.assertNotIn("INJECTED", d)

    def test_command_stdout_is_stripped(self):
        _, d = self.digest_of([
            ("user", "<local-command-stdout>NOISE</local-command-stdout>ask")])
        self.assertNotIn("NOISE", d)

    def test_slash_command_name_is_kept_as_a_marker(self):
        """Which command ran is useful triage context; its expansion is not."""
        _, d = self.digest_of([
            ("user", "<command-name>/deploy</command-name>"
                     "<command-args>--prod</command-args>")])
        self.assertIn("[/deploy]", d)
        self.assertNotIn("--prod", d)

    def test_long_code_blocks_are_elided(self):
        code = "```\n" + "\n".join("line %d" % i for i in range(40)) + "\n```"
        _, d = self.digest_of([("assistant", "Here you go:\n" + code)])
        self.assertIn("code block omitted", d)
        self.assertNotIn("line 39", d)

    def test_short_code_blocks_are_kept(self):
        _, d = self.digest_of([("assistant", "Use:\n```\nyarn build\n```")])
        self.assertIn("yarn build", d)

    def test_frontmatter_records_what_triage_needs(self):
        meta, d = self.digest_of([("user", "hello")], title="A title")
        self.assertIn("title: A title", d)
        self.assertIn("cwd: %s" % self.proj, d)
        self.assertEqual(meta["user_turns"], 1)
        self.assertEqual(meta["cwd"], str(self.proj))

    def test_turns_are_labelled_by_speaker(self):
        _, d = self.digest_of([("user", "mine"), ("assistant", "theirs")])
        self.assertIn("### USER", d)
        self.assertIn("### CLAUDE", d)

    def test_session_with_no_real_turns_produces_nothing(self):
        text, sid = transcript([("tool", "ls")], cwd=str(self.proj))
        src = self.projects / (sid + ".jsonl")
        src.write_text(text, encoding="utf-8")
        self.assertIsNone(digest_session(src, self.tmp / "digests"))

    def test_malformed_lines_do_not_abort_the_digest(self):
        text, sid = transcript([("user", "still here")], cwd=str(self.proj))
        src = self.projects / (sid + ".jsonl")
        src.write_text("{not json\n" + text + "\ngarbage\n", encoding="utf-8")
        meta = digest_session(src, self.tmp / "digests")
        self.assertIsNotNone(meta)
        self.assertIn("still here",
                      (self.tmp / "digests" / (sid + ".md")).read_text())

    def test_digest_is_far_smaller_than_the_transcript(self):
        turns = [("user", "a real question about the plan")]
        turns += [("tool", "x" * 400)] * 30
        text, sid = transcript(turns, cwd=str(self.proj))
        src = self.projects / (sid + ".jsonl")
        src.write_text(text, encoding="utf-8")
        digest_session(src, self.tmp / "digests")
        raw = src.stat().st_size
        got = (self.tmp / "digests" / (sid + ".md")).stat().st_size
        self.assertLess(got, raw * 0.5, "digest kept too much of the transcript")


if __name__ == "__main__":
    unittest.main()
