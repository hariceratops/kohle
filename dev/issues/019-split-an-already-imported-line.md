# [feat] Split an already-imported line

Manual n-line entries already exist (`record-split` / `RecordSplitEntry`),
so this is not "record a split" — it's the narrower gap: dividing a line
that already arrived through import between the user's own expense account
and one or more person accounts, after the fact.

The line is never rewritten. This follows the same append-only correction
pattern `reclassify` established for classification: post an adjusting
entry that reverses the original counterpart line and re-posts it split
across the expense account and the person account(s). There is no
`crud_update` and nothing writes `Operation.field`/`state` — an in-place
rewrite would be inventing an update mechanism this codebase deliberately
does not have.

Depends on: 018
Spec: `dev/specs/expense-splitting.md`

## Acceptance Criteria

- A CLI command splits an existing imported `JournalLine`'s value between
  the user's own expense account and one or more person accounts.
- The split posts as a reversing-and-re-posting adjusting entry through
  `post_entry` — the original line is never edited, voided, or deleted.
- Test: an imported €80 dinner line split €32 own-share / €48 person-share
  leaves the expense account holding €32 and the person account holding a
  €48 receivable.
- Both the reversal and the re-post are traceable via `Operation` rows back
  to the original import.
- An unknown line, an unknown person account, or split amounts that don't
  sum to the original line's value produce a clear error, not a traceback.
