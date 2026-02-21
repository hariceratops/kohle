from textual.app import App, ComposeResult
import uuid
from textual.containers import Container
from textual.widgets import DataTable
from textual.widgets import Input
from textual.binding import Binding
from textual.widgets import Header, Footer
from textual.containers import Container
from textual.message import Message
from statemachine import StateMachine, State
from dataclasses import dataclass
from typing import Protocol, Iterable, Sequence, Optional
import logging
from textual.logging import TextualHandler

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
    def request_add(self, values: Sequence[str]) -> str | None: ...
    def request_edit(self, row_key: str, column_key: str, new_value: str) -> bool: ...
    def request_delete(self, row_key: str) -> bool: ...


class SpreadsheetStateMachine(StateMachine):
    navigation = State("navigation", initial=True)
    edit = State("edit")
    edit_commit = State("edit_commit")
    delete = State("delete")
    append = State("append")
    new_row_commit = State("new_row_commit")

    cursor_movement = navigation.to.itself()
    ctrl_e = navigation.to(edit)
    ctrl_d = navigation.to(delete)
    ctrl_a = navigation.to(append)
    cell_submitted = edit.to(edit_commit) | append.to.itself()
    cell_edit_aborted = edit.to(navigation) | append.to(navigation)
    edit_commit_approved = edit_commit.to(navigation)
    edit_commit_rejected = edit_commit.to(navigation)
    delete_approved = delete.to(navigation)
    delete_rejected = delete.to(navigation)
    append_next = append.to.itself()
    append_finished = append.to(new_row_commit)
    new_row_commit_approved = new_row_commit.to(navigation)
    new_row_commit_rejected = new_row_commit.to(navigation)

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.append_index = 0

    def on_ctrl_e(self):
        self.owner.start_edit()

    def on_ctrl_d(self):
        self.owner.start_delete()

    def on_ctrl_a(self):
        self.append_index = 0
        self.owner.start_append()

    def on_cell_submitted(self, value):
        if self.current_state == self.edit:
            self.owner.request_edit_commit(value)

        elif self.current_state == self.append:
            self.owner.update_append_value(self.append_index, value)
            self.append_index += 1
            if self.append_index >= self.owner.column_count():
                self.send("append_finished")
                self.owner.request_new_row_commit()
            else:
                self.owner.focus_next_column()
                self.send("append_next")

    def on_cell_edit_aborted(self):
        if self.current_state == self.edit:
            self.owner.abort_edit()
        elif self.current_state == self.append:
            self.owner.abort_append()

    def on_edit_commit_approved(self, value):
        self.owner.finish_edit(value)

    def on_edit_commit_rejected(self):
        self.owner.abort_edit()

    def on_delete_approved(self):
        self.owner.delete_row()

    def on_delete_rejected(self):
        self.owner.abort_delete()

    def on_new_row_commit_approved(self, record, key):
        self.owner.finish_append(record, key)

    def on_new_row_commit_rejected(self):
        self.owner.abort_append()


class SpreadsheetCellEditor(Input):
    class CellEditStart(Message):
        def __init__(self, context: CellContext):
            super().__init__()
            self.context = context

    class CellEdited(Message):
        def __init__(self, value: str):
            super().__init__()
            self.value = value

    class CellEditAborted(Message):
        pass

    def show(self, context):
        geometry = context.geometry
        self.styles.offset = (geometry.x, geometry.y)
        self.styles.width = geometry.width
        self.styles.height = geometry.height
        self.styles.border = "none"
        self.styles.layer = "above"
        self.styles.display = "block"
        self.value = context.current_cell_value
        self.focus()

    def stop(self):
        self.styles.display = "none"

    def on_input_submitted(self, event):
        self.post_message(self.CellEdited(event.value))

    def on_key(self, event):
        if event.key == "escape":
            self.post_message(self.CellEditAborted())


