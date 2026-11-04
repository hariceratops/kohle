# kohle
A command line money manager  
Kohle ist umgangssprachlich für 'Geld' im Deutschen

> [!WARNING]
> The app is still a bit personalized: it is built around one household's
> needs (German banks and public holidays, euro as the base currency), and
> some of that shows.

kohle keeps your money in a double-entry ledger that lives in one local file.
Bank accounts, savings envelopes, shares and expense categories are all
accounts, so one mechanism moves value between all of them and every report
reads the same books.

<!-- DRAFT for the author to edit: the key features -->
## Key features

- **One ledger for everything.** Cash, envelopes, shares and the people you
  share costs with are all accounts, so a purchase of shares is as ordinary as
  buying groceries.
- **Bank statements in, categories out.** Import a statement and let your own
  rules sort every line, with a queue for what is left.
- **Shared costs without a spreadsheet.** Split a line with someone, group the
  splits by trip and let kohle suggest the fewest transfers that settle up.
- **Net worth you can check.** Reports show each holding at cost and at market
  value, say how fresh every price is, and never fetch anything behind your
  back.
- **Budgets that are estimates.** Caps per category and period, compared with
  what was spent, with overshoots shown and never enforced.
- **Plugins for the edges.** Statement importers and price sources are plugins,
  and new ones need no change to the core.
- **Yours, on your machines.** A single SQLite file, upgraded safely, with
  read-only copies for your other devices.

## A taste

<!-- GIF: docs/demo/taste.gif is added by issue 104; place it here. -->

A fictional statement, three rules and a report. The files are in
[`docs/examples/`](docs/examples/).

<!-- The GIF tape (issue 104) must mirror the block below; change them together. -->

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli add-account Rent --type expense
Added account Rent (expense) with id 3
$ kohle-cli add-account Groceries --type expense
Added account Groceries (expense) with id 4
$ kohle-cli add-account Salary --type income
Added account Salary (income) with id 5
$ kohle-cli apply-rules rules.toml --yes
3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
  rule 1 (new) -> Rent { iban = "DE02120300000000202051", amount = { min = 400, max = 1500 }, direction = "out" }
  rule 2 (new) -> Groceries { any_field = "FRISCHMARKT|KORNLADEN" }
  rule 3 (new) -> Salary { counterparty = "Beispiel Software", direction = "in" }
Applied: 3 added, 0 retired, 0 reordered, 0 note changed, 0 unchanged
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeded, 9 entries imported
$ kohle-cli balance Groceries
unit                     quantity  price    price date      market value  status      average cost
---------------------  ----------  -------  ------------  --------------  --------  --------------
EUR                        125.05  -        -                     125.05  -                   1.00
Total (base currency)      125.05  -        -                     125.05  -                   -
```

## Read the guide

The guide covers installing kohle, every concept and every command. Read it at
<https://hariceratops.github.io/kohle/> once GitHub Pages is switched on for
the repository, or on GitHub in [`docs/`](docs/index.md), or serve it locally
from the repository root:

```sh
uv run --with-requirements docs/requirements.txt mkdocs serve -f docs/mkdocs.yml
```

The examples in the guide and in this README are run by the test suite, so
they show what kohle really prints. Notes for people working on kohle itself
are in [`dev/docs/`](dev/docs/index.md).

## Roadmap

Planned, in no particular order:

- Consistent, guessable command names, grouped by concept, before more
  commands are added.
- A terminal interface (the TUI, which is not wired up yet) over the same use
  cases as the command line, for tables and graphs.
- Accounts and holdings in more than one currency, with one comparable total in
  euros and gains that reflect what was actually paid.
- Debts and liabilities such as mortgages and credit cards, with each payment
  split between what is spent and what is repaid.
- Savings targets per period, and where contributions fell short of them.
- Expected payments, and a warning when a recurring one has not appeared.
- A second price source with good European coverage, for portfolios the first
  source's daily quota cannot refresh.
- A general stance on undoing, deleting and editing recorded entries, as
  corrections that keep the history.
- Keeping reader devices in sync by sending recorded changes instead of whole
  copies, and agreeing between devices on which one writes.
