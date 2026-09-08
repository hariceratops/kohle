# Kohle: everything-is-an-account ledger

## Goal

Kohle should model every place money or value sits as an account — current and
savings accounts, virtual sub-accounts, gold, ETFs, shares, expense categories,
and eventually people — so that value moves between them through one mechanism
rather than a separate one per asset class.

The problem behind it: today a ledger line stores a bare `amount` float that
silently means euros, and an entirely separate set of instrument tables was
started alongside it. Neither composes with the other. Portfolio tracking,
expense categorisation and savings goals each want their own bespoke mechanism,
and the moment more than one asset class exists, a number without a unit stops
meaning anything.

The fix is that every journal line carries quantity, unit, and the price at the
time of the transaction. Cash normalises to price 1, so a €80 grocery line and a
10-share purchase line are structurally identical and reporting never has to
branch on which kind it is. Buying shares stops being a conversion and becomes
an ordinary two-sided transaction: euros leave one account, shares arrive in
another.

## Considerations surfaced

**Prices are recorded, never computed.** The price on a line is what actually
happened at that moment. If the ledger instead asked a price source to derive
one side from the other, re-running an import a year later would produce
different books. Fetched prices live in a separate history table that only
reporting reads, and answer a different question — what is this worth today.

**Lots are derived, not stored.** Profit reporting needs to know which shares
were sold. Because FIFO is forced for German securities there is no choice to
record, so replaying a unit's lines in date order at report time reconstructs
the lots without any extra schema. This only holds if sales carry quantity,
price and date exactly as purchases do — if a sale ever lands as a bare transfer
with no price, the replay does not fail, it silently returns wrong profit. That
argues for the importer plugin contract requiring price on asset movements
rather than trusting each plugin to remember.

**Virtual accounts are real accounts.** A virtual account is a child of a
physical account, letting savings be earmarked for a purpose without opening
accounts at more banks. The parent is purely the sum of its children: on
creation, a physical account gets a default child that inherits its balance, and
further children are made on demand. Allocating to a goal is then a transfer
between siblings that nets to zero at the parent — no new concept needed. The
self-referential `parent_id` needed for this already exists on `Account`.

Two rules follow. Only leaf accounts should be postable: if a transaction lands
directly on a parent, parent-is-sum quietly stops holding and reports go wrong
with no error raised anywhere. And nesting should be recursive rather than
two-level, since a recursive sum costs nothing and a two-level assumption ends
up baked into every report.

**`iban` cannot be mandatory.** Virtual accounts, expense accounts and people
accounts have no IBAN. This is already broken for expense accounts today,
independent of virtual accounts. (Made nullable in `kohle/domain/models.py` as
part of this discussion.)

**Bank reconciliation happens at the parent level.** The bank reports one
balance for an account that Kohle holds as a rollup of children. That
reconciles correctly, but only if reporting knows which level to compare at —
a rule that has to be built, not inherited.

**Classification starts as rules.** A rule engine matching description and
counterparty to an expense account comes first. Its accumulated output is what
would later train an ML classifier, so there is no reason to build both at once.

**Splitting is decoupled.** People modelled as accounts makes a split expense
just several lines against several people-accounts. Nothing in the core depends
on it, so it can land whenever — deferring it costs nothing.

**Frontend shape.** CLI stays primary. The TUI is a second frontend over the
same use cases and services, which is why those layers are the ones worth
keeping stable.

**Account names are globally unique, not unique per parent.** A
`(name, parent_id)` constraint does not constrain root accounts at all, because
SQL treats NULL parents as distinct — two top-level accounts could share a name,
and lookup by name uses `one_or_none()`, which would then raise. Until accounts
are addressable by qualified path (`Assets:Checking:Holiday`), names have to
stay globally unique, which means two parents cannot each hold a child called
"Holiday". Introducing qualified paths is the follow-up that lifts this.

**The default "unallocated" child is not built.** An account with no children is
a leaf and is postable, so the simple case works without it. What is missing is
the operation that adds the first envelope to an account that already has
postings: at that moment the parent stops being a leaf and its existing lines
are stranded on a non-leaf. That operation has to move them to the new default
child.

**Current state of the tree.** The rework described above has been implemented:
the multi-unit ledger, the migration (`7f3c1d9a2b40`, verified to round-trip on
the real database with its three accounts preserved), the account tree, and the
CLI are working with 35 tests passing. The TUI is deliberately excluded and is
still unwired — see [[tui-wiring]].

## Directions rejected

**A parallel instrument ledger.** The `Instrument` / `InstrumentJournalEntry` /
`InstrumentJournalLine` tables currently sitting uncommitted form a second set of
books with no link to the cash side, so a share purchase could never reconcile
against the euros that paid for it. Superseded by units on every line.

**An adaptor that converts between units.** Anything that takes "1000 EUR" and
computes how many shares that is makes recorded history depend on whatever a
price source said that day. The adaptor concept survives only in its recording
sense — capturing the rate that was in the transaction.

**Storing explicit lot linkage.** Unnecessary when the consumption order is
forced; derive by replay instead.

**Dummy German IBANs for accounts that have none.** Stores a falsehood in the
column the importer uses to match statements to accounts, requires either
checksum-valid values that could collide with real accounts or invalid ones that
make the column meaningless, and needs display rules to hide the fakes.
Nullable is less work and stays true.

**Property tracking.** Out for now.

## Open questions

- Is non-EUR cash in scope? It is the same unit machinery plus FX rates, but the
  rates raise the same record-vs-compute question that securities prices did.
- What does "reports" mean beyond positions, profit and net worth? This is the
  least specified area and plausibly hides the most work.
- Does the TUI's generic serde layer (`model_serde.py`) survive the schema
  change, or does the new model make it simplifiable? It is currently the least
  finished part of the codebase.
- How should the importer plugin contract enforce that asset movements carry a
  price, given a silent omission produces wrong profit rather than an error?
- Does a virtual child inherit its parent's account type, or can it differ?
- Where is the leaf-only posting rule enforced — use case layer, or a database
  constraint?
