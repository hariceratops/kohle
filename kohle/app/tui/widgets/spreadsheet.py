import uuid
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol, Iterable, Sequence

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.widgets import DataTable, Input, Header, Footer
import logging
from textual.app import App
from textual.logging import TextualHandler

logging.basicConfig(level="NOTSET", handlers=[TextualHandler()])


@dataclass(frozen=True, slots=True)
class CellGeometry:
    x: int
    y: int
    width: int
    height: int


class EditMode(Enum):
    NONE = auto()
    ADD = auto()
    EDIT = auto()


@dataclass(frozen=True, slots=True)
class RowData:
    key: str
    values: Sequence[str]


class SpreadsheetController(Protocol):
    def populate(self) -> Iterable[RowData]:
        ...

    def request_add(self, values: Sequence[str]) -> str | None:
        """
        Return new row key if approved.
        Return None to reject.
        """
        ...

    def request_edit(
        self,
        row_key: str,
        column_key: str,
        new_value: str,
    ) -> bool:
        """
        Return True if edit allowed.
        """
        ...

    def request_delete(self, row_key: str) -> bool:
        """
        Return True if delete allowed.
        """
        ...


class SpreadsheetCellEditor(Input):
    class StartEdit(Message):
        def __init__(self, sender, value: str, geometry: CellGeometry):
            super().__init__()
            self.sender = sender
            self.value = value
            self.geometry = geometry

    class CellEdited(Message):
        def __init__(self, sender, value: str):
            super().__init__()
            self.sender = sender
            self.value = value

    class CellEditAborted(Message):
        def __init__(self, sender):
            super().__init__()
            self.sender = sender

    # DEFAULT_CSS = """
    # SpreadsheetCellEditor {
    #     display: none;
    #     layer: above;
    #     border: none;
    #     padding: 0;
    #     margin: 0;
    #     min-height: 1;
    # }
    # """

    def on_spreadsheet_cell_editor_start_edit(self, event: StartEdit):
        geom = event.geometry
        self.value = event.value
        self.styles.offset = (geom.x, geom.y)
        self.styles.width = geom.width
        self.styles.height = geom.height
        self.styles.min_height = geom.height
        self.styles.max_height = geom.height
        self.styles.display = "block"
        self.styles.layer = "above"
        self.styles.border = "none"
        self.focus()

    def hide_editor(self):
        self.styles.display = "none"

    def on_input_submitted(self, event: Input.Submitted):
        logging.debug(event.value)
        self.post_message(self.CellEdited(self, event.value))

    def on_key(self, event):
        if event.key == "escape":
            self.post_message(self.CellEditAborted(self))
            event.stop()


