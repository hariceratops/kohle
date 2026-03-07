from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Generic, Optional, Set, TypeVar, Union

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


T = TypeVar("T")


class FieldFilter(Enum):
    drop = "drop"
    pass_id = "pass_id"
    pass_all = "pass_all"


@dataclass(slots=True)
class PassOnly:
    fields: Set[str]


SerializationPolicy = Union[FieldFilter, PassOnly]
Policies = Dict[str, SerializationPolicy]


@dataclass(slots=True)
class Record:
    id: str
    fields: Optional[Dict[str, Union[str, "Record"]]] = None


class Serializer(Generic[T]):
    @staticmethod
    def serialize(instance: T, policies: Policies) -> Optional[Record]:
        mapper = inspect(instance.__class__)
        pk_column = mapper.primary_key[0]
        record_id = str(getattr(instance, pk_column.key))

        root_policy = policies.get("*", FieldFilter.pass_all)

        if root_policy == FieldFilter.drop:
            return None

        if root_policy == FieldFilter.pass_id:
            return Record(id=record_id)


        fields: Dict[str, Union[str, Record]] = {}
        root_fields: Optional[Set[str]] = None
        if isinstance(root_policy, PassOnly):
            root_fields = root_policy.fields

        for column in mapper.columns:
            if column.key == pk_column.key:
                continue

            if root_fields and column.key not in root_fields:
                continue

            value = getattr(instance, column.key)
            fields[column.key] = str(value)

        # relationships
        for relationship in mapper.relationships:
            key = relationship.key
            # HARD root filter boundary
            if root_fields is not None and key not in root_fields:
                continue
            policy = policies.get(key, FieldFilter.pass_id)

            value = getattr(instance, key)

            if value is None:
                continue

            if policy == FieldFilter.drop:
                continue

            related_mapper = inspect(value.__class__)
            related_pk = related_mapper.primary_key[0]

            related_id = str(getattr(value, related_pk.key))

            if policy == FieldFilter.pass_id:
                fields[key] = Record(id=related_id)
                continue

            nested_fields: Dict[str, str] = {}

            if policy == FieldFilter.pass_all:

                for col in related_mapper.columns:
                    if col.key == related_pk.key:
                        continue

                    nested_fields[col.key] = str(getattr(value, col.key))

            elif isinstance(policy, PassOnly):

                for col in related_mapper.columns:
                    if col.key in policy.fields:
                        nested_fields[col.key] = str(getattr(value, col.key))

            fields[key] = Record(
                id=related_id,
                fields=nested_fields if nested_fields else None
            )

        return Record(
            id=record_id,
            fields=fields if fields else None
        )

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


class FlattenedDeserializer:
    @staticmethod
    def deserialize(model: type[T], record: Record, policies: Policies) -> T:
        instance = model()
        mapper = inspect(model)
        pk_column = mapper.primary_key[0]
        setattr(instance, pk_column.key, record.id)
        flat = record.fields or {}

        # scalar fields
        for column in mapper.columns:
            if column.key == pk_column.key:
                continue

            if column.key in flat:
                setattr(instance, column.key, flat[column.key])

        # relationships
        for relationship in mapper.relationships:
            key = relationship.key
            policy = policies.get(key, FieldFilter.pass_id)

            if policy == FieldFilter.drop:
                continue

            id_key = f"{key}.id"
            if id_key not in flat:
                continue

            related_model = relationship.mapper.class_
            related_mapper = inspect(related_model)
            related_pk = related_mapper.primary_key[0]
            related_instance = related_model()
            setattr(
                related_instance,
                related_pk.key,
                flat[id_key]
            )

            prefix = f"{key}."

            for k, v in flat.items():
                if not k.startswith(prefix):
                    continue

                sub = k[len(prefix):]
                if sub == "id":
                    continue
                setattr(related_instance, sub, v)

            setattr(instance, key, related_instance)

        return instance


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)

    user: Mapped[Optional["User"]] = relationship(
        back_populates="company",
        uselist=False
    )

    def __str__(self) -> str:
        return f"{self.id} {self.name}"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))

    company: Mapped[Optional[Company]] = relationship(
        back_populates="user",
        uselist=False
    )

    profile: Mapped[Optional["Profile"]] = relationship(
        back_populates="user",
        uselist=False
    )

    def __str__(self) -> str:
        return f"{self.id} {self.name} {self.company}"


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bio: Mapped[str] = mapped_column(String)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    user: Mapped[User] = relationship(
        back_populates="profile",
        uselist=False
    )


# =========================
# Example
# =========================

policy: Policies = {
    "*": PassOnly({"name", "company"}),
    "company": PassOnly({"name"}),
    "profile": FieldFilter.drop
}

company = Company(id=1, name="Acme")
user = User(id=10, name="Alice", company=company)
profile = Profile(id=100, bio="Engineer", user=user)

