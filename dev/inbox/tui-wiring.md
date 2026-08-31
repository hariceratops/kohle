# Wiring the TUI to the use cases

## Goal

Make the TUI a real second frontend over the same use cases and services the CLI
uses: one application, reaching the domain through the same layer, surfacing
errors to the user instead of dying on them.

The problem behind it is that the TUI is currently two disconnected halves. The
shipped entry point (`kohle-tui` → `kohle/app/tui/tui.py`) renders a static
"Welcome to Kohle!" and a footer, and reaches no use case at all. The table
editor — which is where all the actual work went — is only ever instantiated by
a `DemoApp` at the bottom of `table_editor.py`, run by executing that file
directly. Neither half knows about the other, so the generic editing machinery
that was built is not reachable from the application that ships.

## Considerations surfaced

**The connective tissue is missing, not just untidy.** `CategoriesScreen`
imports `AddCategoryForm` from `kohle.app.tui.widgets.category_form`, which does
not exist. Both `category_screen.py` and `table_editor.py` import
`list_debit_categories` / `add_debit_category` from
`kohle.use_cases.debit_categories`, which exports the classes `ListCategories`
and `AddDebitCategory` instead. So the one command-palette entry that exists
("Manage Categories") cannot open its screen. These are import-time failures,
which means large parts of the TUI have not been run recently.

**The controller and the use-case layer disagree about their contract.**
`TableController` calls `self.list_use_case(uow)` — a callable taking a unit of
work — while use cases are classes constructed with a session and invoked via
`.execute()`. It also does `with UnitOfWork(session_local()) as uow`, but
`UnitOfWork` defines no `__enter__`/`__exit__`. Settling what a use case looks
like from a frontend's perspective is the substance of this work; the rest
follows from it.

**The UI currently builds its own sessions.** Every controller method opens
`session_local()` and its own unit of work, so each keystroke-level operation is
an independent transaction created from the presentation layer. This is the
existing `# todo remove uow from ui`, and it is the layering decision that
should be made deliberately rather than inherited.

**Errors terminate the application by design.** `commit_edit` and
`handle_append` call `result.unwrap()` on the error path, which raises. That was
a deliberate step at the time, but it means an ordinary domain error — a
duplicate category name, an empty field — kills the TUI. Deciding how errors
reach the user is the other half of "closing the loops", alongside the
`# todo error` markers scattered through `column_editor.py`,
`table_edit_policy.py` and `TableControllerBuilder`.

**Some loops are bound to keys that cannot work.** `ctrl+d` is bound to delete
and `TableController.request_delete` raises `NotImplementedError`.

**The builder does not fail the way it was designed to.** `TableControllerBuilder`
accumulates build errors into an `Option` and returns them from `build()`, but
`build()` then unwraps the other options unconditionally, so omitting an adder
or a lister raises instead of producing the build error the design intends.
`edit_policies` is collected by the builder and never passed to the controller.

**Two smaller defects will distort anything built on top.**
`populate_columns` returns `[{ "key": col for col in cols_list }]` — a
single-element list holding one dict keyed to the last column, rather than one
dict per column. And `populate_rows` returns `Result.err(rows)`, wrapping the
whole `Result` rather than its error.

**The model the TUI is wired to no longer exists.** The ledger rework has landed
and `DebitCategory` is gone, replaced by expense accounts. `table_editor.py` and
`category_screen.py` still import it and the use-case functions that went with
it, so the whole table-editor stack is now dead code until it is pointed at the
new model. That was the intended sequencing — rewiring before the schema settled
would have meant doing it twice — but it means nothing under `app/tui/` runs
today.

**`AppPalleteCommands` exists twice**, identically, in `tui.py` and
`provider.py`, with the `provider.py` import commented out in `tui.py`.

## Directions rejected

Terminating the application on controller errors. It was a reasonable staging
decision and is recorded in the history as such, but it cannot survive contact
with a user who types a duplicate name.

## Open questions

- What is a use case, seen from a frontend? A callable taking a transaction
  context, or a class owning its own session? The CLI and the table controller
  currently assume different answers, and both frontends have to agree.
- Who owns the session and the transaction boundary — the frontend, the
  controller, or the use case itself?
- How does an error reach the user: an inline cell message, a dialog, a status
  line? A `dialog` widget already exists but is unused here.
- Does the generic table editor stay generic — reused across accounts,
  instruments, rules — or does the schema rework make purpose-built screens
  cheaper than the serde machinery that generality costs?
- Is the command palette the primary navigation, or is it a stand-in for a real
  screen structure?
- What does the TUI need to do beyond editing tables — is reporting a TUI
  concern at all, or does that stay CLI-only?
