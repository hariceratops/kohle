import inspect
from typing import Generic, Callable, TypeVar, Any
from kohle.core.result import Result
from kohle.core.option import Option
from kohle.infrastructure.uow import UnitOfWork
from kohle.app.tui.widgets.table_editor.table_editor_errors import TableEditorBuildError


T = TypeVar("T")
E = TypeVar("E")


class ColumnEditor(Generic[E]):
    def __init__(self, fn: Callable[..., Result[Any, E]], row_id: str, dest: str) -> None:
        self.fn = fn
        self.row_id = row_id
        self.dest: str = dest

    def invoke(self, uow: UnitOfWork, row_key: str, value: Any) -> Result[Any, E]:
        return self.fn(uow, **{ self.row_id: row_key, self.dest: value })


class ColumnEditorBuilder:
    def __init__(self) -> None:
        self.fn: Option[Callable] = Option()
        self.row_id: Option[str] = Option()
        self.source: Option[str] = Option()
        self.dest: Option[str] = Option()

    def for_fn(self, fn: Callable[..., Result[Any, E]]) -> "ColumnEditorBuilder":
        self.fn = Option.some(fn)
        sig = inspect.signature(fn)
        self.fn_args = [p for p in sig.parameters.keys() if p != "uow"]
        return self
    
    def key(self, row_key) -> "ColumnEditorBuilder":
        if self.row_id.is_some:
            # todo error multiple key overwrite
            pass
        if not row_key:
            # todo empty row_key
            pass
        if row_key not in self.fn_args:
            # todo bind failure
            pass
        self.key = row_key
        return self

    def bind(self, source: str, dest: str) -> "ColumnEditorBuilder":
        if self.source.is_some or self.dest.is_some:
            # todo error multiple key overwrite
            pass
        if not self.source or not self.dest:
            # todo empty source or dest
            pass
        if dest not in self.fn_args:
            # todo bind failure
            pass
        self.source = Option.some(source)
        self.dest = Option.some(dest)
        return self

    def build(self) -> Result[ColumnEditor, TableEditorBuildError]:
        fn = self.fn.unwrap()
        row_id = self.row_id.unwrap()
        dest = self.dest.unwrap()
        return Result.ok(ColumnEditor(fn, row_id, dest))

