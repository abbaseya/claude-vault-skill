#!/usr/bin/env python
"""Load, validate and resolve the user's my-vault configuration.

Everything user-specific lives in ONE file outside the plugin, because a plugin
update replaces the plugin directory. Config that lived inside it would be
deleted by the first `/plugin` update, taking the user's vault mapping with it.

    ~/.claude/my-vault/config.json     the configuration
    ~/.claude/my-vault/entities.json   people and orgs, learned over time
    ~/.claude/my-vault/state.json      which sessions have been captured
    ~/.claude/my-vault/run/            transient, cleared by each scan

Set MY_VAULT_HOME to point all of that somewhere else. The test suite relies on
this; so can anyone who keeps dotfiles elsewhere.
"""
import json
import os
import re
from pathlib import Path

CONFIG_VERSION = 1

SCOPE_PRESETS = {
    "everything-except-technical": {
        "include": ("Decisions, reasoning, business and commercial matters, strategy, "
                    "positioning, plans, ideas, lessons learned, working relationships, "
                    "and anything about why something was done."),
        "exclude": ("Technical implementation. No code, no pull-request mechanics, no CI, "
                    "no debugging steps, no API details, no stack traces. If a note is "
                    "about HOW something was built, it does not belong."),
    },
    "work-knowledge": {
        "include": ("Decisions and their reasoning, project direction, trade-offs "
                    "considered and rejected, commitments made, and lessons learned."),
        "exclude": ("Routine task execution, implementation detail, and anything that "
                    "would be obvious from reading the code or the ticket."),
    },
    "business-and-strategy": {
        "include": ("Business, commercial and financial matters, pitches, negotiations, "
                    "partnerships, competitive positioning, pricing, and strategy."),
        "exclude": ("Day-to-day execution, technical work, and operational detail."),
    },
    "research": {
        "include": ("Findings, sources, hypotheses, arguments, counter-arguments, "
                    "open questions, and conclusions with their evidence."),
        "exclude": ("Tooling, scripts, data-wrangling mechanics, and process logistics."),
    },
}

DEFAULT_FOLDERS = {
    "inbox": "00 Inbox",
    "notes": "01 Notes",
    "topics": "02 Topics",
    "people": "03 People",
    "orgs": "04 Companies",
    "private": "05 Private",
    "sources": "06 Sessions",
    # Entities we have seen referenced but cannot yet classify as a person or an
    # organisation. They live here rather than being guessed into the wrong folder,
    # and move once classified.
    "unsorted": "07 Entities",
    "meta": "99 Meta",
}

