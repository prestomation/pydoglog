"""pydoglog - Python client library for the DogLog pet tracking service."""

from .client import DogLogClient
from .exceptions import DogLogAPIError, DogLogAuthError, DogLogError, DogLogNotFoundError
from .models import Dog, DogEvent, EventType, Pack

__version__ = "0.1.0"

__all__ = [
    "DogLogClient",
    "DogLogAuthError",
    "DogLogAPIError",
    "DogLogError",
    "DogLogNotFoundError",
    "Dog",
    "DogEvent",
    "EventType",
    "Pack",
]
