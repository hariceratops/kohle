# [feat] `ecb` price plugin for exchange rates

A plugin returns the ECB daily reference rate for a currency code as a price in EUR, so INR can be valued without typing a rate.

Depends on: 108

## Acceptance Criteria

- Registered under `kohle.plugins`; the symbol is the ISO code, e.g. `INR`; no API key is needed.
- For each requested code it returns the latest published rate as a price of that currency in EUR (the reciprocal of the quoted INR-per-EUR), within the precision the design settles.
- A code the ECB does not publish is `Unavailable(no_symbol)`.
- The HTTP call sits behind a seam; tests use recorded responses and make no network calls.
- The design's findings on the endpoint, final-rate marking and terms of use are recorded in `dev/design/multi-currency-and-fx.md`.
- `prices.md` lists the plugin.
