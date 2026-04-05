from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Type, Any, Dict, Generic, Optional, Set, TypeVar, Union, Iterator, Tuple, List
from sqlalchemy.inspection import inspect
from datetime import datetime
from decimal import Decimal
import enum
from kohle.core.result import Result
from typing import Type, TypeVar, Generic, Dict

T = TypeVar("T")

# todo tests
# todo bound generic to kohlebase
# todo refactor as much as possible with no loops and monadic operations
# todo engage string conversion utilities
# todo strong typing over enums
# todo rename wherever possible
# todo handle error if keys not present?
# todo make policy strong type
# todo cache inspect results
# todo improve visitor
# todo fix all type errors and warnings


T = TypeVar("T")

class Drop: pass

class PassId: pass

class PassAll: pass

@dataclass(slots=True)
class PassOnly:
    fields: Set[str]


RootFilter = Union[Drop, PassId, PassAll, PassOnly]


@dataclass(slots=True)
class Record:
    id: str
    fields: Optional[Dict[str, Union[str, "Record"]]] = None

    def __len__(self):
        return len(self.fields) if self.fields else 0

    # todo handle gracefully
    def __getitem__(self, key):
        return self.fields[key]

    # todo handle gracefully
    def __setitem__(self, key, value):
        self.fields[key] = value


@dataclass(slots=True)
class SingleRecord:
    id: str
    fields: Tuple[str, str]


class SerdePolicy(Generic[T]):
    def __init__(self, root_policy, root_foreign_policy: Dict[str, "SerdePolicy"]) -> None:
        self.root_policy = root_policy
        self.root_foreign_policy = root_foreign_policy

    def __iter__(self) -> Iterator[Tuple[str, "SerdePolicy"]]:
        return iter(self.root_foreign_policy.items())

    @classmethod
    def create(cls, model: Type[T], root_policy, foreign: Dict[str, "SerdePolicy"] | None = None):
        mapper = inspect(model)
        columns = {c.key for c in mapper.columns}
        relations = {r.key: r.mapper.class_ for r in mapper.relationships}
        valid_fields = columns | relations.keys()

        if isinstance(root_policy, PassOnly):
            for field in root_policy.fields:
                if field not in valid_fields:
                    return Result.err(f"{field} not part of model {model.__name__}")

        foreign = foreign or {}
        validated_foreign: Dict[str, SerdePolicy] = {}

        for key, sub_policy in foreign.items():
            if key not in relations:
                return Result.err(f"{key} not relation of {model.__name__}")

            related_model = relations[key]

            res = cls.create(related_model, sub_policy.root_policy, sub_policy.root_foreign_policy)
            if res.is_err:
                return res
            validated_foreign[key] = res.unwrap()

        return Result.ok(cls(root_policy, validated_foreign))

    @staticmethod
    def for_model(model: Type[T]) -> PolicyBuilder[T]:
        return PolicyBuilder(model)


class PolicyBuilder(Generic[T]):
    def __init__(self, model: Type[T]) -> None:
        self.model: Type[T] = model
        self._root: Optional[RootFilter] = None
        self._relations: Dict[str, SerdePolicy] = {}
        self._error: Optional[str] = None

    def _set_root(self, root: RootFilter) -> PolicyBuilder[T]:
        if self._root is not None:
            self._error = "Conflicting root filters specified"
            return self
        self._root = root
        return self

    def only(self, *fields: str) -> PolicyBuilder[T]:
        return self._set_root(PassOnly(set(fields)))

    def pass_all(self) -> PolicyBuilder[T]:
        return self._set_root(PassAll())

    def drop(self) -> PolicyBuilder[T]:
        return self._set_root(Drop())

    def relation(self, name: str, policy: SerdePolicy) -> PolicyBuilder[T]:
        self._relations[name] = policy
        return self

    def build(self) -> Result[SerdePolicy[T], str]:
        if self._error:
            return Result.err(self._error)

        root: RootFilter = self._root or PassAll()

        if isinstance(root, PassOnly):
            missing = set(self._relations) - root.fields
            if missing:
                return Result.err(f"PassOnly root must include relations: {missing}")

        return SerdePolicy.create(self.model, root, self._relations)


