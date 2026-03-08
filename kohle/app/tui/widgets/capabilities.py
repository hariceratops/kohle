from typing import Protocol, TypeVar, Type, Callable, List
from kohle.core.result import Result
from kohle.infrastructure.infra_errors import SerializationFailed
from kohle.infrastructure.model_serde import Record, Serializer, RecordFlattener, FlattenedDeserializer, flattened_columns, Policy
from kohle.infrastructure.uow import UnitOfWork
from kohle.db.connection import session_local


T = TypeVar("T")
E = TypeVar("E")


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
        model_instance = \
            FlattenedDeserializer.deserialize(self.model_cls, values, self.serde_policy)

        with UnitOfWork(session_local()) as uow:
            res = self.add_use_case(uow, model_instance)
            if res.is_err:
                return Result.err(res.unwrap_err())
            # todo constraint kohle base to have an integer id of name id
            pk_value = model_instance.id
            return Result.ok(pk_value)


    def request_delete(self, key: str) -> Result[str, E]:
        with UnitOfWork(session_local()) as uow:
            pass
        return Result.ok("")


    def request_edit(self, row_key: str, column_key: str, value: str) -> Result[str, E]:
        with UnitOfWork(session_local()) as uow:
            pass
        return Result.ok("")

