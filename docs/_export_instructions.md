---
title: "Export Instructions"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Stakeholders", "Developers"]
---

## MkDocs
- Dev server: `mkdocs serve`
- Build site: `mkdocs build`

## PDF Export Options
- Material for MkDocs with `with-pdf` plugin (preferred for full site export).
- Simple Pandoc per-file:
  - `pandoc docs/overview/introduction.md -o out/introduction.pdf --from gfm --toc --metadata title="CLARA Docs"`

Tips
- Keep Mermaid diagrams simple for rendering.
- Update `last_updated` on edits; use CI to rebuild docs site.


