"""Async DogLog API client using aiohttp."""

from __future__ import annotations

import json
import time
from pathlib import Path

import aiohttp

from .auth import (
    DEFAULT_CONFIG_PATH,
    FIREBASE_API_KEY,
    load_config,
    save_config,
)
from .exceptions import DogLogAPIError, DogLogAuthError, DogLogNotFoundError
from .models import Dog, DogEvent, EventType, Pack

FIREBASE_DB_URL = "https://doglog-18366.firebaseio.com"


class AsyncDogLogClient:
    """Async client for the DogLog Firebase backend.

    Usage::

        async with AsyncDogLogClient() as client:
            dogs = await client.get_dogs()
            events = await client.list_events(pack_id, dog_id)
    """

    def __init__(
        self,
        id_token: str | None = None,
        refresh_token: str | None = None,
        uid: str | None = None,
        email: str | None = None,
        config_path: str | Path | None = None,
        session: aiohttp.ClientSession | None = None,
    ):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.id_token = id_token
        self.refresh_token = refresh_token
        self.uid = uid
        self.email = email
        self.expires_at: float = 0
        self._session = session
        self._owns_session = session is None

        # If no explicit credentials provided, load from config file
        if not id_token:
            cfg = load_config(self.config_path)
            self.id_token = cfg.get("id_token")
            self.refresh_token = cfg.get("refresh_token")
            self.uid = cfg.get("uid")
            self.email = cfg.get("email")
            self.expires_at = cfg.get("expires_at", 0)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session and not self._session.closed and self._owns_session:
            await self._session.close()

    async def __aenter__(self) -> AsyncDogLogClient:
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def _save(self) -> None:
        save_config({
            "id_token": self.id_token,
            "refresh_token": self.refresh_token,
            "uid": self.uid,
            "email": self.email,
            "expires_at": self.expires_at,
        }, self.config_path)

    async def _refresh_token(self) -> None:
        """Refresh the ID token using the refresh token via aiohttp."""
        if not self.refresh_token:
            raise DogLogAuthError("Session expired and no refresh token available.")
        session = await self._get_session()
        async with session.post(
            f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}",
            json={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise DogLogAuthError(f"Token refresh failed: {text}")
            data = await resp.json()
        try:
            self.id_token = data["id_token"]
            self.refresh_token = data["refresh_token"]
            self.expires_at = time.time() + int(data["expires_in"]) - 60
        except (KeyError, ValueError) as exc:
            raise DogLogAuthError(
                f"Malformed token refresh response: {exc}"
            ) from exc
        self._save()

    async def ensure_token(self) -> None:
        """Ensure we have a valid (non-expired) ID token."""
        if not self.id_token:
            raise DogLogAuthError("Not authenticated. Login first.")
        if time.time() >= self.expires_at:
            await self._refresh_token()

    # -- Low-level Firebase DB helpers --

    async def _request(self, method: str, path: str, json_data=None):
        """Make an authenticated request to Firebase RTDB, retrying once on 401."""
        await self.ensure_token()
        session = await self._get_session()
        url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"

        async with session.request(method, url, json=json_data) as resp:
            status = resp.status
            if status == 401:
                pass  # will retry below
            elif status != 200:
                text = await resp.text()
                raise DogLogAPIError(
                    f"Firebase {method} {path} failed: {status} {text}",
                    status_code=status,
                    path=path,
                )
            else:
                body = await resp.read()
                if not body or body.strip() == b"null":
                    return None
                try:
                    return json.loads(body)
                except json.JSONDecodeError as exc:
                    raise DogLogAPIError(
                        f"Invalid JSON response for {method} {path}: {exc}",
                        path=path,
                    ) from exc

        # 401 path: try one refresh and retry
        if self.refresh_token:
            await self._refresh_token()
            url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"
            async with session.request(method, url, json=json_data) as resp:
                status = resp.status
                if status == 401:
                    raise DogLogAuthError(f"Authentication failed for {path}")
                if status != 200:
                    text = await resp.text()
                    raise DogLogAPIError(
                        f"Firebase {method} {path} failed: {status} {text}",
                        status_code=status,
                        path=path,
                    )
                body = await resp.read()
                if not body or body.strip() == b"null":
                    return None
                try:
                    return json.loads(body)
                except json.JSONDecodeError as exc:
                    raise DogLogAPIError(
                        f"Invalid JSON response for {method} {path}: {exc}",
                        path=path,
                    ) from exc

        raise DogLogAuthError(f"Authentication failed for {path}")

    async def _db_get(self, path: str):
        return await self._request("GET", path)

    async def _db_put(self, path: str, data):
        return await self._request("PUT", path, json_data=data)

    async def _db_post(self, path: str, data):
        return await self._request("POST", path, json_data=data)

    async def _db_patch(self, path: str, data):
        return await self._request("PATCH", path, json_data=data)

    async def _db_delete(self, path: str):
        return await self._request("DELETE", path)

    # -- Public API --

    def _require_uid(self) -> str:
        """Return uid or raise DogLogAuthError if not set."""
        if not self.uid:
            raise DogLogAuthError("No uid available. Login first.")
        return self.uid

    async def get_packs(self) -> list[Pack]:
        """Return all packs the current user belongs to."""
        self._require_uid()
        await self.ensure_token()
        user = await self._db_get(f"users/{self.uid}")
        if not user or "packs" not in user:
            return []

        packs_raw = user["packs"]
        if isinstance(packs_raw, list):
            pack_ids = [p for p in packs_raw if p]
        elif isinstance(packs_raw, dict):
            pack_ids = list(packs_raw.keys())
        else:
            return []

        packs = []
        for pid in pack_ids:
            pack_data = await self._db_get(f"packs/{pid}")
            if pack_data:
                packs.append(Pack(
                    id=pid,
                    name=pack_data.get("name", "Unnamed"),
                    owner=pack_data.get("mod", ""),
                    members=pack_data.get("members", {}),
                ))
        return packs

    async def get_dogs(self, pack_id: str | None = None) -> list[Dog]:
        """Return all dogs, optionally filtered to a single pack."""
        if not pack_id:
            self._require_uid()
        await self.ensure_token()
        if pack_id:
            pack_ids = [pack_id]
        else:
            user = await self._db_get(f"users/{self.uid}")
            if not user:
                return []
            packs_raw = user.get("packs", [])
            if isinstance(packs_raw, list):
                pack_ids = [p for p in packs_raw if p]
            elif isinstance(packs_raw, dict):
                pack_ids = list(packs_raw.keys())
            else:
                return []

        dogs = []
        for pid in pack_ids:
            pets_data = await self._db_get(f"packs/{pid}/pets")
            if pets_data and isinstance(pets_data, dict):
                for pet_id, pet in pets_data.items():
                    if not isinstance(pet, dict):
                        continue
                    dogs.append(Dog(
                        id=pet_id,
                        name=pet.get("name", "Unnamed"),
                        pack_id=pid,
                        free=bool(pet.get("free", False)),
                        profile=pet.get("profile", {}),
                    ))
        return dogs

    async def list_events(
        self,
        pack_id: str,
        dog_id: str | None = None,
        limit: int = 50,
        event_type: EventType | str | None = None,
    ) -> list[DogEvent]:
        """Fetch events for a pack, optionally filtered by dog and/or event type."""
        if isinstance(event_type, str):
            event_type = EventType.from_name(event_type)

        raw = await self._db_get(f"packs/{pack_id}/events")
        if not raw or not isinstance(raw, dict):
            return []

        events = []
        for eid, ev in raw.items():
            if not isinstance(ev, dict):
                continue
            if dog_id and ev.get("petId") != dog_id and ev.get("pet") != dog_id:
                continue
            if event_type is not None and ev.get("type") != event_type.value:
                continue
            events.append(DogEvent.from_firebase(eid, ev))

        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    async def create_event(
        self,
        pack_id: str,
        dog_id: str,
        event_type: EventType | str,
        note: str = "",
        dog_name: str = "",
        **extra,
    ) -> str:
        """Log a new event. Returns the Firebase event ID."""
        self._require_uid()
        if isinstance(event_type, str):
            event_type = EventType.from_name(event_type)

        await self.ensure_token()
        now_ms = int(time.time() * 1000)
        event = {
            "user": self.uid,
            "userName": self.email,
            "petId": dog_id,
            "pet": dog_name or dog_id,
            "date": now_ms,
            "type": event_type.value,
            "comment": note,
            "visible": True,
            "photoevent": False,
        }

        for field in ("quantity", "quantityUnit", "weightKg", "weightPound", "weightMeasure",
                       "temperatureCelsius", "temperatureFahrenheit", "temperatureMeasure",
                       "vaccine", "glucose", "glucoseUnit", "medicineUnit", "stoolQualityUnit",
                       "startTime", "endTime"):
            if field in extra and extra[field] is not None:
                event[field] = extra[field]

        result = await self._db_post(f"packs/{pack_id}/events", event)
        return result.get("name", "") if result else ""

    async def delete_event(self, pack_id: str, event_id: str) -> None:
        """Delete an event by ID."""
        await self._db_delete(f"packs/{pack_id}/events/{event_id}")

    async def get_user_data(self) -> dict:
        """Return the raw user data dict from Firebase."""
        self._require_uid()
        await self.ensure_token()
        data = await self._db_get(f"users/{self.uid}")
        if data is None:
            raise DogLogNotFoundError("No user data found.", path=f"users/{self.uid}")
        return data

    async def db_read(self, path: str):
        """Raw Firebase RTDB read (for debugging / advanced use)."""
        return await self._db_get(path)

    async def db_write(self, path: str, data) -> None:
        """Raw Firebase RTDB write."""
        await self._db_put(path, data)
