# Design: Structured documentation

Spec: `dev/specs/cli-documentation.md` (frozen). Issues: `dev/issues/090`–`106`.

**Upstream state this design assumes.**

- The spec is in `dev/specs/`, so it is treated as frozen. The move out of
  `dev/inbox/` is not committed yet: git shows the inbox copy deleted and the
  spec and issues untracked.
- The spec's two open questions are settled here (§9 developer site, §8.3
  interface docs). The first still says "settle this before freezing". The
  spec was frozen with it open, so the design settles it as the caller asked.
- §16 lists gaps, conflicts and readings. Each one names the decision taken so
  that slices are not blocked, and marks the ones the author should confirm.

---

## 1. Decisions at a glance

| Question | Decision | § |
|---|---|---|
| How a block marks itself checked | Every fenced block tagged `console` is a checked example. `$ ` lines are commands, and the lines under each one are its expected output. An optional `<!-- docs: ... -->` comment on the line directly above a fence carries options (the s2s convention). | 4.1 |
| How the checker finds blocks | markdown-it-py (already a dependency) tokenises each page. Examples come from one `pytest.mark.parametrize`, with ids `page:line`. There is no custom collector. | 4.2, 4.6 |
| Runner | Click's `CliRunner`, in process, with `obj=None`, so the real `_KohleCommand.invoke` opens the scratch ledger. Not a subprocess. | 4.4, 4.7 |
| Scratch ledger | One fresh fake `$HOME` per block. `KOHLE_DB` points at `~/.local/share/kohle/kohle.db` inside it, which is a copy of a template made once per session by the real `kohle-cli init`. A `first-run` block starts with no ledger and no `KOHLE_DB`. | 4.3 |
| Fixtures | Shipped samples in `docs/examples/` are copied into every scratch home. A page can also define a file inline (`<!-- docs: file rules.toml -->`), and an example opts in to it with `uses`. | 4.3, 6 |
| Pinned dates | One date for the whole guide, `DOCS_TODAY = 2026-06-17`. It is applied by patching `kohle.app.cli.cli.date`, the same seam four test modules already use. It is factored into a `pin_today` fixture in `conftest.py`. | 5 |
| Exact match | Line by line. Trailing whitespace on each line and trailing blank lines are ignored. The scratch home path is shown as `~`. Nothing else is normalised. | 4.5 |
| mkdocs-click | `::: mkdocs-click` with `:module: kohle.app.cli.cli`, `:command: cli`, `:prog_name: kohle-cli`, `:style: table`, `:list_subcommands: true`, on `docs/reference.md`. | 7 |
| Plugin list | An MkDocs hook, `docs/hooks/plugin_list.py`, replaces a placeholder with a table built from `load_plugins()` and `load_price_plugins()`. "Accepts" is the first paragraph of the plugin class's **own** docstring. | 8.1, 8.2 |
| Plugin interface docs | mkdocstrings[python] directives on `docs/writing-plugins.md`, after a docstring pass over `kohle/plugin/*.py`. The narrative stays hand-written. | 8.3 |
| Developer site | `dev/docs/`, titled "kohle developer notes", local only. It is never built in CI and never published. | 9 |
| Sample data | `docs/examples/statement.csv` (Deutsche Bank format, fictional), `broker.csv` (simple-broker format), `prices.csv` (`file` plugin) and `rules.toml` (for the README taste). | 6 |
| GIF | A VHS tape, `docs/demo/taste.tape`, writes `docs/demo/taste.gif`. It is run by hand with `uv run vhs docs/demo/taste.tape`. vhs, ttyd and ffmpeg are system tools and never Python dependencies. | 12 |
| Docs environment | `uv run --with-requirements docs/requirements.txt mkdocs …`, both locally and in CI. The docs toolchain is layered onto the project environment, because mkdocs-click and the plugin hook import kohle. | 3.3, 13 |

---

## 2. Files

```
.gitignore                         + site/  + site-dev/                      090, 102
.github/workflows/docs.yml         first workflow                             105
AGENTS.md                          pointer to docs/ + three rules             106
README.md                          cut to the pitch (103), GIF (104)
archive/double_entry.md, to_llm.md git mv from docs/                          090
docs/
  mkdocs.yml, requirements.txt     090; 092 adds mkdocs-click; 101 adds mkdocstrings + hook
  index.md                         organisation, reading locally, about the examples   090
  getting-started.md               093
  accounts-and-units.md            094
  recording-entries.md             094
  import-and-classification.md     first checked block 091, page 095
  people-and-splitting.md          096
  prices.md                        097
  reports.md                       098
  budgeting.md                     099
  several-devices.md               100
  writing-plugins.md               101
  reference.md                     092 (generated)
  plugins.md                       101 (generated list)
  examples/statement.csv           091
  examples/prices.csv              097
  examples/broker.csv              098
  examples/rules.toml              103
  hooks/plugin_list.py             101
  demo/taste.tape, demo/taste.gif  104
dev/docs/
  mkdocs.yml, index.md, migrations.md, tests.md, guide.md                     102
tests/
  conftest.py                      + pin_today fixture                        091
  docs_examples.py                 parser + runner; module docstring is the syntax reference   091
  test_docs_examples.py            parametrised examples, well-formedness, meta-tests          091
  test_docs_plugin_list.py         stub plugin appears in the list            101
kohle/app/cli/cli.py               one-line docstring per command (§7, gap G5)  092
kohle/plugin/importer_plugin.py,
kohle/plugin/price_plugin.py       docstring pass (§8.3)                      101
kohle/app/plugins/*.py             class docstrings = "what it accepts"       101
```

Slice 090 creates every page in the tree above as a stub (a title and one
sentence), all in the nav. That way every later slice fills a page that
already exists, and index.md can link to all of them under `strict`.

---

## 3. The guide site (090)

### 3.1 `docs/mkdocs.yml`

This file copies s2s's file almost line for line: `docs_dir: .`,
`site_dir: ../site`, `exclude_docs`, the material theme block and its
palette, `strict: true`. These are the differences:

```yaml
site_name: kohle
repo_url: https://github.com/hariceratops/kohle
edit_uri: edit/main/docs/
docs_dir: .
site_dir: ../site            # inside docs_dir is an error
exclude_docs: |
  mkdocs.yml
  requirements.txt
  hooks/
  demo/*.tape
validation:
  nav:
    omitted_files: warn      # a page on disk but in no nav entry fails strict
  links:
    anchors: warn            # a broken #anchor fails strict
markdown_extensions:
  - toc: {permalink: true}
  - pymdownx.highlight
  - pymdownx.superfences
  - tables
  - mkdocs-click             # 092
strict: true
```

- `validation.nav.omitted_files: warn` does the job of s2s's
  `scripts/check_nav.py` in one config line, because MkDocs 1.6 has the check
  built in and only logs it at `info` by default. `strict` turns the warning
  into a failure. The same holds for `links.anchors`. A nav entry pointing at
  a moved page (`nav.not_found`) and a broken page link (`links.not_found`)
  already warn by default.
- `docs/examples/` is not excluded, so the sample files are copied into the
  site and pages can link to them for download.
