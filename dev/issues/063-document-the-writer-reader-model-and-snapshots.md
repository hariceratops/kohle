# [chore] Document the writer/reader model and snapshots

Users need to know how kohle supports several devices, and that the supported
approach is one of several possible, not the only one.

Depends on: 059, 060, 061, 062
Spec: `dev/specs/device-topology-and-sync.md`

## Acceptance Criteria

- The docs explain the model kohle uses: one device holds the writable
  ledger, other devices read a copy, `snapshot` produces that copy, and
  `ledger.mode = reader` keeps a copy read-only.
- The one-writer rule is stated as a property of copying the file between
  devices, not of kohle: file sync produces conflict copies when two devices
  write, and network filesystems lock unreliably.
- The docs say this is option one of the known strategies, the one kohle
  supports. A server layer in front of SQLite (rqlite, LiteFS, libSQL) is a
  possible later option, and a synced operation log is a larger, separate
  feature; neither is built.
- The docs say the connection is a single seam, so another layer could be
  added later.
- Syncthing, `rsync`, a Raspberry Pi and cron appear only as examples of
  moving and scheduling the copy; the user's own setup is one worked example.
- The docs cover `ledger.mode` and `ledger.path` on a reader, the `chmod 444`
  backstop, and that reader copies are not backups.
- The docs state the limit: nothing in kohle stops a second device from being
  configured as a writer, and a reader whose `config.toml` is missing falls
  back to `writer`. The guarantee comes from the one-way transport, the
  device configuration and file permissions, not from coordination between
  devices.
- The docs name record-and-replay and a writer handshake as possible later
  work and do not present Receive Only as the only correct reader setup.
- A user with a single machine can skip the topic entirely: nothing in the
  quick start mentions it.
