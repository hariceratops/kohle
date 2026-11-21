# [feat] Join a late mirror to its transfer, and unjoin

A fall-through line outside the window can be joined to a named transfer by adjusting entry, and the join can be undone. This corrects one line; it is not the rejected suggest-and-confirm workflow. Depends on 127.

## Acceptance Criteria

- `join-transfer LINE_ENTRY TRANSFER_ENTRY` (working name) joins a named fall-through line to a named transfer: the line's bucket posting is cancelled and the line becomes the transfer's mirror.
- `unjoin-transfer` reverses it, reinstating the row's own posting in its bucket.
- Both are adjusting entries; nothing is edited or deleted, and the audit trail keeps every step.
- Each is all-or-nothing and one audit-trail group.
- Joining refuses a line that is not a fall-through, a transfer that already has a mirror, a line whose account is not the transfer's counterpart, a line with a different amount, and a line in the same direction as the transfer.
- `unjoin-transfer LINE_ENTRY` takes the line only.
- The classification record distinguishes the join from a rule-made transfer and from a category correction.
- `import-and-classification.md` is updated.
- Every existing test passes unchanged.
