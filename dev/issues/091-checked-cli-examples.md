# [feat] Checked CLI examples

Make documentation examples fail the suite when they drift. pytest finds marked `kohle-cli` blocks in the markdown pages, runs each against a fresh scratch ledger and compares its printed output exactly.

Depends on: 090

## Acceptance Criteria

- A documented marker in a fenced block says it is a checked example and holds its expected output; the design chooses the syntax.
- Each block runs on its own against a fresh scratch ledger (`KOHLE_DB` at a temp path) with its fixtures available.
- Examples pin their dates, so the result never depends on the day the suite runs.
- Unmarked blocks (install lines, config snippets) are not run.
- A shipped sample page with a fictional sample statement and at least one passing block proves it.
- A block whose expected output no longer matches fails the suite, naming the page and block; a test proves this with a deliberately wrong block.
- No example touches the network.
