# [feat] `apply-rules <file>` with content-based identity

Let the user, an agent or a script replace the rule set from a TOML file, with a summary and a confirmation before anything changes.

Depends on: 082, 083
Spec: `dev/specs/complex-classification-rules.md`

## Acceptance Criteria

- `apply-rules <file>` accepts `description`, `counterparty`, `iban` and `any_field` conditions in `[rule.when]`, ANDed together; patterns are case-insensitive and an IBAN ignores spaces and letter case.
- It prints a summary (added, retired, unchanged, reordered) and asks before applying; `--yes` skips the question; it exits non-zero on any error.
- A rule with unchanged conditions and account keeps its id, and moving it only changes its priority; a change to the note alone updates the note; any other change retires the old rule and adds a new one.
- The apply is all-or-nothing and recorded as one audit-trail group; a failed check, a declined prompt or a crash part-way leaves the rules untouched.
- Applying an unchanged file writes nothing and leaves no audit-trail entry.
- Applying the output of `show-rules` with `--yes` reports no changes.
- It refuses to apply when the stored rules changed after the file was rendered.
- An empty file, or one with every rule deleted, retires all rules; the summary shows that count before anything is applied.
- A file is rejected, with nothing written, for: a TOML syntax error, an unknown key, a pattern that does not compile, an account that is missing or not a leaf, a rule with no conditions, and two rules with identical content. Each error names the rule's position in the file and the key at fault.
- A reader device refuses `apply-rules`.
