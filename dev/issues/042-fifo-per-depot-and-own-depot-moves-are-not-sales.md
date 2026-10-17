# [feat] FIFO per depot, and own-depot moves are not sales

The same security can sit in several depots, each with its own FIFO queue, as
a broker's tax certificate computes it. Moving shares between two own depots
realises nothing and carries the original acquisition data.

Depends on: 040, 041
Spec: `dev/specs/portfolio-and-profit-reporting.md`

## Acceptance Criteria

- Queues are keyed by (account, unit): the same security in two depots replays
  independently.
- A move from depot A to depot B produces no `realised` row.
- B's later sale consumes A's original lots at their original cost and in
  original purchase-date order.
- A move-out larger than the sending depot's lots fails as in 041.
- An entry that moves a security out of own depots and into own depots in
  unequal quantities fails with `UnbalancedOwnMove`, naming the entry, rather
  than guessing which part moved and which was sold (decided with the user;
  not in the frozen spec).
- The design's rule for recognising an own-depot move from an entry's lines is
  documented in `dev/design/portfolio-and-profit-reporting.md`.
- Existing tests pass unchanged.
