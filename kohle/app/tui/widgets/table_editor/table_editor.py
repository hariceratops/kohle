from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional
import logging

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Input, Header, Footer
from textual.binding import Binding
from textual.message import Message
from statemachine import StateMachine, State

from kohle.app.tui.widgets.table_editor.row_adder import RowAdder, RowAdderBuilder
from kohle.app.tui.widgets.table_editor.table_controller import TableControllerBuilder
from kohle.app.tui.widgets.table_editor.table_edit_policy import EditPolicyBuilder
from kohle.core.result import Result
from kohle.infrastructure.model_serde import Record, SerdePolicy
from kohle.app.tui.widgets.table_editor.table_controller import TableControllerBuilder, TableController
from kohle.domain.models import DebitCategory
from kohle.use_cases.debit_categories import add_debit_category, list_debit_categories
from textual.logging import TextualHandler

logging.basicConfig(level="NOTSET", handlers=[TextualHandler()])


@dataclass(slots=True)
class CellGeometry:
    x: float
    y: float
    width: int
    height: int


@dataclass(slots=True)
class CellContext:
    geometry: CellGeometry
    value: str


class TableCellEditor(Input):
    class CellEdited(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    class CellEditCancelled(Message):
        pass

    def show(self, context: CellContext) -> None:
        g = context.geometry
        self.styles.offset = (int(g.x), int(g.y))
        self.styles.width = g.width
        self.styles.height = g.height
        self.styles.display = "block"
        self.styles.layer = "above"
        self.styles.border = "none"
        self.value = context.value
        self.focus()

    def hide(self) -> None:
        self.styles.display = "none"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.post_message(self.CellEdited(event.value))

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.post_message(self.CellEditCancelled())


class TableEditorStateMachine(StateMachine):
    navigation = State("navigation", initial=True)
    editing = State("editing")
    appending = State("appending")

    ctrl_e = navigation.to(editing)
    ctrl_a = navigation.to(appending)
    cancel = editing.to(navigation) | appending.to(navigation)
    submit_edit = editing.to(navigation)
    submit_append = appending.to(navigation)
    submit_one = appending.to.itself()

    def __init__(self, owner: TableEditor) -> None:
        super().__init__()
        self.owner = owner

    def on_ctrl_e(self) -> None:
        self.owner.start_edit()

    def on_ctrl_a(self) -> None:
        self.owner.start_append()

    def on_submit_edit(self, value: str) -> None:
        self.owner.commit_edit(value)

    def on_submit_one(self, value: str) -> None:
        self.owner.handle_append(value)
    def on_submit_append(self, value: str) -> None:
        self.owner.handle_append(value)

    def on_cancel(self) -> None:
        self.owner.abort_current()


# todo handle primary key readonly
# todo handle foreign key
# todo collect value as string dictionary
# todo pass around temp key
# todo remove uow from ui
class TableEditor(Container):
    BINDINGS = [
        Binding("ctrl+e", "ctrl_e"),
        Binding("ctrl+a", "ctrl_a"),
        Binding("ctrl+d", "ctrl_d"),
    ]

    def __init__(self, controller: TableController) -> None:
        super().__init__()
        self.controller = controller
        self.table = DataTable()
        self.editor = TableCellEditor()
        self.machine = TableEditorStateMachine(self)
        self.ctx: Optional[CellContext] = None
        self._temp_record: Record = Record(f"{uuid.uuid4().hex}", {})

    def compose(self) -> ComposeResult:
        yield self.table
        yield self.editor

    def on_mount(self) -> None:
        for column in self.controller.populate_columns():
            self.table.add_column(column["key"], key=str(column["key"]))

        result = self.controller.populate_rows()
        if result.is_ok:
            for row in result.unwrap():
                fields = row.fields if row.fields else {}
                self.table.add_row(*fields.values(), key=row.id)

    def action_ctrl_e(self) -> None:
        self.machine.send("ctrl_e")

    def action_ctrl_a(self) -> None:
        self.machine.send("ctrl_a")

    def action_ctrl_d(self) -> None:
        row_key, _ = self.to_table_key()
        res = self.controller.request_delete(row_key)
        if res.is_ok:
            self.table.remove_row(row_key)

    def on_table_cell_editor_cell_edited(self, event: TableCellEditor.CellEdited) -> None:
        if self.machine.current_state == self.machine.editing:
            self.machine.send("submit_edit", event.value)
        else:
            _, col_key = self.to_table_key()
            self._temp_record[col_key] = event.value
            if len(self._temp_record) >= self.column_count():
                self.machine.send("submit_append", event.value)
            else:
                self.machine.send("submit_one", event.value)

    def on_table_cell_editor_cell_edit_cancelled(self, _: TableCellEditor.CellEditCancelled) -> None:
        self.machine.send("cancel")

    def start_edit(self) -> None:
        self.ctx = self._get_context()
        self.editor.show(self.ctx)

    def commit_edit(self, value: str) -> None:
        row_key, column_key = self.to_table_key()
        result = self.controller.request_edit(row_key, column_key, value)
        if result.is_ok:
            self.table.update_cell(row_key, column_key, value)
        else:
            result.unwrap()
        self.editor.hide()

    def _reset_temp_record(self) -> None:
        self._temp_record.id = f"{uuid.uuid4().hex}"
        self._temp_record.fields = {}

    def start_append(self) -> None:
        self.table.add_row(*self._temp_record.fields.values(), key=self._temp_record.id)
        self.table.move_cursor(row=self.table.row_count - 1, column=0)
        self.ctx = self._get_context()
        self.editor.show(self.ctx)

    def handle_append(self, value: str) -> None:
        row_key, column_key = self.to_table_key()
        self.table.update_cell(row_key, column_key, value)

        if len(self._temp_record) >= self.column_count():
            result = self.controller.request_add(self._temp_record)
            if result.is_ok:
                self.table.remove_row(self._temp_record.id)
                self.table.add_row(*self._temp_record.fields.values(), key=result.unwrap())
                self.table.move_cursor(row=self.table.row_count - 1, column=0)
                self._reset_temp_record()
            else:
                result.unwrap()
            self.editor.hide()
        else:
            self._move_next_column()

    def abort_current(self) -> None:
        self.editor.hide()
        # todo make it only for appending mode
        self._reset_temp_record()

    def column_count(self) -> int:
        return len(self.table.columns)

    def _move_next_column(self) -> None:
        coord = self.table.cursor_coordinate
        self.table.move_cursor(row=coord.row, column=coord.column + 1)
        self.ctx = self._get_context()
        self.editor.show(self.ctx)

    def to_table_key(self) -> tuple[str, str]:
        coord = self.table.cursor_coordinate
        row_key, column_key = self.table.coordinate_to_cell_key(coord)
        return row_key.value, column_key.value

    def _get_context(self) -> CellContext:
        coord = self.table.cursor_coordinate
        columns = list(self.table.columns.values())
        x = sum(c.get_render_width(self.table) for c in columns[:coord.column]) - self.table.scroll_x
        y = 1 + coord.row - self.table.scroll_y
        width = columns[coord.column].get_render_width(self.table)
        row_key, column_key = self.to_table_key()
        value = str(self.table.get_cell(row_key, column_key))
        return CellContext(geometry=CellGeometry(x, y, width, 1), value=value)



class DemoApp(App):
    def compose(self) -> ComposeResult:
        serde_policy = (
            SerdePolicy
            .for_model(DebitCategory)
            .only("category")
            .build()
        )
        edit_policy =  (
            EditPolicyBuilder
            .for_model(DebitCategory)
            .serde_policy(serde_policy.unwrap()) # todo avoid unwrap
            .visible(["category"])
            .build()
        )
        add_use_case = (
            RowAdderBuilder
            .for_fn(add_debit_category)
            .bind("category", "name")
            .build()
        )
        table_controller = (
            TableControllerBuilder
            .for_model(DebitCategory)
            .serde(serde_policy)
            .edit_policy(edit_policy)
            .lister(list_debit_categories)
            .adder(add_use_case)
            .build()
        )

        yield Header()
        yield TableEditor(table_controller.unwrap())
        yield Footer()


if __name__ == "__main__":
    DemoApp().run()

