# [feat] set-sampling-rules and list-sampling-rules

Let the user replace the stored rule list and read it back, and add the
`last day` kind.

Depends on: 064
Spec: `dev/specs/configurable-net-worth-sampling.md`

## Acceptance Criteria

- `set-sampling-rules "<role>: <rule>; …"` replaces the whole list; it applies
  to the whole history and re-samples past months.
- `list-sampling-rules` shows the current list and leaves no
  `OperationGroup` behind.
- The `last day` kind (calendar last day of the month) is accepted.
- Roles are the fixed set `mid-month` and `salary`; a role may appear more
  than once; an empty list is allowed or refused as the design decides and
  documents.
- An invalid rule, role or date writes nothing; the error names the bad part
  and lists the valid choices. A test shows `list-sampling-rules` output and
  the `operations` row count unchanged after a failed set.
- Each successful change is one audited `Operation`.
- After `set-sampling-rules "salary: last day"`, every month in range has
  exactly one sample row (plus the `--to` row).
- No new command changes the `prices` row count or calls a price plugin.
- Existing tests pass.
