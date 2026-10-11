# [feat] Classify a unit's latest close as fresh, stale or none

The read side that reporting will consume: a unit's latest stored close with
its date and source, classified against a staleness threshold. Offline means no
fetch, and the reader still serves the last stored close, flagged stale once it
ages.

Depends on: 030
Spec: `dev/specs/price-fetcher-plugin.md`

## Acceptance Criteria

- A read function returns the latest stored close for a unit with its date and
  source, classified as `fresh` (no older than N days), `stale` (older than N
  days) or `none` (no close stored).
- N is a parameter with default 7, not a constant. How a user sets it is out
  of scope and left to `portfolio-and-profit-reporting`.
- "No price" and "stale price" are distinct outcomes, never collapsed.
- Tests produce each of the three outcomes from a fixture and pin the boundary
  day (age exactly N and N + 1).
