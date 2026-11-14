# [feat] A binding and a close name their quote currency

A price binding records the currency its closes are quoted in (EUR by default), so a rupee close can no longer pass as a euro close.

## Acceptance Criteria

- A new migration off the current head adds a quote-currency column to `price_bindings`, defaulting to EUR; existing bindings read as EUR.
- `set-price-source UNIT PLUGIN SYMBOL` takes a quote currency; it must be EUR or an existing currency unit.
- `validate_close` compares a close's currency to its binding's quote currency instead of `BASE_CURRENCY`; a mismatch is rejected with the reason named and nothing written for that unit.
- An INR close for a unit bound with EUR, and a EUR close for a unit bound with INR, are each rejected and leave `prices` unchanged.
- `file`'s CSV accepts an optional `currency` column, defaulting to EUR; `alphavantage` reports the binding's quote currency.
- Rebinding to a different quote currency while closes are stored follows the rule the design settles (per-row currency, or refusal).
- `prices.md` describes the quote currency, with fictional units.
- Every existing test passes unchanged.
- The first commit of the slice captures the pre-feature output of every command on a EUR-and-securities ledger, as the baseline for 124.
