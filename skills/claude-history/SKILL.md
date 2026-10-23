---
name: claude-history
description: Use when the user asks to find, recall, resume, summarize, or export a past Claude Code OR Codex conversation, or to continue/take over a session started in the other tool. Triggers on phrases like "find that chat about X", "what did we decide about Y last week", "resume the session where we did Z", "continue the codex session", "pick up what Claude was doing", "show prior sessions on this project". Auto-invokes the chist CLI.
---

# Claude History Skill

`chist` indexes both stores into one search index: Claude Code (`~/.claude/projects`)
and Codex (`~/.codex/sessions`). Codex session ids carry a `codex-` prefix; both use
the same project key (cwd with `/` replaced by `-`).

When the user asks to find or recall a past conversation:

1. Run `chist index --incremental --quiet` first (cheap; Codex has no SessionEnd hook to keep it fresh).
2. Identify the search query and any filters (project, time range).
3. Default to the cwd's project: run
   `chist search "<query>" --project="$(pwd | tr / -)" --limit 10 --format json`.
   For the latest sessions instead of a keyword: `chist list --project="$(pwd | tr / -)" --limit 10`.
4. Present a numbered list with date, tool (Claude or Codex), project, and snippet.
5. Ask the user which session to resume or export (skip if they already named it).
6. Run `chist resume <id>` for context, or `chist export <id>` for a saved file.
7. If the summary is insufficient, run `chist resume <id> --full`.

Taking over a session from the other tool: tell the user to stop the original session first
so both agents do not edit the same files, then read the resumed context and continue.
