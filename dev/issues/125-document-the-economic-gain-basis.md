# [chore] Document that the gain is the economic gain, not the tax basis

State plainly what kohle's euro gain is, with a worked INR example, so it is not read as a tax figure.

Depends on: 124

## Acceptance Criteria

- `reports.md` says cost is the euros actually sent and proceeds use the rate recorded on the entry.
- It says this is not the basis German tax law converts on, and that no German broker certificate exists to check against for these holdings.
- A worked example from remittance to sale uses fictional accounts and amounts.
- `mkdocs build --strict` passes.
