# [feat] `nse` price plugin for Indian closes

A plugin returns the official NSE close in INR for an ISIN, so Indian stocks can be priced.

Depends on: 107

## Acceptance Criteria

- Registered under `kohle.plugins`; the symbol is the ISIN; the row matched is the one in the `EQ` series.
- It fetches the UDiFF bhavcopy for the latest weekday and steps back over holidays until a file exists, sending browser-like headers.
- Each close is reported in INR.
- A file whose columns are not the expected ones is a plugin `Err`, never a guess; an ISIN with no `EQ` row is `Unavailable(no_symbol)`.
- The HTTP call sits behind a seam; tests use recorded fixtures and make no network calls.
- `prices.md` lists the plugin.
