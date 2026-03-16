"""Tests for pydoglog.models."""

from datetime import datetime, timezone

import pytest

from pydoglog.models import DogEvent, EventType, Dog, Pack, EVENT_CATEGORIES


class TestEventType:
    def test_all_18_types_exist(self):
        assert len(EventType) == 18

    def test_int_values(self):
        assert EventType.FOOD == 0
        assert EventType.BLOOD_GLUCOSE == 17

    def test_from_name_case_insensitive(self):
        assert EventType.from_name("walk") == EventType.WALK
        assert EventType.from_name("WALK") == EventType.WALK
        assert EventType.from_name("Walk") == EventType.WALK

    def test_from_name_invalid(self):
        with pytest.raises(ValueError, match="Unknown event type"):
            EventType.from_name("invalid_type")

    def test_categories_cover_all_types(self):
        categorized = set()
        for types in EVENT_CATEGORIES.values():
            categorized.update(types)
        assert categorized == set(EventType)


class TestDogEvent:
    def test_from_firebase_milliseconds(self):
        ev = DogEvent.from_firebase("id1", {
            "date": 1710500000000,
            "type": 0,
            "petId": "pet1",
            "pet": "Buddy",
            "comment": "Breakfast",
            "user": "uid1",
            "userName": "alice@test.com",
            "visible": True,
            "photoevent": False,
        })
        assert ev.id == "id1"
        assert ev.event_type == EventType.FOOD
        assert ev.timestamp.year == 2024
        assert ev.pet_id == "pet1"
        assert ev.pet_name == "Buddy"
        assert ev.note == "Breakfast"
        assert ev.created_by == "uid1"

    def test_from_firebase_seconds(self):
        ev = DogEvent.from_firebase("id2", {"date": 1710500000, "type": 2})
        assert ev.timestamp == datetime.fromtimestamp(1710500000, tz=timezone.utc)

    def test_from_firebase_zero_date(self):
        ev = DogEvent.from_firebase("id3", {"date": 0, "type": 10})
        assert ev.timestamp == datetime.fromtimestamp(0, tz=timezone.utc)

    def test_extra_fields_captured(self):
        ev = DogEvent.from_firebase("id4", {
            "date": 1710500000000,
            "type": 12,
            "petId": "p",
            "weightKg": 25.5,
            "weightMeasure": "Kilograms",
        })
        assert ev.extra["weightKg"] == 25.5
        assert ev.extra["weightMeasure"] == "Kilograms"


class TestDog:
    def test_creation(self):
        dog = Dog(id="p1", name="Rex", pack_id="pack1")
        assert dog.id == "p1"
        assert dog.free is False


class TestPack:
    def test_creation(self):
        pack = Pack(id="pk1", name="My Pack", owner="uid1")
        assert pack.name == "My Pack"
