# [feat] Bind and fetch currency units

A currency unit can be bound to a price source, so its rate is fetched like a security's close.

Depends on: 107

## Acceptance Criteria

- `set-price-source` accepts a unit of kind `currency` (no `NotASecurityUnit`); such a unit must be quoted in EUR, otherwise the command fails naming the reason.
- `fetch-prices` covers held currency units as well as held securities.
- A currency unit's stored rate is an ordinary row in `prices`, in EUR.
- `prices.md` is updated.
- `fetch-prices` also fetches the rate of any currency a held security is quoted in, even when no unit of that currency is held.
