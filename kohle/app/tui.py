from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Static
from kohle.services.debit_categories import add_debit_category
from kohle.db.uow import UnitOfWork
from kohle.db.connection import session_local


class DebitCategoryApp(App):
    # CSS_PATH = "styles.css"

    def compose(self) -> ComposeResult:
        yield Static("Enter a new debit category:")
        self.input = Input()
        yield self.input
        yield Button("Add", id="add-btn")
        yield Static("", id="output")

    def on_button_pressed(self, event):
        uow = UnitOfWork(session_local)
        name = self.input.value
        result = add_debit_category(uow, name)

        out = ""
        if result.is_ok:
            out += f"✅ Category '{name}' added with ID {result.unwrap()}\n"
        else:
            out += f"❌ {result.unwrap_err()}\n"

        self.query_one("#output").update(out)


def main():
    DebitCategoryApp().run()


if __name__ == "__main__":
    main()

