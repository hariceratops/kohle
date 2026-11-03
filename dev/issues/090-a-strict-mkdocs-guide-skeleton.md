# [chore] A strict MkDocs guide skeleton

Make `docs/` a MkDocs guide in the s2s layout, with an empty-but-navigable skeleton, so every later page has a place to land. The two LLM transcripts currently in `docs/` are not documentation and move out first.

Depends on: none

## Acceptance Criteria

- `docs/double_entry.md` and `docs/to_llm.md` live in `archive/`, moved with `git mv`.
- `docs/mkdocs.yml` sets `docs_dir: .`, the mkdocs-material theme and `strict: true`.
- `docs/requirements.txt` pins mkdocs, mkdocs-material and mkdocs-click, separate from the app's `requirements.txt`.
- `docs/index.md` explains how the guide is organised and lists the v1 pages.
- `mkdocs build --strict -f docs/mkdocs.yml` succeeds; `mkdocs serve -f docs/mkdocs.yml` serves the guide.
- The build output directory is git-ignored.