class PolicyTraversal:
    """
    Traverses a validated Policy tree and emits flattened paths. This traversal is reused by serializer and column generator.
    """
    @staticmethod
    def walk(model: Type, policy: SerdePolicy, visit_column, visit_relation, prefix: str = "") -> None:
        mapper = inspect(model)
        pk_column = mapper.primary_key[0]
        root_filter = policy.root_policy

        if isinstance(root_filter, Drop):
            return

        allowed_fields: Optional[Set[str]] = None
        if isinstance(root_filter, PassOnly):
            allowed_fields = root_filter.fields

        for column in mapper.columns:
            if column.key == pk_column.key:
                continue
            if allowed_fields and column.key not in allowed_fields:
                continue
            path = f"{prefix}{column.key}" if prefix else column.key
            visit_column(path, column)

        for relationship in mapper.relationships:
            key = relationship.key
            if allowed_fields and key not in allowed_fields:
                continue

            sub_policy = policy.root_foreign_policy.get(key)
            if sub_policy is None:
                sub_policy = SerdePolicy(PassId(), {})

            relation_prefix = f"{prefix}{key}." if prefix else f"{key}."
            visit_relation(relation_prefix, relationship, sub_policy)

            if isinstance(sub_policy.root_policy, PassId):
                continue

            PolicyTraversal.walk(relationship.mapper.class_, sub_policy, visit_column, visit_relation, relation_prefix)


class Serializer(Generic[T]):
    @staticmethod
    def serialize(instance: T, policy: SerdePolicy[T]) -> Optional[Record]:
        mapper = inspect(instance.__class__)
        pk_column = mapper.primary_key[0]
        record_id = str(getattr(instance, pk_column.key))

        if isinstance(policy.root_policy, Drop):
            return None

        if isinstance(policy.root_policy, PassId):
            return Record(id=record_id)

        fields: Dict[str, Union[str, Record]] = {}

        def visit_column(path, column):
            value = getattr(instance, column.key)
            fields[path] = Serializer._convert_to_string(value)

        def visit_relation(prefix, relationship, sub_policy):
            key = relationship.key
            related = getattr(instance, key)

            if related is None:
                return

            related_mapper = inspect(related.__class__)
            related_pk = related_mapper.primary_key[0]

            related_id = str(getattr(related, related_pk.key))

            if isinstance(sub_policy.root_policy, Drop):
                return

            if isinstance(sub_policy.root_policy, PassId):
                fields[prefix[:-1]] = Record(id=related_id)
                return

            nested = Serializer.serialize(related, sub_policy)

            if nested:
                fields[prefix[:-1]] = nested

        PolicyTraversal.walk(instance.__class__, policy, visit_column, visit_relation)

        return Record(id=record_id, fields=fields if fields else None)

    @staticmethod
    def _convert_to_string(value: Any) -> Optional[str]:
        if value is None:
            return None

        if isinstance(value, datetime):
            return value.isoformat()

        if isinstance(value, enum.Enum):
            return value.name

        return str(value)



def flattened_columns(model: Type, policy: SerdePolicy) -> List[str]:
    columns: List[str] = []

    def visit_column(path, column):
        columns.append(path)

    def visit_relation(prefix, relationship, sub_policy):
        relation_name = prefix[:-1]
        columns.append(f"{relation_name}.id")

    PolicyTraversal.walk(model, policy, visit_column, visit_relation)
    return columns


class RecordFlattener:
    @staticmethod
    def flatten(record: Record) -> Record:
        flat: Dict[str, str] = {}

        def walk(prefix: str, rec: Record):
            if rec.fields is None:
                return

            for key, value in rec.fields.items():
                path = key if prefix == "" else f"{prefix}.{key}"
                if isinstance(value, Record):
                    flat[f"{path}.id"] = value.id
                    if value.fields:
                        walk(path, value)
                else:
                    flat[path] = value

        walk("", record)
        return Record(id=record.id, fields=flat)


class FlattenedDeserializer(Generic[T]):
    @staticmethod
    def deserialize(model: Type[T], record: Record, policy: SerdePolicy[T]) -> T:
        """
        Reconstructs a SQLAlchemy model instance from a flattened Record
        using the validated Policy tree.
        """
        instance = model()
        mapper = inspect(model)
        pk_column = mapper.primary_key[0]

        # set root id
        setattr(instance, pk_column.key, record.id)
        flat = record.fields or {}
        # cache created relation instances
        relation_instances: Dict[str, Any] = {}

        def visit_column(path: str, column):
            if path not in flat:
                return

            value = flat[path]
            target_type = column.type.python_type
            converted = FlattenedDeserializer._convert_from_string(target_type, value)

            # root column
            if "." not in path:
                setattr(instance, column.key, converted)
                return

            # nested column
            relation_name, field_name = path.split(".", 1)
            related_instance = relation_instances.get(relation_name)
            if related_instance is None:
                return
            setattr(related_instance, field_name, converted)


        def visit_relation(prefix: str, relationship, sub_policy):
            relation_name = prefix[:-1]
            id_key = f"{relation_name}.id"

            if id_key not in flat:
                return

            related_model = relationship.mapper.class_
            related_mapper = inspect(related_model)
            related_pk = related_mapper.primary_key[0]
            related_instance = related_model()
            setattr(related_instance, related_pk.key, flat[id_key])
            setattr(instance, relation_name, related_instance)
            relation_instances[relation_name] = related_instance

        PolicyTraversal.walk(model, policy, visit_column, visit_relation)
        return instance


    @staticmethod
    def _convert_from_string(target_type: Type, value: str) -> Any:
        if value == "":
            return None
        if value == None:
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


