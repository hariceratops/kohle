from dataclasses import dataclass
from typing import Protocol, TypeVar, Type, Callable, List, Generic, Dict
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
class SpreadsheetError: pass

@dataclass
class MissingSerdePolicy(SpreadsheetError): pass

@dataclass
class MissingListUseCase(SpreadsheetError): pass

@dataclass
class MissingAddUseCase(SpreadsheetError): pass

@dataclass
class NoEditableColumns(SpreadsheetError):
    def __str__(self) -> str:
        return f"No editable columns mentioned"

@dataclass
class UnknownColumnsRequested(SpreadsheetError):
    columns: List[str]
    operation: str

    def __str__(self) -> str:
        return f"Unknown columns {self.columns} requested for operation {self.operation}"

@dataclass
class EditPolicyBuildOrderConflict(SpreadsheetError):
    first: str
    second: str

    def __str__(self) -> str:
        return f"Operation {self.first} must precede {self.second}"

@dataclass
class MappingFailed(SpreadsheetError):
    reason: str


@dataclass(slots=True)
class EditPolicy:
    key: str
    readonly: bool = False


class EditPolicyBuilder(Generic[T, E]):
    def __init__(self, model_cls: Type[T]) -> None:
        self.model_cls = model_cls
        self._readonly: set[str] = set()
        self._visible: set[str] = set()
        self.error: Option[SpreadsheetError] = Option()

    def serde_policy(self, policy: Policy[T]) -> "EditPolicyBuilder[T, E]":
        self.available_columns = flattened_columns(self.model_cls, policy)
        return self

    def visible(self, columns: List[str]) -> "EditPolicyBuilder[T, E]":
        if not columns:
             self.error = Option.some(Result.err(NoEditableColumns()))
             return self

        if not set(columns).issubset(self.available_columns):
            missing_columns = [x for x in columns if columns not in self.available_columns]
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
            missing_columns = [x for x in columns if columns not in self.available_columns]
            self.error = Option.some(UnknownColumnsRequested(missing_columns, "setting readonly attribute"))
            return self

        self._readonly.update(columns)
        return self

    def build(self) -> Result[list[EditPolicy], E]:
         if self.error.is_some:
             return Result.err(self.error.unwrap())

         policies: List[EditPolicy] = [EditPolicy(column, column in self._readonly) for column in self._visible]
         return Result.ok(policies)
    
    @classmethod
    def for_model(cls, model: Type[T]) -> "EditPolicyBuilder[T, E]":
        return cls(model)


@dataclass
class ArgBind:
    source: str
    dest: str

@dataclass
class UnknownArgument(SpreadsheetError):
    fn_name: str
    argument: str

    def __str__(self) -> str:
        return f"Unknown argument {self.argument} for {self.fn_name}"

@dataclass
class NotAFunction(SpreadsheetError):
    fn_name: str

    def __str__(self) -> str:
        return f"{self.fn_name} is not callable"

@dataclass
class NotAllArgsBound(SpreadsheetError):
    fn_name: str
    unbound_args: List[str]

    def __str__(self) -> str:
        return f"Arguments {self.unbound_args} are unbound for {self.fn_name}"


class UseCase(Generic[E]):
    def __init__(self, fn: Callable) -> None:
        self.fn: Callable = fn
        self.fn_args: List[str] = []
        self.bindings: List[ArgBind] = []
        self.error: Option[SpreadsheetError] = Option()

    def bind(self, source_argument, dest_argument) -> "UseCase":
        if dest_argument not in self.fn_args:
            self.error = Option.some(UnknownArgument(self.fn.__name__, dest_argument))
            return self
        self.bindings.append(ArgBind(source_argument, dest_argument))
        return self
    
    @staticmethod
    def for_use_case(fn: Callable) -> "UseCase":
        instance = UseCase(fn)
        if not inspect.isfunction(instance.fn):
            instance.error = Option.some(NotAFunction(fn.__name__))
        else:
            fn_signature = inspect.signature(fn)
            parameters = fn_signature.parameters.keys()
            instance.fn = fn
            instance.fn_args = [p for p in parameters]
        return instance

    def build(self) -> "Result[UseCase, E]":
        if self.error.is_some:
            return Result.err(self.error.unwrap())
        if not self.fn_args == [b.source for b in self.bindings]:
            missing_columns = [x.source for x in self.bindings if x.source not in self.fn_args]
            return Result.err(NotAllArgsBound(self.fn.__name__, missing_columns))
        return Result.ok(self)

    # todo type annotation
    def invoke(self, record: Record):
        return self.fn()


