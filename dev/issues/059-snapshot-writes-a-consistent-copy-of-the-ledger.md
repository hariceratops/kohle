# [feat] `snapshot <path>` writes a consistent copy of the ledger

A device that holds the writable ledger can produce a single self-contained
copy for other devices to read. How the copy is scheduled or distributed is
outside kohle.

Depends on: none
Spec: `dev/specs/device-topology-and-sync.md`

## Acceptance Criteria

- `snapshot <path>` writes the ledger to `<path>` with SQLite's `VACUUM INTO`
  and exits zero. No journal or WAL side file is left beside it.
- The snapshot opens as an ordinary ledger: `balance` and `list-accounts` on
  it give the same results as on the live ledger.
- An existing `<path>` is refused with a clear message and exit non-zero;
  nothing is overwritten.
- The live ledger is not modified and no `Operation` is recorded.
- A missing ledger fails as every other command does; no empty database is
  created.
- The command takes any destination path and assumes no transport, schedule
  or fixed location.
- The SQLite-specific code sits with the connection code, not spread through
  the use cases.
- Existing tests pass.
