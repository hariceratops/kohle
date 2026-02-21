from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass
from typing import Iterable, Sequence, Optional, Protocol

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Input, Header, Footer
from textual.binding import Binding
from textual.message import Message
from textual.logging import TextualHandler

from statemachine import StateMachine, State


logging.basicConfig(level="NOTSET", handlers=[TextualHandler()])


@dataclass(slots=True)
class CellGeometry:
    x: int
    y: int
    width: int
    height: int


@dataclass(slots=True)
class CellContext:
    row_key: str
    column_key: str
    geometry: CellGeometry
    current_cell_value: str


@dataclass(frozen=True, slots=True)
class RowData:
    key: str
    values: Sequence[str]


@dataclass(frozen=True, slots=True)
class ColumnData:
    key: str
    value: str


class SpreadsheetController(Protocol):
    def populate_columns(self) -> Iterable[ColumnData]: ...
    def populate_rows(self) -> Iterable[RowData]: ...
    def request_add(self, values: Sequence[str]) -> Optional[str]: ...
    def request_edit(self, row_key: str, column_key: str, new_value: str) -> bool: ...
    def request_delete(self, row_key: str) -> bool: ...


class SpreadsheetStateMachine(StateMachine):
    navigation = State("navigation", initial=True)
    editing = State("editing")
    appending = State("appending")

    ctrl_e = navigation.to(editing)
    ctrl_a = navigation.to(appending)

    edit_done = editing.to(navigation)
    append_done = appending.to(navigation)
    cancel = editing.to(navigation) | appending.to(navigation)

    def __init__(self, owner: Spreadsheet) -> None:
        super().__init__()
        self.owner = owner
        self.append_index: int = 0

    def on_ctrl_e(self) -> None:
        self.owner.start_edit()

    def on_ctrl_a(self) -> None:
        self.append_index = 0
        self.owner.start_append()

    def on_edit_done(self, value: str) -> None:
        self.owner.finish_edit(value)

    def on_append_done(self) -> None:
        self.owner.finish_append()

    def on_cancel(self) -> None:
        self.owner.abort_current()


