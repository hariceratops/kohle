# kohle

kohle is a command-line double-entry ledger for personal finance. This guide
explains how to use it.

## How this guide is organised

- **Getting started** installs kohle and walks through a first ledger.
- **Concepts** has one page per topic, each building on the previous ones.
- **Writing plugins** is for people who add a statement importer or a price
  source.
- **Reference** lists every command and option, and the plugins installed.

## Pages

- [Getting started](getting-started.md)
- [Accounts and units](accounts-and-units.md)
- [Recording entries](recording-entries.md)
- [Import and classification](import-and-classification.md)
- [People and splitting](people-and-splitting.md)
- [Prices](prices.md)
- [Reports](reports.md)
- [Budgeting](budgeting.md)
- [Several devices](several-devices.md)
- [Writing plugins](writing-plugins.md)
- [Command reference](reference.md)
- [Installed plugins](plugins.md)

## Reading it

Read the pages on GitHub, or serve the guide locally from the repository root.
The command layers the documentation tools over the project environment, which
the generated pages need in order to import kohle.

```sh
uv run --with-requirements docs/requirements.txt mkdocs serve -f docs/mkdocs.yml
```

## About the examples

Every console session on these pages is run by the test suite against a fresh
ledger that `kohle-cli init` created with `state = "BW"`, on 17 June 2026.
Sample files are in `examples/`. That is why reports here show the same
figures from day to day.
