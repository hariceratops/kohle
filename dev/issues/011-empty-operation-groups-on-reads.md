# [fix] Read-only commands leave empty operation groups behind

`DbTransactionContext.__init__` unconditionally creates and flushes an
`OperationGroup`, and `DbTransaction.execute` commits it on success. Every
command therefore writes a group row, including ones that only read.

Measured on a fresh in-memory ledger:

```
start                     groups=0  ops=0
after 1 write             groups=1  ops=1
after 5 read-only calls   groups=6  ops=1
after 5 more reads        groups=11 ops=1
```

Two consequences. The `operation_groups` table grows without bound in
proportion to read traffic — `list-accounts`, `balance`, `entries-in-period`
and `list-operations` itself all contribute. And the audit trail's `group`
column shows gaps wherever a read happened between two writes, so group ids
read as though transactions are missing.

The fix is to create the group lazily, on the first
`record_transaction_step`, rather than in the context constructor.

Found while implementing issue 008, and deliberately kept out of it: this
touches the transaction boundary that `AGENTS.md` singles out as the
codebase's most delicate seam — the one place broad exception catching is a
recorded override — and that is not CLI-slice work.

## Acceptance Criteria

- A command that writes nothing creates no `OperationGroup` row.
- A command that writes creates exactly one group, containing its operations,
  as it does today.
- Group ids for consecutive writes are consecutive, with no gaps introduced by
  intervening reads.
- The audit trail recorded for an existing write path is unchanged — same
  operations, same grouping.
- Rollback behaviour is unchanged: a failed use case still leaves no group and
  no operations.
- The existing operation-tracking tests still pass.
