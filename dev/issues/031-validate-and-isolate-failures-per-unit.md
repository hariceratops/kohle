# [feat] Validate every price and isolate failures per unit

Every plugin result passes the same checks in core before it is written, and
one unit's failure never rolls back another unit's valid close. Price rows are
independent facts, unlike an import statement, which is one document.
The unpriced outcome, plugin `Err` handling and the non-zero exit already
exist from 030; this slice adds the validation reasons to them.

Depends on: 030
Spec: `dev/specs/price-fetcher-plugin.md`

## Acceptance Criteria

- Core rejects, with a distinct named reason each: a zero or negative price,
  a date after today, and a currency other than `BASE_CURRENCY`. Each leaves
  the table unchanged for that unit, reports the unit unpriced with the
  reason, and the other units are unaffected. The checks apply to the `file`
  plugin like any other.
- A result for a symbol that was not requested can never be written. It is
  reported on its own line and does not change the exit code.
- Validation compares against the existing `BASE_CURRENCY` constant, not a
  second copy.
- A close failing validation does not roll back another unit's valid close in
  the same run. Two units sharing one plugin and symbol get the same close and
  so the same verdict: a rejected shared close leaves both unpriced while a
  third unit's valid close is still written; a valid shared close may leave
  one unit already stored and the other priced.
- A validation failure makes the exit code non-zero, like any other unpriced
  bound unit.
