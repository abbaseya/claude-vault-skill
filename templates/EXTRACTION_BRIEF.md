# Extraction brief — Claude Code sessions → Obsidian notes

You are extracting notes from {{USER_NAME}}'s work sessions into an Obsidian vault.
Pronouns: {{PRONOUNS}}.

## Absolute rules

1. **NEVER invent a quote.** Every blockquote must be copied **character-exact**
   from the source file. A verification pass greps each quote back against the raw
   transcript; anything that does not match is rejected and the whole merge is
   refused. If you are unsure a quote is exact, re-read the line. Do not
   reconstruct, tidy, correct a typo, or fix punctuation inside a quote.
2. **Prefer {{USER_NAME}}'s own words.** In digests their turns are marked
   `### USER hh:mm`; the assistant's are `### CLAUDE hh:mm`. Quote USER text by
   default. Quote CLAUDE prose only when it states a conclusion they then acted on,
   and attribute it `— Claude, <date>` rather than to them.
3. **Stay in scope.**
   - IN: {{SCOPE_INCLUDE}}
   - OUT: {{SCOPE_EXCLUDE}}
4. **One idea per note.** If a note needs "and" between two unrelated claims, split it.
5. **Never write outside your assigned staging directory.** Do not touch the vault
   itself, the transcripts, or anything under `~/.claude/`. Those are read-only.

## Note format — exactly this

Filename: the note title. Title Case. Max ~80 characters. Strip these characters
from filenames: `/ \ : * ? " < > |` (an em-dash ` — ` is fine).

```markdown
---
title: The Claim, Stated Plainly
type: decision
date: 2026-01-15
tags: [project-x, vendor, cost]
people: ["[[A Colleague]]"]
entities: ["[[Some Company]]"]
sensitivity: normal
source_session: 0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0
source_title: Choosing a billing provider
fidelity: verbatim
---

One to three sentences in plain prose stating the claim. This is your own
wording, and it is what a reader sees first.

> "the exact text as it appears in the source, copied not retyped"
> — {{USER_NAME}}, 2026-01-15, Choosing a billing provider

One to three sentences of context: why it matters, or what followed.

Related: [[Another Note]], [[Some Company]]
```

For a note sourced from a document rather than a session, replace the two source
fields with:

```
source_doc: NOTES-ON-VENDORS.md
source_title: Notes on vendors
```

### Field rules

- `type`: one of {{NOTE_TYPES}}
- `date`: for sessions, the `start:` value in the digest's frontmatter (YYYY-MM-DD).
  For documents, run `stat -f '%Sm' -t '%Y-%m-%d' <path>` (macOS) or
  `date -r <path> '+%Y-%m-%d'` (Linux).
- `tags`: 2–5 lowercase, hyphenated.
- `people` / `entities`: wikilinks. **Use a name exactly as it appears in the
  source, and use the same spelling every time** — consistency is what makes the
  graph work. Omit the key entirely if empty. Never guess who someone is.
- `sensitivity`: `private` when the note touches any of these —
{{PRIVATE_WHEN}}
  Otherwise `normal`. Judge each note on its merits; do not blanket-mark.
- `fidelity`: always `verbatim`.

## Body shape

1. **Synthesis** — 1–3 sentences stating the claim, in your words.
2. **The verbatim blockquote** with its attribution line.
3. **Optional context** — 1–3 sentences.
4. **`Related:`** — 1–4 wikilinks to sibling notes or entities.

## How many notes

Judge by substance, not volume. A dense strategy session may yield 8–12 notes; a
short exchange may yield one. **Do not pad.** A source with no in-scope content
yields zero notes — say so in your manifest and move on.

## Your return value

Do not return note bodies. Return a compact manifest:

```
WROTE <n> notes to <dir>
- <filename> | <type> | <sensitivity>
SKIPPED: <source> — <reason>
NOTES: <ambiguous routing, a quote you could not verify, anything worth knowing>
```
