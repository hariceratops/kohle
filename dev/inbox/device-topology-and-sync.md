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

**Agreed topology: the Raspberry Pi 3 is the single writer.**

- *Read-write: the Pi.* It runs the daily price fetch (cron) and the imports —
  statements are downloaded by browsing on the Pi itself. Every write
  (imports, fetches, corrections, settings) happens there.
- *Read-only: every other device* — the laptop, tablet and phone receive the
  ledger through Syncthing.

With one writer, Syncthing needs nothing custom and no protocol of kohle's
own is needed. An earlier idea — the Pi writing closes to a separate CSV that
the laptop reads through the file price plugin — is unnecessary once the Pi
writes the ledger directly.

**Readers must not write by accident.** A stray write on a reader device
creates a conflict copy that silently diverges. kohle on a reader should open
the database read-only (SQLite's read-only mode), so a write command fails
there rather than forking the ledger. How a device knows it is a reader is
open.

**Copies in transit.** A reader may open the file while Syncthing replaces it.
Syncthing writes a temporary file and renames it into place, so a reader sees
the old or the new file, not a mix; confirm before relying on it. SQLite's WAL
mode keeps extra files beside the database, which sync separately; the journal
mode on the writer should be one that leaves a single consistent file.

**The Pi as the only copy that matters.** The writer holds the ledger of
record on an SD card, which wears and corrupts. Backups of the Pi's database
(the existing `kohle.db.bak-*` files are manual ones) become important.
Syncthing copies on readers are not backups: a corruption on the Pi syncs out.

**Resource fit on a Pi 3.** 1 GB of RAM and an ARM CPU; kohle's dependencies
(SQLAlchemy, the price plugins, the `holidays` package) are expected to run,
unverified. Imports and reports are small.

**Reading on a phone or tablet.** Something must open the ledger there; the
TUI does not run on a phone. What the reader is (a synced file plus a viewer,
a read-only web view served by the Pi, a static export) is open and is a
larger question than sync.

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
- **Price fetching only on the laptop**: it is not always on; the Pi is.
- **A separate closes file written by the Pi for the laptop to read**: needed
  only while the laptop was the writer.
- **An ESP32 as the price fetcher**: it cannot run Syncthing, so it would need
  its own channel to the writer, and unpacking a 200 KB bhavcopy is tight in
  its RAM without PSRAM.

## Open questions

- What reads the ledger on a phone or tablet?
- How does a reader device know it is read-only: a setting, an environment
  variable, the absence of something only the writer has?
- Which SQLite journal mode on the writer keeps the synced file consistent?
- Backup schedule and destination for the Pi's database.
- Does the Pi run the CLI only, or also the TUI for imports and corrections?
- What goes into the ESP32 summary file, and in what format?
