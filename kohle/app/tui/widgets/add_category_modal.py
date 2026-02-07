from textual.screen import ModalScreen
from textual.containers import Center
from textual.widgets import Input, Button, Static
from textual.binding import Binding
from kohle.db.connection import session_local
from kohle.services.debit_categories import add_debit_category
from kohle.db.uow import UnitOfWork

class AddCategoryModal(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel"),
    ]

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def compose(self):
        with Center():
            yield Static("New Debit Category")
            self.input = Input(placeholder="Category name")
            yield self.input
            yield Button("Add", id="add")

    def on_button_pressed(self):
        name = self.input.value.strip()
        uow = UnitOfWork(session_local)
        result = add_debit_category(uow, name)
        if result.is_ok:
            self.callback(result.unwrap())
        self.dismiss()

