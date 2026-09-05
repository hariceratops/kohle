# [feat] Record a cross-unit purchase or sale via `record`

Buying and selling a non-base unit must both be expressible in the shorthand.
A sale forced onto `record-split` is a sale likely to be recorded without its
price, which raises no error and silently corrupts FIFO profit reporting
later.

Depends on: 001
Spec: `dev/specs/cli-record-and-balances.md`

## Acceptance Criteria

- `--unit` and `--price` allow `record` to post an entry in which one side is
  denominated in a non-base unit.
- A purchase (units arrive) and a sale (units leave) are both expressible
  through `record`; neither requires falling back to `record-split`.
- The entry balances by value: the base-currency side's quantity is
  quantity x price.
- The flag shape is whatever the design settles on. The constraint this issue
  is accepted against is that both directions are equally reachable — a
  design in which one side always carries the non-base unit does not satisfy
  it.
- Passing `--price` alongside a base-currency `--unit` is rejected with a
  clear error rather than silently ignored. (Flagged in the spec's Open
  Questions as revisable during design.)
- The spec's ETF example posts the stated two-line entry: 1000 EUR credited
  from `Checking`, 10 units debited to `Broker` at price 100.
- The equivalent sale is expressible and produces a correctly-signed entry.
