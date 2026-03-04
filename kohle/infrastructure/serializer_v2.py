from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Generic, Optional, TypeVar, Union

from sqlalchemy.inspection import inspect
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


T = TypeVar("T")


@dataclass(slots=True)
class Record:
    id: Any
    fields: Dict[str, Any]


@dataclass(slots=True)
class RelationshipId:
    id: Any


@dataclass(slots=True)
class RelationshipView:
    fields: Dict[str, Any]


@dataclass(slots=True)
class RelationshipFull:
    id: Any
    fields: Dict[str, Any]


RelationshipValue = Union[
    RelationshipId,
    RelationshipView,
    RelationshipFull,
]


class RelationshipMode(Enum):
    EXCLUDE = "exclude"
    ID_ONLY = "id_only"
    EXPAND = "expand"


@dataclass(slots=True)
class RelationshipConfig:
    mode: RelationshipMode
    fields: Optional[set[str]] = None


RelationshipPolicy = Dict[str, RelationshipConfig]


class Serializer(Generic[T]):

    @staticmethod
    def serialize(
        instance: T,
        policy: RelationshipPolicy,
        max_depth: int = 1,
    ) -> Record:
        return Serializer._serialize_impl(
            instance=instance,
            policy=policy,
            max_depth=max_depth,
            depth=0,
        )

    @staticmethod
    def _serialize_impl(
        instance: T,
        policy: RelationshipPolicy,
        max_depth: int,
        depth: int,
    ) -> Record:
        mapper = inspect(instance.__class__)
        pk_column = mapper.primary_key[0]
        record_id = getattr(instance, pk_column.key)

        fields: Dict[str, Any] = {
            column.key: getattr(instance, column.key)
            for column in mapper.columns
            if column.key != pk_column.key
        }

        if depth >= max_depth:
            return Record(id=record_id, fields=fields)

        for relationship in mapper.relationships:
            config = policy.get(
                relationship.key,
                RelationshipConfig(RelationshipMode.ID_ONLY),
            )

            value = getattr(instance, relationship.key)

            if config.mode == RelationshipMode.EXCLUDE:
                continue

            if value is None:
                fields[relationship.key] = None
                continue

            related_mapper = inspect(value.__class__)
            related_pk = related_mapper.primary_key[0]
            related_id = getattr(value, related_pk.key)

            if config.mode == RelationshipMode.ID_ONLY:
                fields[relationship.key] = RelationshipId(id=related_id)

            elif config.mode == RelationshipMode.EXPAND:
                nested_fields: Dict[str, Any] = {}

                if config.fields is None:
                    for col in related_mapper.columns:
                        if col.key != related_pk.key:
                            nested_fields[col.key] = getattr(value, col.key)
                else:
                    for col in related_mapper.columns:
                        if (
                            col.key in config.fields
                            and col.key != related_pk.key
                        ):
                            nested_fields[col.key] = getattr(value, col.key)

                if "id" in (config.fields or set()):
                    fields[relationship.key] = RelationshipFull(
                        id=related_id,
                        fields=nested_fields,
                    )
                else:
                    fields[relationship.key] = RelationshipView(
                        fields=nested_fields,
                    )

        return Record(id=record_id, fields=fields)

    @staticmethod
    def deserialize(
        model: type[T],
        record: Record,
    ) -> T:
        instance = model()
        mapper = inspect(model)
        pk_column = mapper.primary_key[0]

        setattr(instance, pk_column.key, record.id)

        for column in mapper.columns:
            key = column.key
            if key == pk_column.key:
                continue
            if key in record.fields:
                setattr(instance, key, record.fields[key])

        for relationship in mapper.relationships:
            key = relationship.key
            if key not in record.fields:
                continue

            value = record.fields[key]

            if value is None:
                setattr(instance, key, None)
                continue

            related_model = relationship.mapper.class_

            if isinstance(value, RelationshipId):
                related_instance = related_model()
                related_mapper = inspect(related_model)
                related_pk = related_mapper.primary_key[0]
                setattr(related_instance, related_pk.key, value.id)
                setattr(instance, key, related_instance)

            elif isinstance(value, RelationshipView):
                related_instance = related_model()
                for k, v in value.fields.items():
                    setattr(related_instance, k, v)
                setattr(instance, key, related_instance)

            elif isinstance(value, RelationshipFull):
                related_instance = related_model()
                related_mapper = inspect(related_model)
                related_pk = related_mapper.primary_key[0]
                setattr(related_instance, related_pk.key, value.id)
                for k, v in value.fields.items():
                    setattr(related_instance, k, v)
                setattr(instance, key, related_instance)

        return instance

