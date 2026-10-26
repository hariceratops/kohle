# [fix] Writers wait out a competing writer instead of failing

Two processes writing one ledger on the same machine, such as a long import
and a scheduled price fetch, are serialised by SQLite's lock. The second
should wait for the first rather than fail at once.

Depends on: none
Spec: `dev/specs/device-topology-and-sync.md`

## Acceptance Criteria

- Writer connections set a busy timeout.
- A test with two connections to one ledger: the second writer, started while
  the first holds its write transaction, succeeds once the first commits.
- A writer that waits past the timeout fails with a clear message, not a raw
  "database is locked".
- The timeout is not tied to any particular caller.
- Existing tests pass.
