# [feat] Define classification rules from the CLI

Classification needs a rule set before it can classify anything. Rules live
in a database table rather than a config file, matching how `Account` and
`Unit` are already DB rows with CLI CRUD — and giving each rule the stable
id that the classification record in 015 refers to.

This slice creates and lists rules. Nothing matches on them yet.

Independent of 013.
Spec: `dev/specs/expense-classification.md`

## Acceptance Criteria

- A `Rule` table holds a pattern, a target account, and a priority, added by
  an Alembic migration.
- `kohle-cli add-rule` creates a rule against an existing leaf account; an
  unknown account name produces a clear error, not a traceback.
- `kohle-cli list-rules` renders the rule set with `tabulate`, matching the
  other listing commands, in the order rules would be evaluated.
- `kohle-cli remove-rule` removes a rule.
- The pattern language is whatever the design settles on — substring, regex
  or a small DSL. The constraint this issue is accepted against is that a
  malformed pattern is rejected when the rule is created, not when an import
  later fails.
- Rule evaluation order is deterministic and visible in `list-rules`. Two
  rules that both match one line must resolve the same way on every run.
- Commands route through new use cases following the established
  `UnitOfWork` / `DbTransactionContext` pattern; the CLI holds no query
  logic.
- Rule writes appear in the operation audit trail through `crud_create`,
  like every other write.
