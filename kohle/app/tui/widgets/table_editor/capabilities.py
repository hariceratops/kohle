from dataclasses import dataclass
from typing import Protocol, TypeVar, Type, Callable, List, Generic, Dict, Any
import inspect
from kohle.core.result import Result
from kohle.core.option import Option
from kohle.infrastructure.infra_errors import SerializationFailed
from kohle.infrastructure.model_serde import PlainDeserializer, Record, Serializer, RecordFlattener, FlattenedDeserializer, flattened_columns, Policy
from kohle.infrastructure.uow import UnitOfWork
from kohle.db.connection import session_local


T = TypeVar("T")
E = TypeVar("E")


@dataclass
class TableEditorError: pass

@dataclass
class MultipleSerdePolicy(TableEditorError): pass

@dataclass
class MultipleEditPolicy(TableEditorError): pass

@dataclass
class MultipleListUseCase(TableEditorError): pass

@dataclass
class MultipleAddUseCase(TableEditorError): pass

@dataclass
class NoEditableColumns(TableEditorError):
    def __str__(self) -> str:
        return f"No editable columns mentioned"

@dataclass
class UnknownColumnsRequested(TableEditorError):
    columns: List[str]
    operation: str

    def __str__(self) -> str:
        return f"Unknown columns {self.columns} requested for operation {self.operation}"

@dataclass
class EditPolicyBuildOrderConflict(TableEditorError):
    first: str
    second: str

    def __str__(self) -> str:
        return f"Operation {self.first} must precede {self.second}"


class ResultBuilder:
    def __init__(self) -> None:
        self.error: Option[TableEditorError] = Option()

    def absorb(self, result: Result[Any, TableEditorError], setter: Callable[[Any], None]):
        if self.error.is_some:
            return self
        if result.is_err:
            self.error = Option.some(result.unwrap_err())
            return self
        setter(result.unwrap())
        return self


@dataclass(slots=True)
class EditPolicy:
    key: str
    readonly: bool = False


class EditPolicyBuilder(Generic[T, E]):
    def __init__(self, model_cls: Type[T]) -> None:
        self.model_cls = model_cls
        self._readonly: set[str] = set()
        self._visible: set[str] = set()
        self.available_columns: List[str] = []

    def serde_policy(self, policy: Policy[T]) -> "EditPolicyBuilder[T, E]":
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

    def build(self) -> Result[List[EditPolicy], TableEditorError]:
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


@dataclass
class UnknownArgument(TableEditorError):
    fn: Callable
    argument: str

    def __str__(self) -> str:
        return f"Unknown argument {self.argument} for {self.fn.__name__}"

@dataclass
class NotAFunction(TableEditorError):
    fn: Callable

    def __str__(self) -> str:
        return f"{self.fn.__name__} is not callable"

@dataclass
class NotAllArgsBound(TableEditorError):
    fn: Callable
    unbound_args: List[str]

    def __str__(self) -> str:
        return f"Arguments {self.unbound_args} are unbound for {self.fn.__name__}"

@dataclass
class MappingFailed(TableEditorError):
    src: str
    dst: str

    def __str__(self) -> str:
        return f"{self.src} is not bound to {self.dst}"


@dataclass
class AddArgumentBinding:
    source: str
    dest: str


class AddUseCase(Generic[E]):
    def __init__(self, fn: Callable[..., Result[Any, E]]) -> None:
        self.fn = fn
        self.fn_args: List[str] = []
        self.bindings: List[AddArgumentBinding] = []

    @staticmethod
    def for_fn(fn: Callable[..., Result[Any, E]]) -> "AddUseCase[E]":
        instance = AddUseCase(fn)
        sig = inspect.signature(fn)
        instance.fn_args = [p for p in sig.parameters.keys() if p != "uow"]
        return instance

    def bind(self, source: str, dest: str) -> "AddUseCase[E]":
        self.bindings.append(AddArgumentBinding(source, dest))
        return self

    def build(self) -> Result["AddUseCase[E]", TableEditorError]:
        bound = [b.dest for b in self.bindings]
        missing = [x for x in self.fn_args if x not in bound]
        if missing:
            return Result.err(NotAllArgsBound(self.fn, missing))
        return Result.ok(self)

    def invoke(self, uow: UnitOfWork, record: Record) -> Result[Any, E]:
        ordered_args: List[Any] = []

        for arg in self.fn_args:
            match = next((b for b in self.bindings if b.dest == arg), None)
            if not record.fields:
                return Result.err(MappingFailed(f"{arg} missing"))
            if match is None or match.source not in record.fields:
                return Result.err(MappingFailed(f"{arg} missing"))
            ordered_args.append(record.fields[match.source])

        return self.fn(uow, *ordered_args)


@dataclass
class EditArgumentBinding:
    value_source: str
    dest: str
    id_dest: str


