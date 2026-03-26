
from dataclasses import dataclass
from typing import TypeVar, Callable, List

T = TypeVar("T")
E = TypeVar("E")


@dataclass
class TableEditorBuildError(Exception): pass


@dataclass
class MultipleSerdePolicy(TableEditorBuildError): pass


@dataclass
class MultipleEditPolicy(TableEditorBuildError): pass


@dataclass
class MultipleListUseCase(TableEditorBuildError): pass


@dataclass
class MultipleAddUseCase(TableEditorBuildError): pass


@dataclass
class NoEditableColumns(TableEditorBuildError):
    def __str__(self) -> str:
        return f"No editable columns mentioned"


@dataclass
class UnknownColumnsRequested(TableEditorBuildError):
    columns: List[str]
    operation: str

    def __str__(self) -> str:
        return f"Unknown columns {self.columns} requested for operation {self.operation}"


@dataclass
class EditPolicyBuildOrderConflict(TableEditorBuildError):
    first: str
    second: str

    def __str__(self) -> str:
        return f"Operation {self.first} must precede {self.second}"


@dataclass
class UnknownArgument(TableEditorBuildError):
    fn: Callable
    argument: str

    def __str__(self) -> str:
        return f"Attempt to bind unknown argument {self.argument} for {self.fn.__name__}"


@dataclass
class NotAFunction(TableEditorBuildError):
    fn: Callable

    def __str__(self) -> str:
        return f"{self.fn.__name__} is not callable"


@dataclass
class NotAllArgsBound(TableEditorBuildError):
    fn: Callable
    unbound_args: List[str]

    def __str__(self) -> str:
        return f"Arguments {self.unbound_args} are unbound for {self.fn.__name__}"


@dataclass
class MappingFailed(TableEditorBuildError):
    src: str
    dst: str

    def __str__(self) -> str:
        return f"{self.src} is not bound to {self.dst}"


@dataclass
class MissingSerdePolicy(TableEditorBuildError): pass

@dataclass
class MissingAddUseCase(TableEditorBuildError): pass

@dataclass
class MissingListUseCase(TableEditorBuildError): pass


