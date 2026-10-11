# [feat] Alpha Vantage price plugin

The first networked price source. Throttling partway through a run is the
normal case on the free tier (about 25 requests a day), so a throttled run
keeps what it fetched and reports the rest as transient.

Depends on: 030, 031
Spec: `dev/specs/price-fetcher-plugin.md`

## Acceptance Criteria

- Discovered through the `kohle.plugins` group as `alphavantage`.
- The API key comes from `KOHLE_ALPHAVANTAGE_KEY`. A missing key is a named
  plugin `Err`, not an exception and not a per-unit failure.
- The design confirms which endpoint returns a finished daily close, so a
  trading day still in progress is never stored; the choice is recorded in
  `dev/design/price-fetcher-plugin.md`.
- The HTTP call sits behind a seam tests replace. The suite makes no live
  network calls; responses are recorded fixtures under `tests/fixtures/`.
- The plugin recognises the throttling signal in the response body. When the
  limit hits it keeps the closes already fetched and returns
  `Unavailable(transient)` for every symbol it did not reach; this is not a
  whole-plugin `Err`. A recorded run throttled after the first symbol writes
  that symbol's close, reports the rest as transient, and exits non-zero.
- A symbol the provider does not carry is `Unavailable(not_covered)`.
- Closes are reported in EUR: binding a symbol is the user's assertion that it
  quotes in EUR, and the plugin makes no extra request to check.
