"""Tests for pydoglog.client — list/create events (mocked HTTP)."""

import json

import pytest
import responses

from pydoglog.client import DogLogClient, FIREBASE_DB_URL
from pydoglog.exceptions import DogLogAuthError, DogLogAPIError
from pydoglog.models import DogEvent, EventType


def db_url(path: str, token: str = "fake-id-token") -> str:
    return f"{FIREBASE_DB_URL}/{path}.json?auth={token}"


class TestListEvents:
    @responses.activate
    def test_returns_typed_events(self, fake_config, sample_events):
        responses.get(db_url("packs/pack1/events"), json=sample_events)

        client = DogLogClient(config_path=fake_config)
        events = client.list_events("pack1")

        assert len(events) == 5
        assert all(isinstance(e, DogEvent) for e in events)
        # Should be sorted newest-first
        assert events[0].timestamp >= events[-1].timestamp

    @responses.activate
    def test_filter_by_dog(self, fake_config, sample_events):
        responses.get(db_url("packs/pack1/events"), json=sample_events)

        client = DogLogClient(config_path=fake_config)
        events = client.list_events("pack1", dog_id="pet_002")

        assert len(events) == 1
        assert events[0].pet_name == "Luna"

    @responses.activate
    def test_filter_by_event_type(self, fake_config, sample_events):
        responses.get(db_url("packs/pack1/events"), json=sample_events)

        client = DogLogClient(config_path=fake_config)
        events = client.list_events("pack1", event_type=EventType.FOOD)

        assert len(events) == 1
        assert events[0].event_type == EventType.FOOD

    @responses.activate
    def test_filter_by_type_string(self, fake_config, sample_events):
        responses.get(db_url("packs/pack1/events"), json=sample_events)

        client = DogLogClient(config_path=fake_config)
        events = client.list_events("pack1", event_type="walk")

        assert len(events) == 1
        assert events[0].event_type == EventType.WALK

    @responses.activate
    def test_limit(self, fake_config, sample_events):
        responses.get(db_url("packs/pack1/events"), json=sample_events)

        client = DogLogClient(config_path=fake_config)
        events = client.list_events("pack1", limit=2)

        assert len(events) == 2

    @responses.activate
    def test_empty_events(self, fake_config):
        responses.get(db_url("packs/pack1/events"), json=None)

        client = DogLogClient(config_path=fake_config)
        events = client.list_events("pack1")

        assert events == []


class TestCreateEvent:
    @responses.activate
    def test_sends_correct_payload(self, fake_config):
        responses.post(db_url("packs/pack1/events"), json={"name": "-NxNewEvent123"})

        client = DogLogClient(config_path=fake_config)
        event_id = client.create_event("pack1", "pet_001", EventType.WALK, note="Evening walk")

        assert event_id == "-NxNewEvent123"

        body = json.loads(responses.calls[0].request.body)
        assert body["type"] == EventType.WALK.value
        assert body["petId"] == "pet_001"
        assert body["comment"] == "Evening walk"
        assert body["visible"] is True
        assert body["user"] == "uid_abc123"

    @responses.activate
    def test_create_with_string_type(self, fake_config):
        responses.post(db_url("packs/pack1/events"), json={"name": "-NxNew2"})

        client = DogLogClient(config_path=fake_config)
        event_id = client.create_event("pack1", "pet_001", "food")

        body = json.loads(responses.calls[0].request.body)
        assert body["type"] == 0

    @responses.activate
    def test_create_with_extra_fields(self, fake_config):
        responses.post(db_url("packs/pack1/events"), json={"name": "-NxNew3"})

        client = DogLogClient(config_path=fake_config)
        client.create_event("pack1", "pet_001", EventType.WEIGHT,
                            weightKg=25.5, weightMeasure="Kilograms")

        body = json.loads(responses.calls[0].request.body)
        assert body["weightKg"] == 25.5
        assert body["weightMeasure"] == "Kilograms"


class TestAuth:
    def test_no_token_raises(self, tmp_path):
        config = tmp_path / "empty.json"
        config.write_text("{}")
        client = DogLogClient(config_path=config)

        with pytest.raises(DogLogAuthError, match="Not authenticated"):
            client.ensure_token()

    @responses.activate
    def test_auto_refresh_on_expired_token(self, expired_config, sample_events):
        # Token refresh endpoint
        responses.post(
            "https://securetoken.googleapis.com/v1/token?key=AIzaSyCBNSh63pQeV7qB1igqF_QK56xTXuAS-zE",
            json={
                "id_token": "refreshed-token",
                "refresh_token": "new-refresh-token",
                "expires_in": "3600",
            },
        )
        # The actual DB request (with refreshed token)
        responses.get(
            db_url("packs/pack1/events", token="refreshed-token"),
            json=sample_events,
        )

        client = DogLogClient(config_path=expired_config)
        events = client.list_events("pack1")

        assert len(events) == 5
        assert client.id_token == "refreshed-token"

    @responses.activate
    def test_api_error_raised(self, fake_config):
        responses.get(db_url("packs/pack1/events"), json={"error": "Permission denied"}, status=403)

        client = DogLogClient(config_path=fake_config)
        with pytest.raises(DogLogAPIError):
            client.list_events("pack1")