class SpreadsheetCellEditor(Input):
    class CellEdited(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    class CellEditAborted(Message):
        pass

    def show_editor(self, context: CellContext) -> None:
        g = context.geometry
        self.styles.offset = (g.x, g.y)
        self.styles.width = g.width
        self.styles.height = g.height
        self.styles.border = "none"
        self.styles.layer = "above"
        self.styles.display = "block"
        self.value = context.current_cell_value
        self.focus()

    def hide_editor(self) -> None:
        self.styles.display = "none"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.post_message(self.CellEdited(event.value))

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.post_message(self.CellEditAborted())


class Spreadsheet(Container):
    BINDINGS = [
        Binding("ctrl+e", "ctrl_e"),
        Binding("ctrl+a", "ctrl_a"),
        Binding("ctrl+d", "ctrl_d"),
    ]

    def __init__(self, controller: SpreadsheetController) -> None:
        super().__init__()
        self.controller = controller
        self.table = DataTable()
        self.editor = SpreadsheetCellEditor()
        self.machine = SpreadsheetStateMachine(self)
        self._active_context: Optional[CellContext] = None
        self._temp_row_key: Optional[str] = None
        self._append_buffer: list[str] = []

    def compose(self) -> ComposeResult:
        yield self.table
        yield self.editor

    def on_mount(self) -> None:
        for column in self.controller.populate_columns():
            self.table.add_column(column.value, key=column.key)
        for row in self.controller.populate_rows():
            self.table.add_row(*row.values, key=row.key)

    def column_count(self) -> int:
        return len(self.table.columns.values())

    def action_ctrl_e(self) -> None:
        self.machine.send("ctrl_e")

    def action_ctrl_a(self) -> None:
        self.machine.send("ctrl_a")

    def action_ctrl_d(self) -> None:
        ctx = self._get_context()
        if self.controller.request_delete(ctx.row_key):
            self.table.remove_row(ctx.row_key)
            self.table.refresh(layout=True)

    def on_spreadsheet_cell_editor_cell_edited(
        self, event: SpreadsheetCellEditor.CellEdited
    ) -> None:
        if self.machine.current_state == self.machine.editing:
            self._handle_edit_submit(event.value)
        elif self.machine.current_state == self.machine.appending:
            self._handle_append_submit(event.value)

    def on_spreadsheet_cell_editor_cell_edit_aborted(
        self, _: SpreadsheetCellEditor.CellEditAborted
    ) -> None:
        self.machine.send("cancel")

    def _get_context(self) -> CellContext:
        coord = self.table.cursor_coordinate
        columns = list(self.table.columns.values())

        x = sum(
            c.get_render_width(self.table)
            for c in columns[: coord.column]
        ) - self.table.scroll_x

        y = 1 + coord.row - self.table.scroll_y
        width = columns[coord.column].get_render_width(self.table)
        height = 1

        row_key, column_key = self.table.coordinate_to_cell_key(coord)
        value = str(self.table.get_cell(row_key, column_key))

        return CellContext(
            row_key=row_key,
            column_key=column_key,
            geometry=CellGeometry(x, y, width, height),
            current_cell_value=value,
        )

    def start_edit(self) -> None:
        self._active_context = self._get_context()
        self.editor.show_editor(self._active_context)

    def _handle_edit_submit(self, value: str) -> None:
        assert self._active_context is not None
        ok = self.controller.request_edit(
            self._active_context.row_key,
            self._active_context.column_key,
            value,
        )
        if ok:
            self.machine.send("edit_done", value)
        else:
            self.machine.send("cancel")

    def finish_edit(self, value: str) -> None:
        assert self._active_context is not None
        self.table.update_cell(
            self._active_context.row_key,
            self._active_context.column_key,
            value,
        )
        self.table.refresh(layout=True)
        self.editor.hide_editor()
        self._active_context = None

    def start_append(self) -> None:
        self._append_buffer = []
        self._temp_row_key = f"__{uuid.uuid4().hex}__"
        empty_row = [""] * self.column_count()
        self.table.add_row(*empty_row, key=self._temp_row_key)
        self.table.move_cursor(row=self.table.row_count - 1, column=0)
        self._active_context = self._get_context()
        self.editor.show_editor(self._active_context)

    def _handle_append_submit(self, value: str) -> None:
        assert self._temp_row_key is not None
        self._append_buffer.append(value)
        index = len(self._append_buffer) - 1
        self.table.update_cell(
            self._temp_row_key,
            list(self.table.columns.keys())[index],
            value,
        )

        if len(self._append_buffer) >= self.column_count():
            new_key = self.controller.request_add(self._append_buffer)
            if new_key:
                self._temp_row_key = new_key
                self.machine.send("append_done")
            else:
                self.machine.send("cancel")
        else:
            coord = self.table.cursor_coordinate
            self.table.move_cursor(
                row=coord.row,
                column=coord.column + 1,
            )
            self._active_context = self._get_context()
            self.editor.show_editor(self._active_context)

    def finish_append(self) -> None:
        assert self._temp_row_key is not None
        record = self._append_buffer
        temp_key = list(self.table.rows.keys())[-1]
        self.table.remove_row(temp_key)
        self.table.add_row(*record, key=self._temp_row_key)
        self.table.refresh(layout=True)
        self.editor.hide_editor()
        self._append_buffer.clear()
        self._temp_row_key = None
        self._active_context = None

    def abort_current(self) -> None:
        if self.machine.current_state == self.machine.appending and self._temp_row_key:
            self.table.remove_row(self._temp_row_key)
            self.table.refresh(layout=True)
        self.editor.hide_editor()
        self._append_buffer.clear()
        self._temp_row_key = None
        self._active_context = None


class MemoryController:
    def __init__(self) -> None:
        self.rows: dict[str, list[str]] = {
            "101": ["Alice"],
            "102": ["Bob"],
            "103": ["Charlie"],
        }
        self.columns: dict[str, str] = {"name": "Name"}

    def populate_columns(self) -> Iterable[ColumnData]:
        for k, v in self.columns.items():
            yield ColumnData(k, v)

    def populate_rows(self) -> Iterable[RowData]:
        for k, v in self.rows.items():
            yield RowData(k, v)

    def request_add(self, values: Sequence[str]) -> Optional[str]:
        new_key = uuid.uuid4().hex[:8]
        self.rows[new_key] = list(values)
        return new_key

    def request_edit(
        self,
        row_key: str,
        column_key: str,
        new_value: str,
    ) -> bool:
        if row_key in self.rows:
            self.rows[row_key][0] = new_value
            return True
        return False

    def request_delete(self, row_key: str) -> bool:
        if row_key in self.rows:
            del self.rows[row_key]
            return True
        return False


class MemoryController1:
    def __init__(self):
        self.rows = {"101": ["Alice", "sde1"], "102": ["Bob", "sde2"], "103": ["Charlie", "sde2"]}
        self.columns = {"name": "Name", "role": "Role"}

    def populate_columns(self):
        for k, v in self.columns.items():
            yield ColumnData(k, v)

    def populate_rows(self):
        for k, v in self.rows.items():
            yield RowData(k, v)

    def request_add(self, values):
        new = uuid.uuid4().hex[:8]
        self.rows[new] = list(values)
        return new

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
        yield Spreadsheet(MemoryController1())
        yield Footer()


if __name__ == "__main__":
    DemoApp().run()
