from textual.screen import ModalScreen
from textual.containers import Center, Container
from textual.widgets import Input, Static
from textual.binding import Binding
from kohle.use_cases.debit_categories import add_debit_category


class AddCategoryForm(ModalScreen):
    CSS_PATH = "../styles/category_form.tcss"
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel"),
    ]

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def compose(self):
        with Container(id="dialog"):
            yield Static("> Add debit category")
            self.input = Input(placeholder="Category name")
            yield self.input

    def on_mount(self):
        self.input.focus()

    def on_input_submitted(self, _: Input.Submitted):
        self.submit()

    def submit(self):
        result = add_debit_category(self.input.value)
        self.callback(result)
        self.dismiss()

