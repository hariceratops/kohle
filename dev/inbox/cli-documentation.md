# Structured documentation

## Goal

Split kohle's documentation into a short README that sells the app and a
structured guide under `docs/` that can be navigated: by the author, by
future users if the app ever becomes useful to others, and by agents working
on the code. The guide reads as plain markdown on GitHub and optionally
renders as a site with MkDocs.

The problem behind it: `README.md` is 687 lines and carries everything —
setup, concepts, every command's options, every report's columns. It cannot
be navigated, a new command is a second place to edit, and a stale statement
survives until someone notices.

## Considerations surfaced

**Follow the s2s layout** (`../s2s`). Its README holds the pitch, key
features, a short "taste" of the API, a link to the guide, how to read the
guide locally, and a roadmap. Its `docs/` holds an `index.md` explaining how
the guide is organised, one page per concept, a reference page, and
`mkdocs.yml` plus `requirements.txt` beside the pages (`docs_dir: .`,
mkdocs-material, `strict: true`), invoked as `mkdocs serve -f docs/mkdocs.yml`.

**For kohle that means:**

- README: what kohle is, key features, a taste (create accounts, import a
  statement, run a report), a roadmap if one is useful, and a link to the
  guide.
- `docs/`: concept pages carved from the current README — accounts and units,
  recording entries, import and classification, people and splitting, prices,
  reports, and settings/initialization once `app-initialization` lands.

**The command reference is generated, not written.** Click already declares
every command, option, default and choice; `mkdocs-click` can render them
into a reference page. That is the one page that would otherwise drift. The
concept pages carry the explanations no generator can produce (FIFO across own
depots, why reports never call a price plugin), and they become the reason to
write good Click help text.

**Checking examples.** s2s compiles every fenced program under ctest. The
kohle equivalent would run the CLI examples in the README and guide against a
scratch ledger in the test suite. It would also catch command renames from
`cli-command-naming`. Worth considering, not yet decided.

**Existing `docs/` content is not documentation.** `double_entry.md` and
`to_llm.md` are old LLM conversation transcripts. They move to `archive/`
before `docs/` becomes the guide.

**Roadmap source.** `todo.md` is stale and ignored. The roadmap, if the README
carries one, reflects the inbox and current work instead.

**Order of work.** Doing this before `cli-command-naming` makes the rename
cheaper: the reference regenerates, and only the concept pages need edits.

## Directions rejected

- **Help text alone, no rendered guide**: `--help` covers options but not
  concepts, and gives no navigation across them; structured documentation is
  wanted for the author, for others, and for agents.
- **Sphinx**: the s2s precedent is MkDocs with mkdocs-material; one toolchain
  across the author's projects.
- **A hand-written command reference**: it is exactly the page that drifts.
- **Migrating `todo.md` into the roadmap**: it is stale; the inbox is the
  source of what is planned.

## Open questions

- Are the CLI examples checked in the test suite, and how strictly?
- Does the rendered site get published anywhere, or is it local only?
- Do plugin-provided commands and options (importers, price plugins) appear
  in the generated reference?
- What is the "taste" in the README: one end-to-end session, or a few short
  snippets?
