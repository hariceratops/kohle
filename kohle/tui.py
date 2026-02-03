# kohle/tui.py
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Static

from kohle.services.categories import add_debit_category
from kohle.db import session_local


class DebitCategoryApp(App):
    # CSS_PATH = "styles.css"

    def compose(self) -> ComposeResult:
        yield Static("Enter a new debit category:")
        self.input = Input()
        yield self.input
        yield Button("Add", id="add-btn")
        yield Static("", id="output")

    def on_button_pressed(self, event):
        session = session_local()
        name = self.input.value
        try:
            result = add_debit_category(session, name)
        except ValueError as e:
            self.query_one("#output").update(f"❌ {e}")
            return
        finally:
            session.close()

        out = ""
        if result.added:
            out += f"✅ Category '{name}' added\n"
        else:
            out += f"⚠ Category '{name}' already exists\n"

        for w in result.warnings:
            out += f"⚠ Similar category exists: {w}\n"

        self.query_one("#output").update(out)


if __name__ == "__main__":
    DebitCategoryApp().run()

