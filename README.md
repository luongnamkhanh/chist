# chist - Claude Code history manager

`chist` indexes, searches, resumes, and exports Claude Code session transcripts (the JSONL files written under `~/.claude/projects/`).

## Install

```
git clone <repo> ~/tools/claude-history
ln -s ~/tools/claude-history/chist ~/.local/bin/chist
chist index           # initial full index of all existing sessions
```

Requires Python 3.9+. No third-party dependencies.

## Usage

```
chist index --incremental      # refresh index after sessions change
chist search "<query>"         # ranked full-text search
chist list                     # all sessions, newest first
chist show <id-prefix>         # session metadata + messages
chist export <id-prefix>       # session as Markdown
chist resume <id-prefix>       # distilled summary; --full for verbatim
chist resume --last            # most recent session in cwd's project
chist banner --cwd-project     # one-line "most recent session" banner
chist prune --older-than 180d  # archive old JSONL into gzip
chist vacuum                   # rebuild FTS5 + VACUUM
```

## Slash commands and skill

Three slash commands shell out to the CLI:

- `/history-search <query>`
- `/history-resume <id>`
- `/history-export <id>`

The `claude-history` skill auto-triggers on natural-language queries like "find that chat about X".

## Hooks

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionEnd": [{"matcher": "*", "hooks": [{"type": "command",
      "command": "chist index --incremental --quiet >> ~/.claude/history-index.log 2>&1 &"}]}],
    "SessionStart": [{"matcher": "*", "hooks": [{"type": "command",
      "command": "chist banner --cwd-project"}]}]
  }
}
```

## Tests

```
python3 -m unittest discover tests -v
```
