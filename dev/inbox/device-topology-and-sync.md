# Device topology and sync

## Goal

Decide which device writes the ledger and which only read it, so that the
ledger can be read on a tablet or phone while prices keep being fetched when
the laptop is off — without a proprietary sync protocol.

The problem behind it: statements are imported where a browser can download
them, reading should work on every device, and price fetching needs a machine
that is on every day. The laptop is not always on and other devices have
downtime. Where writes happen decides the sync mechanism.

## Considerations surfaced

**Syncthing does not merge.** If two devices write the same SQLite file,
Syncthing produces a `.sync-conflict` copy and one side's writes are lost.
Syncing a SQLite file is safe only with exactly one writer per file.

**Agreed topology: the Raspberry Pi 3 is the master.**

- *The Pi holds the only writable ledger.* It runs the cron jobs (daily price
  fetch) and every write: imports, corrections, settings.
- *Imports are driven from the laptop over SSH.* Statements are copied to the
  Pi and the import is run there; the laptop holds no writable ledger.
- *Every other device reads a copy*, refreshed daily at a planned time — the
  laptop, tablet and phone.

With one writer and copies flowing one way, no proprietary sync protocol or
merge workflow is needed.

**Statements arrive through an inbox folder on the Pi.** Statements are
posted (copied) into an inbox folder; the import runs either explicitly over
SSH or from an inotify job watching the folder. Because imports are
idempotent (deduplication by native reference per account), the inbox can
keep filling for a long time and be re-run safely.

- *The path carries the import arguments.* `import-statement` takes a plugin
  name, a cash account and possibly instrument accounts; a file in a flat
  folder carries none of that. Proposed: `inbox/<plugin>/<cash-account>/`,
  so a file cannot be imported against the wrong account. Broker imports
  with instrument accounts need a deeper path or a small manifest.
- *Never import a half-written file.* An inotify job triggers on
  `close_write` or `moved_to`, never `create`; uploads write under a
  temporary name and are renamed in, which is atomic. A half file that
  happens to parse would otherwise import silently short.
- *Two writers on the Pi.* The price-fetch cron and an inotify import can
  run at once. SQLite serialises them with its lock; the loser waits only
  for its busy timeout, so a long import overlapping a fetch should retry
  rather than fail.
- *The inbox is also an archive.* Keeping every raw statement lets a lost
  ledger be partly rebuilt by re-importing. Not a full backup:
  classifications, splits and manual entries exist only in the database.

**Sync a snapshot, never the live file.** At the planned time the Pi writes a
consistent snapshot with SQLite's `VACUUM INTO 'snapshot.db'` (or the backup
API), and only the snapshot is distributed. A snapshot cannot be caught
halfway through a cron write, and the live file never leaves the Pi.
Verified: `VACUUM INTO` produces a single self-contained file with no
journal or WAL side files, so the writer's journal mode no longer matters to
readers.

**Keeping readers read-only: three layers.** Verified on 2026-10-18 against
kohle's SQLAlchemy setup, except the first, which is from Syncthing's
documented behaviour.

1. *Copies flow one way.* Syncthing folder types: Send Only on the Pi,
   Receive Only on readers; a reader never sends changes back, and local
   modifications on a reader are flagged and can be reverted to the Pi's
   version. A scheduled `rsync` pull is one-way by construction and gives the
   same guarantee. The Pi's ledger cannot be touched from a reader.
2. *kohle opens the copy read-only.* `sqlite:///file:<path>?mode=ro&uri=true`
   reads normally and refuses any write with "attempt to write a readonly
   database". A missing file is an error ("unable to open database file") and
   no empty database is created, so a wrong path fails loudly instead of
   showing an empty ledger. In kohle this is the engine URL in
   `kohle/db/connection.py`, chosen by whatever marks a device as a reader.
3. *File permissions.* A `chmod 444` snapshot also refused a write from a
   plain (non-read-only) open. A backstop, not the guarantee.

**The Pi as the only copy that matters.** The master holds the ledger of
record on an SD card, which wears and corrupts. Backups of the Pi's database
(the existing `kohle.db.bak-*` files are manual ones) become important.
Syncthing copies on readers are not backups: a corruption on the Pi syncs out.

**Resource fit on a Pi 3.** 1 GB of RAM and an ARM CPU; kohle's dependencies
(SQLAlchemy, the price plugins, the `holidays` package) are expected to run,
unverified. Imports and reports are small.

**Syncthing across all devices is the base.** Agreed: the Pi, laptop, tablet
and phone already sync other tools with Syncthing (Taskwarrior, Logseq, a
language app), so the kohle snapshot is one more synced folder, not a separate
mechanism. The Pi is not exposed to the internet; no VPN or tunnel service.

**TUI over SSH at home.** Running the TUI on the Pi from any device's SSH
client reads the live ledger without a copy, and is the intended way to use
kohle interactively once `tui-wiring` lands. It works on the home network
only; away from home, devices read their synced snapshot.

**Reading on a phone or tablet away from home.** Something must open the
synced snapshot there; the TUI does not run on a phone. What that reader is (a
viewer app, a static export written alongside the snapshot) is open.

**An ESP32 display (optional, for fun).** The read side suits an embedded
project: an e-ink display showing net worth, or the month's spending against
budget caps. The Pi writes a small summary file after each import or fetch;
the ESP32 reads it over Wi-Fi. Read-only and single-writer, so it cannot
corrupt the ledger. An ESP32 is rejected as the price fetcher (below).

**Interaction with initialization.** `app-initialization` moves the database
to a per-user path with `KOHLE_DB` as override; the synced folder location on
each device has to fit that.

## Directions rejected

- **Writes on several devices with Syncthing**: produces conflict copies, not
  merges.
- **A proprietary sync protocol or merge workflow**: unnecessary with a single
  writer.
- **A VPN or tunnel to reach the Pi from outside**: the Pi stays off the
  internet; Syncthing covers reading away from home.
- **Price fetching only on the laptop**: it is not always on; the Pi is.
- **A separate closes file written by the Pi for the laptop to read**: needed
  only while the laptop was the writer.
- **Syncing the live database file**: a copy can catch a write in progress;
  snapshots replace it.
- **The laptop as a writer that imports locally**: imports run on the Pi over
  SSH instead, keeping one writable ledger.
- **An ESP32 as the price fetcher**: it cannot run Syncthing, so it would need
  its own channel to the writer, and unpacking a 200 KB bhavcopy is tight in
  its RAM without PSRAM.

## Open questions

- What reads the synced snapshot on a phone or tablet away from home?
- How does a reader device know it is read-only: a setting, an environment
  variable, the absence of something only the writer has?
- Distribution: Syncthing (Send Only / Receive Only) or a scheduled `rsync`
  pull? And at what time of day, relative to the price-fetch cron?
- Backup schedule and destination for the Pi's database.
- Does the Pi run the CLI only, or also the TUI over SSH for imports and
  corrections?
- Explicit import over SSH, an inotify job, or both?
- How does a broker statement name its instrument accounts in the inbox
  layout: deeper path or manifest?
- Does a processed file stay in place, or move to a processed folder (both
  are safe given idempotence; the second makes re-runs cheaper)?
- What goes into the ESP32 summary file, and in what format?
