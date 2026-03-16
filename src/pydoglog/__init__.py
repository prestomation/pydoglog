"""pydoglog - Python client library for the DogLog pet tracking service."""

from .async_client import AsyncDogLogClient
from .client import DogLogClient
from .exceptions import DogLogAPIError, DogLogAuthError, DogLogError, DogLogNotFoundError
from .models import Dog, DogEvent, EventType, Pack

__version__ = "0.1.1"

__all__ = [
    "AsyncDogLogClient",
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
