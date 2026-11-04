# Import and classification

Importing bank statements and classifying them with rules.

A statement is imported into a cash account with the importer plugin that
reads its format. The sample below is a fictional Deutsche Bank export,
`statement.csv`, shipped with these docs.

```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli import-statement kohle-deutsche-bank Checking statement.csv
Import succeded, 9 entries imported
```