company.user = user
user.profile = profile


structured = Serializer.serialize(user, policy)
flattened = RecordFlattener.flatten(structured) if structured else None
reconstructed = FlattenedDeserializer.deserialize(User, flattened, policy) if flattened else None


print("Structured:")
print(structured)

print("\nFlattened:")
print(flattened)

print("\nReconstructed:")
print(reconstructed)

# from __future__ import annotations
# from dataclasses import dataclass
# from enum import Enum
# from typing import Any, Dict, Generic, Optional, TypeVar, Union
# from sqlalchemy.inspection import inspect
# from sqlalchemy import ForeignKey, Integer, String
# from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column, relationship)
#
#
# T = TypeVar("T")
#
#
# class FieldFilter(Enum):
#     drop = "drop"
#     id_only = "id_only"
#     pass_only = "pass_only"
#     pass_all = "pass_all"
#
#
# @dataclass(slots=True)
# class RelationshipId:
#     id: Any
#
#
# @dataclass(slots=True)
# class RelationshipView:
#     fields: Dict[str, Any]
#
#
# @dataclass(slots=True)
# class RelationshipFull:
#     id: Any
#     fields: Dict[str, Any]
#
#
# RelationshipValue = Union[RelationshipId, RelationshipView, RelationshipFull]
#
# @dataclass(slots=True)
# class RelationshipPolicy:
#     mode: FieldFilter
#     fields_to_include: Optional[set[str]] = None
#
#
# RelationshipPolicies = Dict[str, RelationshipPolicy]
#
# @dataclass(slots=True)
# class Record:
#     id: Any
#     fields: Dict[str, str | RelationshipValue]
#
#
# class Serializer(Generic[T]):
#     @staticmethod
#     def serialize(instance: T, policies: RelationshipPolicies, max_depth: int = 1) -> Record:
#         return Serializer._serialize_impl(instance, policies, max_depth, depth=0)
#
#     @staticmethod
#     def _serialize_impl(instance: T, policies: RelationshipPolicies, max_depth: int, depth: int) -> Record:
#         mapper = inspect(instance.__class__)
#         pk_column = mapper.primary_key[0]
#         record_id = getattr(instance, pk_column.key)
#
#         fields: Dict[str, Any] = {
#             column.key: getattr(instance, column.key)
#             for column in mapper.columns
#             if column.key != pk_column.key
#         }
#
#         if depth >= max_depth:
#             return Record(id=str(record_id), fields=fields)
#
#         for relationship in mapper.relationships:
#             config = policies.get(relationship.key, RelationshipPolicy(FieldFilter.id_only))
#
#             value = getattr(instance, relationship.key)
#
#             if config.mode == FieldFilter.drop:
#                 continue
#
#             if value is None:
#                 fields[relationship.key] = None
#                 continue
#
#             related_mapper = inspect(value.__class__)
#             related_pk = related_mapper.primary_key[0]
#             related_id = getattr(value, related_pk.key)
#
#             if config.mode == FieldFilter.id_only:
#                 fields[relationship.key] = RelationshipId(id=related_id)
#
#             elif config.mode == FieldFilter.pass_all:
#                 nested_fields: Dict[str, Any] = {}
#
#                 if config.fields_to_include is None:
#                     for col in related_mapper.columns:
#                         if col.key != related_pk.key:
#                             nested_fields[col.key] = getattr(value, col.key)
#                 else:
#                     for col in related_mapper.columns:
#                         if (col.key in config.fields_to_include and col.key != related_pk.key):
#                             nested_fields[col.key] = getattr(value, col.key)
#
#                 if "id" in (config.fields_to_include or set()):
#                     fields[relationship.key] = RelationshipFull(id=related_id, fields=nested_fields)
#                 else:
#                     fields[relationship.key] = RelationshipView(fields=nested_fields)
#
#         return Record(id=str(record_id), fields=fields)
#
#     @staticmethod
#     def deserialize(model: type[T], record: Record) -> T:
#         instance = model()
#         mapper = inspect(model)
#         pk_column = mapper.primary_key[0]
#
#         setattr(instance, pk_column.key, record.id)
#
#         for column in mapper.columns:
#             key = column.key
#             if key == pk_column.key:
#                 continue
#             if key in record.fields:
#                 setattr(instance, key, record.fields[key])
#
#         for relationship in mapper.relationships:
#             key = relationship.key
#             if key not in record.fields:
#                 continue
#
#             value = record.fields[key]
#
#             if value is None:
#                 setattr(instance, key, None)
#                 continue
#
#             related_model = relationship.mapper.class_
#
#             if isinstance(value, RelationshipId):
#                 related_instance = related_model()
#                 related_mapper = inspect(related_model)
#                 related_pk = related_mapper.primary_key[0]
#                 setattr(related_instance, related_pk.key, value.id)
#                 setattr(instance, key, related_instance)
#
#             elif isinstance(value, RelationshipView):
#                 related_instance = related_model()
#                 for k, v in value.fields.items():
#                     setattr(related_instance, k, v)
#                 setattr(instance, key, related_instance)
#
#             elif isinstance(value, RelationshipFull):
#                 related_instance = related_model()
#                 related_mapper = inspect(related_model)
#                 related_pk = related_mapper.primary_key[0]
#                 setattr(related_instance, related_pk.key, value.id)
#                 for k, v in value.fields.items():
#                     setattr(related_instance, k, v)
#                 setattr(instance, key, related_instance)
#
#         return instance
#
# class RecordFlattener:
#     @staticmethod
#     def flatten(record: Record) -> Record:
#         flat_fields: Dict[str, Any] = {}
#
#         def walk(prefix: str, fields: Dict[str, Any]) -> None:
#             for key, value in fields.items():
#                 path = f"{prefix}{key}" if prefix == "" else f"{prefix}.{key}"
#
#                 if isinstance(value, RelationshipId):
#                     flat_fields[f"{path}.id"] = value.id
#
#                 elif isinstance(value, RelationshipView):
#                     for sub_key, sub_value in value.fields.items():
#                         flat_fields[f"{path}.{sub_key}"] = sub_value
#
#                 elif isinstance(value, RelationshipFull):
#                     flat_fields[f"{path}.id"] = value.id
#                     for sub_key, sub_value in value.fields.items():
#                         flat_fields[f"{path}.{sub_key}"] = sub_value
#
#                 else:
#                     flat_fields[path] = value
#
#         walk("", record.fields)
#         return Record(id=record.id, fields=flat_fields)
#
#
# class FlattenedDeserializer:
#     @staticmethod
#     def deserialize(model: type[T], record: Record, policy: RelationshipPolicies) -> T:
#         instance = model()
#
#         mapper = inspect(model)
#         pk_column = mapper.primary_key[0]
#         setattr(instance, pk_column.key, record.id)
#
#         flat_fields = record.fields
#
#         for column in mapper.columns:
#             key = column.key
#             if key == pk_column.key:
#                 continue
#
#             if key in flat_fields:
#                 setattr(instance, key, flat_fields[key])
#
#         relationship_keys = {
#             rel.key: rel for rel in mapper.relationships
#         }
#
#         for rel_key, rel in relationship_keys.items():
#             config = policy.get(
#                 rel_key,
#                 RelationshipPolicy(FieldFilter.id_only),
#             )
#
#             if config.mode == FieldFilter.drop:
#                 continue
#
#             related_model = rel.mapper.class_
#             related_mapper = inspect(related_model)
#             related_pk = related_mapper.primary_key[0]
#
#             if config.mode == FieldFilter.id_only:
#                 id_key = f"{rel_key}.id"
#                 if id_key in flat_fields:
#                     related_instance = related_model()
#                     setattr(related_instance, related_pk.key, flat_fields[id_key])
#                     setattr(instance, rel_key, related_instance)
#
#             elif config.mode == FieldFilter.pass_all:
#                 related_instance = related_model()
#
#                 prefix = f"{rel_key}."
#
#                 for key, value in flat_fields.items():
#                     if key.startswith(prefix):
#                         sub_key = key[len(prefix):]
#
#                         if sub_key == "id":
#                             setattr(related_instance, related_pk.key, value)
#                         else:
#                             if config.fields_to_include is None or sub_key in config.fields_to_include:
#                                 setattr(related_instance, sub_key, value)
#                 setattr(instance, rel_key, related_instance)
#         return instance
#
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
#     user: Mapped[Optional["User"]] = relationship(back_populates="company", uselist=False)
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
#     company: Mapped[Optional[Company]] = relationship(back_populates="user", uselist=False)
#     profile: Mapped[Optional["Profile"]] = relationship(back_populates="user", uselist=False)
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
#     user: Mapped[User] = relationship(back_populates="profile", uselist=False)
#
#  
# policy: RelationshipPolicies = {
#     "company": RelationshipPolicy(mode=FieldFilter.pass_all, fields_to_include={"name"}),
#     "profile": RelationshipPolicy(mode=FieldFilter.id_only, fields_to_include={"bio"})
# }
#
# company = Company(id=1, name="Acme")
# user = User(id=10, name="Alice", company=company)
# profile = Profile(id=100, bio="Engineer", user=user)
#
# company.user = user
# user.profile = profile
#
# structured = Serializer.serialize(instance=user, policies=policy, max_depth=2)
# rows = RecordFlattener.flatten(structured)
# reconstructed = Serializer.deserialize(User, structured)
# print(structured)
# print(rows)
# print(reconstructed)
# print(FlattenedDeserializer.deserialize(User, rows, policy))
#
