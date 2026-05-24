---
name: feedback-coding-style
description: Use ASCII-only in print() statements; Windows cp1254 terminal can't encode Unicode arrows or checkmarks
metadata:
  type: feedback
---

Use ASCII-only characters in all print() and f-string output that goes to the terminal.
Specifically: replace → with ->, replace × with x, replace ✓ with OK or (done), replace ← with <-.

**Why:** Windows terminal uses cp1254 encoding by default; Unicode arrows and symbols cause UnicodeEncodeError at runtime. This bug was found and fixed in generate_phase20_presentation_figures.py.

**How to apply:** When writing any script that has print() statements with diagnostic/progress output, scan for non-ASCII characters and replace with ASCII equivalents before finalizing.
