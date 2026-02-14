from functools import partial
from textual.command import Hit, Hits, Provider
from kohle.app.tui.screens.category_screen import CategoriesScreen
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from kohle.app.tui.tui import KohleApp


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


