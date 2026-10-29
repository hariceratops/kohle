# [feat] net-worth-history samples from a stored default rule list and shows a role column

Replace the hard-coded 15th plus period end with one stored rule list, seeded
with the default `mid-month: day 15; salary: last workday`. The output is
unchanged apart from a new `role` column.

Depends on: none (the `portfolio-and-profit-reporting` amendment should land first)
Spec: `dev/specs/configurable-net-worth-sampling.md`

## Acceptance Criteria

- The rule list is ledger data that travels with snapshots; it is not in
  `config.toml` and not a device setting.
- `init` and the packaged migration both store the default list; the default
  is defined in one place in the code.
- `day N` and `last workday` are parsed and generate dates; the rule syntax
  for the other kinds is not yet accepted.
- `net-worth-history` takes its sample dates from the stored list within
  `--from`/`--to`, then the final `--to` row unless `--to` is already a
  sample date.
- New `role` column; a date reached by several rules is one row listing every
  role (`mid-month, salary`); the non-sample `--to` row has an empty role.
- `--period-end` is removed; no internal `month-end` default remains.
- After `migrate` on a ledger with `state = BY`, dates and figures equal the
  pre-feature output of `--period-end last-working-day --state BY`, apart from
  the `role` column.
- Sample-date generation is a pure function of rules, state and range, with no
  price access.
- No command touched here changes the `prices` row count or calls a price plugin.
- README lines that describe `--period-end` are removed in this slice.
- Existing tests pass, apart from those that test `--period-end`.
