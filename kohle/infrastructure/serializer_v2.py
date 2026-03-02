from enum import Enum
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.inspection import inspect


class RelationshipMode(Enum):
    ID_ONLY = "id_only"
    EXCLUDE = "exclude"
    EXPAND = "expand"


class RelationshipConfig:
    def __init__(
        self,
        mode: RelationshipMode,
        fields: Optional[List[str]] = None,
    ) -> None:
        self.mode = mode
        self.fields = fields


RelationshipPolicy = Dict[str, RelationshipConfig]


class PolicyDepthSerializer:
    def __init__(self, policy: RelationshipPolicy, max_depth: int = 1) -> None:
        self.policy = policy
        self.max_depth = max_depth

    def to_dict(self, instance: Any, depth: int = 0) -> Dict[str, Any]:
        mapper = inspect(instance.__class__)
        result: Dict[str, Any] = {}

        for column in mapper.columns:
            result[column.key] = getattr(instance, column.key)

        if depth >= self.max_depth:
            return result

        for relationship in mapper.relationships:
            config = self.policy.get(
                relationship.key,
                RelationshipConfig(RelationshipMode.ID_ONLY),
            )

            if config.mode == RelationshipMode.EXCLUDE:
                continue

            value = getattr(instance, relationship.key)

            if value is None:
                result[relationship.key] = None
                continue

            if config.mode == RelationshipMode.ID_ONLY:
                if relationship.uselist:
                    result[relationship.key] = [
                        getattr(item, "id") for item in value
                    ]
                else:
                    result[relationship.key] = getattr(value, "id")

            elif config.mode == RelationshipMode.EXPAND:
                if relationship.uselist:
                    result[relationship.key] = [
                        self._project(item, config, depth + 1)
                        for item in value
                    ]
                else:
                    result[relationship.key] = self._project(
                        value, config, depth + 1
                    )

        return result

    def _project(
        self,
        instance: Any,
        config: RelationshipConfig,
        depth: int,
    ) -> Dict[str, Any]:
        data = self.to_dict(instance, depth)

        if config.fields is None:
            return data

        return {k: v for k, v in data.items() if k in config.fields}


class DictionaryNormalizer:
    @staticmethod
    def normalize(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = [{}]

        for key, value in data.items():
            if isinstance(value, list):
                new_rows: List[Dict[str, Any]] = []

                for item in value:
                    if isinstance(item, dict):
                        flattened = DictionaryNormalizer._flatten(item, key)
                    else:
                        flattened = {key: item}

                    for row in rows:
                        combined = row.copy()
                        combined.update(flattened)
                        new_rows.append(combined)

                rows = new_rows

            elif isinstance(value, dict):
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
                nested = DictionaryNormalizer._flatten(value, new_key)
                result.update(nested)
            else:
                result[new_key] = value

        return result


class NoListRelationshipsMixin:
    @classmethod
    def __declare_last__(cls) -> None:
        mapper = inspect(cls)
        for relationship in mapper.relationships:
            if relationship.uselist:
                raise TypeError(
                    f"{cls.__name__}.{relationship.key} must not be a list relationship"
                )


class Base(DeclarativeBase):
    pass


class Address(Base, NoListRelationshipsMixin):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city: Mapped[str] = mapped_column(String)
    country: Mapped[str] = mapped_column(String)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"))

    profile: Mapped["Profile"] = relationship(back_populates="address")


class Profile(Base, NoListRelationshipsMixin):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bio: Mapped[str] = mapped_column(String)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    user: Mapped["User"] = relationship(back_populates="profile")
    address: Mapped[Optional[Address]] = relationship(
        back_populates="profile",
        uselist=False,
    )


class Company(Base, NoListRelationshipsMixin):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)

    user: Mapped[Optional["User"]] = relationship(
        back_populates="company",
        uselist=False,
    )


