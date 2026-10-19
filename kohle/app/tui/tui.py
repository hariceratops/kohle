from textual.app import App
from textual.widgets import Static, Footer
from textual.containers import Vertical
from textual.command import Hit, Hits, Provider
from functools import partial
from kohle.db.connection import ledger_path, ledger_url, make_engine, make_session_factory
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
    make_session = make_session_factory(make_engine(ledger_url(ledger_path())))
    KohleApp(make_session).run()


if __name__ == "__main__":
    main()

