# Accounts and units

Accounts say where money and holdings are; units say what they are counted in.
Every entry kohle records, covered in [Recording entries](recording-entries.md),
moves quantities of units between accounts.

## Accounts

An account has a name, a type and, optionally, an IBAN. The type is one of
`asset`, `liability`, `income` or `expense`; leave `--type` out and you get
`expense`, so give it explicitly for money you hold. Names are unique across
the whole ledger, even between different parents, because commands refer to an
account by its name alone. An IBAN is unique too.

A fresh ledger is not empty. It already has one account, `People`, which is the
root for the people you share costs with. Leave it alone for now;
[People and splitting](people-and-splitting.md) explains it.

```console
$ kohle-cli list-accounts
account    type    iban
---------  ------  ------
People     asset   -
$ kohle-cli add-account Checking --type asset --iban DE89370400440532013000
Added account Checking (asset) with id 2
$ kohle-cli add-account Cash --type asset
Added account Cash (asset) with id 3
$ kohle-cli add-account Cash --type asset
Error: Account Cash already exists
```

The IBAN is optional and kohle only stores it: it is a label for your own
reference, not something an import is matched against.

### Account trees

`--parent` puts an account under another one, so that related accounts can be
read together. A common use is a virtual envelope: a sub-account of `Cash`
that sets aside money for one purpose, such as groceries, without a second
bank account behind it.

`list-accounts` draws the tree, marking a parent with a trailing `/`. Name an
account to see just its subtree:

```console
$ kohle-cli add-account Cash --type asset
Added account Cash (asset) with id 2
$ kohle-cli add-account Groceries --type asset --parent Cash
Added account Groceries (asset) with id 3
$ kohle-cli add-account Rent --type asset --parent Cash
Added account Rent (asset) with id 4
$ kohle-cli list-accounts
account       type    iban
------------  ------  ------
Cash/         asset   -
|- Groceries  asset   -
|- Rent       asset   -
People        asset   -
$ kohle-cli list-accounts Cash
account       type    iban
------------  ------  ------
Cash/         asset   -
|- Groceries  asset   -
|- Rent       asset   -
```

Only the unmarked accounts, the leaves, can be posted to. An entry that names
`Cash` here is refused, because the money has to sit in one of its envelopes:

```console
$ kohle-cli add-account Cash --type asset
Added account Cash (asset) with id 2
$ kohle-cli add-account Groceries --type asset --parent Cash
Added account Groceries (asset) with id 3
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 4
$ kohle-cli record 2026-03-05 "Top up" 50 --from Checking --to Cash
Error: Account id 2 has children and cannot be posted to directly
```

So make the envelopes before the first posting. An account that already has
postings cannot become a parent, because those postings would stay on it with
no way to post to it or move them:

```console
$ kohle-cli add-account Cash --type asset
Added account Cash (asset) with id 2
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 3
$ kohle-cli record 2026-03-05 "Top up" 50 --from Checking --to Cash
Recorded 50 EUR: credited Checking, debited Cash
$ kohle-cli add-account Groceries --type asset --parent Cash
Error: Account 'Cash' already has postings and cannot become a parent; its postings would be stranded on it
```

Reading is different: a report on a parent rolls up everything beneath it,
which is why `balance Cash` totals all the envelopes.

## Units

A unit is what a quantity is counted in. There are three kinds: `currency`,
`security` and `commodity` (grams of gold, for instance). A unit has an
identifier, which is what you type everywhere else, and a free-text name.

EUR is the base unit. Every value in kohle, and every balance in a report, is
expressed in it. You never add it: kohle creates it the first time an entry
uses it, so a new ledger lists no units at all. Any other unit you hold has to
be added before it can be used:

```console
$ kohle-cli list-units
$ kohle-cli add-unit ACME "Acme Global Equity" --kind security
Added unit ACME (security) with id 1
$ kohle-cli add-unit GOLD-G "Gold, grams" --kind commodity
Added unit GOLD-G (commodity) with id 2
$ kohle-cli list-units
1: ACME (security) Acme Global Equity
2: GOLD-G (commodity) Gold, grams
$ kohle-cli add-unit ACME "Acme again"
Error: Unit ACME already exists
```

`--kind` defaults to `security`. The identifier is the name you type in
entries and see in reports. The symbol a price source knows a security by is
a separate thing, bound to the unit later, as described in
[Prices](prices.md).

Units are what make an account hold more than money. Once `ACME` exists,
[an entry can carry it](recording-entries.md#buying-and-selling-units), and
the account that received it holds a quantity of `ACME` beside its euros.

Every option of `add-account`, `add-unit` and the list commands is in the
[command reference](reference.md).
