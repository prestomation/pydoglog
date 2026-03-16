"""Data models for the pydoglog library."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone


class EventType(enum.IntEnum):
    FOOD = 0
    TREAT = 1
    WALK = 2
    PEE = 3
    POOP = 4
    TEETH_BRUSHING = 5
    GROOMING = 6
    TRAINING = 7
    MEDICINE = 8
    SPARE = 9
    EVENT = 10
    PHOTO = 11
    WEIGHT = 12
    TEMPERATURE = 13
    WATER = 14
    SLEEP = 15
    VACCINE = 16
    BLOOD_GLUCOSE = 17

    @classmethod
    def from_name(cls, name: str) -> EventType:
        """Look up an EventType by its name (case-insensitive)."""
        try:
            return cls[name.upper()]
        except KeyError:
            raise ValueError(f"Unknown event type: {name!r}. Valid types: {', '.join(e.name for e in cls)}")


# Category groupings (mirrors the app's EventType.java)
EVENT_CATEGORIES: dict[str, list[EventType]] = {
    "DIET": [EventType.FOOD, EventType.TREAT, EventType.WATER],
    "OUTDOORS": [EventType.WALK, EventType.PEE, EventType.POOP],
    "CARE": [EventType.TEETH_BRUSHING, EventType.GROOMING, EventType.TRAINING,
             EventType.SPARE, EventType.PHOTO, EventType.SLEEP],
    "MEDICAL": [EventType.MEDICINE, EventType.WEIGHT, EventType.TEMPERATURE,
                EventType.VACCINE, EventType.BLOOD_GLUCOSE],
    "CUSTOM": [EventType.EVENT],
}


@dataclass
class DogEvent:
    id: str
    event_type: EventType
    timestamp: datetime
    pet_id: str
    pet_name: str = ""
    note: str = ""
    created_by: str = ""
    created_by_name: str = ""
    visible: bool = True
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_firebase(cls, event_id: str, data: dict) -> DogEvent:
        """Parse a Firebase event dict into a DogEvent."""
        date_ms = data.get("date", 0)
        if date_ms > 1e12:
            ts = datetime.fromtimestamp(date_ms / 1000, tz=timezone.utc)
        elif date_ms > 0:
            ts = datetime.fromtimestamp(date_ms, tz=timezone.utc)
        else:
            ts = datetime.fromtimestamp(0, tz=timezone.utc)

        # Collect extra fields (weight, temperature, glucose, etc.)
        known_keys = {"user", "userName", "petId", "pet", "date", "type",
                       "comment", "visible", "photoevent"}
        extra = {k: v for k, v in data.items() if k not in known_keys}

        return cls(
            id=event_id,
            event_type=EventType(data.get("type", 10)),
            timestamp=ts,
            pet_id=data.get("petId", data.get("pet", "")),
            pet_name=data.get("pet", data.get("petId", "")),
            note=data.get("comment", ""),
            created_by=data.get("user", ""),
            created_by_name=data.get("userName", ""),
            visible=data.get("visible", True),
            extra=extra,
        )


@dataclass
class Dog:
    id: str
    name: str
    pack_id: str
    free: bool = False
    profile: dict = field(default_factory=dict)


@dataclass
class Pack:
    id: str
    name: str
    owner: str = ""
    members: dict = field(default_factory=dict)
