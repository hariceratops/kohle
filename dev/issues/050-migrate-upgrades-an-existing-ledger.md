# [feat] `migrate` upgrades an existing ledger

`kohle-cli migrate` brings a ledger behind head up to head using the packaged
migrations, as a deliberate step separate from `init`.

Depends on: 049
Spec: `dev/specs/app-initialization.md`

## Acceptance Criteria

- Behind head: upgrades to head and reports the new revision.
- Already at head: reports so, exits 0.
- No database at the path: exits non-zero and points to `init`; nothing is
  created.
- Database newer than the code: exits non-zero and says to upgrade kohle.
- A failed or interrupted `migrate` leaves the ledger at its previous
  revision with its data unchanged.
- The README documents `migrate`.
- Existing tests pass.
