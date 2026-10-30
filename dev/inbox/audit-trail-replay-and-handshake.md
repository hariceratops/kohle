# Audit-trail replay and a writer handshake

A brief, not a spec. Follows `device-topology-and-sync`, which ships option
one (one writer, read copies via `snapshot`). This is the later, more robust
option, and partly a project to learn from.

## Goal

Keep reader devices in sync by sending the changes the master recorded,
instead of copying the whole ledger, and let devices agree on who the writer
is instead of relying on configuration.

## Replay: what was found

- **Capture, not replay.** The master sends the current rows for each changed
  `(entity_type, entity_id)` plus child rows, and the replica upserts by id.
  Re-running commands would give different `created_at` / `deleted_at`.
  Recording values in `Operation.state` is the worse variant: it needs
  serialisation for Decimal, date and enum values and gains nothing.
- **The trail is mostly complete.** All runtime writes go through
  `crud_create` / `crud_update` / `crud_delete`; no raw SQL in the services.
  Gaps: journal lines get no `Operation` of their own
  (`kohle/services/journal_services.py:64-74`), migrations write and delete
  data unaudited (`d4a2e6f0b917_people_root_account.py`), and rows from before
  the operations table existed have none. Whether the real ledger has such
  rows is unchecked.
- **Cost:** master recording S; export command M (changed rows and their
  lines in foreign-key order, group-id range, schema revision); apply step L
  (upserts by id in table order, `PRAGMA defer_foreign_keys` for
  `accounts.parent_id`, never `INSERT OR REPLACE`); gap and schema checks S
  each; tests M (random command sequences, export, apply, compare with a
  snapshot).
- **Hard parts.** The apply step is a write on a device whose guarantee is
  that it never writes, so it needs an exception to the reader guard. And
  every future write path must stay audited, or replicas drift quietly; a
  snapshot cannot fail that way.
- **A re-sync is a snapshot.** Any schema mismatch, `migrate` on the master,
  or gap in the group ids forces one, so `snapshot` stays.
- **Syncthing:** a replica's database can no longer sit in a Receive Only
  folder, since its own writes would be flagged. Only the change files sync.

## Handshake: what it must settle

- Who may write, and how a device learns it. Today this is configuration
  only (`ledger.mode`); nothing stops a second device from being set to
  `writer`.
- Candidates: a lease held by one device; a ledger id and epoch stamped into
  each copy, with an explicit promote command that bumps the epoch and
  devices refusing a snapshot with a lower epoch (catches the old master
  returning after a promotion); a coordinator service. Only live
  coordination stops two devices promoting themselves while offline.
- Reaching the master from outside the home network is a separate decision;
  the Pi is not exposed today and a tunnel was rejected.

## Triggers to start

- The ledger grows to tens of MB, or a reader cannot take a whole file (the
  ESP32 display).
- Or the wish to build it as a learning project.

## What to keep open in the meantime

- `device-topology-and-sync` must not state that a reader never changes its
  file more strongly than "except by an apply command".
- Its docs must not present Receive Only as the only correct reader setup.

## Update 2026-10-27: moved out of kohle

Decided: multi-device and multi-master sync is a separate side project, not a
kohle feature. Repo under `~/code`, reference implementation in Rust, protocol
specified separately from the code; aimed at a conference talk. Scope is mid
2028, not the January release. kohle becomes the first adopter later. No
further discussion planned until then.

Why the brief above is not the basis for it (colleague session):

- `operations` is not an op log. It records which `(entity_type, entity_id)`
  was touched and the verb; `field` and `state` are almost always NULL
  (`kohle/infrastructure/crud.py`). Fine for a reader catching up to one
  writer, useless for merging two.
- SQLite's session extension captures every write on a connection, including
  journal lines and migrations that never get an `Operation`. Prefer
  changesets over the audit trail. Unverified: APSW exposing the extension in
  recent versions; rusqlite has a `session` feature.
- Not a CRDT problem for kohle. Prices, imports (bank reference as idempotency
  key) and soft deletes commute. Classifications and splits merge but
  last-writer-wins drops a human decision. `uq_account_name` is global, so
  concurrent creates conflict. FIFO is recomputed from journal lines, so it
  merges as state, but "no sale exceeds its lots" does not (Bailis et al.,
  "Coordination Avoidance in Database Systems", VLDB 2015).
- Integer primary keys collide across writers: multi-writer needs UUIDs or
  `(device, counter)` ids, a migration across every table. That is kohle's
  adoption cost.
- Category theory link is patch theory (Mimram and Di Giusto), not CRDTs
  (order theory).
- Prior art to read first: cr-sqlite, Litestream and LiteFS, Turso and
  libSQL, Electric, Automerge.
- First experiment: session on a copy of the real ledger, run `import-statement`
  and `fetch-prices`, apply the changeset to an older snapshot, compare with a
  fresh one. Then two copies with random command sequences cross-applied, logging
  SQLite conflict types per table.
- Open: whether recording on a laptop away from the Pi is wanted; if not, the
  talk should say multi-master is a learning exercise.
