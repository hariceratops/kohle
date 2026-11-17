# [feat] Correct a wrong remittance Y

A completed remittance whose Y was mistyped is corrected by reversing the completion and redoing it, in either direction. Depends on 133 and 134.

## Acceptance Criteria

- A command reverses a completion by adjusting entry, returning the remittance to pending, and the completing command then redoes it with the right Y.
- The command is `uncomplete-remittance ENTRY_ID`.
- It works for outgoing and incoming remittances.
- A new `journal_entries.reverses_entry_id` column (the migration of this slice) links the reversal to its completion, and `lots.replay` counts an entry and its reversal as if neither existed, so no spurious gain is booked and no wrong lot is taken.
- Reversing an outgoing completion that would leave a later spend short refuses and writes nothing; the incoming completion and this reversal replay the lots in their own transaction and refuse on a shortfall, including on a ledger whose replay already fails.
- Reversing an incoming completion restores the consumed lots and un-realises the gain.
- Reversal is all-or-nothing and one audit-trail group; reversing a remittance that is not completed fails and writes nothing.
- Nothing is edited or deleted; the audit trail keeps every step.
- The classification records distinguish the reversal from a human category correction.
- `recording-entries.md` is updated.
- Every existing test passes unchanged.
