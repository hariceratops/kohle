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
        self.post_message(self.CellEdited(self, event.value))

    def on_key(self, event):
        if event.key == "escape":
            self.post_message(self.CellEditAborted(self))
            event.stop()


class Spreadsheet(Container):
    BINDINGS = [
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

    def deduce_edit_location(self):
        coord = self.table.cursor_coordinate
        cell = self.table.coordinate_to_cell_key(coord)
        return cell.row_key, cell.column_key, coord

    def compute_cell_geometry(self):
        result = self.deduce_edit_location()
        _, _, coord = result
        row_idx = coord.row
        col_idx = coord.column
        columns = list(self.table.columns.values())
        logging.debug(columns)
        width = columns[col_idx].get_render_width(self.table)
        x = sum(c.get_render_width(self.table) for c in columns[:col_idx]) - self.table.scroll_x
        y = 1 + row_idx - self.table.scroll_y
        return CellGeometry(x=x, y=y, width=width, height=1)

    def action_edit_cell(self):
        result = self.deduce_edit_location()
        row_key, col_key, _ = result
        self.mode = EditMode.EDIT
        self.edit_row_key = row_key
        self.edit_col_key = col_key
        value = str(self.table.get_cell(row_key, col_key))
        geom = self.compute_cell_geometry()
        self.editor.post_message(SpreadsheetCellEditor.StartEdit(self.editor, value, geom))

    def action_add_row(self):
        self.mode = EditMode.ADD
        self._temp_row_key = f"__{uuid.uuid4().hex}__"
        empty = [""] * len(self.table.columns)
        self.table.add_row(*empty, key=self._temp_row_key)
        self.table.move_cursor(row=self.table.row_count - 1, column=0)
        geom = self.compute_cell_geometry()
        self.editor.post_message(SpreadsheetCellEditor.StartEdit(self.editor, "", geom))

    def action_delete_row(self):
        result = self.deduce_edit_location()
        row_key, _, _ = result
        approved = self.controller.request_delete(row_key)
        if approved:
            self.table.remove_row(row_key)

    def on_spreadsheet_cell_editor_cell_edited(self, event: SpreadsheetCellEditor.CellEdited):
        value = event.value.strip()
        if self.mode is EditMode.EDIT:
            approved = self.controller.request_edit(self.edit_row_key, self.edit_col_key, value)
            if approved:
                self.table.update_cell(self.edit_row_key, self.edit_col_key, value)
                self.table.refresh(layout=True)

        elif self.mode is EditMode.ADD:
            new_key = self.controller.request_add([value])
            if new_key is not None:
                self.table.remove_row(self._temp_row_key)
                self.table.add_row(value, key=new_key)
                self.table.refresh(layout=True)

        self.editor.hide_editor()
        self.table.focus()
        self.mode = EditMode.NONE

    def on_spreadsheet_cell_editor_cell_edit_aborted(self, _):
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

