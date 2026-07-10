---
name: claude-history
description: Use when the user asks to find, recall, resume, summarize, or export a past Claude Code conversation. Triggers on phrases like "find that chat about X", "what did we decide about Y last week", "resume the session where we did Z", "show prior sessions on this project", "summarize last week's work". Auto-invokes the chist CLI.
---

# Claude History Skill

When the user asks to find or recall a past conversation:

1. Identify the search query and any filters (project, time range).
2. Default to the cwd's project: run
   `chist search "<query>" --project "$(basename "$(pwd)")" --limit 10 --format json`.
3. Parse the JSON; present a numbered list with date, project, and snippet.
4. Ask the user which session to resume or export.
5. On confirmation, run `chist resume <id>` for context, or `chist export <id>` for a saved file.
6. If the heuristic summary is insufficient, offer `chist resume <id> --full`.

Do NOT run `chist index` proactively; the SessionEnd hook keeps the index fresh.
