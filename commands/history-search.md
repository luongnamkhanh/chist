---
description: Search past Claude Code sessions by full-text query
---

Run the following bash command and present the top hits to the user as a numbered list.
On user confirmation, suggest using `/history-resume <id>` for the chosen session.

```
chist search "$ARGUMENTS" --project "$(basename "$(pwd)")" --limit 10 --format human
```
