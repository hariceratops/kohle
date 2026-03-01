from typing import Protocol, Iterable, Sequence, TypeVar, Type, Callable, Any
from sqlalchemy.inspection import inspect
from kohle.core.result import Result
from kohle.infrastructure.sqlalchemy_model_adapter import SQLAlchemyModelAdapter
from kohle.infrastructure.uow import UnitOfWork


E = TypeVar("E")
T = TypeVar("T")
PK = TypeVar("PK")


class SpreadsheetCapabilities(Protocol[E]):
    def populate_columns(self) -> Iterable[dict[str, Any]]: ...
    def populate_rows(self, uow: UnitOfWork) -> Result[list[dict[str, str]], E]: ...
    def request_add(self, uow: UnitOfWork, values: Sequence[str]) -> Result[str, E]: ...
    def request_delete(self, uow: UnitOfWork, key: str) -> Result[str, E]: ...
    def request_edit(self, uow: UnitOfWork, row_key: str, column_key: str, value: str) -> Result[str, E]: ...


class SpreadsheetController[E]:
    def __init__(self, capabilities: SpreadsheetCapabilities) -> None:
        self.capabilities = capabilities
    def populate_columns(self) -> Iterable[dict[str, Any]]:
        return self.capabilities.populate_columns()
    def populate_rows(self, uow: UnitOfWork) -> Result[list[dict[str, str]], E]:
        return self.capabilities.populate_rows(uow)
    def request_add(self, uow: UnitOfWork, values: Sequence[str]) -> Result[str, E]:
        return self.capabilities.request_add(uow, values)
    def request_delete(self, uow: UnitOfWork, key: str) -> Result[str, E]:
        return self.capabilities.request_delete(uow, key)
    def request_edit(self, uow: UnitOfWork, row_key: str, column_key: str, value: str) -> Result[str, E]:
        return self.capabilities.request_edit(uow, row_key, column_key, value)


class ModelSpreadsheetCapabilities[E, T]:
    def __init__(
        self,
        model_cls: Type[T],
        list_use_case: Callable[[UnitOfWork], Result[list[dict[str, Any]], E]],
        add_use_case: Callable[[UnitOfWork, T], Result[PK, E]],
    ) -> None:
        self.model_cls = model_cls
        self.list_use_case = list_use_case
        self.add_use_case = add_use_case
        self.mapper = inspect(model_cls)
        self.columns = list(self.mapper.columns)
        self.primary_key_columns = list(self.mapper.primary_key)

    def populate_columns(self) -> Iterable[dict[str, Any]]:
        return [
            {
                "key": column.key,
                "primary_key": column.primary_key,
                "editable": not column.primary_key,
            }
            for column in self.columns
        ]

    def populate_rows(self, uow: UnitOfWork) -> Result[list[dict[str, str]], E]:
        return self.list_use_case(uow)

    def request_add(self, uow: UnitOfWork, values: Sequence[str]) -> Result[str, E]:
        editable_columns = [c for c in self.columns if not c.primary_key]
        if len(values) != len(editable_columns):
            return Result.err(Exception("Invalid column count"))

        data: dict[str, str] = {
            column.key: value
            for column, value in zip(editable_columns, values)
        }
        model_instance = SQLAlchemyModelAdapter.from_string_dict(
            self.model_cls,
            data,
        )

        res = self.add_use_case(uow, model_instance)
        if res.is_err:
            return Result.err(res.unwrap_err())

        pk_value = self._extract_primary_key(model_instance)
        return Result.ok(pk_value)

    def _extract_primary_key(self, instance: T) -> str:
        values: list[str] = []

        for column in self.primary_key_columns:
            value = getattr(instance, column.key)
            values.append(SQLAlchemyModelAdapter._convert_to_string(value))

        return values[0] if len(values) == 1 else ",".join(values)

    def request_delete(self, uow: UnitOfWork, key: str) -> Result[str, E]:
        return Result.ok("")

    def request_edit(self, uow: UnitOfWork, row_key: str, column_key: str, value: str) -> Result[str, E]:
        return Result.ok("")


# Example Wiring for DebitCategory

# uow = UnitOfWork()
# capabilities = ModelSpreadsheetCapabilities(
#     model_cls=DebitCategory,
#     uow=uow,
#     list_use_case=list_debit_categories,
#     add_use_case=add_debit_category,
# )
# controller = SpreadsheetController(capabilities)
