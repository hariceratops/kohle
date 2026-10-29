# [feat] move-state --from D XX records a move of Bundesland

Let the user record when they moved, so past samples keep the holidays that
applied then.

Depends on: 069 (lands immediately after it, with no review stop between them)
Spec: `dev/specs/configurable-net-worth-sampling.md`

## Acceptance Criteria

- `move-state --from D XX` records the Bundesland from D onward; `--from` is
  required and takes a date or `start`.
- D may be in the future; repeating an existing D replaces that entry; a later
  entry wins from its own date onward.
- `move-state --from 2026-01-01 NI` on a `BY` ledger changes no row dated
  before 2026-01-01: the October 2025 `salary` row stays Friday 31 October;
  the October 2028 `salary` row is Monday 30 October (Reformation Day in NI).
- An invalid state code or date writes nothing; the error names the bad part
  and lists the valid choices.
- A state entry cannot be removed, only overwritten by repeating its date.
- Each successful change is one audited `Operation`.
- The command does not change the `prices` row count or call a price plugin.
- Existing tests pass.
