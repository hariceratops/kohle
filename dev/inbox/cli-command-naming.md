# Readable CLI command names

## Goal

Give `kohle-cli` a consistent, guessable command vocabulary before more
commands are added, so that a human can drive it directly and compose it into
scripts and cron jobs without looking names up.

The problem behind it: the names grew one slice at a time and mix styles.
Some are verb-object (`add-account`, `add-unit`, `add-rule`, `remove-rule`,
`set-price-source`), some are nouns for reports (`balance`, `net-worth`,
`positions`, `realised`), some are listings with two spellings
(`list-accounts`, `list-child-accounts`, `list-operations`, `list-rules`,
`list-unclassified`), and some are phrases (`who-owes-what`, `settle-up`,
`entries-in-period`, `net-worth-history`, `split-line`, `unsplit-line`).

## Considerations surfaced

**What the CLI is for.** The TUI is meant to become the app — the place for
visualising tables and graphs. The CLI is the scaffolding that is quick to
roll out, and the surface for cron jobs, imports, agents and quick one-off
hits. Many operations are intuitive enough to use directly from the CLI
without the TUI, and a person automating kohle will cascade CLI commands from
their own Python or bash scripts. So the names are read by humans and typed
into scripts; both need them guessable and stable.

**The TUI builds on the commands.** The TUI is built on top of what the CLI
commands do, not beside it. A command vocabulary that maps cleanly onto
concepts gives the TUI the same structure.

**The names are settled in a Q&A session.** The vocabulary itself is not
decided in this brief; it is the subject of the requirements interview.

**Grouping is the main structural choice.** Click supports command groups, so
noun-first forms like `kohle-cli account add`, `kohle-cli rule list` and
`kohle-cli report positions` are possible. A proposed direction, not agreed:
at about 25 commands, and past 30 once init, settings and budgeting land,
groups make top-level help readable and map one-to-one onto the concept pages
in `cli-documentation`. The cost is a longer invocation.

**The entry point stays `kohle-cli`.** It is kept distinct from the TUI, which
is coming back.

**History is left alone.** The issue and design files quote today's names.
They record what was built at the time; rewriting them would make them
disagree with the commits.

**Cost of a rename.** The README and the user's own scripts call the current
names. Renaming after `cli-documentation` lands is cheaper, since the
reference regenerates.

**Do it before adding more.** `init`, settings, budgeting and the held-lines
work in `strict-classification` each add commands; naming them into a scheme
once is cheaper than renaming them later.

## Directions rejected

- **Renaming the entry point to `kohle`**: the TUI will be integral; the two
  entry points stay distinct.
- **Machine-readable output as part of this work**: deferred, see below.

## Deferred: machine-readable output

Output today is human-readable tables, and stays so for now. Once the TUI is
stable, evaluate adding machine-readable output alongside it. When that
happens, the format must be one that serialises and deserialises faithfully
(round-trips) for agents and other programs — not merely something
parseable. Not part of this brief.

## Open questions

- The command names themselves (for the Q&A session).
- Command groups or flat names with one convention?
- Keep old names as aliases for a while, or a clean break? (One user today;
  the user's own scripts are the only callers known.)
- Is this one rename sweep, or a rule applied to new commands only?
