from dataclasses import dataclass
from typing import TypeVar, Type, List, Generic
from kohle.core.result import Result
from kohle.core.option import Option
from kohle.infrastructure.model_serde import SerdePolicy, flattened_columns
from kohle.app.tui.widgets.table_editor.table_editor_errors import (
    TableEditorBuildError,
    UnknownColumnsRequested,
    NoEditableColumns,
    EditPolicyBuildOrderConflict
)


T = TypeVar("T")
E = TypeVar("E")


@dataclass(slots=True)
class EditPolicy:
    key: str
    readonly: bool = False


class EditPolicyBuilder(Generic[T, E]):
    def __init__(self, model_cls: Type[T]) -> None:
        #todo check absence of model_cls
        self.model_cls = model_cls
        self._readonly: set[str] = set()
        self._visible: set[str] = set()
        self.available_columns: List[str] = []
        self.error: Option[TableEditorBuildError] = Option()

    # todo must take a result
    def serde_policy(self, policy: SerdePolicy[T]) -> "EditPolicyBuilder[T, E]":
        self.available_columns = flattened_columns(self.model_cls, policy)
        return self

    def visible(self, columns: List[str]) -> "EditPolicyBuilder[T, E]":
        if not columns:
            self.error = Option.some(NoEditableColumns())
            return self
        if not set(columns).issubset(self.available_columns):
            missing_columns = [x for x in columns if x not in self.available_columns]
            self.error = Option.some(UnknownColumnsRequested(missing_columns, "setting visibility"))
            return self
        self._visible.update(columns)
        return self
    
    def readonly(self, columns: List[str]) -> "EditPolicyBuilder[T, E]":
        if not self._visible:
            self.error = Option.some(EditPolicyBuildOrderConflict("visible", "readonly"))
            return self
        if self.error.is_some:
            return self
        if not set(columns).issubset(self.available_columns):
            missing_columns = [x for x in columns if x not in self.available_columns]
            self.error = Option.some(UnknownColumnsRequested(missing_columns, "setting readonly attribute"))
            return self
        self._readonly.update(columns)
        return self

    def build(self) -> Result[List[EditPolicy], TableEditorBuildError]:
        if self.error.is_some:
            return Result.err(self.error.unwrap())
        policies: List[EditPolicy] = [
            EditPolicy(column, column in self._readonly) 
            for column in self._visible
        ]
        return Result.ok(policies)

    @classmethod
    def for_model(cls, model: Type[T]) -> "EditPolicyBuilder[T, E]":
        return cls(model)