- There are no `admonition` or `pymdownx.tabbed` blocks. They do not read as
  plain markdown on GitHub, and markdown-it does not see a fence indented
  under `!!! note`, so the checker would miss it (§4.2).

Nav:

```yaml
nav:
  - Overview: index.md
  - Getting started: getting-started.md
  - Concepts:
      - Accounts and units: accounts-and-units.md
      - Recording entries: recording-entries.md
      - Import and classification: import-and-classification.md
      - People and splitting: people-and-splitting.md
      - Prices: prices.md
      - Reports: reports.md
      - Budgeting: budgeting.md
      - Several devices: several-devices.md
  - Writing plugins: writing-plugins.md
  - Reference:
      - Commands: reference.md
      - Installed plugins: plugins.md
```

### 3.2 `docs/requirements.txt`

It pins `mkdocs==1.6.1` and `mkdocs-material==9.5.39`, the versions s2s uses
(one toolchain across projects), plus `mkdocs-click`. Slice 101 adds
`mkdocstrings[python]`. Only top-level packages are pinned, as in s2s.

### 3.3 Reading and building locally

```sh
uv run --with-requirements docs/requirements.txt mkdocs serve -f docs/mkdocs.yml
```

`--with-requirements` layers the docs toolchain over the project environment
for that run only. The toolchain never enters `pyproject.toml`, and kohle
(with its `kohle.plugins` entry points) is importable, which mkdocs-click and
the plugin hook need. s2s can use a bare `pip install -r` because its docs
import nothing; kohle's do (gap G18). The spec's
`mkdocs serve -f docs/mkdocs.yml` is the command; `uv run` is the environment
it runs in.

### 3.4 `docs/index.md`

- "How this guide is organised", s2s style: what each section holds.
- "Reading it": on GitHub, or locally with the command in §3.3.
- "About the examples", for readers: every console session on these pages is
  run by the test suite against a fresh ledger that `kohle-cli init` created
  with `state = "BW"`, on 17 June 2026. Sample files are in `examples/`. That
  is why reports here show the same figures from day to day.

---

## 4. Checked examples (091)

### 4.1 Syntax

A checked example is any fence whose info string is `console`:

````markdown
```console
$ kohle-cli add-account Checking --type asset
Added account Checking (asset) with id 2
$ kohle-cli list-accounts
account    type    iban
---------  ------  ------
Checking   asset   -
People     asset   -
```
````

