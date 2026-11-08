# [test] A ledger with no non-EUR currency unit is unchanged

Every command produces exactly today's output when no non-EUR currency unit exists.

Depends on: 107, 123

## Acceptance Criteria

- A test ledger with only EUR and securities produces output identical to the pre-feature output from every command.
- Every existing test passes unchanged.
- The comparison is against the baseline captured in 107.
