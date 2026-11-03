# [feat] Getting started page

Carve the setup material out of the README into a Getting started page: install, where the ledger lives, device config, first run, schema check, upgrading.

Depends on: 091

## Acceptance Criteria

- `docs/getting-started.md` covers install, where the ledger lives, device config, first run, schema check and upgrading, moved from the README and rewritten as needed.
- Every `kohle-cli` invocation on the page is a checked example and passes; install and setup shell lines and config snippets are unchecked illustration.
- The page is in the nav and the strict build passes.
- The README content it replaces is not yet removed (issue 103 does that).
