# [feat] Generated plugin list and plugin interface docs

List the plugins that are installed, and document the plugin contracts, in a way that cannot drift from the code, then add the Writing plugins page.

Depends on: 090

## Acceptance Criteria

- The guide lists every plugin in the `kohle.plugins` entry-point group with name, kind (importer or price) and what it accepts, generated from the installed entry points.
- "What each accepts" comes from the plugin itself (docstring or declared attribute), not a docs table.
- A newly installed plugin appears without a docs edit; a test proves this with a stub plugin.
- The importer and price-plugin contracts and `CashRow` / `SecurityRow` are documented from docstrings if that scales; otherwise on the page, and the design records why.
- `docs/writing-plugins.md` covers writing an importer and a price plugin.
- The pages are in the nav and the strict build passes.
