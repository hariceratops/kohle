# [feat] Group splits under a trip label

A single split expense is useful on its own, but a multi-day shared trip
produces many of them, and viewing balances only per person loses the
"what happened on this trip" grouping. This bundles multiple splits under a
shared label so balances and settlement can later be viewed per group as
well as per person.

Depends on: 019
Spec: `dev/specs/expense-splitting.md`

## Acceptance Criteria

- A split (019) can optionally be tagged with a group/trip label at
  creation time.
- A group can be queried for its member splits.
- A group's per-person balances (the net effect of its member splits on
  each person account) can be computed from that query.
- A split created without a group label works exactly as before — grouping
  is additive, not required.
- The schema for groups (standalone table vs. attribute on existing
  entries/operations) follows whatever the architect's design settles on.
