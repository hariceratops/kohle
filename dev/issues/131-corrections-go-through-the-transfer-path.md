# [feat] Corrections go through the transfer path

`reclassify` and `split-line` learn about transfers, so correcting a line neither double counts nor leaves a half-undone pair. Depends on 127 and 130.

## Acceptance Criteria

- `reclassify` of a transfer line to a category reverses the move and un-absorbs its mirror in the same operation; the mirror goes back to its bucket.
- `reclassify` onto an own account goes through the same transfer path instead of double counting.
- Each correction is by adjusting entry, all-or-nothing, one audit-trail group.
- `reclassify` refuses an absorbed mirror (unjoin first), and `reclassify` onto own accounts refuses the pending bucket and the line's own account.
- `split-line` is refused on a transfer line and an absorbed mirror, with an error naming why. (The pending-remittance refusal moves to 132, and the completed-remittance one to 133.)
- The classification records for these corrections are distinguishable from rule-made ones.
- `import-and-classification.md` is updated.
- Every existing test passes unchanged.
