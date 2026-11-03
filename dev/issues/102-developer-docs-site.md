# [chore] Developer docs site

Give developer-facing material its own MkDocs site, separate from the user guide and not part of the published user site, and move "Writing migrations" into it.

Depends on: 090

## Acceptance Criteria

- The developer site has its own `mkdocs.yml` at the location the design chooses, and builds with `mkdocs build --strict`.
- It is not part of the published user site and not in the user guide's nav.
- "Writing migrations" moves out of the README into it.
- The design records where the site lives and whether it is built or published anywhere.
- The README content it replaces is not yet removed (issue 103 does that).
