from dataclasses import dataclass
import inspect
from typing import Generic, List, Callable, TypeVar, Any
from kohle.core.result import Result
from kohle.core.option import Option
from kohle.infrastructure.model_serde import Record
from kohle.infrastructure.uow import UnitOfWork
from kohle.app.tui.widgets.table_editor.table_editor_build_errors import TableEditorBuildError, NotAllArgsBound


T = TypeVar("T")
E = TypeVar("E")


@dataclass
class AddArgumentBinding:
    source: str
    dest: str


class RowAdder(Generic[E]):
    def __init__(self,
                 fn: Callable[..., Result[Any, E]], 
                 fn_args: List[str], 
                 bindings: List[AddArgumentBinding]
                 ) -> None:
        self.fn = fn
        # todo sort bindings in same order as fn_args and eliminate fn_args
        self.fn_args = fn_args
        self.bindings = bindings

    def invoke(self, uow: UnitOfWork, record: Record) -> Result[Any, E]:
        ordered_args: List[Any] = []

        for arg in self.fn_args:
            match = next((b for b in self.bindings if b.dest == arg), None)
            ordered_args.append(record.fields[match.source])

        return self.fn(uow, *ordered_args)


class RowAdderBuilder:
    def __init__(self) -> None:
        self.fn: Option[Callable] = Option()
        self.fn_args: List[str] = []
        self.bindings: List[AddArgumentBinding] = []
    
    @classmethod
    def for_fn(cls, fn: Callable[..., Result[Any, E]]) -> "RowAdderBuilder":
        instance = cls()
        instance.fn = Option.some(fn)
        sig = inspect.signature(fn)
        instance.fn_args = [p for p in sig.parameters.keys() if p != "uow"]
        return instance

    def bind(self, source: str, dest: str) -> "RowAdderBuilder":
        self.bindings.append(AddArgumentBinding(source, dest))
        return self

    def build(self) -> Result[RowAdder, TableEditorBuildError]:
        bound = [b.dest for b in self.bindings]
        missing = [x for x in self.fn_args if x not in bound]
        if missing:
            return Result.err(NotAllArgsBound(self.fn.unwrap(), missing))
        return Result.ok(RowAdder(self.fn.unwrap(), self.fn_args, self.bindings))

