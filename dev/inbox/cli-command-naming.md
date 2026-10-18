# Revisit the CLI command names

## Goal

Give the commands a consistent, guessable vocabulary before more are added.

The problem behind it: the names grew one slice at a time and mix styles.
Some are verb-object (`add-account`, `add-unit`, `add-rule`, `remove-rule`,
`set-price-source`), some are nouns for reports (`balance`, `net-worth`,
`positions`, `realised`), some are listings with two spellings
(`list-accounts`, `list-child-accounts`, `list-operations`, `list-rules`,
`list-unclassified`), and some are phrases (`who-owes-what`, `settle-up`,
`entries-in-period`, `net-worth-history`, `split-line`, `unsplit-line`).

## Considerations surfaced

**Grouping.** Click supports command groups, so `kohle-cli rule add`,
`kohle-cli account list` and `kohle-cli report positions` are possible. That
shrinks the top level but lengthens every invocation.

**Cost of a rename.** The README, the issue files and the design documents
quote command names throughout, and any scripts the user has written call
them. Renaming after `cli-documentation` exists is cheaper, since the
reference would regenerate.

**Compatibility.** Whether old names stay as aliases for a time, or the break
is clean because there is one user, is a choice to make explicitly.

**Do it before adding more.** `init`, budgeting and the held-lines work in
`strict-classification` each add commands; naming them into a scheme once is
cheaper than renaming them later.

## Directions rejected

None yet.

## Open questions

- Flat names with one convention, or command groups?
- Keep old names as aliases?
- Is this one rename sweep, or a rule applied to new commands only?
