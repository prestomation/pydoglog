"""Tests for AsyncDogLogClient."""

from __future__ import annotations

import time

import pytest
from aioresponses import aioresponses

from pydoglog.async_client import AsyncDogLogClient, FIREBASE_DB_URL
from pydoglog.auth import FIREBASE_API_KEY
from pydoglog.exceptions import DogLogAuthError, DogLogAPIError

FAKE_TOKEN = "fake-id-token"
FAKE_REFRESH = "fake-refresh-token"
FAKE_UID = "user123"
TOKEN_URL = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"


def make_client(**kwargs) -> AsyncDogLogClient:
    defaults = dict(
        id_token=FAKE_TOKEN,
        refresh_token=FAKE_REFRESH,
        uid=FAKE_UID,
        email="test@example.com",
    )
    defaults.update(kwargs)
    client = AsyncDogLogClient(**defaults)
    client.expires_at = time.time() + 3600  # not expired
    return client


def db_url(path: str) -> str:
    return f"{FIREBASE_DB_URL}/{path}.json?auth={FAKE_TOKEN}"


@pytest.mark.asyncio
async def test_get_dogs():
    client = make_client()
    async with client:
        with aioresponses() as m:
            m.get(
                db_url(f"users/{FAKE_UID}"),
                payload={"packs": {"pack1": True}},
            )
            m.get(
                db_url("packs/pack1/pets"),
                payload={
                    "dog1": {"name": "Rex", "free": False, "profile": {}},
                    "dog2": {"name": "Buddy", "free": True, "profile": {}},
                },
            )
            dogs = await client.get_dogs()
    assert len(dogs) == 2
    names = {d.name for d in dogs}
    assert names == {"Rex", "Buddy"}


@pytest.mark.asyncio
async def test_get_packs():
    client = make_client()
    async with client:
        with aioresponses() as m:
            m.get(
                db_url(f"users/{FAKE_UID}"),
                payload={"packs": {"pack1": True}},
            )
            m.get(
                db_url("packs/pack1"),
                payload={"name": "My Pack", "mod": "owner1", "members": {}},
            )
            packs = await client.get_packs()
    assert len(packs) == 1
    assert packs[0].name == "My Pack"


@pytest.mark.asyncio
async def test_list_events():
    client = make_client()
    async with client:
        with aioresponses() as m:
            m.get(
                db_url("packs/pack1/events"),
                payload={
                    "ev1": {
                        "petId": "dog1",
                        "pet": "Rex",
                        "type": 1,
                        "date": 1700000000000,
                        "user": FAKE_UID,
                        "userName": "test@example.com",
                        "comment": "",
                        "visible": True,
                        "photoevent": False,
                    },
                },
            )
            events = await client.list_events("pack1")
    assert len(events) == 1
    assert events[0].pet_name == "Rex"


@pytest.mark.asyncio
async def test_create_event():
    client = make_client()
    async with client:
        with aioresponses() as m:
            m.post(
                db_url("packs/pack1/events"),
                payload={"name": "-NewEventId"},
            )
            event_id = await client.create_event(
                "pack1", "dog1", "pee", note="Good boy", dog_name="Rex"
            )
    assert event_id == "-NewEventId"


@pytest.mark.asyncio
async def test_token_refresh_on_expiry():
    client = make_client()
    client.expires_at = 0  # expired
    async with client:
        with aioresponses() as m:
            m.post(
                TOKEN_URL,
                payload={
                    "id_token": "new-token",
                    "refresh_token": "new-refresh",
                    "expires_in": "3600",
                },
            )
            m.get(
                f"{FIREBASE_DB_URL}/users/{FAKE_UID}.json?auth=new-token",
                payload={"packs": {}},
            )
            packs = await client.get_packs()
    assert packs == []
    assert client.id_token == "new-token"


@pytest.mark.asyncio
async def test_auth_error_no_token():
    # Use a nonexistent config path so no tokens are loaded from disk
    client = AsyncDogLogClient(
        config_path="/tmp/nonexistent_doglog_config.json",
    )
    assert client.id_token is None
    async with client:
        with pytest.raises(DogLogAuthError):
            await client.get_packs()


@pytest.mark.asyncio
async def test_api_error():
    client = make_client()
    async with client:
        with aioresponses() as m:
            m.get(db_url("packs/pack1/events"), status=500, body="Internal Error")
            with pytest.raises(DogLogAPIError):
                await client.list_events("pack1")


@pytest.mark.asyncio
async def test_context_manager():
    async with AsyncDogLogClient(
        id_token=FAKE_TOKEN, refresh_token=FAKE_REFRESH, uid=FAKE_UID, email="t@t.com"
    ) as client:
        assert client._session is not None
        assert not client._session.closed
    assert client._session.closed
