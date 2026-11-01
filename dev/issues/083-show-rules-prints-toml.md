# [feat] `show-rules` prints the rule set as TOML

Render the whole rule set as TOML so it can be read, diffed and fed back in.

Depends on: 082
Spec: `dev/specs/complex-classification-rules.md`

## Acceptance Criteria

- `show-rules` prints each rule as a `[[rule]]` entry with `account`, an optional `note` and a `[rule.when]` table; entry order is the priority order.
- The same rule set always renders as the same text, and the text parses back with `tomllib` to the same rule set.
- Rule ids never appear in the output.
- `show-rules` is read-only, so a reader device may run it.
