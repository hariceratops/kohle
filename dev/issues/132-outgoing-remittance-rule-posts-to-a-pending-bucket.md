# [feat] An outgoing remittance rule posts to a pending bucket

A remittance rule names the counterpart and the non-base currency unit; a matched euro line moves into a pending own-asset bucket until Y is known. Depends on 126.

## Acceptance Criteria

- A remittance rule uses `remittance = "<counterpart>"` with `unit = "<UNIT>"`, stored as `rules.kind` and `rules.unit_id`; no code names INR. The kind and the unit are part of the rule's content identity, and a remittance rule never matches a row imported into its own counterpart.
- The pending bucket is `Pending Remittances`, created on the first remittance only, so ledgers without remittance rules gain no account.
- `list-pending-remittances` lists pending remittances in their own listing, with direction, counterpart and unit; they do not appear in `list-unclassified`.
- `classify-rules` applies remittance rules to fall-through lines, as for transfer rules.
- `reclassify` of a pending remittance reverses it; `split-line` is refused on a pending remittance.
- Classification record columns: `kind` (category, transfer, mirror or remittance), `mirror_of_entry_id`, `remittance_account_id`, `remittance_unit_id`, `completion_entry_id`, tied to the kind by CHECK constraints; direction is derived from the line's sign. This slice carries the remittance-columns migration.
- The same counterpart validation as 126 applies.
- A matched outgoing line moves from the euro account to the pending bucket, an own asset account created on first use like the unclassified buckets; the architect names it.
- Net worth counts the euros in transit at face value until completion.
- The classification record holds the counterpart, the unit and the direction, and tells a pending remittance apart from a transfer and from a category classification.
- Pending remittances are listed; the architect decides whether in `list-unclassified` or in a listing of their own.
- Mirror recognition does not absorb into or from a pending remittance.
- The import is all-or-nothing and one audit-trail group.
- `import-and-classification.md` is updated with a fictional remittance-service card payment on Checking.
- Every existing test passes unchanged.
