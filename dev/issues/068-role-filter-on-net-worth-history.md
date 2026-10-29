# [feat] --role filter on net-worth-history

Let the user show only mid-month or only salary rows, for example to compare
month to month after pay arrives.

Depends on: 064
Spec: `dev/specs/configurable-net-worth-sampling.md`

## Acceptance Criteria

- `--role mid-month|salary` keeps rows whose role column lists that role.
- A row listing both roles matches either value.
- The row dated `--to` is always shown under `--role`, even when that date is
  itself a sample date for the other role.
- An empty role is rendered as `-`.
- An unknown role value fails with the valid choices named.
- Existing tests pass.
