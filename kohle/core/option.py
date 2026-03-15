from dataclasses import dataclass
from typing import Generic, TypeVar, Callable, Any
from kohle.core.result import Result


T = TypeVar("T")
T2 = TypeVar("T2")
E = TypeVar("E")

_none = object()


@dataclass(frozen=True)
class Option(Generic[T]):
    _value: Any = _none

    @staticmethod
    def some(value: T) -> "Option[T]":
        return Option(value)

    @staticmethod
    def none() -> "Option[T]":
        return Option()

    @property
    def is_some(self) -> bool:
        return self._value is not _none

    @property
    def is_none(self) -> bool:
        return self._value is _none

    def unwrap(self) -> T:
        if self.is_none:
            raise RuntimeError("called unwrap on None")
        return self._value

    def expect(self, msg: str) -> T:
        if self.is_none:
            raise RuntimeError(msg)
        return self._value

    def unwrap_or(self, default: T) -> T:
        return self._value if self.is_some else default

    def unwrap_or_else(self, fn: Callable[[], T]) -> T:
        return self._value if self.is_some else fn()

    def map(self, fn: Callable[[T], T2]) -> "Option[T2]":
        if self.is_some:
            return Option.some(fn(self._value))
        return Option.none()

    def map_or(self, default: T2, fn: Callable[[T], T2]) -> T2:
        if self.is_some:
            return fn(self._value)
        return default

    def map_or_else(self, default_fn: Callable[[], T2], fn: Callable[[T], T2]) -> T2:
        if self.is_some:
            return fn(self._value)
        return default_fn()

    def and_then(self, fn: Callable[[T], "Option[T2]"]) -> "Option[T2]":
        if self.is_some:
            return fn(self._value)
        return Option.none()

    def or_else(self, fn: Callable[[], "Option[T]"]) -> "Option[T]":
        if self.is_some:
            return self
        return fn()

    def filter(self, predicate: Callable[[T], bool]) -> "Option[T]":
        if self.is_some and predicate(self._value):
            return self
        return Option.none()

    def inspect(self, fn: Callable[[T], None]) -> "Option[T]":
        if self.is_some:
            fn(self._value)
        return self

    def flatten(self: "Option[Option[T]]") -> "Option[T]":
        if self.is_some:
            return self._value
        return Option.none()

    def zip(self, other: "Option[T2]") -> "Option[tuple[T, T2]]":
        if self.is_some and other.is_some:
            return Option.some((self._value, other._value))
        return Option.none()

    def ok_or(self, err: E):
        from typing import cast
        if self.is_some:
            return Result.ok(self._value)  # requires your Result class
        return Result.err(cast(E, err))
