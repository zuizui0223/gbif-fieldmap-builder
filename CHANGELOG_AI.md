# AI Change Log

This file records changes made by AI coding agents such as Codex, Claude, ChatGPT, or other assistants.

Each agent should update this file after editing code.

## Template

```md
## YYYY-MM-DD - Agent name

Changed files:
- path/to/file.py

Summary:
- Briefly describe what changed.

Features preserved:
- GBIF pagination
- CSV upload
- map-click occurrence exclusion
- red QC excluded points
- SDM
- VIF stepwise filtering
- spatial partition diagnostics
- predict map
- SDM-high exploration candidates
- route planner
- downloads

Known risks / TODO:
- List anything that still needs checking.
```

## 2026-06-02 - ChatGPT

Changed files:
- AGENTS.md
- CHANGELOG_AI.md

Summary:
- Added AI collaboration rules and a shared changelog format.
- Defined core features that future AI edits must preserve.
- Added routing caution that straight-line route planning does not account for roads, ferries, mountains, cliffs, restricted access, or island barriers.
- Added requirement that every AI agent update this changelog after code changes.

Features preserved:
- No application code changed.

Known risks / TODO:
- Add GitHub Actions syntax check workflow.
- Improve route planning so Google Maps verification and accessible-site selection are explicit.
