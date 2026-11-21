# [feat] `classify-rules` applies transfer rules and absorbs mirrors

Re-applying the rule file to fall-through lines moves lines matched by a transfer rule, and absorbs the counterpart's fall-through mirror in the same run. Depends on 127.

## Acceptance Criteria

- `classify-rules` applies transfer rules to fall-through lines, as it does category rules.
- A transfer move also absorbs the counterpart's fall-through mirror in the same run, and the preview shows both lines.
- It never touches lines a rule or a human already classified.
- Transfer rules are ordinary entries in the one ordered list; the first match wins, and mirror recognition runs before any rule.
- Retiring or editing a transfer rule never undoes a posted move; only `classify-rules` moves anything.
- A run is all-or-nothing and is one audit-trail group.
- `import-and-classification.md` is updated.
- Every existing test passes unchanged.
