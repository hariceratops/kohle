# [feat] Expose the staleness threshold on net-worth

How old a close may be before it is flagged stale is a per-run choice, not
stored configuration; this settles the price-fetcher spec's open item on how
the threshold is set.

Depends on: 035
Spec: `dev/specs/market-value-reporting.md`

## Acceptance Criteria

- `net-worth --max-age-days N` takes a click `IntRange(min=0)`, default 7, and
  passes it straight to `latest_close`'s `max_age_days`. 0 means only today's
  close is fresh.
- With `--max-age-days 7` a close 7 days old is `fresh` and one 8 days old is
  `stale`; the same pair is pinned at a non-default N.
- The CLI boundary test pins `today` by monkeypatching `kohle.app.cli.cli.date`;
  the exact 7/8-day boundary is also tested at the use-case level with an
  explicit `today`.
- A negative or non-integer value is rejected by click with a usage error and
  nothing is read.
- No persistent setting or config mechanism is added.
