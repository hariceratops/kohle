# Roadmap

The order in which `dev/inbox/` briefs go through `new_feature`. Each brief
becomes a spec through `product-owner`; this file only orders them.

## Target: a working system by 2026-12-31

Working means: running on the Pi as master, priced correctly including the
Indian holdings, readable on every device, and budgeting ready for the new
year.

1. `app-initialization` — per-user database, settings table, `init`. Sampling
   and budgeting need its settings mechanism.
2. `device-config` — a user-editable per-device config file (like git
   config), separate from ledger settings. Split out of
   `device-topology-and-sync`; sampling, budgeting and topology need it.
3. `device-topology-and-sync` — reader/writer guardrails, `snapshot` and
   `backup`; built on `device-config`. The Pi and the transport are the
   user's side.
4. `configurable-net-worth-sampling` — designs the recurrence vocabulary that
   budgeting reuses.
5. `cli-command-naming` — a short Q&A; done before budgeting so its commands
   get the new names from the start.
6. `budgeting` — needed going into the new year.
7. `multi-currency-and-fx` with `eu-price-provider` — INR lots and the NSE
   bhavcopy plugin; net worth is wrong for the Indian holdings until these
   land.
8. `complex-classification-rules` — editor-driven rules with column
   conditions.
9. `cli-documentation` — first to slip into January if time runs short; the
   README works until then.

## Early 2027

- `tui-wiring` — optional for December; the TUI over SSH on the Pi is the
  intended interactive use.
- `undo-delete-edit`
- `debts-and-liabilities` — planned last; needed only once debt appears.

## Basis for the estimate

As of 2026-10-18: seven features took spec to done between 2026-09-05 and
2026-10-17 (about 1.2 a week), faster in October. Eight briefs in about ten
weeks leaves little slack. The Pi setup and multi-currency have no precedent
in the codebase and are the likeliest to overrun.
