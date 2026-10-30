# [feat] Bundesland becomes an effective-dated history, and init compares with the start entry

Replace the single `state` setting with a history, so sampling uses the
Bundesland in force on each date, and keep `init` safe to re-run. This absorbs
the former issue 071: with `state` out of the settings registry, `init` would
otherwise report "already initialized" for a different state. Recording a move
comes in 070, which must land immediately after this slice.

Depends on: 064, 073 (the `app-initialization` amendment should land first)
Spec: `dev/specs/configurable-net-worth-sampling.md`

## Acceptance Criteria

- The history is ledger data that travels with snapshots; it is not
  `config.toml` and not a general key/value channel.
- The migration converts a stored `state` setting into the `start` entry, or
  creates none if it was unset. `init` writes `init.toml`'s `state` as the
  `start` entry.
- `list-states` shows the full history, oldest first, with `start` for the
  first entry, and leaves no `OperationGroup` behind.
- `net-worth-history` uses the state in force on each rule's unshifted date for
  holiday shifts; `--state` is removed and there is no `BY` default anywhere.
- A ledger with no `start` entry makes `net-worth-history` refuse and point to
  `move-state --from start <code>`.
- `state` leaves the settings registry; `set-setting state …` refuses and
  points to `move-state`, as it refuses device keys.
- The state-code validator is shared by `init.toml` and the new write path.
- The output of `net-worth-history` after `migrate` on a `state = BY` ledger is
  unchanged.
- No command touched here changes the `prices` row count or calls a price plugin.
- On an existing database at head, `init` compares `init.toml`'s `state` with
  the `start` entry, not the state in force today. Equal: reports "already
  initialized" and writes nothing. Different or missing: exits non-zero,
  points to `move-state --from start`, writes nothing. `init.toml` has no key
  for the rule list.
- A history with dated entries but no `start` entry makes `net-worth-history`
  refuse, as when there are no entries at all.
- README lines that describe `--state` and `state` as a setting are removed in
  this slice.
- Existing tests pass, apart from those that test `--state` and `set-setting state`.

## Review 2026-10-30
- Medium: `kohle/use_cases/ledger.py:51-53` fails mypy. `checked` is inferred as `Result[str, InvalidState]`, then assigned a `Result[str, InvalidSettingValue]`; annotate it as the union.
- Low: `kohle/use_cases/ledger.py:42` has `# SETTINGS keys; none today`, which says what, not why.
- Gap: "after `migrate` on a `state = BY` ledger, output equals the pre-feature output" is covered only by the oracle test, which seeds `start BY` directly. Add a test that runs `net-worth-history` on a ledger migrated from `state = BY`.
- Opinion: `SETTINGS` is empty, so `tests/test_settings.py` tests `SetSettings`/`ListSettings` through a monkeypatched stand-in `colour` key. Kept: dropping it would lose that coverage.
- Opinion: the migration revision id `a7c3e9d5b124` was chosen by the implementer; recorded here as the canonical id.
