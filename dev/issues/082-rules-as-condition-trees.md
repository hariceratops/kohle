# [feat] Rules as condition trees, behaviour unchanged

Make a rule a condition tree so later slices can add conditions without another storage change. Nothing a user does today changes.

Depends on: none
Spec: `dev/specs/complex-classification-rules.md`

## Acceptance Criteria

- A packaged Alembic migration converts each existing rule into one `any_field` condition and keeps its id; `Classification.matched_rule_id` rows still point at the same rule.
- A statement imported after the migration classifies exactly as it would have before, including the first-match-by-priority order.
- `match_rule` stays a pure function with no database session.
- `list-rules` shows one row per rule in evaluation order: id, account, and the conditions in the compact form used in the TOML file.
- `add-rule` keeps its single-pattern form and appends the new rule at the end of the order; `remove-rule` is unchanged.
- Rules stay immutable at the storage level.
