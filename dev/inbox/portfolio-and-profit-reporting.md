# Portfolio and profit reporting

## Goal

Report what is held, what it is worth now, and what was gained on things sold —
across every account type, from one ledger.

The problem behind it: these look like three features but are two very different
computations. Current standing needs only quantity and today's price and no
history at all. Profit needs to know which specific units were sold, because
they were bought at different prices. Conflating them leads to building lot
machinery for reports that never needed it.

## Considerations surfaced

Positions are cheap: holdings times latest price, per unit. No purchase history
required.

Profit is a replay. Because FIFO is forced for German securities, no choice
needs recording — walking a unit's lines in date order and consuming purchases
against sales reconstructs the lots at report time. This depends entirely on
sales carrying quantity, price and date the way purchases do, which is why the
importer contract matters to this brief.

Net worth is a recursive rollup over the account tree. It is only trustworthy
because of the leaf-only posting rule from the ledger design — if anything ever
posts to a parent, every rollup is quietly wrong. Bank reconciliation compares
at the parent level while postings live in children, so reports need to know
which level a given question is asked at.

This is the least specified area of the whole vision, and plausibly hides the
most work. "Reports" has been used throughout the discussion without ever being
pinned down.

## Directions rejected

Storing explicit lot linkage — sales pointing at the purchases they consumed.
Unnecessary when the consumption order is forced, and it would have to be
maintained on every edit.

## Open questions

- Unrealised gains as well as realised, or only realised?
- Net worth over time, not just today? That needs historical prices at past
  dates rather than just the latest, which changes what the price-history table
  has to hold.
- What is the actual report inventory? Positions, profit and net worth are
  established; everything else is guesswork.
- CLI output shape — tables, or something a spreadsheet can consume?
- Does the TUI get its own reporting views, or does it stay an editor over the
  same use cases?
