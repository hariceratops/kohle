from sqlalchemy.sql.roles import LabeledColumnExprRole
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.containers import Container
from textual.widgets import (
    Label,
    Static,
    TabbedContent,
    TabPane,
    DataTable,
    Footer,
    Header,
    Input,
)
import logging
from textual.app import App
from textual.logging import TextualHandler

logging.basicConfig(level="NOTSET", handlers=[TextualHandler()])


class ListDialog(ModalScreen):
    BINDINGS = [
        Binding("left", "prev_tab", "Prev Tab"),
        Binding("right", "next_tab", "Next Tab"),
        Binding("h", "prev_tab", "Prev Tab"),
        Binding("l", "next_tab", "Next Tab"),
        Binding("tab", "next_tab", "Next Tab"),
        Binding("shift+tab", "prev_tab", "Prev Tab"),

        # Binding("j", "focus_next", "Next Focus"),
        # Binding("k", "focus_prev", "Prev Focus"),
        #
        # Binding("ctrl+a", "add_item", "Add"),
        # Binding("ctrl+d", "delete_item", "Delete"),
        # Binding("ctrl+e", "edit_item", "Edit"),
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

    def compose(self) -> ComposeResult:
        with Container(id="edit_categories_dialog"):
            with TabbedContent(id="tabs"):
                with TabPane("Debit Categories", id="debit_categories"):
                    yield Label("hello_debit")
                with TabPane("Credit Categories", id="credit_categories"):
                    yield Label("hello_debit")

    def get_tabs(self):
        return self.query_one("#tabs", TabbedContent)

    def get_panes(self):
        return list(self.query("#tabs > TabPane"))

    def get_active_table(self):
        pane = self.get_tabs().active_pane
        return pane

    def _switch_tab(self, direction):
        tabbed_content = self.query_one("#tabs", TabbedContent)
        current_pane = tabbed_content.active_pane
        number_of_panes = tabbed_content.tab_count
        tabbed_content.active_pane = 0
        logging.debug(self.get_active_table())
        # tabs = self.get_tabs()
        # panes = self.get_panes()
        # ids = [p.id for p in panes]
        # idx = ids.index(tabs.active)
        # tabs.active = ids[(idx + direction) % len(ids)]
        # self.get_active_table().focus()

    def action_next_tab(self):
        self._switch_tab(1)

    def action_prev_tab(self):
        self._switch_tab(-1)

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
