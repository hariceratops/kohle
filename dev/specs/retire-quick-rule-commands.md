# Retire the quick rule commands

## Goal

Make the rule file the only way to manage classification rules, by removing
`add-rule`, `list-rules` and `remove-rule`.

The problem behind it: `complex-classification-rules` added a rule file
(`show-rules`, `edit-rules`, `apply-rules`) and kept the three quick commands
for simple rules. In use, the two paths contradict each other and the quick one
is the cumbersome one.

## Considerations surfaced

**The file model already covers `add-rule`.** `add-rule PATTERN ACCOUNT` makes
a rule whose only condition is `any_field = PATTERN`. The same regex syntax
(Python, `search`, case-insensitive) is available in the file through
`any_field`, `description` and `counterparty`, so nothing `add-rule` can say is
lost. `edit-rules` reaches it in one command, with a place to set order and
richer conditions at the same time.

**`list-rules` duplicates `show-rules`.** It prints a subset (no notes) of what
`show-rules` prints in full, in the same evaluation order.

**`remove-rule` is a deletion in the editor.** The file model already retires a
rule that is dropped from the file, and keeps past classifications pointing at
it, so no behaviour is lost.

**Two ways to one job.** Every behaviour of the quick commands (duplicate
refusal, leaf-account check, pattern validation, the compact conditions form)
exists twice, once per path, and each needs documenting and testing. The
earlier decision to "keep the CLI for simpler rules" assumed the file would be
heavy to edit; in hindsight it is not.

## Open questions

- Is there still a scripted use for a one-line rule add (a shell loop, a
  document in the README)? If so the file can be applied with `--yes`.
- What replaces the compact conditions form `list-rules` prints, if anything?
  `show-rules` may already be enough.
- Does anything outside the CLI (README samples, AGENTS.md, tests) name the
  removed commands? They need to follow.

## Notes

A breaking CLI change, and a removal: no new capability, so it is a `change`
more than a `new_feature`. Do it after `complex-classification-rules` is
merged, on its own branch off `main`.
