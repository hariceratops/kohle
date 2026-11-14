# [feat] `positions` shows the quote currency and INR cash

`positions` labels the price with its quote currency and lists INR cash as a row whose unrealised gain is the unrealised FX gain.

Depends on: 120

## Acceptance Criteria

- `price` is shown in the quote currency, labelled with it; `market value`, `FIFO cost` and `unrealised gain` are in euros.
- INR cash appears as a row; its unrealised gain is the unrealised FX gain.
- `reports.md` is updated.
