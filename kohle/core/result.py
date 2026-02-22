from dataclasses import dataclass
from typing import Generic, TypeVar, Callable, Union

T = TypeVar("T")
E = TypeVar("E")
T2 = TypeVar("T2")
E2 = TypeVar("E2")


@dataclass(frozen=True)
class Result(Generic[T, E]):
    _ok: Union[T, None] = None
    _err: Union[E, None] = None

    @staticmethod
    def ok(value: T) -> "Result[T, E]":
        return Result(_ok=value)

    @staticmethod
    def err(error: E) -> "Result[T, E]":
        return Result(_err=error)

    @property
    def is_ok(self) -> bool:
        return self._err is None

    @property
    def is_err(self) -> bool:
        return self._err is not None

    def unwrap(self) -> T:
        if self.is_err:
            raise RuntimeError(f"called unwrap on Err: {self._err}")
        return self._ok  # type: ignore

    def unwrap_err(self) -> E:
        if self.is_ok:
            raise RuntimeError("called unwrap_err on Ok")
        return self._err  # type: ignore

    # Transform success value
    def map(self, fn: Callable[[T], T2]) -> "Result[T2, E]":
        if self.is_ok:
            return Result.ok(fn(self._ok))  # type: ignore
        return Result.err(self._err)  # type: ignore

    # Transform error value (allows changing error type)
    def map_err(self, fn: Callable[[E], E2]) -> "Result[T, E2]":
        if self.is_err:
            return Result.err(fn(self._err))  # type: ignore
        return Result.ok(self._ok)  # type: ignore

    def and_then(self, fn: Callable[[T], "Result[T2, E]"]) -> "Result[T2, E]":
        if self.is_ok:
            return fn(self._ok)  # type: ignore
        return Result.err(self._err)  # type: ignore

    def unwrap_or(self, default: T) -> T:
        if self.is_ok:
            return self._ok  # type: ignore
        return default

