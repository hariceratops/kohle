from typing import Type, TypeVar, Dict, Any
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import DeclarativeMeta
from datetime import datetime
from decimal import Decimal
import enum

T = TypeVar("T")

class SQLAlchemyModelAdapter:
    @staticmethod
    def from_string_dict(model_cls: Type[T], data: Dict[str, str]) -> T:
        mapper = inspect(model_cls)
        converted: Dict[str, Any] = {}

        for column in mapper.columns:
            name = column.key
            if name not in data:
                continue
            value = data[name]
            converted[name] = SQLAlchemyModelAdapter._convert_from_string(
                column.type.python_type,
                value
            )

        return model_cls(**converted)

    @staticmethod
    def to_string_dict(instance: Any) -> Dict[str, str]:
        mapper = inspect(instance.__class__)
        result: Dict[str, str] = {}

        for column in mapper.columns:
            value = getattr(instance, column.key)
            if value is None:
                result[column.key] = ""
            else:
                result[column.key] = SQLAlchemyModelAdapter._convert_to_string(value)
        return result

    @staticmethod
    def _convert_from_string(target_type: Type, value: str) -> Any:
        if value == "":
            return None

        if target_type is bool:
            return value.lower() in ("true", "1", "yes")

        if target_type is int:
            return int(value)

        if target_type is float:
            return float(value)

        if target_type is Decimal:
            return Decimal(value)

        if target_type is datetime:
            return datetime.fromisoformat(value)

        if issubclass(target_type, enum.Enum):
            return target_type[value]

        return target_type(value)

    @staticmethod
    def _convert_to_string(value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, enum.Enum):
            return value.name
        return str(value)
