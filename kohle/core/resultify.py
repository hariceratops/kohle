from typing import TypeVar, Callable, Any, Generic
from kohle.core.result import Result
from kohle.core.option import Option


T = TypeVar("T")
E = TypeVar("E")


class _ResultShortCircuit(Generic[E], Exception):
    def __init__(self, err: E) -> None:
        self.err = err


def q(result: Result[T, E]) -> T:
    if result.is_err:
        raise _ResultShortCircuit(result.unwrap_err())
    return result.unwrap()


def resultify(fn: Callable[..., T]) -> Callable[..., Result[T, E]]:
    def wrapper(*args: Any, **kwargs: Any) -> Result[T, E]:
        try:
            value = fn(*args, **kwargs)
            return Result.ok(value)
        except _ResultShortCircuit as e:
            return Result.err(e.err)
    return wrapper