- A line beginning with `$ ` is a command. A command ending in ` \` continues
  on the next line.
- The lines after a command, up to the next `$ ` line or the end of the block,
  are its expected output.
- The language tag is the marker. Nothing else is needed, so there is no
  "forgot the marker" failure: a session shown with output is checked.
  Install lines and config snippets go in `sh` / `toml` fences and are never
  run.
- The `console` lexer (Pygments' ShellSessionLexer) highlights prompts and
  output on both GitHub and MkDocs.

**Options.** An HTML comment on the line directly above a fence carries
options. This is the s2s binding convention, and the comment is invisible on
GitHub and in the site. The vocabulary is closed, and an unknown word is
reported as a problem (§4.6):

| Comment | Above | Meaning |
|---|---|---|
| `<!-- docs: file PATH -->` | any non-console fence | The fence's content is a page file named `PATH`, relative to the scratch home (`~/` allowed, e.g. `~/.config/kohle/config.toml`). The path must be relative and contain no `..`. |
| `<!-- docs: uses PATH [PATH ...] -->` | console | Before this example runs, write each named page file. Each name resolves to the latest `file` fence with that path **earlier on the same page**. A name with no such fence is a problem. |
| `<!-- docs: first-run -->` | console | Start from a machine kohle has never run on (§4.3). Combines with `uses`: `<!-- docs: first-run uses ~/.config/kohle/init.toml -->`. |
| `<!-- docs: illustration -->` | non-console | This fence contains `kohle-cli` lines on purpose and is not run (the cron snapshot recipe, `edit-rules`, an Alpha Vantage fetch). |

Unsupported, and each one reported as a problem with a message saying what to
do instead:

- A `$ ` line whose command is not `kohle-cli`, after optional leading
  `NAME=value` assignments.
- Shell operators (`|`, `&&`, `;`, `>`, `<`).
- A command that would prompt. Pages pass `--yes`, and the prompt is
  described in prose. Without input, `click.confirm` prints `Aborted!`, which
  fails the match anyway.

### 4.2 Discovery and the invocation lint

- Pages: `docs/**/*.md`. Slice 103 adds `README.md` when the README is cut
  (gap G11). `dev/docs/` is never scanned.
- `MarkdownIt("commonmark").parse(text)` gives `fence` tokens with `info`,
  `content` and `map` (0-based start line). Fences inside list items are
  found, with their content dedented. The options comment is read from the
  raw line `map[0] - 1`, as s2s does.
- **Lint.** These are problems:
  - a raw line matching `^\s*\$ (NAME=\S+ )*kohle-cli\b` outside any console
    fence;
  - a line in a non-console fence whose first word, after `$ ` and
    assignments, is `kohle-cli`, unless the fence is marked `illustration`.

  This enforces the spec's "every invocation shown … runs in pytest". It also
  catches the one construct the parser cannot see: a fence indented under an
  admonition, which markdown-it treats as paragraph text. Prose never starts a
  line with `$ kohle-cli`, so the raw-line rule has no false positives in
  practice.

### 4.3 Starting state of a block

The test sets up each example in `tmp_path`, with every change made through
`monkeypatch` and so undone afterwards:

1. `home = tmp_path / "home"`. `HOME=home`,
   `XDG_CONFIG_HOME=home/.config`, `XDG_DATA_HOME=home/.local/share` and
   `COLUMNS=80` (§4.4) are set. These override the autouse
   `_no_real_user_paths` values, which stay as the safety net.
2. **Default state.** Write `home/.config/kohle/init.toml` with the
   `INIT_TOML` constant (`state = "BW"\n`). Copy the session's template
   ledger to `home/.local/share/kohle/kohle.db` and set `KOHLE_DB` to that
   path. This is the AC's "KOHLE_DB at a temp path". The path is also where
   the default would resolve, so `init` and `snapshot` output reads
   naturally as `~/.local/share/kohle/kohle.db`.
3. **`first-run` state.** No init file, no ledger, and `KOHLE_DB` deleted.
   The ledger resolves through `XDG_DATA_HOME` to the same scratch location,
   so `list-config` shows `(default)` and not `(KOHLE_DB)` (gap G1). The
   block brings its own `init.toml` with `uses` and runs `kohle-cli init`
   itself.
4. Copy every file in `docs/examples/` into `home`, then write the `uses` page
   files. A page file may overwrite a sample of the same name.
5. `chdir(home)`. Pin today to `DOCS_TODAY` (§5). Make
   `socket.socket.connect` raise `RuntimeError("network access in a docs
   example")`. That turns the AC "no example touches the network" into a
   check instead of a convention.

**Template ledger.** A session-scoped fixture runs `kohle-cli init` once,
through `CliRunner` with an `env=` mapping, because a session fixture cannot
use function-scoped `monkeypatch`. It writes to a `tmp_path_factory`
directory with the same `INIT_TOML`, asserts exit 0, and yields the file.
Each example copies it with `shutil.copyfile`. The copy is byte-identical to
a fresh `init` and costs about 2 ms instead of about 250 ms (measured), which
matters at roughly 60 blocks. The template is never opened for writing.

### 4.4 Running a command

- `shlex.split(text)`. Leading `NAME=value` tokens become the per-command
  `env=` of `CliRunner.invoke`. This is how a page shows
  `$ KOHLE_PRICE_FILE=prices.csv kohle-cli fetch-prices` truthfully. The next
  token must be `kohle-cli`. A token starting with `~` is expanded with
  `os.path.expanduser`, so the fake `HOME` applies, as a shell would.
- `CliRunner().invoke(cli, args, env=env, prog_name="kohle-cli")`, with **no
  `obj`**:
  - Without `prog_name`, usage errors and `--help` say `Usage: cli …`. The
    real script says `kohle-cli`.
  - With `obj=None`, the real `_KohleCommand.invoke` reads the device config,
    applies the reader refusal, opens the ledger at `KOHLE_DB` and runs the
    schema check. That is exactly the path a user's command takes.
- `COLUMNS=80` pins Click's help wrapping. Click sizes help text from
  `shutil.get_terminal_size()`, which reads the developer's real terminal even
  under capture, so `--help` and usage output would otherwise depend on the
  window width.
- Output is `result.output`. In Click 8.3 that is stdout and stderr
  interleaved as a terminal shows them, so a shown `Error: …` line is
  compared like any other line. The exit code is not compared: a page shows
  output, not exit codes, and the text already tells success from failure.

### 4.5 Comparing

- Actual: replace every occurrence of `str(home)` with `~`, split into lines,
  `rstrip` each line, and drop trailing blank lines. Expected: the same, minus
  the replacement.
- Equal lists pass. That is the only normalisation, and §16 G2 records why
  it is still "exact". There are no wildcards and no placeholder for the
  Alembic revision (G12).
- The first mismatch stops the example, because later commands depend on
  earlier ones.
- If `result.exception` is set and is not `SystemExit`, the failure includes
  the formatted traceback from `result.exc_info`. Without it, a crash would
  show only as a short output.

Failure text, delivered with `pytest.fail(msg, pytrace=False)`:

```
docs/reports.md:57: `kohle-cli net-worth` printed something else (example at line 52)
--- expected (page)
+++ actual
@@ ... unified diff ...
```

### 4.6 Tests

`tests/docs_examples.py` is a helper module. `tests/rule_helpers.py` is the
precedent, and `tests/__init__.py` makes it importable as
`tests.docs_examples`. Its module docstring is the authoritative description
of the syntax in §4.1–4.5, as s2s's `check_doc_examples.py` docstring is. It
holds:

```python
DOCS_TODAY = date(2026, 6, 17)   # also stated in docs/index.md
INIT_TOML = 'state = "BW"\n'

@dataclass(frozen=True, slots=True)
class Command:
    line: int            # 1-based page line of the `$ ` line
    text: str            # continuations joined
    expected: list[str]

@dataclass(frozen=True, slots=True)
class Example:
    page: str            # repo-relative, e.g. "docs/reports.md"
    line: int            # 1-based line of the opening fence
    first_run: bool
    files: dict[str, str]  # home-relative path -> content, resolved from `uses`
    commands: list[Command]

def parse_page(page: str, text: str) -> tuple[list[Example], list[str]]  # examples, problems
def collect(root: Path) -> tuple[list[Example], list[str]]
def run_example(example: Example, home: Path) -> str | None             # failure text or None
```

Problems are returned rather than raised. Python style here is Result-like,
and one malformed page should not stop every other page's examples from being
collected.

`tests/test_docs_examples.py`:

- `test_docs_example[docs/reports.md:52]`: one case per example. The id names
  the page and block, so `pytest -k reports` selects one page.
- `test_docs_pages_are_well_formed`: asserts that `collect`'s problem list is
  empty, and lists every problem at once.
- `test_a_wrong_block_fails_naming_its_page_and_block`: writes a two-command
  page into `tmp_path` with one wrong expected line, runs it through the same
  setup and `run_example`, and asserts that the failure text contains
  `sample.md:<line>` and the diff. This is the AC's deliberately wrong block.
- `test_unmarked_blocks_are_not_run`: a synthetic page with an `sh` fence
  (`uv sync`) and a `toml` fence yields no examples and no problems.

### 4.7 Relation to the existing CLI test helpers

| Helper | Used? | Why |
|---|---|---|
| `CliRunner` | yes | It is the established CLI test layer (`tests/test_cli.py` and others), and the only way to pin today without touching app code (§5). |
| `session_factory` / `obj=` injection | **no** | It builds the schema with `base.metadata.create_all`, seeds through a conftest listener, has no People root unless asked, and skips the schema check. A page must show what a user's ledger does (`People` in `list-accounts`, the `no ledger at …` line), so examples run on a real `init`-made file. |
| `_no_real_user_paths` (autouse) | yes, implicitly | It stays the outer guard. Each example overrides it with its own home. |
| `run_init`, `write_init_toml` | no | They write to `tmp_path/xdg-config`. Examples need `~/.config/...` so that printed paths read like a real machine. |
| `_pin_today` (four copies) | factored | It becomes a `pin_today` fixture in `conftest.py`, a factory fixture like `write_config`. The docs test uses it. The existing copies in `test_portfolio_cli`, `test_budgeting_cli`, `test_budgeting_scenario` and `test_market_value_cli` are left alone. Moving them is a `change` follow-up, not this feature's scope. |

---

## 5. Pinned dates

### 5.1 What depends on the current date

The audit covers every `today()`, `now()` and `utcnow()` in `kohle/`. All
user-visible dependence flows from one place: the CLI's `date.today()` calls,
which are passed down to the use cases as a parameter.

| Command | Use of today | Visible effect |
|---|---|---|
| `balance` | valuation date | `fresh` / `stale (…)` status and market value of non-base units |
| `net-worth` | valuation date | the same, plus the estimates line |
| `positions` | valuation date | the same |
| `fetch-prices` | `validate_close` | a close dated after today is rejected |
| `net-worth-history` | default `--to`, `--to` ≤ today check | the last row and the refusal |
| `budget` | default `--to`, `--from` = 1 Jan of `--to`'s year, `--to` ≤ today, `partial day N of M` | rows and notes |

These are not date-dependent in output: `record`, `record-split`,
`entries-in-period`, `realised` (`--year` filters dates already stored),
`list-*`, `who-owes-what` and `settle-up`. `Operation.created_at`,
`rules.deleted_at` and the People row's `created_at` are written but never
printed. The Alpha Vantage plugin's `datetime.now(UTC)` never runs in an
example, because network is blocked (§4.3).

### 5.2 Mechanism

The `pin_today(DOCS_TODAY)` fixture monkeypatches `kohle.app.cli.cli.date`
with a `date` subclass whose `today()` returns the pin. This is the existing
pattern, unchanged. It pins all six commands because none reads the clock
below the CLI.

A subprocess run would need a production override of today, such as a
`KOHLE_TODAY` variable. That is a test-only hook in production code. It
would also be a second environment override, where
`kohle/infrastructure/device_config.py` records `KOHLE_DB` as the only one
and says no spec adds others. This is the deciding reason for `CliRunner`
(§15.8).

### 5.3 One date for the guide

`DOCS_TODAY = 2026-06-17`, a Wednesday and not a BW holiday. It is mid-year,
so `budget` and `net-worth-history` have half a year of examples behind it.
There is no per-block override. No v1 page needs one, and one stated date is
easier for a reader than a hidden date per block. If a later page needs one,
`today=` is a small addition to §4.1.

Page guidance, written into the syntax docstring: pass explicit `--from` and
`--to` where a command takes them, so a reader who reproduces the session
later gets the same rows. Only valuation status and `partial day` notes then
depend on the pin.

---

## 6. Sample data

All of it is fictional. The people, shops and amounts are invented, and the
IBANs are the published documentation examples (`DE89 3704 0044 0532 0130
00` and the like). None of it comes from `tests/fixtures/`, which is free to
change for test reasons.

| File | Format | Used by | Notes |
|---|---|---|---|
| `docs/examples/statement.csv` | `kohle-deutsche-bank` | 091 (first block), 095, 096, 103 | Modelled on `tests/fixtures/deutsche_bank_statement.csv`: account line, period, old balance, the 18-column header, closing balance. Two or three months before `DOCS_TODAY`, with a salary, rent, groceries from two invented shops and a shared dinner to split. It includes one `Debit Card Payment` row, because that format takes its date from the description. |
| `docs/examples/broker.csv` | `kohle-simple-broker` | 098 | Buys, a partial sell and a dividend. Instrument identifiers are fictional and readable in a table (e.g. `ACME`, `GLOBEX`). **Not** the README's real ISINs (gap G13). |
| `docs/examples/prices.csv` | `file` plugin (`identifier,date,close`) | 097, 098 | Closes for the same identifiers, dated on or before `DOCS_TODAY`. One identifier's latest close is older than 7 days, so `stale` can be shown. |
| `docs/examples/rules.toml` | rule file | 103 | The taste's rules. It is shipped rather than defined inline so the GIF tape can use the same file (§12). |

Page-only inputs are `file` fences on the page that uses them, so the text
shown is the text applied: `init.toml` on Getting started, the rule files on
Import and classification, and `config.toml` on Several devices.

---

## 7. Generated command reference (092)

`docs/reference.md`:

```markdown
# Command reference

Generated from the Click definitions when the site is built. On GitHub this
page shows only the directive below; run `kohle-cli <command> --help`, or read
the published guide.

::: mkdocs-click
    :module: kohle.app.cli.cli
    :command: cli
    :prog_name: kohle-cli
    :depth: 1
    :style: table
    :list_subcommands: true
```

- `:prog_name:` makes headings and usage read `kohle-cli …` and not `cli …`.
- `:style: table` renders option name, type (with `Choice` values), help and
  default per row. Defaults and choices are what AC 092 asks for. If the
  installed mkdocs-click shows defaults only for `show_default` options, the
  fallback is `context_settings={"show_default": True}` on the `cli` group.
  That is a one-line change, and it also improves `--help`. The implementer
  verifies this on the first build.
- Rendering builds Click contexts and never calls `invoke`, so building the
  docs never reads `config.toml` or opens a ledger.
- `kohle-tui` is a separate module and is simply not referenced.
- **Command help text.** No command function in `cli.py` has a docstring, so
  the reference would list usage and options with no description. 092 adds a
  one-line docstring to each command and to the group. They become both
  `--help` text and the reference description (gap G5).

---

## 8. Plugins (101)

### 8.1 The installed-plugins list

`docs/plugins.md` holds a sentence of explanation and the placeholder line
`<!-- generated: plugin-list -->`. It uses a different prefix from the
checker's `docs:` comments, so the two vocabularies never mix.

`docs/hooks/plugin_list.py` is registered as `hooks: [hooks/plugin_list.py]`
and excluded from the site:

```python
PLACEHOLDER = "<!-- generated: plugin-list -->"

def plugin_table() -> str: ...          # markdown table, see below

def on_page_markdown(markdown, *, page, config, files):
    return markdown.replace(PLACEHOLDER, plugin_table())
```

- It uses `load_plugins()` and `load_price_plugins()` from
  `kohle.plugin.plugin_manager`. It does not read entry points itself, so the
  list is exactly what `kohle-cli` sees. The same `TypeError` / duplicate-name
  `ValueError` that would stop a command stops the build.
- Columns: `Plugin` (the instance's `name`, which is what a user types),
  `Kind` (`importer` / `price`), `Accepts`. Rows are sorted by kind, then
  name. A `|` inside a cell is escaped.
- On GitHub the placeholder is invisible. The page says the table is
  generated at build time and points to `kohle-cli list-importer-plugins` for
  a local check (gap G4).

### 8.2 Where "what each accepts" comes from

From the **plugin class's own docstring**, first paragraph, whitespace
collapsed. It is read as `type(plugin).__doc__`, which Python never inherits
for classes. It is never read with `inspect.getdoc`, which falls back to the
base class and would print the ABC's contract text as if the plugin had said
it. A plugin with no docstring shows `not stated by the plugin`.

None of the four bundled classes has a docstring today, so 101 adds one each.
For example:

- `DeustcheBankStatementImporter`: a Deutsche Bank account CSV export,
  semicolon-separated. Cash rows only. (Found while building 101: the code
  does not read the file as ISO-8859-1, so no encoding is stated.)
- `SimpleBrokerStatementImporter`: a UTF-8 CSV with header
  `date,reference,type,isin,quantity,price,amount`. Buys and sells become
  trades, dividends cash.
- `FilePriceFetcher`: symbols looked up in the `identifier,date,close` CSV
  named by `KOHLE_PRICE_FILE`. Offline.
- `AlphaVantagePriceFetcher`: Alpha Vantage `TIME_SERIES_DAILY` symbols of
  the EUR listing, with the exchange suffix. Key in `KOHLE_ALPHAVANTAGE_KEY`.

`tests/test_docs_plugin_list.py`:

- **A stub plugin appears without a docs edit.** It loads the hook module by
  path (`importlib.util.spec_from_file_location`) and patches
  `kohle.plugin.plugin_manager.entry_points` to return the real entry points
  plus a stub entry point whose class has a docstring. This is the seam
  `test_price_guards._patched_entry_points` already patches, and that shape
  (real plus extra) is reused. It then asserts that `plugin_table()` has the
  stub's name, kind and first docstring paragraph.
- **Every bundled plugin states what it accepts.** For each plugin loaded
  from the real entry points, `type(p).__doc__` is not `None`. This keeps the
  bundled rows from silently becoming `not stated`.

### 8.3 Plugin interface docs: mkdocstrings, after a docstring pass

**Decision:** generate the contract reference with mkdocstrings[python]
(griffe, static analysis) on `docs/writing-plugins.md`, using one directive
per object. The narrative stays hand-written: registering an entry point in
`pyproject.toml`, what core does with the rows (dedup by reference per cash
account, trades need `INSTRUMENT_ACCOUNT`, unknown identifiers all named in
one error), `Result.ok` / `Result.err` usage, and a minimal example plugin of
each kind.

```markdown
::: kohle.plugin.importer_plugin.StatementImporterPlugin
::: kohle.plugin.importer_plugin.CashRow
::: kohle.plugin.importer_plugin.SecurityRow
::: kohle.plugin.importer_plugin.StatementUnreadable
::: kohle.plugin.price_plugin.PriceFetcherPlugin
::: kohle.plugin.price_plugin.Close
::: kohle.plugin.price_plugin.Unavailable
::: kohle.plugin.price_plugin.UnavailableReason
::: kohle.plugin.price_plugin.MissingEnvironmentVariable
```

mkdocs.yml gains `plugins: [search, mkdocstrings]`. `search` must be listed
explicitly once `plugins:` exists. The mkdocstrings Python handler gets
`paths: [..]`, `show_source: false`, `show_root_heading: true` and
`members_order: source`.

**How good the current docstrings are:**

- Good: `PriceFetcherPlugin` carries the best contract text in the codebase,
  including the rules list on errors, finished closes, no I/O in `__init__`,
  request order and keys. The `CashRow` and `SecurityRow` class docstrings
  state the sign conventions and the reference rule. `Close` and
  `Unavailable` are adequate.
- Thin: `StatementImporterPlugin` has two sentences. `name`,
  `import_statement` and `fetch_latest_closes` have no docstrings at all.
- Missing:
  - Per-field meaning for `CashRow` and `SecurityRow`. It lives only in the
    README tables: `entry_date` is the plugin's choice of booking or value
    date, and `counterparty_iban` is the *other* side's IBAN.
  - `UnavailableReason`'s three members.
  - `ImportError`, `PriceFetchError` and `MissingEnvironmentVariable`.
  - `Result` (`kohle/core/result.py`).
- Not renderable: the "no defaults" rationale above `CashRow` and `Close` is
  a `#` comment. That is correct, because it says *why*, and it stays a
  comment.

**Does it scale?** Yes, for this surface. The public contract is two leaf
modules and about ten names, they change rarely, and most of the text
already exists. 101's docstring pass is a bounded job:

- field docstrings on `CashRow` and `SecurityRow` (griffe reads a string
  literal after an annotated field), moving the README tables into the code;
- method docstrings on `name` (the name typed as `PLUGIN`, or bound by
  `set-price-source`; unique per kind), `import_statement` and
  `fetch_latest_closes`;
- member docstrings on `UnavailableReason`;
- one sentence each on the error bases: their `__str__` is what the user
  sees after `Error: `.

Signatures and field types then come from the code and cannot drift. The
rejected alternative is a hand-written table, which is the README's current
state and drifts (§15.8). `Result` is not rendered. The page shows its two
constructors in the example plugin, because documenting the whole class
would pull core internals into the plugin guide.

The cost is one docs dependency and a new strict-mode failure source:
mkdocstrings or griffe warnings fail the build. That is acceptable, because
a warning there means the reference is wrong.

---

## 9. Developer docs site (102)

- **Location and name:** `dev/docs/`, `site_name: kohle developer notes`.
  `dev/` already holds the maintainer- and agent-facing material (specs,
  designs, issues), so the developer site sits with it and well away from the
  published `docs/`.
- `dev/docs/mkdocs.yml` has the same shape as §3.1: `docs_dir: .`,
  `site_dir: ../../site-dev` (git-ignored), `exclude_docs: mkdocs.yml`,
  material and `strict: true`. It reuses `docs/requirements.txt`, so there is
  one pinned toolchain.
- Pages:
  - `index.md`: what is here, and how to serve it.
  - `migrations.md`: "Writing migrations", moved from the README.
  - `tests.md`: `uv sync --extra dev`, `uv run pytest tests/`, and why
    `--extra dev` is not optional.
  - `guide.md`: how the user guide is checked. It links to the
    `tests/docs_examples.py` docstring by absolute GitHub URL, and covers
    `DOCS_TODAY` and serving.
- **Built or published: local only.** It is served with
  `uv run --with-requirements docs/requirements.txt mkdocs serve -f dev/docs/mkdocs.yml`.
  The reasons:
  1. The spec has CI run the user guide build "and nothing else".
  2. GitHub Pages serves one site per repository, so publishing the dev site
     would mean either nesting it under the user site, which the spec forbids,
     or a second repository.
  3. Its readers, the maintainer and agents, have the repository.

  The trade-off: a broken link in the dev site is caught only when someone
  builds it.
- Its `bash` blocks (alembic, pytest) are unchecked. The checker never scans
  `dev/`.

---

## 10. Concept pages (093–100)

Each page moves README material and may cut, merge or rewrite it. Option and
column lists defer to the reference or to checked output. Notes per page:

- **Getting started (093).**
  - Install lines go in `sh`.
  - The first run is a `first-run uses ~/.config/kohle/init.toml` example
    (`init`, `list-config`, `list-settings`), so sources show `(default)`.
  - The schema check is shown as a `first-run` command before `init`, which
    prints `no ledger at ~/.local/share/kohle/kohle.db; …`.
  - "Upgrading" can only show `migrate` on a current ledger. A behind or
    ahead ledger cannot be made from scratch, so those cases stay prose.
  - The legacy "move `./kohle.db` by hand" paragraph is a cut candidate as
    stale.
- **Accounts and units, Recording entries (094).**
  - Every fresh ledger lists `People`. The page says why, rather than
    hiding it.
  - Units are fictional, not `IE00B4L5Y983`.
  - `balance` on euro-only accounts is date-independent.
- **Import and classification (095).**
  - It builds on 091's first block and uses `statement.csv`.
  - Rule files are `file` fences applied with `apply-rules FILE --yes`, and
    `show-rules` output is checked.
  - `edit-rules` is prose or `illustration`.
  - No `add-rule`, `list-rules` or `remove-rule`. In a console block they
    would fail anyway; in prose, review catches them.
- **People and splitting (096).** Uses the `People` root of a fresh ledger.
  `settle-up` prints `Settle with: kohle-cli record …` as output text. That is
  not an invocation and the lint ignores it, because it does not start with
  `$`.
- **Prices (097).**
  - `$ KOHLE_PRICE_FILE=prices.csv kohle-cli fetch-prices`.
  - Fresh and stale are relative to `DOCS_TODAY`.
  - Alpha Vantage is prose (and at most an `illustration` fence), because it
    needs a key and the network.
  - The page explains why reports never call a plugin.
- **Reports (098).**
  - `broker.csv` via `kohle-simple-broker`, plus `prices.csv`.
  - Explicit `--from` / `--to` on `net-worth-history`; `set-sampling-rules`,
    `move-state` and `list-states`.
  - FIFO across own depots: a `record-split` move between two depots, then
    `positions` and `realised`.
- **Budgeting (099).** Explicit `--from` / `--to` where the narrative allows.
  `partial day` notes depend on `DOCS_TODAY`.
- **Several devices (100).**
  - `snapshot ~/copy.db` (output shows `~` paths).
  - A reader refusal in the default state, with
    `uses ~/.config/kohle/config.toml` holding `[ledger] mode = "reader"`.
    `KOHLE_DB` still points at the scratch ledger, so no `path` key is needed.
  - The cron snapshot recipe is an `illustration` fence.
  - The README's "one worked example is the author's" (Raspberry Pi,
    Syncthing, laptop, tablet) is rewritten as a generic example, under the
    personal-data rule (gap G13).

---

## 11. README (103)

- Pitch, key features (drafted, and marked as drafts in the PR), the "still a
  bit personalized" warning kept, the taste, the GIF, a link to the guide with
  §3.3's local command, and a roadmap.
- **Taste:** one `console` block that creates accounts, applies
  `rules.toml --yes`, imports `statement.csv` and runs one report.
  Constraints, so that the unpinned GIF (§12) replays the same output:
  - inputs are shipped `docs/examples/` files only;
  - the report must not depend on today: a euro-only `balance`, or `budget`
    with an explicit `--to` before `DOCS_TODAY`;
  - no command prints a path.

  The `apply-rules` plan output shows each rule inline, so the README does
  not have to reproduce the file. A comment above the block says the GIF tape
  mirrors it.
- 103 adds `README.md` to the checker's page list (§4.2).
- **Roadmap:** written by hand, one generic line per open `dev/inbox` brief.
  It leaves out what is delivered or documented, and it is not taken from
  `todo.md` or `dev/roadmap.md`, the latter because it carries personal
  targets ("the Pi", "the Indian holdings"). It is not generated from the
  briefs: deciding what is "already covered" takes judgement, and brief text
  may carry personal preferences.
- Removed statements are accounted for in the PR: moved to a page, cut as
  stale or duplicated, or sent to the dev site.

---

## 12. GIF (104)

- **Tool:** VHS (charmbracelet). A `.tape` file is a declarative script with
  `Output`, `Set`, `Type`, `Enter`, `Sleep`, `Hide` and `Show`. Anyone can
  rerun it and get the same typing and timing. It needs `vhs`, `ttyd` and
  `ffmpeg` as system binaries, so it cannot enter the Python dependencies.
- **Files:** `docs/demo/taste.tape` writes `docs/demo/taste.gif`. The tape is
  excluded from the site; the GIF may also appear on `index.md`.
- **Run, from the repo root:** `uv run vhs docs/demo/taste.tape`. `uv run`
  puts `.venv/bin` on the `PATH` that VHS's shell inherits. The implementer
  verifies this, and the fallback is `source .venv/bin/activate` in the
  hidden prelude.
- **Isolation and privacy:** a hidden prelude does the following, so the GIF
  never shows the real ledger, user name, host name or home path:
  - sets `PS1='$ '`;
  - creates `D=$(mktemp -d)` and exports `KOHLE_DB=$D/kohle.db` and
    `XDG_CONFIG_HOME=$D/config`;
  - writes `init.toml`, runs `kohle-cli init >/dev/null`;
  - copies `docs/examples/*` into `$D`, `cd`s there, and clears the screen.
- The visible part types the README taste's commands, one `Type … Enter
  Sleep` each. Today is not pinned, which is why §11 requires a
  date-independent report.
- **Drift:** the tape duplicates about 8 commands from the README. The
  comments at both ends say to change them together. The tests do not check
  the GIF (spec), and generating the tape from the README was rejected
  (§15.8).
- The README says how to regenerate it, and that vhs, ttyd and ffmpeg are
  needed.

---

## 13. Pages workflow (105)

The workflow is s2s's `docs.yml` with three changes:

```yaml
on:
  push:                 # every branch: the spec says every push, s2s says main only
  pull_request:
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv run --frozen --with-requirements docs/requirements.txt mkdocs build --strict -f docs/mkdocs.yml
      - uses: actions/upload-pages-artifact@v3
        if: github.event_name == 'push' && github.ref == 'refs/heads/main'
        with: {path: site}
  deploy:
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    needs: build
    # permissions pages: write, id-token: write; environment github-pages;
    # actions/deploy-pages@v4, as s2s
```

- `uv run --frozen` installs the app from `uv.lock`, because mkdocs-click and
  the hook import kohle, and then layers the docs toolchain. `--frozen`, not
  `--locked`: a stale lock should not turn the docs check red, since CI here
  checks docs and nothing else.
- PRs never deploy: the condition checks the event, not only the ref. A
  failed build uploads no artifact, and `needs:` keeps deploy from running.
- No tests, ruff or mypy.
- **Prerequisite:** the repository's Pages source must be set to "GitHub
  Actions". Pages on a private repository needs a paid plan (gap G7).

---

## 14. AGENTS.md (106)

The Context section points to `docs/` as the user-facing description of
behaviour. The three standing rules from the spec are added:

1. A slice that changes user-visible behaviour updates the matching page in
   the same PR.
2. The README roadmap follows the inbox briefs.
3. No personal data or preferences in user-facing docs; examples use
   fictional accounts, people and amounts.

**Recommended, beyond the ACs:** one sentence saying that `console` blocks are
checked by `tests/docs_examples.py`, whose docstring defines the syntax. Rule
1 has agents editing pages, and they need to find the syntax (gap G20).

---

## 15. Cross-cutting decisions

### 15.1 State and data lifecycle

- **Per example:** the scratch home is the unit. It is created whole before
  the first command (ledger copy, samples, page files, environment) and
  discarded with `tmp_path`. Commands within an example share one ledger, in
  order. Nothing crosses examples, which is the spec's "each block runs on its
  own". The first mismatch ends the example because the rest of it is
  undefined.
- **Template ledger:** written once per session by the real `init`, then only
  read by `copyfile`. No connection writes to it after creation, and
  SQLite's default rollback journal leaves no sidecar file, so a file copy is
  a consistent ledger.
- **Docs build:** read-only. mkdocs-click never invokes commands, and plugin
  instantiation does no I/O by the plugin contract. Nothing persistent is
  written except `site/`.
- **Deploy:** all or nothing through the Pages artifact. A failed build
  deploys nothing.
- **GIF:** regenerating overwrites one committed binary. The session runs in
  a temp directory and never touches the user's ledger.
- There is nothing here that must be reversible, replayable or audited. No
  ledger write path changes.

### 15.2 Error propagation

- **kohle to checker:** kohle's representation is unchanged. A
  `ClickException` becomes `Error: …` on stderr. The checker sees only text
  (`result.output`) and never kohle's error types, which keeps the page the
  contract. An exception that escapes kohle (a bug) is caught by `CliRunner`
  and re-surfaced as a traceback in the failure text.
- **Checker to pytest:** page syntax errors become problem strings
  (`page:line: message`), reported together by one test. A mismatch becomes
  failure text, reported by `pytest.fail(pytrace=False)`. A template `init`
  that fails is an assertion error in the session fixture, so every docs test
  errors, which is loud and correct.
- **Docs build:** an mkdocs-click import error, a hook exception (including
  `plugin_manager`'s `TypeError` / `ValueError`), and griffe or mkdocstrings
  warnings all fail `--strict`. Nothing catches them. A plugin that would
  break `kohle-cli` should break the docs build too.

### 15.3 Concurrency and ownership

Everything is single-threaded. Examples run sequentially in one pytest
process, and the project has no xdist. Each example owns its `tmp_path`. The
process-global state it touches (environment, cwd,
`kohle.app.cli.cli.date`, `socket.socket.connect`) is changed only through
`monkeypatch` and restored per test. The session template is shared but
read-only. If xdist is added later, each worker has its own process and
template, and nothing here breaks. CI's two jobs are ordered by `needs:`.

### 15.4 Reuse

| What already existed | How it is used |
|---|---|
| `CliRunner` and the real `_KohleCommand.invoke` path | the runner (§4.4) |
| `kohle-cli init` (`init_ledger`) | builds the template ledger, so examples get the migrations-made schema |
| `_no_real_user_paths` | the outer guard |
| `_pin_today` pattern (four copies) | factored into a `pin_today` conftest fixture for this and later work |
| `kohle.plugin.plugin_manager.entry_points` seam and `load_plugins` / `load_price_plugins` | the plugin-list hook and its stub-plugin test |
| markdown-it-py (already pinned) | fence parsing |
| s2s: docs layout, `<!-- … -->`-above-fence binding, `docs.yml` | followed (§3, §4.1, §13) |
| uv | the docs environment, locally and in CI |

Introduced and reusable later: the console-block checker works for any future
page; `pin_today`; the hook pattern for any other build-time generated list.

### 15.5 Extension points

- **`kohle.plugins` entry points** are the existing extension point. This
  feature documents them, through the generated list and the generated
  contract, and adds one *soft* convention: a plugin's class docstring, first
  paragraph, is what the guide shows under "Accepts". It is optional for
  third parties, who get `not stated by the plugin`. Bundled plugins are held
  to it by a test.
- **The `docs:` comment vocabulary is closed.** A new option is an edit to
  `tests/docs_examples.py`. It is not a plugin seam.
- **mkdocstrings directives** can document other modules later, but nothing
  beyond the plugin contract is meant to be public API.
- Nothing else is intended to be plugged into.

### 15.6 Build vs. buy

| Component | Decision | Evaluated, and what it could not do |
|---|---|---|
| Site generator | buy: MkDocs + material | given by the spec (s2s precedent; Sphinx rejected) |
| Command reference | buy: mkdocs-click | sphinx-click goes with Sphinx; a hand-written page is the page that drifts |
| Example checker | **build** (~150 lines) | **pytest doctest / `--doctest-glob`**: runs Python `>>>` sessions; pages would have to show Python, not `$ kohle-cli`. **pytest-markdown-docs, phmdoctest**: run Python fences only. **cram / prysk**: shell transcripts through a real subprocess, so today cannot be pinned without an app hook, at about 0.9 s per command. **Sybil**: a framework where we would still write the console parser, scratch ledger and date pin. It provides the per-block plumbing that `parametrize` gives here in a few lines, at the cost of a new test dependency. **pytest-console-scripts**: runs entry points but parses no markdown, and `CliRunner` covers that already. |
| Fence parsing | reuse markdown-it-py | a line regex (s2s) misses CommonMark fence rules (fences in list items, `~~~`, fence length) |
| Plugin list | **build** a 20-line MkDocs hook | **mkdocs-macros**: a new plugin plus Jinja in pages, where `{{` collides with code. **mkdocs-gen-files**: a new plugin, virtual pages, no better on GitHub. A committed generated file needs a regeneration edit, against "without a docs edit". |
| Interface docs | buy: mkdocstrings[python] | a hand-written table drifts, and is the README's current state |
| GIF | buy: VHS | **asciinema + agg**: records a live session, not scripted typing. **terminalizer**: Node; records interactively, then edits a config, so it is less reproducible. VHS is the one built for "rerun the script". |
| Pages deploy | buy: `upload-pages-artifact` + `deploy-pages` | `mkdocs gh-deploy` pushes a `gh-pages` branch and needs a write token; s2s uses artifacts |
| CI Python environment | uv (`setup-uv`) | `setup-python` + `pip install .` ignores `uv.lock`, so the app's dependencies would float in the docs build |

### 15.7 Abstractions introduced

Each one is listed with the problem that forces it. Anything not listed was
collapsed.

1. **`Example` / `Command` records.** The parametrised test, the meta-test on
   a synthetic page and the failure messages all need the parsed block,
   separate from running it. Without the split, the wrong-block test could not
   run the real path on a page that is not shipped.
2. **The `docs:` option comment.** Each keyword answers a specific page:
   - `first-run`: Getting started must show `init` and `(default)` sources;
   - `file` / `uses`: the rule file, `init.toml` and `config.toml` a page
     shows must be the ones applied;
   - `illustration`: the cron recipe, `edit-rules` and Alpha Vantage are
     `kohle-cli` lines that cannot run, so they must be deliberate.

   There are no others.
3. **Session template ledger.** A real `init` costs about 250 ms against 2 ms
   for a copy, across roughly 60 examples. It could be collapsed back to
   per-block `init` if the suite were small; it is kept because it is about 6
   lines.
4. **`pin_today` fixture.** Otherwise the checker would be a fifth copy of the
   same helper.
5. **The plugin-list hook.** No MkDocs feature lists entry points at build
   time.

Not introduced: no custom pytest collector or `Item` class, no markdown
extension of our own, no macro layer, no runner class, no option parser
beyond splitting on whitespace.

### 15.8 Alternatives rejected

- **A subprocess per command.** It is the more faithful run, but it cannot pin
  today without a production `KOHLE_TODAY`-style hook, and costs about 0.9 s
  of import per command against about 12 ms in process. `CliRunner` with
  `prog_name="kohle-cli"` and `obj=None` runs the same `main()` and the same
  invoke hook.
- **The injected `session_factory`.** It has the wrong schema origin, no
  People root and no schema check, so pages would document a ledger no user
  has.
- **A custom `pytest_collect_file` collector for `.md`.** It needs a root
  conftest, a `pytest.Item` subclass and `repr_failure`, and fixtures get
  harder. `parametrize` over parsed examples gives per-block ids and failures
  for free.
- **Options in the fence info string** (`` ```console no-ledger ``). The
  Python-Markdown and superfences fence regexes may refuse unknown words and
  break rendering. An HTML comment is renderer-neutral and is the s2s
  convention.
- **A custom language tag** (`` ```kohle ``). It loses `console` highlighting
  on GitHub and in the site.
- **A required explicit marker** (`<!-- docs: run -->` on every block). A
  forgotten marker silently unchecks a session. With `console` as the marker
  and the lint, a session cannot be shown unchecked by accident.
- **Hidden per-page setup shared across blocks.** Readers could not reproduce
  a block from the page, which breaks "each block runs on its own". The cost
  accepted instead is repeated `add-account` lines.
- **XDG-only isolation with no `KOHLE_DB` anywhere.** It gives cleaner output,
  but AC 091 names `KOHLE_DB`. It is kept only for `first-run`.
- **Output wildcards or placeholders** (doctest `...`, `<revision>`). They
  weaken "exact". Only the temp-path to `~` rewrite is forced.
- **An `--update-docs` mode that rewrites expected output.** It is not
  required, and it invites accepting output in bulk without reading it.
  Deferred.
- **A per-block `today=`.** No v1 page needs it.
- **A committed generated reference or plugin list with a freshness test.**
  A change would need a docs edit, which contradicts the spec.
- **A declared `accepts` attribute on the plugin ABCs.** It would change the
  contract for third-party plugins purely for docs, when docstrings are
  already a plugin's self-description.
- **Hand-written interface tables.** They drift.
- **Publishing the dev site,** as a subpath of Pages (forbidden by the spec)
  or from a second repository (overhead for one maintainer). **Building it in
  CI** (the spec says CI runs nothing else). **Dev pages inside `docs/` kept
  out of the nav** (they would still be copied into the published site).
- **Generating the VHS tape from the README block.** It couples a rarely
  regenerated asset to the test helper's import path, to save about 8
  duplicated lines that change only with the taste.
- **The VHS Docker image.** The container has no uv and no kohle, so a local
  install is simpler.
- **`mkdocs gh-deploy`** (§15.6).
- **A regex fence parser as in s2s** (§15.6).
- **Admonitions and content tabs in pages.** They do not read on GitHub, and
  their fences are invisible to the checker.

---

## 16. Gaps, conflicts and readings  ⚠

Each item has the decision taken. **[confirm]** marks the ones the author
should look at.

- **G1. `KOHLE_DB` against honest source labels.** AC 091 says each block uses
  `KOHLE_DB` at a temp path. With it set, `list-config` and `list-settings`
  report the ledger's source as `(KOHLE_DB)`, which would mislead readers of
  "Where the ledger lives". Decision: `KOHLE_DB` in the default state, and
  `first-run` blocks unset it. Their ledger still resolves into the scratch
  home, through `XDG_DATA_HOME`. **[confirm]**
- **G2. "Must match the page exactly".** Trailing whitespace on each line and
  trailing blank lines are ignored (editors strip them and they are invisible
  on the page), and the scratch home prints as `~` (the alternative is
  per-run temp paths). Everything visible is compared exactly.
- **G3. Invocations that cannot run.** The spec says every `kohle-cli`
  invocation shown runs in pytest. These cannot: `edit-rules` (an editor), a
  prompt without `--yes`, an Alpha Vantage fetch (network and key), and the
  cron snapshot recipe (`&&`, a synced folder). Decision: prose, or a fence
  marked `<!-- docs: illustration -->`, so every exception is explicit and
  visible in source. **[confirm]**
- **G4. Generated sections on GitHub.** The mkdocs-click directive, the
  plugin-list placeholder and the mkdocstrings directives render only on the
  site. On GitHub they show as a raw directive or nothing, which falls short
  of "reads as plain markdown on GitHub" for those sections. This is inherent
  to generation. Each such page says so in one sentence and points to
  `--help` or the source file by absolute URL. A relative link out of
  `docs/` would fail `strict`.
- **G5. No command help text.** No `kohle-cli` command has a docstring, so the
  generated reference has no descriptions. Decision: 092 adds a one-line
  docstring per command. It is an additive, user-visible `--help` change.
  `cli-command-naming` may reword them. **[confirm]**
- **G6. Third-party plugins without docstrings** show `not stated by the
  plugin`. writing-plugins.md asks authors for a first-paragraph "accepts"
  sentence.
- **G7. Pages prerequisites.** The repository's Pages source must be set to
  GitHub Actions, by hand and once. A private repository needs a paid plan for
  Pages. **[confirm]**
- **G8. CI installs the app as well as the docs toolchain.** Issue 105 says
  the toolchain comes from `docs/requirements.txt`, and it does. The app is
  also installed from `uv.lock`, because the reference and the plugin list
  import kohle. s2s needs no such step.
- **G9. Trigger scope.** The spec says every push and PR; s2s's workflow says
  push to `main` and PRs to `main`. The spec wins, at the cost of double runs
  on PR branches.
- **G10. Issue 091's "shipped sample page".** Read as: `docs/examples/statement.csv`
  plus a first checked block (add accounts, import the sample,
  `list-unclassified`) on the `import-and-classification.md` stub from 090,
  which 095 then builds out. **[confirm]**
- **G11. When the README joins the checker.** The current README has 33
  `bash` fences full of `kohle-cli` lines, so the invocation lint would fail
  the suite from 091 on. The checker scans `docs/**` until 103 adds
  `README.md`, in the slice that cuts it.
- **G12. Revision hashes in checked output.** `init`, `migrate` and
  `list-settings` print the Alembic head (`d7f3b9a1c846` today). Every new
  migration will fail Getting started until its output is updated. This is
  intended (AGENTS.md rule 1), but it is a recurring one-line chore.
- **G13. Personal data in the current README** must not move into docs:
  - the author's own worked setup (Raspberry Pi writer, Syncthing, laptop,
    tablet, "the author's");
  - the real securities `IE00B4L5Y983`, `DE0005190003` and `VWCE.DEX`.

  `dev/roadmap.md`'s targets ("the Pi", "the Indian holdings") are personal
  too, which is one more reason the README roadmap is written from the briefs
  and not from that file.
- **G14. `Import succeded`.** The typo is in `import-statement`'s output. The
  checked examples will reproduce it word for word. Fixing it is a CLI change
  outside this spec, a candidate for `cli-command-naming` or a `change`.
- **G15. Config snippets.** The spec says config snippets are illustration.
  Unmarked ones still are. `file` / `uses` lets a page make a snippet the
  actual input of an example (`init.toml`, `config.toml`). That extends the
  spec and does not contradict it.
- **G16. App code touched by a docs feature.** There are three places: the
  docstrings in `kohle/plugin/*.py` and `kohle/app/plugins/*.py` (101), the
  command docstrings in `cli.py` (092, G5), and possibly `show_default` on the
  group (§7 fallback). No behaviour changes beyond `--help` text.
- **G17. `DOCS_TODAY` is stated twice:** the constant and one sentence in
  `docs/index.md`. A comment on the constant names the page.
- **G18. Reading the guide locally needs the project environment,** not a bare
  docs venv as in s2s. The README and the dev site give the
  `uv run --with-requirements …` form.
- **G19. Spec open question 1** (the dev site) was left open in the frozen
  spec. It is settled here: `dev/docs/`, local only (§9).
- **G20. AGENTS.md pointer to the example syntax.** This goes beyond 106's
  three rules; it is recommended, not required.
- **G21. The default Bundesland `BW`** is the value the README already uses.
  If it is the author's own state, any other code works equally well.
  **[confirm]**

---

## 17. Slice notes

- **090** creates all page stubs, both generated pages included, so later
  slices only fill pages. `site/` goes in `.gitignore`. The transcripts move
  with `git mv`.
- **091** depends on 090 for the pages. It ships the checker, `pin_today`,
  `statement.csv` and the first block (G10).
- **092** and **101** can go in parallel after 090. 101 owns the
  `plugins:` / `hooks:` additions to mkdocs.yml.
- **093–100** each fill one stub and add their samples (`prices.csv` in 097,
  `broker.csv` in 098). They do not cut the README.
- **103** cuts the README, adds it to the checker, and ships `rules.toml`.
  **104** follows with the tape and GIF. **106** follows 103.
- **105** depends only on 090, and can land early to guard every later slice.
