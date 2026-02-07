from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Static, Footer
from textual.containers import Vertical
from kohle.services.debit_categories import add_debit_category
from kohle.db.uow import UnitOfWork
from kohle.db.connection import session_local
from textual.app import App
from textual.binding import Binding
from functools import partial
from textual.command import Hit, Hits, Provider
from kohle.app.tui.screens.categories import CategoriesScreen


class ManageCategoriesCommand(Provider):
    async def search(self, query: str) -> Hits:
        """Search for the command in the palette."""
        matcher = self.matcher(query)
        app = self.app
        assert isinstance(app, KohleApp)

        command_name = "Manage Categories"
        score = matcher.match(command_name)
        if score > 0:
            yield Hit(
                score,
                matcher.highlight(command_name),
                partial(app.push_screen, CategoriesScreen()),
                help="Open the categories management screen",
            )

class KohleApp(App):
    # CSS_PATH = None
    COMMANDS = App.COMMANDS | {ManageCategoriesCommand}

    def compose(self):
        with Vertical():
            yield Static("Welcome to Kohle!", id="welcome", expand=True)
            # Footer with palette hint
            yield Footer()

    def on_mount(self):
        pass  # empty welcome screen


def main():
    KohleApp().run()


if __name__ == "__main__":
    main()

