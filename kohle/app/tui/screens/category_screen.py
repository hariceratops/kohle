from textual.screen import Screen
from textual.widgets import TabbedContent, TabPane, DataTable
from textual.binding import Binding
from kohle.app.tui.widgets.category_form import AddCategoryForm
from kohle.use_cases.debit_categories import list_debit_categories


class CategoriesScreen(Screen):
    # todo switching between tabs doesnt seem to work
    BINDINGS = [
        Binding("ctrl+a", "add_category", "Add Category"),
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def compose(self):
        with TabbedContent():
            with TabPane("Debit", id="debit-tab"):
                yield DataTable(id="debit-table")
            with TabPane("Credit", id="credit-tab"):
                yield DataTable(id="credit-table")

    def on_mount(self):
        table = self.query_one("#debit-table", DataTable)
        table.add_columns("Id", "Name")
        self.load_debit_categories()

    def load_debit_categories(self):
        table = self.query_one("#debit-table", DataTable)
        table.clear()
        result = list_debit_categories()
        if result.is_ok:
            debit_category_list = result.unwrap()
            for cat in debit_category_list:
                table.add_row(str(cat["id"]), cat["category"])

    def action_add_category(self):
        self.app.push_screen(AddCategoryForm(self.on_category_added))

    def on_category_added(self, result):
        if result.is_ok:
            self.load_debit_categories()

