# requires resizing on Input
# use custom event for Input - Add, Edit and Delete
# add should move to end of table and fill every column on enter
# edit with current value

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import DataTable, Input, Header, Footer
import logging
from textual.app import App
from textual.logging import TextualHandler

logging.basicConfig(level="NOTSET", handlers=[TextualHandler()])



# --------------------------------------------------
# Editable DataTable
# --------------------------------------------------

class EditableTable(Container):

    BINDINGS = [
        Binding("ctrl+a", "add_row", "Add"),
        Binding("ctrl+e", "edit_row", "Edit"),
        Binding("ctrl+d", "delete_row", "Delete"),
    ]

    CSS = """
    EditableTable {
        height: 1fr;
    }

    #editor {
        layer: overlay;
        display: none;
    }
    """

    def __init__(self):
        super().__init__()
        self.edit_mode = None
        self.edit_row_key = None

    # --------------------------------------------------

    def compose(self) -> ComposeResult:
        table = DataTable(id="table")
        table.add_column("Name", key="name")

        # Simulated DB rows (primary key, value)
        rows = [
            (101, "Alice"),
            (102, "Bob"),
            (103, "Charlie"),
        ]

        for pk, value in rows:
            table.add_row(value, key=str(pk))

        yield table
        yield Input(id="editor")

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    def table(self) -> DataTable:
        return self.query_one("#table", DataTable)

    def editor(self) -> Input:
        return self.query_one("#editor", Input)

    def get_cursor_keys(self):
        table = self.table()
        coord = table.cursor_coordinate
        if coord is None:
            return None, None

        cell_key = table.coordinate_to_cell_key(coord)
        return cell_key.row_key, cell_key.column_key

    # --------------------------------------------------
    # Geometry (correct API usage)
    # --------------------------------------------------

    def position_editor(self):
        table = self.table()
        editor = self.editor()

        coord = table.cursor_coordinate
        if coord is None:
            return

        row_index = coord.row
        col_index = coord.column

        columns = list(table.columns.values())

        # -------- X position --------
        x = 0
        for col in columns[:col_index]:
            x += col.get_render_width(table)

        current_col = columns[col_index]
        width = current_col.get_render_width(table)

        # -------- Y position --------
        header_height = 1
        row_height = 1
        logging.debug(f"row_idx={row_index}")
        logging.debug(f"row_height={row_height}")
        logging.debug(f"width={width}")
        logging.debug(f"header_height={header_height}")
        y = header_height + row_index * row_height

        # -------- apply scroll offsets --------
        # x -= table.scroll_x
        # y -= table.scroll_y
        logging.debug(f"x={x}")
        logging.debug(f"y={y}")
        # logging.debug(x)
        # logging.debug(y)
        # logging.debug(row_height)
        # logging.debug(width)

        # -------- place editor --------
        editor.styles.offset = (x, y)
        editor.styles.width = width
        editor.styles.min_height = row_height
        editor.styles.max_height = row_height
        editor.styles.height = row_height
        editor.styles.layer = "above"
        editor.styles.border = "none"

    # --------------------------------------------------
    # Editor handling
    # --------------------------------------------------

    def show_editor(self, value=""):
        editor = self.editor()
        editor.value = value

        self.position_editor()

        editor.styles.display = "block"
        editor.focus()

    def hide_editor(self):
        self.editor().styles.display = "none"
        self.table().focus()

    # --------------------------------------------------
    # Actions
    # --------------------------------------------------

    def action_add_row(self):
        self.edit_mode = "add"
        self.edit_row_key = None
        self.show_editor()

    def action_edit_row(self):
        row_key, _ = self.get_cursor_keys()
        if row_key is None:
            return

        value = self.table().get_row(row_key)[0]

        self.edit_mode = "edit"
        self.edit_row_key = row_key
        self.show_editor(value)

    def action_delete_row(self):
        row_key, _ = self.get_cursor_keys()
        if row_key is None:
            return

        self.table().remove_row(row_key)
        self.app.notify(f"DELETE id={row_key}")

    # --------------------------------------------------
    # Input handling
    # --------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted):
        value = event.value.strip()
        table = self.table()

        if not value:
            self.hide_editor()
            return

        if self.edit_mode == "add":
            new_id = max(int(k) for k in table.rows.keys()) + 1
            table.add_row(value, key=str(new_id))
            self.app.notify(f"INSERT id={new_id}")

        elif self.edit_mode == "edit":
            table.update_cell(self.edit_row_key, "name", value)
            table.refresh(layout=True)
            self.app.notify(f"UPDATE id={self.edit_row_key}")

        self.hide_editor()

    # --------------------------------------------------

    def on_key(self, event):
        if event.key == "escape":
            if self.editor().styles.display != "none":
                self.hide_editor()
                event.stop()


# --------------------------------------------------
# Demo app
# --------------------------------------------------

class DemoApp(App):

    def compose(self) -> ComposeResult:
        yield Header()
        yield EditableTable()
        yield Footer()


if __name__ == "__main__":
    DemoApp().run()