class Spreadsheet(Container):
    BINDINGS = [
        # Binding("enter", "edit_cell", "Edit"),
        Binding("ctrl+e", "edit_cell", "Edit"),
        Binding("ctrl+a", "add_row", "Add"),
        Binding("ctrl+d", "delete_row", "Delete"),
    ]

    def __init__(self, controller: SpreadsheetController):
        super().__init__()
        self.controller = controller
        self.mode = EditMode.NONE
        self.edit_row_key = None
        self.edit_col_key = None
        self._temp_row_key = None
        self.table = DataTable(id="table")
        self.editor = SpreadsheetCellEditor(id="editor")
        self.table.add_column("Name", key="name")

    def compose(self) -> ComposeResult:
        yield self.table
        yield self.editor

    def on_mount(self):
        rows = [
            (101, "Alice"),
            (102, "Bob"),
            (103, "Charlie"),
        ]
        for pk, value in rows:
            self.table.add_row(value, key=str(pk))

        # rows = list(self.controller.populate())
        # for row in rows:
        #     self.table.add_rows(*row.values, row.key)
        #     [tuple(r.values) for r in rows],
        #     keys=[r.key for r in rows],
        # )

    def deduce_edit_location(self):
        coord = self.table.cursor_coordinate
        if coord is None:
            return None

        cell = self.table.coordinate_to_cell_key(coord)
        return cell.row_key, cell.column_key, coord

    def compute_cell_geometry(self):
        result = self.deduce_edit_location()
        if result is None:
            return None

        _, _, coord = result

        row = coord.row
        col = coord.column
        columns = list(self.table.columns.values())

        x = sum(c.get_render_width(self.table) for c in columns[:col])
        width = columns[col].get_render_width(self.table)

        y = 1 + row

        x -= self.table.scroll_x
        y -= self.table.scroll_y

        return CellGeometry(x=x, y=y, width=width, height=1)


    def action_edit_cell(self):
        result = self.deduce_edit_location()
        if result is None:
            return

        row_key, col_key, _ = result

        self.mode = EditMode.EDIT
        self.edit_row_key = row_key
        self.edit_col_key = col_key

        value = str(self.table.get_cell(row_key, col_key))
        geom = self.compute_cell_geometry()
        if geom is None:
            return

        self.editor.post_message(
            SpreadsheetCellEditor.StartEdit(
                self.editor, value, geom
            )
        )

    def action_add_row(self):
        self.mode = EditMode.ADD
        self._temp_row_key = f"__{uuid.uuid4().hex}__"
        empty = [""] * len(self.table.columns)
        self.table.add_row(*empty, key=self._temp_row_key)
        row = self.table.row_count - 1
        self.table.move_cursor(row=row, column=0)

        geom = self.compute_cell_geometry()
        if geom is None:
            return

        self.editor.post_message(
            SpreadsheetCellEditor.StartEdit(
                self.editor, "", geom
            )
        )

    def action_delete_row(self):
        result = self.deduce_edit_location()
        if result is None:
            return
        row_key, _, _ = result
        approved = self.controller.request_delete(row_key)
        if approved:
            self.table.remove_row(row_key)

    def on_spreadsheet_cell_editor_cell_edited(
        self,
        event: SpreadsheetCellEditor.CellEdited,
    ):

        logging.debug(f"{self.mode}")
        value = event.value.strip()
        if self.mode is EditMode.EDIT:
            approved = self.controller.request_edit(
                self.edit_row_key,
                self.edit_col_key,
                value,
            )
            if approved:
                self.table.update_cell(
                    self.edit_row_key,
                    self.edit_col_key,
                    value,
                )
                self.table.refresh(layout=True)

        elif self.mode is EditMode.ADD:
            new_key = self.controller.request_add([value])
            logging.debug(new_key)
            if new_key is not None:
                self.table.remove_row(self._temp_row_key)
                self.table.add_row(value, key=new_key)

        self.editor.hide_editor()
        self.table.focus()
        self.mode = EditMode.NONE

    def on_spreadsheet_cell_editor_celleditaborted(self, _):
        if self.mode is EditMode.ADD and self._temp_row_key:
            self.table.remove_row(self._temp_row_key)
        self.editor.hide_editor()
        self.table.focus()
        self.mode = EditMode.NONE


class InMemoryController:
    def __init__(self):
        self.rows = {
            "101": ["Alice"],
            "102": ["Bob"],
            "103": ["Charlie"],
        }

    def populate(self):
        for k, v in self.rows.items():
            yield RowData(k, v)

    def request_add(self, values):
        new_id = str(uuid.uuid4().hex[:8])
        self.rows[new_id] = list(values)
        return new_id

    def request_edit(self, row_key, column_key, new_value):
        if row_key in self.rows:
            self.rows[row_key][0] = new_value
            return True
        return False

    def request_delete(self, row_key):
        if row_key in self.rows:
            del self.rows[row_key]
            return True
        return False


class DemoApp(App):

    def compose(self):
        yield Header()
        yield Spreadsheet(controller=InMemoryController())
        yield Footer()


if __name__ == "__main__":
    DemoApp().run()

# requires resizing on Input
# use custom event for Input - Add, Edit and Delete
# add should move to end of table and fill every column on enter
# edit with current value

