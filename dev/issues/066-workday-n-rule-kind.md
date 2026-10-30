# [feat] workday N rule kind

Add `workday N`: day N, or the last working day before it, so a salary paid
on a fixed day that falls on a weekend or holiday is sampled when it arrives.

Depends on: 065
Spec: `dev/specs/configurable-net-worth-sampling.md`

## Acceptance Criteria

- `workday N` (1–31) is accepted by `set-sampling-rules`; in a shorter month
  N is clamped to the last day first.
- `day 15` on a Sunday stays on the 15th; `workday 15` on a Sunday moves to
  Friday the 13th.
- A shift moves backward only and may land in the previous month; the row is
  dated where it lands.
- Working day means Monday to Friday, not a public holiday of the Bundesland,
  and neither 24 nor 31 December.
- After `set-sampling-rules "salary: workday 25"`, every month in range, past
  ones included, has exactly one sample row (plus the `--to` row).
- Existing tests pass.