class Spreadsheet(Container):
    BINDINGS = [
        Binding("ctrl+e", "ctrl_e"),
        Binding("ctrl+a", "ctrl_a"),
        Binding("ctrl+d", "ctrl_d"),
    ]

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.table = DataTable()
        self.editor = SpreadsheetCellEditor()
        self.machine = SpreadsheetStateMachine(self)
        self.context: Optional[CellContext] = None
        self._temp_row_key = ""

    def compose(self):
        yield self.table
        yield self.editor

    def on_mount(self):
        for column in self.controller.populate_columns():
            self.table.add_column(column.value, key=column.key)
        for row in self.controller.populate_rows():
            self.table.add_row(*row.values, key=row.key)

    def column_count(self):
        return len(self.table.columns.values())

    def action_ctrl_e(self):
        self.machine.send("ctrl_e")

    def action_ctrl_a(self):
        self.machine.send("ctrl_a")

    def action_ctrl_d(self):
        self.machine.send("ctrl_d")

    def on_spreadsheet_cell_editor_cell_edited(self, event: SpreadsheetCellEditor.CellEdited):
        self.machine.send("cell_submitted", event.value)

    def on_spreadsheet_cell_editor_cell_edit_aborted(self, _: SpreadsheetCellEditor.CellEditAborted):
        self.machine.send("cell_edit_aborted")

    def get_context(self) -> CellContext:
        coordinates = self.table.cursor_coordinate
        columns = list(self.table.columns.values())
        # skip header + rows and offset the scrolling
        x = sum(c.get_render_width(self.table) for c in columns[:coordinates.column]) - self.table.scroll_x
        y = 1 + coordinates.row - self.table.scroll_y
        width = columns[coordinates.column].get_render_width(self.table)
        # todo get actual height
        height = 1
        row_key, column_key = self.table.coordinate_to_cell_key(self.table.cursor_coordinate)
        current_cell_value = str(self.table.get_cell(row_key, column_key))
        current_cell_geometry = CellGeometry(x=x, y=y, width=width, height=height)
        return CellContext(row_key, column_key, current_cell_geometry, current_cell_value)

    def start_edit(self):
        # todo idiomatic monadic operation for optional
        ctx = self.get_context()
        self.editor.show(ctx)

    def request_edit_commit(self, value):
        ctx = self.get_context()
        ok = self.controller.request_edit(ctx.row_key, ctx.column_key, value)
        if ok:
            self.machine.send("edit_commit_approved", value)
        else:
            self.machine.send("edit_commit_rejected")

    def finish_edit(self, value):
        ctx = self.get_context()
        self.table.update_cell(ctx.row_key, ctx.column_key, value)
        self.table.refresh(layout=True)
        self.editor.stop()

    def abort_edit(self):
        self.editor.stop()

    def start_delete(self):
        ctx = self.get_context()
        ok = self.controller.request_delete(ctx.row_key)
        if ok:
            self.machine.send("delete_approved")
        else:
            self.machine.send("delete_rejected")

    def delete_row(self):
        ctx = self.get_context()
        self.table.remove_row(ctx.row_key)

    def abort_delete(self):
        pass

    def start_append(self):
        self._temp_row_key = f"__{uuid.uuid4().hex}__"
        empty_row = [""] * len(self.table.columns)
        self.table.add_row(*empty_row, key=self._temp_row_key)
        self.table.move_cursor(row=self.table.row_count - 1, column=0)
        self.editor.show(self.get_context())

    def update_append_value(self, index, value):
        ctx = self.get_context()
        self.table.update_cell(ctx.row_key, ctx.column_key, value)

    def focus_next_column(self):
        coordinates = self.table.cursor_coordinate
        self.table.move_cursor(row=coordinates.row, column=coordinates.column + 1)
        self.editor.show(self.get_context())

    def request_new_row_commit(self):
        # possible bug
        coordinates = self.table.cursor_coordinate
        record = self.table.get_row_at(coordinates.row)
        ok = self.controller.request_add(record)
        if ok:
            self.machine.send("new_row_commit_approved", record, ok)
        else:
            self.machine.send("new_row_commit_rejected")

    def finish_append(self, record, ok):
        self.editor.stop()
        self.table.remove_row(self._temp_row_key)
        self.table.add_row(*record, key=ok)
        self.table.refresh(layout=True)
        self.table.move_cursor(row=self.table.row_count - 1, column=0)

    def abort_append(self):
        self.editor.stop()
        self.table.remove_row(self._temp_row_key)
        self.table.refresh(layout=True)
        self.table.move_cursor(row=self.table.row_count - 1, column=0)


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
