# [test] A ledger with no non-EUR currency unit is unchanged

Every command produces exactly today's output when no non-EUR currency unit exists.

Depends on: 107, 123

## Acceptance Criteria

- A test ledger with only EUR and securities produces output identical to the pre-feature output from every command.
- Every existing test passes unchanged.
- The comparison is against the baseline captured in 107.

## Review 2026-11-11
- Commit 96476e8 (rule-check fixes) removed the `# noqa: DTZ007/DTZ011` comments in `cli.py` (lines 127, 787, 1253, 1275, 1460, 1491, 1530) and at `tests/test_multi_currency_valuation.py:329`; ruff now fails on them. Fixed in a follow-up commit.
- `cli.py:74` imports `Position`, unused since `_unit_kind` was removed. Fixed in the follow-up.
- `journal.py:65` `PEOPLE_ROOT as PEOPLE_ROOT` fails PLC0414; callers in `budgeting.py`, `tests/conftest.py`, `tests/test_market_value_cli.py`, `tests/test_classify_rules.py` should import from `kohle.use_cases.accounts`. Fixed in the follow-up.
- Opinion, not fixed: `journal.py:315` has a redundant `currency is not None` condition.
- Opinion, not fixed: commit 96476e8 mixes a defect fix with cleanup, and its message omits the noqa removals.
- Opinion, not fixed: `NonBaseCurrency` is a stale name for a close/binding currency mismatch.