class User(Base, NoListRelationshipsMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))

    company: Mapped[Optional[Company]] = relationship(
        back_populates="user",
        uselist=False,
    )
    profile: Mapped[Optional[Profile]] = relationship(
        back_populates="user",
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

serializer = PolicyDepthSerializer(policy=policy, max_depth=2)

structured = serializer.to_dict(user)

rows = DictionaryNormalizer.normalize(structured)

print(structured)
print(rows)

# from enum import Enum
# from typing import Any, Dict, List, Optional
# from sqlalchemy.inspection import inspect
#
#
# class RelationshipMode(Enum):
#     ID_ONLY = "id_only"
#     EXCLUDE = "exclude"
#     EXPAND = "expand"
#
#
# class RelationshipConfig:
#     def __init__(
#         self,
#         mode: RelationshipMode,
#         fields: Optional[List[str]] = None,
#     ) -> None:
#         self.mode = mode
#         self.fields = fields
#
#
# RelationshipPolicy = Dict[str, RelationshipConfig]
#
#
# class PolicyDepthSerializer:
#     def __init__(self, policy: RelationshipPolicy, max_depth: int = 1) -> None:
#         self.policy = policy
#         self.max_depth = max_depth
#
#     def to_dict(self, instance: Any, depth: int = 0) -> Dict[str, Any]:
#         mapper = inspect(instance.__class__)
#         result: Dict[str, Any] = {}
#
#         for column in mapper.columns:
#             result[column.key] = getattr(instance, column.key)
#
#         if depth >= self.max_depth:
#             return result
#
#         for relationship in mapper.relationships:
#             config = self.policy.get(
#                 relationship.key,
#                 RelationshipConfig(RelationshipMode.ID_ONLY),
#             )
#
#             if config.mode == RelationshipMode.EXCLUDE:
#                 continue
#
#             value = getattr(instance, relationship.key)
#
#             if value is None:
#                 result[relationship.key] = None
#                 continue
#
#             if config.mode == RelationshipMode.ID_ONLY:
#                 if relationship.uselist:
#                     result[relationship.key] = [
#                         getattr(item, "id") for item in value
#                     ]
#                 else:
#                     result[relationship.key] = getattr(value, "id")
#
#             elif config.mode == RelationshipMode.EXPAND:
#                 if relationship.uselist:
#                     result[relationship.key] = [
#                         self._project(item, config, depth + 1)
#                         for item in value
#                     ]
#                 else:
#                     result[relationship.key] = self._project(
#                         value, config, depth + 1
#                     )
#
#         return result
#
#     def _project(
#         self,
#         instance: Any,
#         config: RelationshipConfig,
#         depth: int,
#     ) -> Dict[str, Any]:
#         data = self.to_dict(instance, depth)
#
#         if config.fields is None:
#             return data
#
#         return {k: v for k, v in data.items() if k in config.fields}
#
#
# class DictionaryNormalizer:
#     @staticmethod
#     def normalize(data: Dict[str, Any]) -> List[Dict[str, Any]]:
#         rows: List[Dict[str, Any]] = [{}]
#
#         for key, value in data.items():
#             if isinstance(value, list):
#                 new_rows: List[Dict[str, Any]] = []
#
#                 for item in value:
#                     if isinstance(item, dict):
#                         flattened = DictionaryNormalizer._flatten(item, key)
#                     else:
#                         flattened = {key: item}
#
#                     for row in rows:
#                         combined = row.copy()
#                         combined.update(flattened)
#                         new_rows.append(combined)
#
#                 rows = new_rows
#
#             elif isinstance(value, dict):
#                 flattened = DictionaryNormalizer._flatten(value, key)
#                 for row in rows:
#                     row.update(flattened)
#
#             else:
#                 for row in rows:
#                     row[key] = value
#
#         return rows
#
#     @staticmethod
#     def _flatten(data: Dict[str, Any], prefix: str) -> Dict[str, Any]:
#         result: Dict[str, Any] = {}
#
#         for key, value in data.items():
#             new_key = f"{prefix}.{key}"
#
#             if isinstance(value, dict):
#                 nested = DictionaryNormalizer._flatten(value, new_key)
#                 result.update(nested)
#             else:
#                 result[new_key] = value
#
#         return result
#
# from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
# from sqlalchemy import Integer, String, ForeignKey
# from typing import List
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
#
#     users: Mapped[List["User"]] = relationship(back_populates="company")
#
#
# class User(Base):
#     __tablename__ = "users"
#
#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     name: Mapped[str] = mapped_column(String)
#     company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
#
#     company: Mapped[Company] = relationship(back_populates="users")
#     posts: Mapped[List["Post"]] = relationship(back_populates="user")
#
#
# class Post(Base):
#     __tablename__ = "posts"
#
#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     title: Mapped[str] = mapped_column(String)
#     user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
#
#     user: Mapped[User] = relationship(back_populates="posts")
#     comments: Mapped[List["Comment"]] = relationship(back_populates="post")
#
#
# class Comment(Base):
#     __tablename__ = "comments"
#
#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     content: Mapped[str] = mapped_column(String)
#     post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
#
#     post: Mapped[Post] = relationship(back_populates="comments")
#
#
# company = Company(id=1, name="Acme Corp")
# user = User(id=100, name="Alice", company=company)
# post1 = Post(id=10, title="First Post", user=user)
# post2 = Post(id=11, title="Second Post", user=user)
# comment1 = Comment(id=1000, content="Great", post=post1)
# comment2 = Comment(id=1001, content="Nice", post=post1)
# comment3 = Comment(id=1002, content="Interesting", post=post2)
#
# company.users = [user]
# user.posts = [post1, post2]
# post1.comments = [comment1, comment2]
# post2.comments = [comment3]
#
#
# policy: RelationshipPolicy = {
#     "company": RelationshipConfig(
#         mode=RelationshipMode.EXPAND,
#         fields=["name"],
#     ),
#     "posts": RelationshipConfig(
#         mode=RelationshipMode.EXPAND,
#         fields=["title", "comments"],
#     ),
#     "comments": RelationshipConfig(
#         mode=RelationshipMode.EXPAND,
#         fields=["content"],
#     ),
# }
#
# serializer = PolicyDepthSerializer(policy=policy, max_depth=2)
#
# structured = serializer.to_dict(user)
#
# rows = DictionaryNormalizer.normalize(structured)
#
# print(structured)
# print(rows)
#
