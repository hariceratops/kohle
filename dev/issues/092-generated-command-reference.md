# [feat] Generated `kohle-cli` command reference

Give the guide a command reference that cannot drift, rendered from the Click definitions with mkdocs-click.

Depends on: 090

## Acceptance Criteria

- A reference page lists every `kohle-cli` command with its options, defaults and choices, rendered by mkdocs-click.
- A command or option added to `kohle-cli` appears on the page with no edit to the docs.
- The page is in the nav and passes `mkdocs build --strict`.
- `kohle-tui` is not part of the reference.
