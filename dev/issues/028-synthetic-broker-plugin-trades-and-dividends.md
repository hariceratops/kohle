# [feat] First broker plugin emitting trades and dividends

A broker plugin that maps a statement to both row types: trades become
security rows, dividends become cash rows through the existing
classification path. No real broker format is chosen yet, so this defines a
synthetic CSV to exercise the contract; it can be replaced by a real one
later without touching the contract.

Depends on: 027
Spec: `dev/specs/importer-plugins-for-assets.md`

## Acceptance Criteria

- Discovered through the `kohle.plugins` entry-point group.
- Synthetic CSV columns: `date`, `reference`, `type` (`buy` | `sell` |
  `dividend`), `isin`, `quantity`, `price`, `amount`. Buy/sell rows use
  isin, quantity, price; dividend rows use `amount` (EUR) and carry their
  own `reference` and date.
- A fixture with a buy, a sell and a dividend imports all three; the dividend
  lands as a cash credit on the CLI-named cash account against
  `unclassified-income` when no rule matches.
- Re-importing the fixture writes nothing.
- An unknown `type` value is a named parse error and writes nothing.
