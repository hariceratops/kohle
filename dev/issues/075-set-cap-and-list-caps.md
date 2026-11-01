# [feat] `set-cap` and `list-caps`

Let the user record a spending cap on an expense account as an effective-dated history, and list it. The commands are provisional names (`cli-command-naming` may rename them).

Depends on: none
Spec: `dev/specs/budgeting.md`

## Acceptance Criteria

- `set-cap <account> <amount> "<recurrence>" --from D` records an entry (amount in the base currency, recurrence from the shared vocabulary); `--from` is required and D may be in the future.
- Any expense account, leaf or parent, may be capped.
- `list-caps` shows every account's history, oldest first.
- A packaged Alembic migration adds the storage; caps are ledger data, travel with snapshots and are never written to `config.toml`.
- Each successful `set-cap` is one `Operation` in the audit trail.
- A cap of 0 is valid; a negative amount is refused.
- `set-cap` on `Unclassified Expense`, on an income, asset, liability or People account, or with an invalid account, amount, recurrence or date writes nothing: `list-caps` output and the `operations` row count are unchanged, and the error names the bad part and lists the valid choices.
- A reader device refuses `set-cap`, like the other write commands.
