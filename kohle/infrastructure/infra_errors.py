class InfrastructureError(Exception):
    pass


class UniqueViolation(InfrastructureError):
    def __init__(self, constraint: str):
        self.constraint = constraint