class PlainDeserializer:
    @staticmethod
    def deserialize(model: Type[T], record: Record, policy: SerdePolicy[T]) -> Record:
        """
        Converts flattened Record[str] → Record[typed] using SQLAlchemy
        column types discovered through the policy traversal.
        """

        flat = record.fields or {}
        converted: Dict[str, Any] = {}

        def visit_column(path: str, column):
            if path not in flat:
                return

            value = flat[path]
            target_type = column.type.python_type

            converted[path] = PlainDeserializer._convert_from_string(
                target_type,
                value
            )

        def visit_relation(prefix: str, relationship, sub_policy):
            relation_name = prefix[:-1]
            id_key = f"{relation_name}.id"

            if id_key not in flat:
                return

            related_model = relationship.mapper.class_
            related_mapper = inspect(related_model)
            related_pk = related_mapper.primary_key[0]

            target_type = related_pk.type.python_type

            converted[id_key] = PlainDeserializer._convert_from_string(
                target_type,
                flat[id_key]
            )

        PolicyTraversal.walk(model, policy, visit_column, visit_relation)

        return Record(
            id=record.id,
            fields=converted
        )

    @staticmethod
    def _convert_from_string(target_type: Type, value: str) -> Any:
        if value == "":
            return None

        if value is None:
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


# from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
# from sqlalchemy import ForeignKey, Integer, String
#
# class Base(DeclarativeBase):
#     pass
#
#
# class Company(Base):
#     __tablename__ = "companies"
#
#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     name: Mapped[str] = mapped_column(String)
#
#     user: Mapped[Optional["User"]] = relationship(
#         back_populates="company",
#         uselist=False
#     )
#
#     def __str__(self) -> str:
#         return f"{self.id} {self.name}"
#
#
# class User(Base):
#     __tablename__ = "users"
#
#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     name: Mapped[str] = mapped_column(String)
#     company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
#
#     company: Mapped[Optional[Company]] = relationship(
#         back_populates="user",
#         uselist=False
#     )
#     profile: Mapped[Optional["Profile"]] = relationship(
#         back_populates="user",
#         uselist=False
#     )
#
#     def __str__(self) -> str:
#         return f"{self.id} {self.name} {self.company}"
#
#
# class Profile(Base):
#     __tablename__ = "profiles"
#
#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     bio: Mapped[str] = mapped_column(String)
#     user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
#
#     user: Mapped[User] = relationship(
#         back_populates="profile",
#         uselist=False
#     )
#
#
# company = Company(id=1, name="Acme")
# user = User(id=10, name="Alice", company=company)
# profile = Profile(id=100, bio="Engineer", user=user)
# company.user = user
# user.profile = profile
# # this is not intuitive
# user_policy = SerdePolicy(
#     PassOnly({"name", "company"}),
#     {
#         "company": SerdePolicy(PassOnly({"name"}), {}),
#         "profile": SerdePolicy(Drop(), {})
#     }
# )
# res = SerdePolicy.create(User, user_policy.root_policy, user_policy.root_foreign_policy)
#
# for p in res.unwrap():
#     print(p)
# p = res.unwrap()
#
# structured = Serializer.serialize(user, p)
# flattened = RecordFlattener.flatten(structured) if structured else None
# reconstructed_f = FlattenedDeserializer.deserialize(User, flattened, p) if flattened else None
# reconstructed = PlainDeserializer.deserialize(User, flattened, p) if flattened else None
# flat_columns = flattened_columns(User, p)
# print(f"Structured: {structured}")
# print(f"Flattened: {flattened}")
# print(f"Reconstructed: {reconstructed}")
# print(f"Reconstructed_f: {reconstructed_f}")
# print(f"Flat columns: {flat_columns}")
# user_policy = (
#     SerdePolicy
#     .for_model(User)
#     .only("name", "company")
#     .relation("company", SerdePolicy(PassOnly({"name"}), {}))
#     .build()
#     .unwrap()
# )
#
# flat_columns = flattened_columns(User, user_policy)
# print(f"With builder, flattened_columns: {flat_columns}")
# #
