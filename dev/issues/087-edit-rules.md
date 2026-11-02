# [feat] `edit-rules`

Let the user edit the whole rule set in their editor, with errors shown in place and a confirmation before anything changes.

Depends on: 084
Spec: `dev/specs/complex-classification-rules.md`

## Acceptance Criteria

- `edit-rules` renders the rule set as TOML and opens it in `$VISUAL` or `$EDITOR`.
- If neither is set, the command fails with a clear message and changes nothing.
- On save the file is parsed and checked with the same rules as `apply-rules`; on any error the editor reopens with the error shown and nothing is applied.
- A valid file shows the same summary as `apply-rules` and asks before applying; declining or aborting the editor leaves the rules untouched.
- It applies with the same identity rules, concurrency refusal and audit-trail group as `apply-rules`.
- A reader device refuses `edit-rules`.
