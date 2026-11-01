# [feat] `end-cap`

Let the user stop a cap from a date onward.

Depends on: 078
Spec: `dev/specs/budgeting.md`

## Acceptance Criteria

- `end-cap <account> --from D` records "no cap" from D; `--from` is required; one `Operation`, all-or-nothing.
- `list-caps` shows the end entry in the account's history.
- `budget` shows no periods for the account from D; the period running at D is cut at D−1 and marked short.
- Repeating the D replaces the entry; an account with no cap in force, or an invalid account or date, writes nothing and the error names the bad part.
