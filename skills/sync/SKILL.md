---
name: sync
description: Capture Claude Code sessions that are not yet in the Obsidian vault as atomic, verbatim-quoted notes. Manual only — never run unprompted.
disable-model-invocation: true
---

# my-vault sync

Capture sessions that are not yet in the vault as atomic, interlinked notes, each
anchored to a verbatim quote.

**This runs only when the user types `/my-vault:sync`.** Never offer to run it, never
run it as a side effect of finishing other work, and never write into a vault outside
this skill. What gets captured is their decision.

## 0. Config

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/config.py"
```

If it prints `NO_CONFIG`, this is a first run — hand off to `/my-vault:setup` and stop.
If it reports problems, show them in plain language and offer to fix them.

## 1. Scan

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py"
```

Finds every session whose transcript is new or has grown since the last capture,
digests each to roughly 2% of its raw size, and writes a triage sheet plus an
extraction brief filled in with this user's scope.

Flags: `--all` re-scan everything · `--since YYYY-MM-DD` · `--vault <id>`.

**If it reports nothing new, say so and stop.** Do not invent work.

## 2. Triage — you do this yourself, not a subagent

Read the triage sheet. For each session decide which vault it belongs to, or that it
is out of scope.

The `SIGNAL:` counts are a hint, not a verdict. A high `tech` count often still hides
one real decision; a session that is all routine status updates is usually noise even
when it scores well. `CWD:` tells you which vault a session most likely belongs to.

Read the full digest in `run/digests/<id>.md` for anything ambiguous.

**Show the user a table of your decisions and wait for confirmation** before
extracting. Include what you are dropping and why — a wrong drop is invisible
otherwise.

## 3. Extract

For each in-scope session, spawn a subagent whose prompt tells it to read
`run/EXTRACTION_BRIEF.md` first and follow it exactly. Give it the digest path, the
staging directory for its vault, and what to focus on.

Staging: `run/notes/<vault-id>/`.

Batch small sessions together; give a large or dense one its own agent. If a session
covers subjects belonging to different vaults, split it **by subject**. Cross-references
between vaults must be plain text, never wikilinks — **Obsidian links do not resolve
across vaults.**

## 4. Merge

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/merge.py"
```

Verifies every staged quote against its source, and session quotes against the raw
transcript as well. **It refuses to write anything if verification fails.** On pass it
files new notes by sensitivity, regenerates topic hubs, entity notes, provenance stubs,
the index and Home, then records the captured sessions.

To check without merging:
`python "${CLAUDE_PLUGIN_ROOT}/scripts/verify.py"`

## 5. Report

Tell the user:

- how many notes were added, per vault
- which sessions were captured and which were skipped, with reasons
- **any new unclassified entities** — offer to classify them. Read the notes that
  reference each one and set `kind` (`person` or `org`) and a one-line description
  in the entities file, **grounded only in what those notes say**. Never invent a
  role. Leave `kind: unknown` if the notes do not say.
- any judgement call worth a second look

## What this guarantees

- Every blockquote is character-exact from its source. A subagent claiming it verified
  its own output is a claim, not evidence — `merge.py` re-derives it independently, and
  a single mismatch aborts the whole merge.
- Quotes prefer the user's own words. Where a conclusion exists only in assistant prose
  they acted on, the attribution says `— Claude`.
- Notes already in the vault are never modified, moved or overwritten — including ones
  the user has edited or reorganised themselves.

## Watch out

Claude Code deletes transcripts after about 30 days by default. A session not captured
before then is gone: the prompts survive in `~/.claude/history.jsonl`, but with no
replies and no outcomes. If the user syncs infrequently, mention `cleanupPeriodDays`
once — and only change it if they ask.
