---
description: Export a past session to Markdown under docs/history/
---

Run the following bash command and report the file path written.

```
mkdir -p docs/history && chist export $ARGUMENTS -o "docs/history/$(date +%Y-%m-%d)-$(echo $ARGUMENTS | head -c 8).md"
```
