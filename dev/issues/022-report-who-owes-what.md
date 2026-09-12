# [feat] Report who-owes-what

People-account balances (018) are only useful day to day if they can be
seen at a glance, rather than requiring a manual balance lookup per person.
This turns them into a report.

Depends on: 021
Spec: `dev/specs/expense-splitting.md`

## Acceptance Criteria

- A reporting command lists the net balance per person account.
- The same command (or a flag on it) breaks the view down per group, for
  splits tagged with a group label (021).
- Splits not tagged with any group still show up in the global per-person
  view.
- A person with a zero net balance (fully settled) is distinguishable from
  one who has never been split against.
