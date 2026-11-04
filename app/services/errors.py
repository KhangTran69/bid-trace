class DomainError(Exception):
    """Base exception for a user-correctable workflow error."""


class NotFound(DomainError):
    pass


class Conflict(DomainError):
    pass