class EditUseCase(Generic[E]):
    def __init__(self, fn: Callable[..., Result[Any, E]]) -> None:
        self.fn = fn
        self.value_source: str = ""
        self.dest: str = ""
        self.id_dest: str = ""

    @staticmethod
    def for_fn(fn: Callable[..., Result[Any, E]]) -> "EditUseCase[E]":
        return EditUseCase(fn)

    def bind(self, value_source: str, dest: str, id_dest: str) -> "EditUseCase[E]":
        self.value_source = value_source
        self.dest = dest
        self.id_dest = id_dest
        return self

    def build(self) -> Result["EditUseCase[E]", TableEditorError]:
        if not self.value_source or not self.dest or not self.id_dest:
            return Result.err(MappingFailed(self.value_source, self.dest))
        return Result.ok(self)
    
    def invoke(self, uow: UnitOfWork, row_key: str, value: Any) -> Result[Any, E]:
        return self.fn(
            uow,
            **{
                self.id_dest: row_key,
                self.dest: value
            }
        )

class TableEditorProtocol(Protocol[E]):
    def populate_columns(self) -> List[dict[str, str]]: ...
    def populate_rows(self) -> Result[list[Record], E]: ...
    def request_add(self, values: Record) -> Result[str, E]: ...
    def request_delete(self, key: str) -> Result[str, E]: ...
    def request_edit(self, row_key: str, column_key: str, value: str) -> Result[str, E]: ...


class SpreadsheetController[E]:
    def __init__(self, capabilities: TableEditorProtocol) -> None:
        self.capabilities = capabilities
    def populate_columns(self) -> List[dict[str, str]]:
        return self.capabilities.populate_columns()
    def populate_rows(self) -> Result[list[Record], E]:
        return self.capabilities.populate_rows()
    def request_add(self, values: Record) -> Result[str, E]:
        return self.capabilities.request_add(values)
    def request_delete(self, key: str) -> Result[str, E]:
        return self.capabilities.request_delete(key)
    def request_edit(self, row_key: str, column_key: str, value: str) -> Result[str, E]:
        return self.capabilities.request_edit(row_key, column_key, value)


class ModelSpreadsheetCapabilities[T, E]:
    def __init__(
        self,
        model_cls: Type[T],
        serde_policy: Policy[T],
        list_use_case: Callable[[UnitOfWork], Result[list[T], E]],
        add_use_case: AddUseCase,
        edit_use_case: Dict[str, EditUseCase]
    ) -> None:
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
            return Result.ok(pk_value)

    def request_delete(self, key: str) -> Result[str, E]:
        raise NotImplementedError()

    def request_edit(self, row_key: str, column_key: str, value: str) -> Result[str, E]:
        with UnitOfWork(session_local()) as uow:
            res = self.edit_use_case[column_key].invoke(uow, row_key, value)
            if res.is_err:
                return Result.err(res.unwrap_err())
            # todo better return value
            return Result.ok(row_key)

@dataclass
class MissingSerdePolicy(TableEditorError): pass

@dataclass
class MissingAddUseCase(TableEditorError): pass

@dataclass
class MissingListUseCase(TableEditorError): pass


class SpreadsheetCapabilitiesBuilder(ResultBuilder):
    def __init__(self, model_cls: Type[Any]):
        super().__init__()
        self.model_cls = model_cls
        self.serde_policy: Option[Policy] = Option()
        self.edit_policies: Option[List[EditPolicy]] = Option()
        self.add_use_case: Option[AddUseCase] = Option()
        self.list_use_case: Option[Callable] = Option()
        self.edit_use_cases: Dict[str, EditUseCase] = {}

    def model(self, model_cls: Type[Any]) -> "SpreadsheetCapabilitiesBuilder":
        self.model_cls = model_cls
        return self

    def serde(self, serde_policy: Result[Policy, TableEditorError]) \
            -> "SpreadsheetCapabilitiesBuilder":
        return self.absorb(
            serde_policy,
            lambda v: setattr(self, "serde_policy", Option.some(v))
        )

    def edit_policy(self, edit_policies: Result[List[EditPolicy], TableEditorError]) \
            -> "SpreadsheetCapabilitiesBuilder":
        return self.absorb(
            edit_policies,
            lambda v: setattr(self, "edit_policies", Option.some(v))
        )

    def lister(self, use_case: Callable[[UnitOfWork], Result[List[Any], E]]) \
            -> "SpreadsheetCapabilitiesBuilder":
        self.list_use_case = Option.some(use_case)
        return self

    def adder(self, use_case: Result[AddUseCase, TableEditorError]) \
            -> "SpreadsheetCapabilitiesBuilder":
        return self.absorb(
            use_case,
            lambda v: setattr(self, "add_use_case", Option.some(v))
        )

    def editor(self, column: str, use_case: Result[EditUseCase, TableEditorError]) \
            -> "SpreadsheetCapabilitiesBuilder":
        if use_case.is_err:
            self.error = Option.some(use_case.unwrap_err())
            return self
        self.edit_use_cases[column] = use_case.unwrap()
        return self

    def build(self) -> Result[TableEditorProtocol, TableEditorError]:
        if self.error.is_some:
            return Result.err(self.error.unwrap())
        if self.serde_policy.is_none:
            return Result.err(MissingSerdePolicy())
        if self.list_use_case.is_none:
            return Result.err(MissingListUseCase())
        if self.add_use_case.is_none:
            return Result.err(MissingAddUseCase())
        return Result.ok(
            ModelSpreadsheetCapabilities(
                self.model_cls,
                self.serde_policy.unwrap(),
                self.list_use_case.unwrap(),
                self.add_use_case.unwrap(),
                self.edit_use_cases
            )
        )

