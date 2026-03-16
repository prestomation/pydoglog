"""DogLog API client."""

from __future__ import annotations

import time
from pathlib import Path

import requests

from .auth import (
    DEFAULT_CONFIG_PATH,
    load_config,
    refresh_id_token,
    save_config,
)
from .exceptions import DogLogAPIError, DogLogAuthError, DogLogNotFoundError
from .models import Dog, DogEvent, EventType, Pack

FIREBASE_DB_URL = "https://doglog-18366.firebaseio.com"


class DogLogClient:
    """Synchronous client for the DogLog Firebase backend.

    Usage::

        client = DogLogClient()                     # loads ~/.doglog/config.json
        client = DogLogClient(config_path="creds.json")
        client = DogLogClient(id_token="...", refresh_token="...", uid="...", email="...")

        dogs = client.get_dogs()
        events = client.list_events(pack_id, dog_id)
    """

    def __init__(
        self,
        id_token: str | None = None,
        refresh_token: str | None = None,
        uid: str | None = None,
        email: str | None = None,
        config_path: str | Path | None = None,
    ):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.id_token = id_token
        self.refresh_token = refresh_token
        self.uid = uid
        self.email = email
        self.expires_at: float = 0

        # If no explicit credentials provided, load from config file
        if not id_token:
            cfg = load_config(self.config_path)
            self.id_token = cfg.get("id_token")
            self.refresh_token = cfg.get("refresh_token")
            self.uid = cfg.get("uid")
            self.email = cfg.get("email")
            self.expires_at = cfg.get("expires_at", 0)

    def _save(self) -> None:
        save_config({
            "id_token": self.id_token,
            "refresh_token": self.refresh_token,
            "uid": self.uid,
            "email": self.email,
            "expires_at": self.expires_at,
        }, self.config_path)

    def ensure_token(self) -> None:
        """Ensure we have a valid (non-expired) ID token. Refreshes if needed."""
        if not self.id_token:
            raise DogLogAuthError("Not authenticated. Login first.")
        if time.time() >= self.expires_at:
            if not self.refresh_token:
                raise DogLogAuthError("Session expired and no refresh token available.")
            result = refresh_id_token(self.refresh_token)
            self.id_token = result["id_token"]
            self.refresh_token = result["refresh_token"]
            self.expires_at = result["expires_at"]
            self._save()

    # ── Low-level Firebase DB helpers ──

    def _request(self, method: str, path: str, json_data=None):
        """Make an authenticated request to Firebase RTDB, retrying once on 401."""
        self.ensure_token()
        url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"
        resp = requests.request(method, url, json=json_data)

        if resp.status_code == 401:
            # Token might have been invalidated server-side; try one refresh
            if self.refresh_token:
                result = refresh_id_token(self.refresh_token)
                self.id_token = result["id_token"]
                self.refresh_token = result["refresh_token"]
                self.expires_at = result["expires_at"]
                self._save()
                url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"
                resp = requests.request(method, url, json=json_data)

        if resp.status_code == 401:
            raise DogLogAuthError(f"Authentication failed for {path}")
        if resp.status_code != 200:
            raise DogLogAPIError(
                f"Firebase {method} {path} failed: {resp.status_code} {resp.text}",
                status_code=resp.status_code,
                path=path,
            )
        # Firebase returns literal "null" for empty nodes
        if not resp.content or resp.content.strip() == b"null":
            return None
        return resp.json()

    def _db_get(self, path: str):
        return self._request("GET", path)

    def _db_put(self, path: str, data):
        return self._request("PUT", path, json_data=data)

    def _db_post(self, path: str, data):
        return self._request("POST", path, json_data=data)

    def _db_patch(self, path: str, data):
        return self._request("PATCH", path, json_data=data)

    def _db_delete(self, path: str):
        return self._request("DELETE", path)

    # ── Public API ──

    def get_packs(self) -> list[Pack]:
        """Return all packs the current user belongs to."""
        self.ensure_token()
        user = self._db_get(f"users/{self.uid}")
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
            pack_data = self._db_get(f"packs/{pid}")
            if pack_data:
                packs.append(Pack(
                    id=pid,
                    name=pack_data.get("name", "Unnamed"),
                    owner=pack_data.get("mod", ""),
                    members=pack_data.get("members", {}),
                ))
        return packs

    def get_dogs(self, pack_id: str | None = None) -> list[Dog]:
        """Return all dogs, optionally filtered to a single pack.

        If pack_id is None, fetches dogs from all of the user's packs.
        """
        self.ensure_token()
        if pack_id:
            pack_ids = [pack_id]
        else:
            user = self._db_get(f"users/{self.uid}")
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
            pets_data = self._db_get(f"packs/{pid}/pets")
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

    def list_events(
        self,
        pack_id: str,
        dog_id: str | None = None,
        limit: int = 50,
        event_type: EventType | str | None = None,
    ) -> list[DogEvent]:
        """Fetch events for a pack, optionally filtered by dog and/or event type."""
        if isinstance(event_type, str):
            event_type = EventType.from_name(event_type)

        raw = self._db_get(f"packs/{pack_id}/events")
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

    def create_event(
        self,
        pack_id: str,
        dog_id: str,
        event_type: EventType | str,
        note: str = "",
        dog_name: str = "",
        **extra,
    ) -> str:
        """Log a new event. Returns the Firebase event ID."""
        if isinstance(event_type, str):
            event_type = EventType.from_name(event_type)

        self.ensure_token()
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

        result = self._db_post(f"packs/{pack_id}/events", event)
        return result.get("name", "")

    def delete_event(self, pack_id: str, event_id: str) -> None:
        """Delete an event by ID."""
        self._db_delete(f"packs/{pack_id}/events/{event_id}")

    def get_user_data(self) -> dict:
        """Return the raw user data dict from Firebase."""
        self.ensure_token()
        data = self._db_get(f"users/{self.uid}")
        if data is None:
            raise DogLogNotFoundError("No user data found.", path=f"users/{self.uid}")
        return data

    def db_read(self, path: str):
        """Raw Firebase RTDB read (for debugging / advanced use)."""
        return self._db_get(path)

    def db_write(self, path: str, data) -> None:
        """Raw Firebase RTDB write."""
        self._db_put(path, data)
