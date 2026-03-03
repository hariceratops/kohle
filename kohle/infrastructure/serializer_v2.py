from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, TypeVar, Generic
from sqlalchemy import event, Integer, String, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Mapper
from sqlalchemy.inspection import inspect
from sqlalchemy import Integer, String, ForeignKey
from typing import Optional


def validate_mapper(mapper: Mapper, class_) -> None:
    if hasattr(class_, "__abstract__") and class_.__abstract__:
        return

    primary_keys = mapper.primary_key
    if len(primary_keys) != 1:
        raise TypeError(f"{class_.__name__} must have exactly one primary key column")

    for relationship in mapper.relationships:
        if relationship.uselist:
            raise TypeError(f"{class_.__name__}.{relationship.key} must not be a list relationship")


event.listen(Mapper, "mapper_configured", validate_mapper)


class Base(DeclarativeBase):
    pass


class RelationshipMode(Enum):
    ID_ONLY = "id_only"
    EXCLUDE = "exclude"
    EXPAND = "expand"


@dataclass(frozen=True)
class RelationshipConfig:
    mode: RelationshipMode
    fields: Optional[List[str]] = None


RelationshipPolicy = Dict[str, RelationshipConfig]


T = TypeVar("T")


class Serializer(Generic[T]):
    @staticmethod
    def to_dict(instance: T, policy: RelationshipPolicy, max_depth: int = 1) -> Dict[str, Any]:
        return Serializer._serialize_impl(instance, policy, max_depth, 0)

    @staticmethod
    def _serialize_impl(instance: T, policy: RelationshipPolicy, max_depth: int, depth: int) -> Dict[str, Any]:
        mapper = inspect(instance.__class__)
        result: Dict[str, Any] = {}

        for column in mapper.columns:
            result[column.key] = getattr(instance, column.key)

        if depth >= max_depth:
            return result

        for relationship in mapper.relationships:
            config = policy.get(relationship.key, RelationshipConfig(RelationshipMode.ID_ONLY))
            value = getattr(instance, relationship.key)

            match config.mode:
                case RelationshipMode.EXCLUDE:
                    continue

                case _ if value is None:
                    result[relationship.key] = None

                case RelationshipMode.ID_ONLY:
                    result[relationship.key] = getattr(value, "id")

                case RelationshipMode.EXPAND:
                    nested = Serializer._serialize_impl(value, policy, max_depth, depth + 1)
                    result[relationship.key] = (
                        nested
                        if config.fields is None
                        else {
                            k: v
                            for k, v in nested.items()
                            if k in config.fields
                        }
                    )

        return result


class DictionaryNormalizer:
    @staticmethod
    def normalize(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = [{}]

        for key, value in data.items():
            if isinstance(value, dict):
                flattened = DictionaryNormalizer._flatten(value, key)
                for row in rows:
                    row.update(flattened)
            else:
                for row in rows:
                    row[key] = value

        return rows

    @staticmethod
    def _flatten(data: Dict[str, Any], prefix: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        for key, value in data.items():
            new_key = f"{prefix}.{key}"
            if isinstance(value, dict):
                result.update(DictionaryNormalizer._flatten(value, new_key))
            else:
                result[new_key] = value

        return result


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


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bio: Mapped[str] = mapped_column(String)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    user: Mapped[User] = relationship(
        back_populates="profile",
        uselist=False,
    )

    address: Mapped[Optional["Address"]] = relationship(
        back_populates="profile",
        uselist=False,
    )


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city: Mapped[str] = mapped_column(String)
    country: Mapped[str] = mapped_column(String)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"))

    profile: Mapped[Profile] = relationship(
        back_populates="address",
        uselist=False,
    )

company = Company(id=1, name="Acme")
user = User(id=10, name="Alice", company=company)
profile = Profile(id=100, bio="Engineer", user=user)
address = Address(id=1000, city="Berlin", country="DE", profile=profile)

company.user = user
user.profile = profile
profile.address = address


policy: RelationshipPolicy = {
    "company": RelationshipConfig(
        mode=RelationshipMode.EXPAND,
        fields=["name"],
    ),
    "profile": RelationshipConfig(
        mode=RelationshipMode.EXPAND,
        fields=["bio", "address"],
    ),
    "address": RelationshipConfig(
        mode=RelationshipMode.EXPAND,
        fields=["city", "country"],
    ),
}

structured = Serializer.to_dict(
    instance=user,
    policy=policy,
    max_depth=2,
)

rows = DictionaryNormalizer.normalize(structured)

print(structured)
print(rows)
