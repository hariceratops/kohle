class InfrastructureError(Exception):
    pass


class UniqueViolation(InfrastructureError):
    def __init__(self, constraint: str):
        self.constraint = constraint


def check_if_unique_constraint_failed(err: InfrastructureError, column_name: str) -> bool:
    return \
        isinstance(err, UniqueViolation) and err.constraint == \
        f"UNIQUE constraint failed: {column_name}"

