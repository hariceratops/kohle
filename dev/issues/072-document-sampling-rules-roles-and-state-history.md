# [chore] Document sampling rules, roles and the state history

Bring the README in line with the new commands and the removed flags.

Depends on: 064–070
Spec: `dev/specs/configurable-net-worth-sampling.md`

## Acceptance Criteria

- The README documents the rule vocabulary (including the kinds specified for
  `budgeting` but not built), roles, `set-sampling-rules`,
  `list-sampling-rules`, `move-state`, `list-states`, the `role` column and
  `--role`.
- It states that `--period-end` and `--state` are removed and `state` is no
  longer a setting.
- It states that sample dates cost no API calls and that backfill is not built.
- No statement in the README or `AGENTS.md` still refers to the removed flags.