class SpreadsheetCapabilities(Protocol[E]):
    def populate_columns(self) -> List[dict[str, str]]: ...
    def populate_rows(self) -> Result[list[Record], E]: ...
    def request_add(self, values: Record) -> Result[str, E]: ...
    def request_delete(self, key: str) -> Result[str, E]: ...
    def request_edit(self, row_key: str, column_key: str, value: str) -> Result[str, E]: ...


class SpreadsheetController[E]:
    def __init__(self, capabilities: SpreadsheetCapabilities) -> None:
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
    def __init__(self,
                model_cls: Type[T],
                serde_policy: Policy[T],
                list_use_case: Callable[[UnitOfWork], Result[list[T], E]],
                add_use_case: Callable[[UnitOfWork, T], Result[T, E]]):
        self.model_cls = model_cls
        self.serde_policy = serde_policy
        self.list_use_case = list_use_case
        self.add_use_case = add_use_case


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


    def request_add(self, values: Record) -> Result[str, E]:
        deserialized = \
            FlattenedDeserializer.deserialize(self.model_cls, values, self.serde_policy)

        with UnitOfWork(session_local()) as uow:
            res = self.add_use_case(uow, *values.fields.values())
            if res.is_err:
                return Result.err(res.unwrap_err())
            # todo constraint kohle base to have an integer id of name id
            pk_value = res.unwrap().id
            return Result.ok(pk_value)


    def request_delete(self, key: str) -> Result[str, E]:
        raise NotImplementedError()


    def request_edit(self, record: Record) -> Result[str, E]:
        with UnitOfWork(session_local()) as uow:
            deserialized = PlainDeserializer.deserialize(self.model_cls, record, self.serde_policy) 
        return Result.ok("")


class SpreadsheetCapabilitiesBuilder:
    def __init__(self,  model_cls):
        self.model_cls = model_cls
        self.serde_policy: Option[Policy] = Option()
        self.edit_policies: Option[List[EditPolicy]] = Option()
        self.add_use_case: Option[UseCase] = Option()
        self.list_use_case: Option[UseCase] = Option()
        self.edit_use_case: Dict[str, UseCase] = {}
        self.error: Option[SpreadsheetError] = Option()

    def model(self, model_cls) -> "SpreadsheetCapabilitiesBuilder":
        self.model_cls = model_cls
        return self

    def serde(self, serde_policy: Result[Policy, SpreadsheetError]) -> "SpreadsheetCapabilitiesBuilder":
        if serde_policy.is_err:
           self.error = Option.some(serde_policy.unwrap_err())
           return self
        self.serde_policy = Option.some(serde_policy.unwrap())
        return self

    def editp(self, edit_policies: Result[List[EditPolicy], SpreadsheetError]) -> "SpreadsheetCapabilitiesBuilder":
        if edit_policies.is_err:
            self.error = Option.some(edit_policies.unwrap_err())
            return self
        self.edit_policies = Option.some(edit_policies.unwrap())
        return self

    def lister(self, use_case: UseCase) -> "SpreadsheetCapabilitiesBuilder":
        self.list_use_case = Option.some(use_case)
        return self

    def adder(self, use_case: Result[UseCase, SpreadsheetError]) -> "SpreadsheetCapabilitiesBuilder":
        if use_case.is_err:
            self.error = Option.some(use_case.unwrap_err())
            return self
        self.add_use_case = Option.some(use_case.unwrap())
        return self

    def editor(self, use_case: Result[UseCase, SpreadsheetError]) -> "SpreadsheetCapabilitiesBuilder":
        if use_case.is_err:
            self.error = Option.some(use_case.unwrap_err())
            return self
        self.edit_use_case[""] = use_case.unwrap()
        return self

    def build(self, model_cls) -> Result[SpreadsheetCapabilities, SpreadsheetError]:
        if self.error.is_some:
            return Result.err(self.error.unwrap())

        return Result.ok(ModelSpreadsheetCapabilities(
            model_cls, 
            self.serde_policy.unwrap(), 
            self.list_use_case.unwrap(),
            self.add_use_case.unwrap(),
            # self.edit_use_case.unwrap()
        ))

