# CLI output and message polish

## Goal

Fix a handful of small defects in command output and messages that writing
the user guide turned up, so the checked examples show clean, correct text.

The problem behind it: the guide's examples run the real commands and match
their output exactly, so each of these now appears on a page word for word.
None is a feature; each is a `change`. They are listed together because they
share a cause (found by documenting the commands) and a cost (the page or
README block that shows the output has to follow the fix).

## Findings

**`import-statement` prints `Import succeded`.** A typo for "succeeded". It
is on the README taste, the first thing a reader sees, and in every guide
example that imports a statement. Fixing it means updating those blocks in
the same change; the suite fails until they follow.

**`reclassify` after `unsplit-line` still says the entry is split.** After
`split-line 4 ...` and then `unsplit-line 4`, `reclassify 4 Dining` fails with
"Journal entry id 4 is split; undo the split with unsplit-line 4, reclassify,
then split again". The advice is what was just done. Either the unsplit leaves
state behind that `reclassify` still reads, or the check is wrong. Needs a
look at how `reclassify` decides an entry is split. A bug, so it goes through
`change` with a regression test.

**Unrounded amounts in `who-owes-what`.** Some runs print `32.00000000` or
`0E-8`, but only when a person with no splits (shown as `-`) is also listed.
Other runs print `32.00`. The share-sum error also prints the line amount as
`64.00000000`.

**`fetch-prices` prints the previous close with eight decimals.** When a
second close is appended it prints `previous 110.50000000 on 2026-06-16`,
where other commands print `110.5`.

## Not findings, but worth knowing

- **Actions are pinned to major tags.** `.github/workflows/docs.yml` uses
  `actions/checkout@v4`, `astral-sh/setup-uv@v6`, `actions/upload-pages-artifact@v3`
  and `actions/deploy-pages@v4`. Pin them to full releases at least two weeks
  old, from a session with network access.
- **The revision hash on Getting started.** The `init`, `list-settings` and
  `migrate` blocks print the current Alembic head. Each new migration fails
  those checked examples until the three blocks are updated. That is the
  drift check working, but whoever adds a migration should know.
- **Repo-wide `ruff` and `mypy` are not clean.** Unchanged by the
  documentation feature; the files it touched are clean.

## Open questions

- Should `who-owes-what` and the share-sum error round to the unit's display
  precision everywhere, or only where the value is shown to a person?
- Should the error-message wording in the CLI be reviewed together with
  `cli-command-naming`, since both change text the guide shows?
