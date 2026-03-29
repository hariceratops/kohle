from typing import Type, Callable, List, Dict, Any
from kohle.core.result import Result
from kohle.core.option import Option
from kohle.infrastructure.infra_errors import SerializationFailed
from kohle.infrastructure.model_serde import (
    Record, 
    Serializer, 
    RecordFlattener, 
    flattened_columns, 
    SerdePolicy
)
from kohle.infrastructure.uow import UnitOfWork
from kohle.db.connection import session_local
from kohle.app.tui.widgets.table_editor.table_edit_policy import EditPolicy
from kohle.app.tui.widgets.table_editor.row_adder import RowAdder
from kohle.app.tui.widgets.table_editor.column_editor import ColumnEditor
from kohle.app.tui.widgets.table_editor.table_editor_build_errors import TableEditorBuildError

from textual.logging import TextualHandler
import logging
logging.basicConfig(level="NOTSET", handlers=[TextualHandler()])

class TableController[T, E]:
    def __init__(self,
                 model_cls: Type[T],
                 serde_policy: SerdePolicy[T],
                 list_use_case: Callable[[UnitOfWork], Result[list[T], E]],
                 add_use_case: RowAdder,
                 edit_use_case: Dict[str, ColumnEditor]
                ) \
            -> None:
        self.model_cls = model_cls
        self.serde_policy = serde_policy
        self.list_use_case = list_use_case
        self.add_use_case = add_use_case
        self.edit_use_case = edit_use_case

    def populate_columns(self) -> List[dict[str, str]]:
        cols_list = flattened_columns(self.model_cls, self.serde_policy)
        return [{ "key": col for col in cols_list }]

    def populate_rows(self) -> Result[list[Record], E]:
        with UnitOfWork(session_local()) as uow:
            rows = self.list_use_case(uow)
            if rows.is_err:
                return Result.err(rows)
            serialized = [Serializer.serialize(t, self.serde_policy) for t in rows.unwrap()]
            if any(x is None for x in serialized):
                return Result.err(SerializationFailed)
            return Result.ok([RecordFlattener.flatten(s) for s in serialized])

    def request_add(self, record: Record) -> Result[str, E]:
        with UnitOfWork(session_local()) as uow:
            res = self.add_use_case.invoke(uow, record)
            if res.is_err:
                return Result.err(res.unwrap_err())
            # todo constraint kohle base to have an integer id of name id
            pk_value = res.unwrap().id
            return Result.ok(str(pk_value))

    def request_delete(self, _: str) -> Result[str, E]:
        raise NotImplementedError()

    def request_edit(self, row_key: str, column_key: str, value: str) -> Result[str, E]:
        with UnitOfWork(session_local()) as uow:
            res = self.edit_use_case[column_key].invoke(uow, row_key, value)
            if res.is_err:
                return Result.err(res.unwrap_err())
            # todo better return value
            return Result.ok(row_key)


class TableControllerBuilder:
    def __init__(self, model_cls: Type[Any]):
        # todo check model class absence
        self.model_cls = model_cls
        self.serde_policy: Option[SerdePolicy] = Option()
        self.edit_policies: Option[List[EditPolicy]] = Option()
        self.row_adder: Option[RowAdder] = Option()
        self.list_use_case: Option[Callable] = Option()
        self.column_editors: Dict[str, ColumnEditor] = {}
        self.error: Option[TableEditorBuildError] = Option()

    def absorb(self, result, attribute: str):
        if self.error.is_some:
            return self
        if result.is_err:
            self.error = Option.some(result.unwrap_err())
            return self
        if getattr(self, attribute).is_some:
            # pass multiple set error
            pass
        setattr(self, attribute, Option.some(result.unwrap()))
        return self
    
    @classmethod
    def for_model(cls, model_cls: Type[Any]) -> "TableControllerBuilder":
        return cls(model_cls)

    def serde(self, serde_policy: Result[SerdePolicy, TableEditorBuildError]) \
            -> "TableControllerBuilder":
        return self.absorb(serde_policy, "serde_policy")

    def edit_policy(self, edit_policies: Result[List[EditPolicy], TableEditorBuildError]) \
            -> "TableControllerBuilder":
        return self.absorb(edit_policies, "edit_policies")

    def lister(self, use_case: Callable[[UnitOfWork], Result[List[Any], TableEditorBuildError]]) \
            -> "TableControllerBuilder":
        if self.list_use_case.is_some:
            # todo error
            pass
        self.list_use_case = Option.some(use_case)
        return self

    def adder(self, use_case: Result[RowAdder, TableEditorBuildError]) \
            -> "TableControllerBuilder":
        return self.absorb(use_case, "row_adder")

    def editor(self, column: str, use_case: Result[ColumnEditor, TableEditorBuildError]) \
            -> "TableControllerBuilder":
        if use_case.is_err:
            self.error = Option.some(use_case.unwrap_err())
            return self
        self.column_editors[column] = use_case.unwrap()
        return self

    def build(self) -> Result[TableController, TableEditorBuildError]:
        if self.error.is_some:
            return Result.err(self.error.unwrap())
        return Result.ok(
            TableController(
                self.model_cls,
                self.serde_policy.unwrap(),
                self.list_use_case.unwrap(),
                self.row_adder.unwrap(),
                self.column_editors
            )
        )

