import sys
from textual.app import App
from textual.widgets import Static, Footer
from textual.containers import Vertical
from textual.command import Hit, Hits, Provider
from functools import partial
from kohle.db.connection import ledger_mode, ledger_path
from kohle.db.schema import open_ledger
from kohle.infrastructure.device_config import load_device_config
from kohle.app.tui.screens.category_screen import CategoriesScreen

# from kohle.app.tui.provider import AppPalleteCommands

class AppPalleteCommands(Provider):
    async def search(self, query: str) -> Hits:
        """Search for the command in the palette."""
        matcher = self.matcher(query)
        app = self.app
        assert isinstance(app, KohleApp)

        command_name = "Manage Categories"
        score = matcher.match(command_name)
        if score > 0:
            yield Hit(score, matcher.highlight(command_name), partial(app.push_screen, CategoriesScreen()), help="Open the categories management screen",)


class KohleApp(App):
    COMMANDS = App.COMMANDS | {AppPalleteCommands}

    def __init__(self, make_session):
        super().__init__()
        self.make_session = make_session

    def compose(self):
        with Vertical():
            yield Static("Welcome to Kohle!", id="welcome", expand=True)
            yield Footer()

    def on_mount(self):
        pass


def main():
    loaded = load_device_config()
    if loaded.is_err:
        sys.exit(str(loaded.unwrap_err()))
    config = loaded.unwrap()
    opened = open_ledger(ledger_path(config), ledger_mode(config))
    if opened.is_err:
        sys.exit(str(opened.unwrap_err()))
    KohleApp(opened.unwrap()).run()


if __name__ == "__main__":
    main()

