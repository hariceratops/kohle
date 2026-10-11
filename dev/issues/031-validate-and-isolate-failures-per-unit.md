# [feat] Validate every price and isolate failures per unit

Every plugin result passes the same checks in core before it is written, and
one unit's failure never rolls back another unit's valid close. Price rows are
independent facts, unlike an import statement, which is one document.

Depends on: 030
Spec: `dev/specs/price-fetcher-plugin.md`

## Acceptance Criteria

- Core rejects, with a distinct named reason each: a result for a symbol that
  was not requested, a zero or negative price, a date after today, and a
  currency other than `BASE_CURRENCY`. Each leaves the table unchanged for
  that unit and the other units are unaffected. The checks apply to the
  `file` plugin like any other.
- Validation compares against the existing `BASE_CURRENCY` constant, not a
  second copy.
- A plugin `Err` leaves every unit bound to it unpriced, with the plugin's
  error as the reason, and writes no row for them. Rows from other plugins in
  the same run are still written.
- An `Unavailable` result leaves that unit unpriced with its reason
  (`no_symbol`, `not_covered`, `transient`) in the output.
- The exit code is non-zero if any bound unit ends unpriced, for any of the
  reasons above.
