---
name: mermaid-marked2-markdown
description: Use when creating or editing standalone Markdown files with Mermaid charts for Marked 2 sharing in both light and dark mode. Apply the proven init pattern, explicit text color, and avoid fragile Mermaid constructs.
---

# Mermaid Marked 2 Markdown

## Overview

Create Mermaid charts that remain readable when a Markdown file is viewed standalone in Marked 2 and shared with others.

## When To Use

Use this skill when:

- A Markdown file includes Mermaid diagrams and is meant to be viewed in Marked 2.
- The file is an ephemeral spec or discussion note, not generated site documentation.
- The user reports dark/light mode readability issues.

## Workflow

1. Keep Mermaid CSS minimal.
2. Add the proven per-diagram `init` with `theme: base` and explicit `themeVariables`.
3. For flowcharts, avoid edge labels such as `A -->|label| B`; use intermediate label nodes instead.
4. If text contrast is unstable in a renderer, use inline span labels with explicit text color.
5. Verify in both Marked 2 light and dark modes when possible.

## Rules

- Do not add broad Mermaid CSS overrides for all text, nodes, or edges unless requested.
- Prefer diagram-local `themeVariables` over global CSS hacks.
- Keep diagram content simple; add nodes for labels instead of styled edge labels.
- Use the exact templates in [references/patterns.md](references/patterns.md) when starting a new diagram.
