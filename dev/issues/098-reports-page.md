# [feat] Reports page

Carve the reporting material into one concept page: net worth, positions and profit, and net worth over time.

Depends on: 091

## Acceptance Criteria

- `docs/reports.md` covers net worth, positions and profit (including FIFO across own depots), and net worth over time with sampling rules and Bundesland history.
- Every `kohle-cli` invocation is a checked example with pinned dates, and passes.
- Report column lists defer to the generated reference or to checked output rather than a hand-written table.
- The page is in the nav and the strict build passes.
