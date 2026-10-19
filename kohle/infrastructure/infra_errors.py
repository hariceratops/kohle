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


class LedgerBuildFailed(LedgerError):
    def __init__(self, path: Path, reason: str):
        super().__init__()
        self.path = path
        self.reason = reason

    def __str__(self) -> str:
        return f"building the ledger at {self.path} failed and left it as it was: {self.reason}"


class LedgerExists(LedgerError):
    """Interim: 051 replaces it with the existing-ledger comparison."""

    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def __str__(self) -> str:
        return f"a ledger already exists at {self.path}"
