"""Typed exceptions for the pydoglog library."""


class DogLogError(Exception):
    """Base exception for all pydoglog errors."""


class DogLogAuthError(DogLogError):
    """Authentication or authorization failure."""


class DogLogAPIError(DogLogError):
    """Firebase API request failed."""

    def __init__(self, message: str, status_code: int | None = None, path: str | None = None):
        self.status_code = status_code
        self.path = path
        super().__init__(message)


class DogLogNotFoundError(DogLogAPIError):
    """Requested resource was not found."""
