---
name: setup
description: Configure my-vault — find the user's Obsidian vault, map project folders to it, and write the configuration. Run on first use or to change the setup.
disable-model-invocation: true
---

# my-vault setup

Walk the user through configuring `my-vault`. **Assume they have never opened a
terminal and do not know what JSON is.** Never show them raw JSON unless they ask.
Ask one thing at a time. Offer numbered choices rather than free text wherever you can.

If a config already exists, say what it currently does in plain language and ask
what they want to change, rather than starting over.

## 1. Find their vault

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/detect.py" --json
```

This reads Obsidian's own registry of vaults it has opened, and falls back to
scanning for `.obsidian` folders.

- **One vault found** — confirm it: *"I found your Obsidian vault called X at Y. Is
  that the one you want to use?"*
- **Several found** — show a numbered list and ask which. They can pick more than one;
  each gets its own entry.
- **None found** — do not guess a path. Tell them: *"I couldn't find an Obsidian
  vault. If you haven't made one yet, open Obsidian, choose 'Create new vault', pick
  a name and a folder, then tell me you're done. If you already have one, paste the
  folder path here."*

## 2. Map folders to the vault

The `watch` list decides which working directories belong to which vault. The
`--json` output includes likely project folders and the git repos inside them.

Ask: *"Which folders do you work in that should feed this vault?"* Offer the detected
ones as numbered options, and accept a typed path.

With two or more vaults, do this per vault and make sure the paths do not overlap
ambiguously. Longest match wins, so a nested folder can legitimately override a
broader one — but say so if you set that up.

## 3. Ask their name

*"What name should notes use when they quote you?"* Used in quote attributions.

## 4. Choose what gets captured

Offer these as numbered options — do not ask them to write a definition:

| Preset | Captures |
|---|---|
| `everything-except-technical` | Decisions, reasoning, business, strategy, ideas, lessons. No code or implementation detail. |
| `work-knowledge` | Decisions and their reasoning, direction, trade-offs, commitments, lessons. |
| `business-and-strategy` | Commercial matters, pitches, negotiations, positioning, pricing. |
| `research` | Findings, sources, hypotheses, arguments, conclusions with evidence. |
| Custom | They describe it; you write `include` and `exclude`. |

## 5. Ask what is sensitive

*"Is there anything you'd want kept in a separate, clearly-marked folder — pay,
contracts, anything about specific people?"*

Offer the defaults, let them add or remove. These become `sensitivity.private_when`,
and matching notes are filed in the private folder rather than mixed in.

## 6. Suggest topics

Topics are the hubs that group notes. Propose a starting set based on what they said
in steps 4 and 5, using the template at
`${CLAUDE_PLUGIN_ROOT}/templates/config.default.json` as the shape.

Tell them these are a starting point and will be refined once there are real notes to
look at. **Exactly one topic must have `"fallback": true`** so nothing is ever
orphaned.

## 7. Write the config and create the folders

Write to the path printed by:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/config.py"
```

Then create the vault's folders, and verify:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/config.py"
```

It exits non-zero and prints every problem if anything is wrong. Fix and re-run until
it is clean. **Do not tell the user setup succeeded until it exits 0.**

## 8. Offer a first run

*"Setup's done. Want me to look at your recent sessions now and show you what's
worth keeping?"* If yes, hand off to `/my-vault:sync`.

Mention once, plainly: Claude Code deletes transcripts after about 30 days by
default, so anything not captured before then is gone. If they want to keep them
longer they can set `cleanupPeriodDays` in `~/.claude/settings.json` — offer to do it,
do not do it unasked.
