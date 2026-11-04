# Structured documentation

## Overview

`README.md` is 1199 lines and holds everything: setup, concepts, the options
of every command, the columns of every report. Nobody can find their way
around it. A new command has to be documented in a second place by hand, and
a stale statement stays until someone happens to notice it.

This work splits it into two parts:
- A short README that sells the app.
- A navigable guide under `docs/` for the author, for future users, and for
  agents working on the code. The guide reads as plain markdown on GitHub and
  renders as a MkDocs site published to GitHub Pages.

The layout follows `../s2s`. The command reference is generated from the Click
definitions, and the CLI examples are checked by the test suite. That way the
documentation fails loudly when it drifts from the code, rather than rotting
quietly.

Personal-scale: the author is the only maintainer. This lands before
`cli-command-naming`, so that a later rename only regenerates the reference
and edits the concept pages.

## Goals

- **README.** It contains:
  - The pitch.
  - Key features, succinct and attractive. The agent drafts these and the
    author edits them in review.
  - The existing warning, kept, that the app is still a bit personalized.
  - A taste.
  - A GIF.
  - A link to the guide, and how to read the guide locally.
  - A roadmap.

  It no longer lists any command's options or any report's columns.
- **The taste.** One end-to-end session in one block: create accounts,
  import a statement, classify, run a report. It shows each command and its
  output. The statement it imports is fictional sample data shipped with the
  docs.
- **The GIF.** A recording of the same session, made by a checked-in script
  that anyone can rerun to regenerate it. The tests do not check it.
- **The roadmap.** Built from the `dev/inbox` briefs. It leaves out what has
  been delivered and anything already covered elsewhere in the docs. It does
  not come from `todo.md`, which is stale.
- **Guide layout.** `docs/` follows the s2s layout:
  - `index.md` explains how the guide is organised.
  - `mkdocs.yml` and `requirements.txt` sit beside the pages, with
    `docs_dir: .`, mkdocs-material and `strict: true`.
  - The guide is served with `mkdocs serve -f docs/mkdocs.yml`.
- **Concept pages (v1).**
  - Getting started: install, where the ledger lives, device config, first
    run, schema check, upgrading.
  - Accounts and units.
  - Recording entries and reading the ledger.
  - Import and classification: rules, conditions, the rule file.
  - People and splitting: splits, trip labels, who owes what, settling.
  - Prices, including the bundled price plugins.
  - Reports: net worth, positions and profit, net worth over time with
    sampling rules and Bundesland history.
  - Budgeting.
  - Several devices.
  - Writing plugins (importer and price).

  README material is moved, and may be cut, merged or rewritten in the move.
  It does not have to survive word for word. Explanations a generator cannot
  produce stay on the concept pages, such as FIFO across own depots, or why
  reports never call a price plugin.
- **Generated command reference.** A reference page for `kohle-cli`,
  generated from the Click definitions. A command or option added to
  `kohle-cli` appears there with no edit to the docs.
- **Plugins.**
  - The guide lists the plugins in the `kohle.plugins` entry-point group:
    name, kind (importer or price), and what each accepts. The list is
    generated from the installed entry points, so a newly installed plugin
    appears without a docs edit.
  - The plugin interface (the importer and price-plugin contracts,
    `CashRow` / `SecurityRow`) is documented in a way that cannot drift from
    the code. Generating it from docstrings is preferred, if that scales.
- **Checked examples.** Every `kohle-cli` invocation shown in the README and
  the guide runs in pytest against a scratch ledger. Its printed output must
  match the page exactly.
  - Each block runs on its own and sets up whatever it needs.
  - Examples pin their dates, so the output never depends on the day the
    suite runs.
  - Price examples use the bundled `file` price plugin and never touch the
    network.
  - Install and setup shell lines (`uv sync`, venv activation) and
    config-file snippets are illustration only and are not checked.

  A rename or output change that the page does not follow fails the suite.
- **Developer docs.** Developer-facing material, starting with "Writing
  migrations", moves out of the README into its own MkDocs site, separate
  from the user guide and not part of the published user site.
- **Transcripts archived.** `docs/double_entry.md` and `docs/to_llm.md` move
  to `archive/` before `docs/` becomes the guide.
- **First CI.** A GitHub Actions workflow, modelled on s2s's `docs.yml`:
  - Every PR and every push runs `mkdocs build --strict -f docs/mkdocs.yml`.
  - Pushes to `main` deploy to GitHub Pages.

  A broken link, or a nav entry pointing at a moved page, fails the build,
  and a failed build does not deploy. CI runs nothing else.
- **AGENTS.md** points to `docs/` as the user-facing description of
  behaviour, and gains standing rules:
  - A slice that changes user-visible behaviour updates the matching page in
    the same PR.
  - The README roadmap follows the inbox briefs.
  - Personal data or preferences (from briefs, the author's own ledger or
    setup) never appear in user-facing docs. Examples use fictional accounts,
    people and amounts.

## Non-Goals

- No reference for `kohle-tui` and no TUI GIFs of reports, graphs or tables.
  These come later, once the TUI is wired.
- No test, ruff or mypy runs in CI. The example checks run in the local
  pytest suite only.
- No command renames. That is `cli-command-naming`.
- No rewriting of `dev/specs` or `dev/design`. They quote the names as they
  were.
- No versioned documentation.
- No machine-readable CLI output.
- No other restructuring of the concept pages beyond the v1 set above.

## Technical Approach

- MkDocs with mkdocs-material and mkdocs-click. The docs toolchain is pinned
  in `docs/requirements.txt`, separate from the app's dependencies.
- The design decides:
  - How the example checker finds `kohle-cli` blocks in markdown, and how a
    block marks its expected output.
  - How each block gets a fresh scratch ledger (`KOHLE_DB` pointing at a temp
    path) and its fixture files, such as the sample statement and the price
    file.
- The plugin list reads the `kohle.plugins` entry points. "What each accepts"
  should come from the plugin itself, such as its docstring or a declared
  attribute, rather than a docs table.
- The GIF script: a terminal-recording tool driven by a checked-in script,
  for example a VHS tape. The design picks the tool and keeps it out of the
  app's dependencies.
- The Pages workflow goes in `.github/workflows/docs.yml`. It is the repo's
  first workflow.
- Constraint: the README taste and the guide examples need no network and no
  real personal data.

## Directions rejected

- **Help text alone, no rendered guide**: `--help` covers options but not
  concepts, and gives no navigation across them; structured documentation is
  wanted for the author, for others, and for agents.
- **Sphinx**: the s2s precedent is MkDocs with mkdocs-material; one toolchain
  across the author's projects.
- **A hand-written command reference**: it is exactly the page that drifts.
- **Migrating `todo.md` into the roadmap**: it is stale; the inbox is the
  source of what is planned.

## Open Questions

- Developer docs site: where it lives (for example `dev/docs/` with its own
  `mkdocs.yml`) and what it is called. That is for the design. It must stay
  out of the published user site. Is it built or published anywhere at all,
  or local only? The author hasn't said; settle this before freezing.
- Plugin interface docs: generated from docstrings, or written on the
  "Writing plugins" page. The design picks whichever stays maintainable, and
  docstrings are preferred if they scale.
