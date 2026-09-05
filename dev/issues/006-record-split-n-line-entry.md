# [feat] Record an n-line entry with `record-split`

Entries with more than two lines — a shared expense split several ways, an
entry touching three accounts — need a general form in which every line is
given in full rather than derived.

Depends on: 001 (shares its CLI parsing and presentation patterns)
Spec: `dev/specs/cli-record-and-balances.md`

## Acceptance Criteria

- `kohle-cli record-split ENTRY_DATE DESCRIPTION --line
  ACCOUNT:QUANTITY:UNIT:PRICE:SIDE [--line ...]` posts an n-line entry.
- `SIDE` is `debit` or `credit`.
- Every line is given in full; nothing is derived from another line.
- A malformed `--line` value produces a clear parse error naming the
  offending value, not a traceback.
- Fewer than two lines is rejected by the existing `EmptyEntry` check in
  `RecordJournalEntry`, surfaced readably.
- Balance-by-value and leaf-only posting are enforced by
  `RecordJournalEntry`, not by the CLI.
- A three-way shared expense — one account credited, two debited — posts
  successfully.
