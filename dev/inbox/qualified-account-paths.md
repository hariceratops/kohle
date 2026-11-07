# Qualified account paths

## Goal

Let two different parents each hold a child with the same name, such as
`Cash/Holiday` and `Checking/Holiday`, by addressing accounts through their
position in the tree instead of a bare name.

The problem behind it: account names are globally unique today, so a name is
a complete address and every command takes one. A second "Holiday" under
another parent is refused. Envelopes make this bite sooner than it did when
the tree held only a few accounts: the natural names for an envelope
(Holiday, Groceries, Rent) repeat across the physical accounts that hold them.

This is a nice-to-have, not a defect. Nothing in the double-entry model or the
account tree depends on it, and the global rule is a deliberate, documented
one.

## Considerations surfaced

**Why names are unique today.** A `(name, parent_id)` constraint does not
constrain root accounts, because SQL treats NULL parents as distinct: two
top-level accounts could share a name, and lookup by name uses
`one_or_none()`, which would then raise. So the rule stayed global until
accounts can be addressed by a qualified path.

**What a path looks like.** The brief that started this used
`Assets:Checking:Holiday`. Whether kohle uses a separator character, a slash,
or something else is open, and so is what happens to names that already
contain it.

**Every command that takes an account name is affected.** `record`,
`record-split`, `balance`, `entries-in-period`, `add-account --parent`,
rules (`account = "Groceries"` in the rule file), `set-cap`, `end-cap`,
`reclassify`, `list-child-accounts`. A bare name would have to keep working
where it is still unambiguous, or every command, rule file and checked
example in the guide changes at once.

**Stored data refers to accounts by id, not by name,** so the schema is not
the hard part. The rule file is: it stores account names as text, and a rule
that names `Holiday` must keep meaning one account after a second `Holiday`
exists.

## Open questions

- Is a bare name still accepted when it is unambiguous, and an error naming
  the candidates when it is not? Or are paths always required?
- What is the separator, and how are names containing it handled?
- Does an existing ledger need a migration, or do existing names simply stay
  valid as one-segment paths?
- Does this wait for the first-envelope move (adding a child to an account
  that already has postings), which is refused today?
