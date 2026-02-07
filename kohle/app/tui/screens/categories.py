from textual.screen import Screen
from textual.widgets import TabbedContent, TabPane, DataTable
from textual.binding import Binding

from kohle.db.uow import UnitOfWork
from kohle.app.tui.widgets.add_category_modal import AddCategoryModal
from kohle.db.connection import session_local
from kohle.services.debit_categories import load_debit_categories


class CategoriesScreen(Screen):

    BINDINGS = [
        Binding("ctrl+a", "add_category", "Add Category"),
        Binding("escape", "pop_screen", "Back"),
    ]

    def compose(self):
        with TabbedContent():
            with TabPane("Debit", id="debit-tab"):
                yield DataTable(id="debit-table")
            with TabPane("Credit", id="credit-tab"):
                yield DataTable(id="credit-table")

    def on_mount(self):
        table = self.query_one("#debit-table", DataTable)
        table.add_columns("ID", "Name")
        self.load_debit_categories()

    def load_debit_categories(self):
        table = self.query_one("#debit-table", DataTable)
        table.clear()
        uow = UnitOfWork(session_local)

        result = load_debit_categories(uow)
        if result.is_ok:
            debit_category_list = result.unwrap()
            for cat in debit_category_list:
                table.add_row(str(cat["id"]), cat["category"])

    def action_add_category(self):
        self.app.push_screen(AddCategoryModal(self.on_category_added))

    def on_category_added(self, result):
        if result.is_ok:
            self.load_debit_categories()

