# [feat] Changing a currency back into euros realises FX gain

An entry taking INR out of an own account and putting euros into a euro account is recorded as two amounts and realises the FX gain.

Depends on: 111, 113

## Acceptance Criteria

- The entry consumes INR lots FIFO; gain = X EUR received minus the euro cost of the lots consumed.
- `realised` shows it as a row with unit `INR`, under the same total.
- A shortfall of INR lots fails as the spec requires.
- `reports.md` and `recording-entries.md` are updated.
