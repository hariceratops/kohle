# [chore] Document richer classification rules

Bring the README and `AGENTS.md` in line with condition trees, the TOML rule file and the new commands.

Depends on: 082–088
Spec: `dev/specs/complex-classification-rules.md`

## Acceptance Criteria

- The README documents the conditions, the TOML layout including `any` and `not` and the one-line limit on OR alternatives, content-based identity, `edit-rules`, `show-rules`, `apply-rules`, `classify-rules`, and what `list-rules` shows.
- It states that the command names are flat for now and may change under `cli-command-naming`.
- `AGENTS.md` reflects how rules are stored and that `match_rule` stays pure.
- No statement in the README or `AGENTS.md` says a rule is a single regular expression.
