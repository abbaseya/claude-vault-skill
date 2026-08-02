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

### Also ask about documents — do not skip this

`watch` decides which *sessions* feed a vault. `documents` is separate: folders whose
`.md` files can be mined for notes alongside the sessions. It defaults to empty, and an
empty value is silent — nothing warns you that your working notes are being ignored.

Ask plainly: *"Do you keep written notes, plans or research as markdown files anywhere?
I can pull from those too, not just your sessions."*

- If yes, add those folders to `documents`. They are often the same folders as `watch`,
  so offer that as the easy answer.
- If they are not sure, describe what it means concretely: *"things like a NOTES.md or a
  planning doc sitting in a project folder."*
- If no, leave it empty and say so out loud, so it is a decision rather than a default.

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

## 6. Topics — LOOK AT THE VAULT BEFORE PROPOSING ANYTHING

Topics are the hubs that group notes. **Most people who want this already have a
vault, and some already ran an earlier version of this plugin.** Proposing a fresh
taxonomy over an organised vault deletes every existing hub and rewrites every note's
`Up:` line on the next sync. Nothing is lost, but nobody asked for it.

So inspect first, for **each** vault:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/inspect_vault.py" "<vault path>"
```

### If it reports the vault is not populated

No existing organisation to preserve. Propose a starting set based on what they said in
steps 4 and 5, using `${CLAUDE_PLUGIN_ROOT}/templates/config.default.json` as the shape.
Say these are a starting point that can be refined once there are real notes.

### If it reports the vault is ALREADY ORGANISED

Do **not** propose a fresh taxonomy. Show them what is there and offer a choice, using
**the numbers the script actually printed for their vault** — never numbers from an
example. The shape to follow, with placeholders:

> *"This vault already has &lt;N&gt; notes organised under &lt;M&gt; topics — &lt;first three hub
> names&gt;, and &lt;M-3&gt; more. I can keep that organisation (rules derived from your notes
> reproduce &lt;PERCENT&gt; of it&lt;, and K notes would move&gt;), or reorganise into fresh
> topics, which would replace all &lt;M&gt; hubs. Which would you prefer?"*

- **Keep it (default).** Use the `derived_topics` array from the `--json` output
  verbatim. Then relay the differences the script reports, and keep its distinction:
  notes that **gain** a hub are still reachable everywhere they are today, while notes
  that **move** drop out of one. Only the second kind needs their attention.
- **Reorganise.** Only on an explicit yes. Before writing the config, state how many
  hubs are deleted and how many notes change grouping.

**Never pick this silently.** A vault someone has curated is theirs.

### Either way

**Exactly one topic must have `"fallback": true`** so nothing is ever orphaned. The
config validator enforces this and will tell you if it is missing.

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
