from pathlib import Path

from kohle.infrastructure.device_config import LedgerMode


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
    def __init__(self, path: Path, mode: LedgerMode):
        super().__init__()
        self.path = path
        self.mode = mode

    def __str__(self) -> str:
        if self.mode == "reader":
            return f"no ledger at {self.path}; this device is configured as a reader and never creates one"
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


class SnapshotExists(LedgerError):
    def __init__(self, dest: Path):
        super().__init__()
        self.dest = dest

    def __str__(self) -> str:
        return f"{self.dest} already exists; snapshot never overwrites a file"


class SnapshotFailed(LedgerError):
    def __init__(self, dest: Path, reason: str):
        super().__init__()
        self.dest = dest
        self.reason = reason

    def __str__(self) -> str:
        return f"writing a snapshot to {self.dest} failed: {self.reason}"


class LedgerBusy(LedgerError):
    def __str__(self) -> str:
        return "the ledger stayed locked by another process; nothing was changed, try again"
