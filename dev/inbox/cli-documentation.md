# Generated CLI documentation

## Goal

Produce command reference documentation from the CLI itself, so it cannot
drift from the commands and options that actually exist.

The problem behind it: `README.md` documents commands by hand, section by
section. Every new command or option is a second place to edit, and a stale
statement survives until someone notices. `todo.md` lists "generate cli
documentation automatically - sphinx / mkdocs + click".

## Considerations surfaced

**Click can describe itself.** Command names, options, defaults, choices and
help text are all declared on the Click commands, so a generator can read them
instead of anyone retyping them. Help text quality then becomes the
documentation's quality.

**Two kinds of documentation.** The reference (what each flag does) can be
generated. The explanation (what FIFO does with an own-depot move, why a
report never calls a price plugin) cannot, and is the larger part of the
current README. The brief concerns the reference; the README keeps the
explanation and would link to the generated reference.

**Staying current.** `todo.md` also lists git hooks for tests and
documentation generation under deployment. Whether generation runs in a hook,
in CI, or by hand decides how a stale reference is caught.

**Order of work.** Command names may change (see `cli-command-naming`).
Generating the reference first would make that rename cheaper to document,
since only the source changes.

## Directions rejected

None yet.

## Open questions

- Sphinx with a Click extension, or MkDocs? Which fits a small project with
  one author?
- Is the generated output committed, or built on demand?
- Do the plugin-provided options (importers, price plugins) appear in it?
