# [chore] Docs build and Pages deploy workflow

Add the repository's first GitHub Actions workflow: build the guide strictly on every change and publish it from `main`.

Depends on: 090

## Acceptance Criteria

- `.github/workflows/docs.yml` runs `mkdocs build --strict -f docs/mkdocs.yml` on every PR and push.
- A push to `main` deploys the built site to GitHub Pages; PRs never deploy.
- A failed build does not deploy.
- The workflow runs no tests, ruff or mypy.
- The docs toolchain is installed from `docs/requirements.txt`.