# from textual.app import App, ComposeResult
# from textual.binding import Binding
# from textual.containers import Container
# from textual.widgets import DataTable, Input, Header, Footer
# import logging
# from textual.app import App
# from textual.logging import TextualHandler
#
# logging.basicConfig(level="NOTSET", handlers=[TextualHandler()])
#
#
#
# # --------------------------------------------------
# # Editable DataTable
# # --------------------------------------------------
#
# class EditableTable(Container):
#
#     BINDINGS = [
#         Binding("ctrl+a", "add_row", "Add"),
#         Binding("ctrl+e", "edit_row", "Edit"),
#         Binding("ctrl+d", "delete_row", "Delete"),
#     ]
#
#     CSS = """
#     EditableTable {
#         height: 1fr;
#     }
#
#     #editor {
#         layer: overlay;
#         display: none;
#     }
#     """
#
#     def __init__(self):
#         super().__init__()
#         self.edit_mode = None
#         self.edit_row_key = None
#         self.on_row_added_callback = None
#         self.on_row_deleted_callback = None
#         self.on_row_edited_callback = None
#         self.on_mount_callback = None
#
#     # --------------------------------------------------
#
#     def compose(self) -> ComposeResult:
#         table = DataTable(id="table")
#         table.add_column("Name", key="name")
#         # Simulated DB rows (primary key, value)
#         rows = [
#             (101, "Alice"),
#             (102, "Bob"),
#             (103, "Charlie"),
#         ]
#         for pk, value in rows:
#             table.add_row(value, key=str(pk))
#         yield table
#         yield Input(id="editor")
#
#
#     def table(self) -> DataTable:
#         return self.query_one("#table", DataTable)
#
#     def editor(self) -> Input:
#         return self.query_one("#editor", Input)
#
#     def get_cursor_keys(self):
#         table = self.table()
#         coord = table.cursor_coordinate
#         if coord is None:
#             return None, None
#
#         cell_key = table.coordinate_to_cell_key(coord)
#         return cell_key.row_key, cell_key.column_key
#
#     def position_editor(self):
#         table = self.table()
#         editor = self.editor()
#
#         coord = table.cursor_coordinate
#         if coord is None:
#             return
#
#         row_index = coord.row
#         col_index = coord.column
#
#         columns = list(table.columns.values())
#
#         x = 0
#         for col in columns[:col_index]:
#             x += col.get_render_width(table)
#
#         current_col = columns[col_index]
#         width = current_col.get_render_width(table)
#
#         # -------- Y position --------
#         header_height = 1
#         row_height = 1
#         logging.debug(f"row_idx={row_index}")
#         logging.debug(f"row_height={row_height}")
#         logging.debug(f"width={width}")
#         logging.debug(f"header_height={header_height}")
#         y = header_height + row_index * row_height
#
#         # -------- apply scroll offsets --------
#         x -= table.scroll_x
#         y -= table.scroll_y
#         logging.debug(f"x={x}")
#         logging.debug(f"y={y}")
#         # logging.debug(x)
#         # logging.debug(y)
#         # logging.debug(row_height)
#         # logging.debug(width)
#
#         # -------- place editor --------
#         editor.styles.offset = (x, y)
#         editor.styles.width = width
#         editor.styles.min_height = row_height
#         editor.styles.max_height = row_height
#         editor.styles.height = row_height
#         editor.styles.layer = "above"
#         editor.styles.border = "none"
#
#     # --------------------------------------------------
#     # Editor handling
#     # --------------------------------------------------
#
#     def show_editor(self, value=""):
#         editor = self.editor()
#         editor.value = value
#         self.position_editor()
#         editor.styles.display = "block"
#         editor.focus()
#
#     def hide_editor(self):
#         self.editor().styles.display = "none"
#         self.table().focus()
#
#     def action_add_row(self):
#         self.edit_mode = "add"
#         self.edit_row_key = "__new__"
#         # add dummy row with dummy data and key, commit real data and then delete the 
#         # temp row
#         empty_row = [""] * len(list(self.table().columns.keys()))
#         self.table().add_row(*empty_row, key="__new__")
#         row_index = self.table().row_count - 1
#         self.table().move_cursor(row=row_index, column=0)
#         self.show_editor()
#
#     def action_edit_row(self):
#         row_key, _ = self.get_cursor_keys()
#         if row_key is None:
#             return
#         value = self.table().get_row(row_key)[0]
#         self.edit_mode = "edit"
#         self.edit_row_key = row_key
#         self.show_editor(value)
#
#     def action_delete_row(self):
#         row_key, _ = self.get_cursor_keys()
#         if row_key is None:
#             return
#
#         self.table().remove_row(row_key)
#         self.app.notify(f"DELETE id={row_key}")
#
#     def on_input_submitted(self, event: Input.Submitted):
#         value = event.value.strip()
#         table = self.table()
#         if not value:
#             self.hide_editor()
#             return
#         if self.edit_mode == "add":
#             new_id = max(int(k.value) for k in table.rows.keys() if k.value != "__new__") + 1
#             table.remove_row("__new__")
#             table.add_row(value, key=str(new_id))
#             self.app.notify(f"INSERT id={new_id}")
#         elif self.edit_mode == "edit":
#             table.update_cell(self.edit_row_key, "name", value)
#             table.refresh(layout=True)
#             self.app.notify(f"UPDATE id={self.edit_row_key}")
#
#         self.hide_editor()
#
#     def on_key(self, event):
#         if event.key == "escape":
#             if self.editor().styles.display != "none":
#                 self.hide_editor()
#                 event.stop()
#
#
# class DemoApp(App):
#
#     def compose(self) -> ComposeResult:
#         yield Header()
#         yield EditableTable()
#         yield Footer()
#
#
# if __name__ == "__main__":
#     DemoApp().run()
