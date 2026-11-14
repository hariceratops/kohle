# [feat] A currency inflow carries a rate the user supplies

INR that arrives other than by remittance (sale proceeds, dividends, interest) records a euro rate, so a stock sale realises its gain in euros on the sale date.

Depends on: 113

## Acceptance Criteria

- `record` takes a rate option for an inflow of a currency unit; the new INR lot costs amount × rate.
- Selling an INR-quoted stock realises proceeds = INR received × the recorded rate, less the stock lots' euro cost.
- Recording such an inflow without a rate is a usage error.
- kohle never fills the rate in from fetched prices.
- `recording-entries.md` is updated.
