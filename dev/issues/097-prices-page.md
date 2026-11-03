# [feat] Prices page

Carve the price material into a concept page that includes the bundled price plugins and explains why reports never call a price plugin.

Depends on: 091

## Acceptance Criteria

- `docs/prices.md` covers setting a price source, fetching and appending prices, and the bundled price plugins.
- It explains why reports never call a price plugin.
- Examples use the bundled `file` price plugin and a fixture price file; they are checked examples and never touch the network.
- The page is in the nav and the strict build passes.
