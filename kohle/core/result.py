from dataclasses import dataclass
from typing import Generic, TypeVar, Optional, Callable

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True)
class Result(Generic[T, E]):
    _ok: Optional[T] = None
    _err: Optional[E] = None

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
        return self._err

    def map(self, fn: Callable[[T], T]) -> "Result[T, E]":
        if self.is_ok:
            return Result.ok(fn(self._ok))
        return self  # type: ignore

    def map_err(self, fn: Callable[[E], E]) -> "Result[T, E]":
        if self.is_err:
            return Result.err(fn(self._err))
        return self  # type: ignore

