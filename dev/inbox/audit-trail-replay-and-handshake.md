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
