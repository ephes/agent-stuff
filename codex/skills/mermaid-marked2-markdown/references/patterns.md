# Marked 2 Mermaid Patterns

## Minimal Style Block

Use once near the top of a standalone Markdown file:

```html
<style>
.mermaid,
.mermaid svg {
  background: transparent !important;
  background-color: transparent !important;
}
</style>
```

## Flowchart Template

This pattern is Marked 2 safe:

- It uses explicit theme variables.
- It enables HTML labels.
- It uses intermediate nodes instead of edge labels.
- It pins label text to a dark color with inline spans.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#f3ecd4', 'secondaryColor': '#f3ecd4', 'tertiaryColor': '#f3ecd4', 'primaryTextColor': '#111111', 'secondaryTextColor': '#111111', 'tertiaryTextColor': '#111111', 'textColor': '#111111', 'lineColor': '#111111', 'primaryBorderColor': '#111111', 'edgeLabelBackground': '#f3ecd4'}, 'flowchart': {'htmlLabels': true}}}%%
flowchart LR
  FE["<span style='color:#111111'>Frontend</span>"] --> P["<span style='color:#111111'>Poll using changed_since</span>"]
  P --> BE["<span style='color:#111111'>Backend endpoint</span>"]
  BE --> R["<span style='color:#111111'>result metadata</span>"]
  R --> FE
```

## Sequence Template

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#f3ecd4', 'secondaryColor': '#f3ecd4', 'tertiaryColor': '#f3ecd4', 'primaryTextColor': '#111111', 'secondaryTextColor': '#111111', 'tertiaryTextColor': '#111111', 'textColor': '#111111', 'lineColor': '#111111', 'primaryBorderColor': '#111111', 'edgeLabelBackground': '#f3ecd4'}}}%%
sequenceDiagram
  participant FE as Frontend
  participant BE as Backend
  FE->>BE: Create
  BE-->>FE: ID
```

## Troubleshooting

- If text is too faint, set node labels with inline spans and explicit color `#111111`.
- If edge-label boxes look wrong, replace edge labels with intermediate nodes.
- If rendering differs between viewers, keep the same `init` and avoid extra CSS.
