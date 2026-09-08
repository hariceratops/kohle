# Price fetcher plugin

## Goal

A plugin contract for fetching current prices for units Kohle holds — ETFs,
shares, gold — into a price-history table that only reporting reads.

The problem behind it: valuing a portfolio needs today's price, but recorded
transactions must never depend on a live source, or re-running an import later
produces different books. Keeping fetched prices in their own table, written by
plugins and read only by reports, is what enforces that separation structurally
rather than by discipline.

## Considerations surfaced

The shape already exists in the codebase. `StatementImporterPlugin` is an ABC
discovered through the `kohle.plugins` entry-point group, and a fetcher is the
same pattern with a different method. But `plugin_manager.load_plugins()`
currently asserts `issubclass(plugin_class, StatementImporterPlugin)` and raises
`TypeError` otherwise, so it has to learn about more than one plugin kind before
a second one can exist.

Different asset classes are different providers. Gold spot, listed equities and
ETFs do not come from one API, so this is several plugins rather than one with
branches — which is an argument for the plugin split being by source, not by
asset class.

Price history should be append-only. A price fetched for a date is a fact about
that date and should never be rewritten, which also makes historical net-worth
reporting possible later without a separate mechanism.

Fetching will fail — offline, rate-limited, delisted. Reporting has to have a
defined behaviour for "no price available" and for "price is old", and those are
different situations.

## Directions rejected

Prices participating in transaction recording — rejected in the ledger design
and restated here because this is where the temptation reappears.

## Open questions

- What granularity is enough? Daily close is the obvious default but has not
  been confirmed.
- How does reporting present a stale price versus no price at all, and at what
  age does a price become stale?
- Is there a manual price-entry path for units with no feed, and does it share
  the same table?
- Does fetching happen on demand during a report, or as an explicit command that
  populates history?