NOTE_TYPES = ["business", "pitch", "employment", "strategy", "idea", "decision", "insight"]
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def data_home():
    """Where the user's config and state live. Never inside the plugin."""
    override = os.environ.get("MY_VAULT_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "my-vault"


def config_path():
    return data_home() / "config.json"


def projects_dir():
    """Where Claude Code keeps session transcripts.

    Overridable via CLAUDE_PROJECTS_DIR so the test suite can run against
    fixture transcripts instead of the user's real history.
    """
    override = os.environ.get("CLAUDE_PROJECTS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "projects"


def expand(p):
    return Path(str(p)).expanduser()


class Vault:
    def __init__(self, raw, folders):
        self.id = raw.get("id") or ""
        self.name = raw.get("name") or self.id
        self.path = expand(raw.get("path", ""))
        self.watch = [expand(w) for w in raw.get("watch", [])]
        self.documents = [expand(d) for d in raw.get("documents", [])]
        self.topics = raw.get("topics") or []
        self.folders = dict(folders)
        self.folders.update(raw.get("folders") or {})

    def dir(self, key):
        return self.path / self.folders[key]

    def topics_for(self, note_type, tags):
        """Which topic hubs a note belongs under. Config-driven, never hardcoded.

        Three tiers, in order:
          1. `types` / `tags`   — explicit matches. A note can join several.
          2. `fallback_types`   — only consulted when nothing matched above, so a
                                  type can have a natural home without dragging
                                  every note of that type into one hub.
          3. `fallback: true`   — the single final catch-all.
        """
        tags = {t.lower() for t in tags}
        hits, by_type, fallback = [], None, None
        for t in self.topics:
            title = t.get("title")
            if not title:
                continue
            if t.get("fallback"):
                fallback = title
            if note_type in (t.get("fallback_types") or []) and by_type is None:
                by_type = title
            if note_type in (t.get("types") or []):
                hits.append(title)
            elif tags & {x.lower() for x in (t.get("tags") or [])}:
                hits.append(title)
        seen, out = set(), []
        for h in hits:
            if h not in seen:
                seen.add(h)
                out.append(h)
        if not out:
            if by_type:
                out.append(by_type)
            elif fallback:
                out.append(fallback)
        return out

    def __repr__(self):
        return "<Vault %s at %s>" % (self.id, self.path)


class Config:
    def __init__(self, raw):
        self.raw = raw
        self.version = raw.get("version", CONFIG_VERSION)
        u = raw.get("user") or {}
        self.user_name = u.get("name") or "the user"
        self.pronouns = u.get("pronouns") or "they/them"
        folders = dict(DEFAULT_FOLDERS)
        folders.update(raw.get("folders") or {})
        self.folders = folders
        self.vaults = [Vault(v, folders) for v in raw.get("vaults") or []]
        s = raw.get("scope") or {}
        preset = SCOPE_PRESETS.get(s.get("preset") or "")
        self.scope_include = s.get("include") or (preset or {}).get("include", "")
        self.scope_exclude = s.get("exclude") or (preset or {}).get("exclude", "")
        self.private_when = (raw.get("sensitivity") or {}).get("private_when") or []

    def vault_by_id(self, vid):
        for v in self.vaults:
            if v.id == vid:
                return v
        return None

    def vault_for_cwd(self, cwd):
        """Longest matching watch prefix wins, so a nested mapping can override."""
        try:
            cwd = Path(cwd).expanduser().resolve()
        except OSError:
            return None
        best, best_len = None, -1
        for v in self.vaults:
            for w in v.watch:
                try:
                    w = w.resolve()
                except OSError:
                    continue
                try:
                    cwd.relative_to(w)
                except ValueError:
                    continue
                if len(str(w)) > best_len:
                    best, best_len = v, len(str(w))
        return best

    def document_roots(self):
        out = []
        for v in self.vaults:
            out.extend(v.documents)
        return out


def validate(raw):
    """Return a list of human-readable problems. Empty list means usable."""
    problems = []
    if not isinstance(raw, dict):
        return ["config is not a JSON object"]

    v = raw.get("version")
    if v is not None and v != CONFIG_VERSION:
        problems.append("config version %r is not supported (expected %d)"
                        % (v, CONFIG_VERSION))

    vaults = raw.get("vaults")
    if not isinstance(vaults, list) or not vaults:
        problems.append("no vaults configured — run /my-vault:setup")
        return problems

    seen = set()
    for i, rv in enumerate(vaults):
        tag = rv.get("id") or "vaults[%d]" % i
        if not rv.get("id"):
            problems.append("%s: missing `id`" % tag)
        elif not SLUG.match(rv["id"]):
            problems.append("%s: id must be lowercase-with-hyphens" % tag)
        elif rv["id"] in seen:
            problems.append("%s: duplicate vault id" % tag)
        seen.add(rv.get("id"))

        p = rv.get("path")
        if not p:
            problems.append("%s: missing `path`" % tag)
        else:
            path = expand(p)
            if not path.exists():
                problems.append("%s: vault path does not exist: %s" % (tag, path))
            elif not path.is_dir():
                problems.append("%s: vault path is not a directory: %s" % (tag, path))

        watch = rv.get("watch")
        if not isinstance(watch, list) or not watch:
            problems.append("%s: needs at least one `watch` directory" % tag)
        else:
            for w in watch:
                if not expand(w).exists():
                    problems.append("%s: watch path does not exist: %s" % (tag, w))

        for d in rv.get("documents") or []:
            if not expand(d).exists():
                problems.append("%s: documents path does not exist: %s" % (tag, d))

        topics = rv.get("topics") or []
        if not topics:
            problems.append("%s: no topics — notes would have nowhere to be grouped" % tag)
        fallbacks = [t for t in topics if t.get("fallback")]
        if len(fallbacks) > 1:
            problems.append("%s: more than one topic marked `fallback`" % tag)
        if topics and not fallbacks:
            problems.append("%s: no topic marked `fallback` — notes matching nothing "
                            "would be orphaned" % tag)
        for t in topics:
            if not t.get("title"):
                problems.append("%s: a topic has no `title`" % tag)
            for key in ("types", "fallback_types"):
                for ty in t.get(key) or []:
                    if ty not in NOTE_TYPES:
                        problems.append("%s: topic %r lists unknown note type %r in `%s`"
                                        % (tag, t.get("title"), ty, key))
        claimed = {}
        for t in topics:
            for ty in t.get("fallback_types") or []:
                if ty in claimed:
                    problems.append("%s: note type %r is claimed as a fallback by both "
                                    "%r and %r" % (tag, ty, claimed[ty], t.get("title")))
                claimed[ty] = t.get("title")

    s = raw.get("scope") or {}
    if s.get("preset") and s["preset"] not in SCOPE_PRESETS:
        problems.append("unknown scope preset %r (choose one of: %s)"
                        % (s["preset"], ", ".join(sorted(SCOPE_PRESETS))))
    if not s.get("preset") and not s.get("include"):
        problems.append("scope needs either a `preset` or an `include` description")

    return problems


def load(strict=True):
    """Load config. Returns (Config|None, problems). Never raises on bad input."""
    p = config_path()
    if not p.is_file():
        return None, ["no config at %s — run /my-vault:setup" % p]
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        return None, ["config is not valid JSON: %s" % e]
    problems = validate(raw)
    if problems and strict:
        return None, problems
    return Config(raw), problems


def save(raw):
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return p


def state_path():
    return data_home() / "state.json"


def entities_path():
    return data_home() / "entities.json"


def run_dir():
    return data_home() / "run"


def load_state():
    p = state_path()
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"processed": {}, "last_sync": None}


def save_state(state):
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")


def load_entities():
    p = entities_path()
    if p.is_file():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
        except ValueError:
            pass
    return {}


def save_entities(ents):
    p = entities_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ents, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                 encoding="utf-8")


if __name__ == "__main__":
    import sys
    cfg, problems = load(strict=False)
    for pr in problems:
        print("PROBLEM  %s" % pr)
    if cfg is None:
        print("NO_CONFIG")
        sys.exit(1)
    print("config   %s" % config_path())
    print("user     %s" % cfg.user_name)
    print("vaults   %d" % len(cfg.vaults))
    for v in cfg.vaults:
        print("  - %-12s %s" % (v.id, v.path))
        print("    watch: %s" % ", ".join(str(w) for w in v.watch))
        print("    topics: %d" % len(v.topics))
    sys.exit(1 if problems else 0)
