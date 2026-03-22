from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.containers import Container
from textual.widgets import (
    Static,
    TabbedContent,
    TabPane,
    DataTable,
    Footer,
    Header,
    Input,
)


class ListDialog(ModalScreen):
    BINDINGS = [
        Binding("left", "prev_tab", "Prev Tab"),
        Binding("right", "next_tab", "Next Tab"),
        Binding("h", "prev_tab", "Prev Tab"),
        Binding("l", "next_tab", "Next Tab"),
        Binding("ctrl+tab", "next_tab", "Next Tab"),
        Binding("ctrl+shift+tab", "prev_tab", "Prev Tab"),
        Binding("tab", "focus_next", "Next Focus"),
        Binding("shift+tab", "focus_prev", "Prev Focus"),
        Binding("j", "focus_next", "Next Focus"),
        Binding("k", "focus_prev", "Prev Focus"),
        Binding("ctrl+a", "add_item", "Add"),
        Binding("ctrl+d", "delete_item", "Delete"),
        Binding("ctrl+e", "edit_item", "Edit"),
        Binding("escape", "dismiss", "Close"),
    ]

    CSS = """
    ListDialog {
        align: center middle;
        background: rgba(0,0,0,0.45);
    }

    #dialog {
        width: 70%;
        height: 90%;
        border: round $accent;
        background: $surface;
        padding: 1;
    }

    #title {
        height: 1;
        content-align: center middle;
        text-style: bold;
    }

    DataTable {
        height: 1fr;
    }

    #editor {
        height: 2;
        display: none;
    }

    #hint_footer {
        height: 3;
        content-align: center middle;
        color: $text-muted;
    }
    """

    def __init__(self, number_of_tabs) -> None:
        super().__init__()
        self.edit_mode = None
        self.edit_key = None
        self.next_key = 0
        self.current_tab = ""
        self.number_of_tabs = number_of_tabs

    def compose(self) -> ComposeResult:
        with Container(id="edit_categories_dialog"):
            with TabbedContent(id="tabs"):
                with TabPane("Debit Categories", id="debit_categories"):
                    table = DataTable(id="debit_categories_table")
                    table.add_column("Categories")
                    yield table
                with TabPane("Credit Categories", id="credit_categories"):
                    table = DataTable(id="credit_categories_table")
                    table.add_column("Catergories")
                    yield table
            yield Input(placeholder="Enter item…", id="editor")
            yield Static(
                "←/→ or h/l tabs | Tab/j/k focus | Ctrl+A add | Ctrl+E edit | Ctrl+D delete",
                id="hint_footer",
            )

    def _new_key(self):
        key = self.next_key
        self.next_key += 1
        return key

    def get_tabs(self):
        return self.query_one("#tabs", TabbedContent)

    def get_panes(self):
        return list(self.query("#tabs > TabPane"))

    def get_active_table(self):
        pane = self.get_tabs().active_pane
        return pane.query_one(DataTable)

    def get_editor(self):
        return self.query_one("#editor", Input)

    def get_cursor_key(self):
        """Get stable row key from cursor position."""
        table = self.get_active_table()
        row_index = table.cursor_row
        if row_index is None:
            return None
        return table.get_row_at(row_index).key

    def _switch_tab(self, direction):
        tabs = self.get_tabs()
        panes = self.get_panes()
        ids = [p.id for p in panes]
        idx = ids.index(tabs.active)
        tabs.active = ids[(idx + direction) % len(ids)]
        self.get_active_table().focus()

    def action_next_tab(self):
        self._switch_tab(1)

    def action_prev_tab(self):
        self._switch_tab(-1)

    def action_focus_next(self):
        table = self.get_active_table()
        tabs = self.get_tabs()
        if self.focused is table:
            tabs.focus()
        else:
            table.focus()

    def action_focus_prev(self):
        self.action_focus_next()

    def show_editor(self, value=""):
        editor = self.get_editor()
        editor.value = value
        editor.styles.display = "block"
        editor.focus()

    def hide_editor(self):
        self.get_editor().styles.display = "none"
        self.get_active_table().focus()

    def action_add_item(self):
        self.edit_mode = "add"
        self.edit_key = None
        self.show_editor()

    def action_edit_item(self):
        table = self.get_active_table()
        key = self.get_cursor_key()
        if key is None:
            return

        value = table.get_row(key)[0]

        self.edit_mode = "edit"
        self.edit_key = key
        self.show_editor(value)

    def action_delete_item(self):
        table = self.get_active_table()
        key = self.get_cursor_key()
        if key is not None:
            table.remove_row(key)

    def on_input_submitted(self, event: Input.Submitted):
        table = self.get_active_table()
        value = event.value.strip()

        if not value:
            self.hide_editor()
            return

        if self.edit_mode == "add":
            table.add_row(value, key=str(self._new_key()))

        elif self.edit_mode == "edit":
            table.update_cell(self.edit_key, 0, value)

        self.hide_editor()

    def on_key(self, event):
        if event.key == "escape":
            editor = self.get_editor()
            if editor.styles.display != "none":
                self.hide_editor()
                event.stop()

    def action_dismiss(self):
        self.dismiss()


class DemoApp(App):

    BINDINGS = [
        Binding("m", "open_modal", "Open Dialog"),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self):
        yield Header(show_clock=True)
        yield Static("Press M to open editable modal", expand=True)
        yield Footer()

    def action_open_modal(self):
        self.push_screen(ListDialog())


if __name__ == "__main__":
    DemoApp().run()
