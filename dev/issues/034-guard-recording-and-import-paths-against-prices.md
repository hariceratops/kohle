# [test] Guard the recording and import paths against prices

The separation between recorded books and fetched prices is structural, so it
needs a test that fails if someone wires them together later, and a test that
the plugin boundary really is plugin-agnostic.

Depends on: 030
Spec: `dev/specs/price-fetcher-plugin.md`

## Acceptance Criteria

- A test fails if recording or import code (the journal use cases and
  `import-statement`) references the price table, the binding table or any
  price plugin.
- Running every existing command with no price plugins installed produces the
  same output as before.
- A third price plugin defined only in the test suite can be bound with
  `set-price-source` and fetched with `fetch-prices` without any change under
  `kohle/plugin/`, `kohle/use_cases/`, `kohle/services/` or the CLI.