class RecordFlattener:

    @staticmethod
    def flatten(record: Record) -> Record:
        flat_fields: Dict[str, Any] = {}

        def walk(prefix: str, fields: Dict[str, Any]) -> None:
            for key, value in fields.items():
                path = f"{prefix}{key}" if prefix == "" else f"{prefix}.{key}"

                if isinstance(value, RelationshipId):
                    flat_fields[f"{path}.id"] = value.id

                elif isinstance(value, RelationshipView):
                    for sub_key, sub_value in value.fields.items():
                        flat_fields[f"{path}.{sub_key}"] = sub_value

                elif isinstance(value, RelationshipFull):
                    flat_fields[f"{path}.id"] = value.id
                    for sub_key, sub_value in value.fields.items():
                        flat_fields[f"{path}.{sub_key}"] = sub_value

                else:
                    flat_fields[path] = value

        walk("", record.fields)

        return Record(id=record.id, fields=flat_fields)


class FlattenedDeserializer:

    @staticmethod
    def deserialize(
        model: type[T],
        record: Record,
        policy: RelationshipPolicy,
    ) -> T:
        instance = model()

        mapper = inspect(model)
        pk_column = mapper.primary_key[0]
        setattr(instance, pk_column.key, record.id)

        flat_fields = record.fields

        for column in mapper.columns:
            key = column.key
            if key == pk_column.key:
                continue

            if key in flat_fields:
                setattr(instance, key, flat_fields[key])

        relationship_keys = {
            rel.key: rel for rel in mapper.relationships
        }

        for rel_key, rel in relationship_keys.items():
            config = policy.get(
                rel_key,
                RelationshipConfig(RelationshipMode.ID_ONLY),
            )

            if config.mode == RelationshipMode.EXCLUDE:
                continue

            related_model = rel.mapper.class_
            related_mapper = inspect(related_model)
            related_pk = related_mapper.primary_key[0]

            if config.mode == RelationshipMode.ID_ONLY:
                id_key = f"{rel_key}.id"
                if id_key in flat_fields:
                    related_instance = related_model()
                    setattr(
                        related_instance,
                        related_pk.key,
                        flat_fields[id_key],
                    )
                    setattr(instance, rel_key, related_instance)

            elif config.mode == RelationshipMode.EXPAND:
                related_instance = related_model()

                prefix = f"{rel_key}."

                for key, value in flat_fields.items():
                    if key.startswith(prefix):
                        sub_key = key[len(prefix):]

                        if sub_key == "id":
                            setattr(
                                related_instance,
                                related_pk.key,
                                value,
                            )
                        else:
                            if config.fields is None or sub_key in config.fields:
                                setattr(
                                    related_instance,
                                    sub_key,
                                    value,
                                )

                setattr(instance, rel_key, related_instance)

        return instance

class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)

    user: Mapped[Optional["User"]] = relationship(
        back_populates="company",
        uselist=False,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))

    company: Mapped[Optional[Company]] = relationship(
        back_populates="user",
        uselist=False,
    )

    profile: Mapped[Optional["Profile"]] = relationship(
        back_populates="user",
        uselist=False,
    )

    def __str__(self) -> str:
        return f"{self.id} {self.name} {self.company.name}"

class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bio: Mapped[str] = mapped_column(String)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    user: Mapped[User] = relationship(
        back_populates="profile",
        uselist=False,
    )
 
policy: RelationshipPolicy = {
    "company": RelationshipConfig(
        mode=RelationshipMode.EXPAND,
        fields={"name"},
    ),
    "profile": RelationshipConfig(
        mode=RelationshipMode.ID_ONLY,
        fields={"bio"},
    ),
}

company = Company(id=1, name="Acme")
user = User(id=10, name="Alice", company=company)
profile = Profile(id=100, bio="Engineer", user=user)

company.user = user
user.profile = profile

structured = Serializer.serialize(
    instance=user,
    policy=policy,
    max_depth=2,
)
rows = RecordFlattener.flatten(structured)
reconstructed = Serializer.deserialize(
    User,
    structured,
)

print(structured)
print(rows)
print(reconstructed)
print(FlattenedDeserializer.deserialize(User, rows, policy))

