from pathlib import Path


class InfrastructureError(Exception):
    pass


class UniqueViolation(InfrastructureError):
    def __init__(self, constraint: str):
        self.constraint = constraint


# todo better error contents
class SerializationFailed(InfrastructureError):
    pass


def check_if_unique_constraint_failed(err: InfrastructureError, column_name: str) -> bool:
    return \
        isinstance(err, UniqueViolation) and err.constraint == \
        f"UNIQUE constraint failed: {column_name}"

#todo null constraint failed



class LedgerError(Exception):
    pass


class NoLedger(LedgerError):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def __str__(self) -> str:
        return f"no ledger at {self.path}; run `kohle-cli init`"


class LedgerBehind(LedgerError):
    def __init__(self, path: Path, stored: str | None, head: str):
        super().__init__()
        self.path = path
        self.stored = stored
        self.head = head

    def __str__(self) -> str:
        return (
            f"ledger at {self.path} is at revision {self.stored or 'none'}, "
            f"this kohle needs {self.head}; run `kohle-cli migrate`"
        )


class LedgerAhead(LedgerError):
    def __init__(self, path: Path, stored: str):
        super().__init__()
        self.path = path
        self.stored = stored

    def __str__(self) -> str:
        return f"ledger at {self.path} is at revision {self.stored}, which this kohle does not know; upgrade kohle"


class LedgerUnreadable(LedgerError):
    def __init__(self, path: Path, reason: str):
        super().__init__()
        self.path = path
        self.reason = reason

    def __str__(self) -> str:
        return f"cannot read ledger at {self.path}: {self.reason}"


class LedgerBuildFailed(LedgerError):
    def __init__(self, path: Path, reason: str):
        super().__init__()
        self.path = path
        self.reason = reason

    def __str__(self) -> str:
        return f"building the ledger at {self.path} failed and left it as it was: {self.reason}"
