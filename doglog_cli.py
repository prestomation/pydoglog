#!/usr/bin/env python3
"""
DogLog CLI - Interact with DogLog's Firebase backend.

Reverse-engineered from com.mobikode.dog APK.
Uses Firebase Realtime Database REST API + Firebase Auth REST API.
"""

import argparse
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: 'requests' package required. Install with: pip install requests")
    sys.exit(1)

# Firebase config extracted from APK
FIREBASE_API_KEY = "AIzaSyCBNSh63pQeV7qB1igqF_QK56xTXuAS-zE"
FIREBASE_DB_URL = "https://doglog-18366.firebaseio.com"
FIREBASE_AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts"
CLOUD_FUNCTIONS_URL = "https://us-central1-doglog-18366.cloudfunctions.net"
GOOGLE_OAUTH_CLIENT_ID = "727208592142-3bvib9btsl71ddapj9b6pgn9ppvd8ov9.apps.googleusercontent.com"

CONFIG_DIR = Path.home() / ".doglog"
TOKEN_FILE = CONFIG_DIR / "config.json"

# Event type mapping from EventType.java
EVENT_TYPES = {
    0: "FOOD",
    1: "TREAT",
    2: "WALK",
    3: "PEE",
    4: "POOP",
    5: "TEETH_BRUSHING",
    6: "GROOMING",
    7: "TRAINING",
    8: "MEDICINE",
    9: "SPARE",
    10: "EVENT",
    11: "PHOTO",
    12: "WEIGHT",
    13: "TEMPERATURE",
    14: "WATER",
    15: "SLEEP",
    16: "VACCINE",
    17: "BLOOD_GLUCOSE",
}

EVENT_CATEGORIES = {
    "DIET": [0, 1, 14],       # FOOD, TREAT, WATER
    "OUTDOORS": [2, 3, 4],    # WALK, PEE, POOP
    "CARE": [5, 6, 7, 9, 11, 15],  # TEETH_BRUSHING, GROOMING, TRAINING, SPARE, PHOTO, SLEEP
    "MEDICAL": [8, 12, 13, 16, 17],  # MEDICINE, WEIGHT, TEMPERATURE, VACCINE, BLOOD_GLUCOSE
    "CUSTOM": [10],            # EVENT
}

EVENT_NAME_TO_TYPE = {v: k for k, v in EVENT_TYPES.items()}


class DogLogClient:
    def __init__(self):
        self.id_token = None
        self.refresh_token = None
        self.uid = None
        self.email = None
        self.expires_at = 0
        self._load_token()

    def _load_token(self):
        if TOKEN_FILE.exists():
            try:
                data = json.loads(TOKEN_FILE.read_text())
                self.id_token = data.get("id_token")
                self.refresh_token = data.get("refresh_token")
                self.uid = data.get("uid")
                self.email = data.get("email")
                self.expires_at = data.get("expires_at", 0)
            except (json.JSONDecodeError, OSError):
                pass

    def _save_token(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps({
            "id_token": self.id_token,
            "refresh_token": self.refresh_token,
            "uid": self.uid,
            "email": self.email,
            "expires_at": self.expires_at,
        }, indent=2))
        TOKEN_FILE.chmod(0o600)

    def _ensure_auth(self):
        if not self.id_token:
            print("Not logged in. Run: doglog_cli.py login --email EMAIL --password PASSWORD")
            sys.exit(1)
        if time.time() >= self.expires_at:
            self._refresh_auth()

    def _refresh_auth(self):
        if not self.refresh_token:
            print("Session expired and no refresh token. Please login again.")
            sys.exit(1)
        resp = requests.post(
            f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}",
            json={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
        )
        if resp.status_code != 200:
            print(f"Token refresh failed: {resp.text}")
            sys.exit(1)
        data = resp.json()
        self.id_token = data["id_token"]
        self.refresh_token = data["refresh_token"]
        self.expires_at = time.time() + int(data["expires_in"]) - 60
        self._save_token()

    def login(self, email: str, password: str):
        resp = requests.post(
            f"{FIREBASE_AUTH_URL}:signInWithPassword?key={FIREBASE_API_KEY}",
            json={
                "email": email,
                "password": password,
                "returnSecureToken": True,
            },
        )
        if resp.status_code != 200:
            err = resp.json().get("error", {})
            print(f"Login failed: {err.get('message', resp.text)}")
            sys.exit(1)
        data = resp.json()
        self.id_token = data["idToken"]
        self.refresh_token = data["refreshToken"]
        self.uid = data["localId"]
        self.email = data["email"]
        self.expires_at = time.time() + int(data["expiresIn"]) - 60
        self._save_token()
        print(f"Logged in as {self.email} (uid: {self.uid})")

    def signup(self, email: str, password: str):
        resp = requests.post(
            f"{FIREBASE_AUTH_URL}:signUp?key={FIREBASE_API_KEY}",
            json={
                "email": email,
                "password": password,
                "returnSecureToken": True,
            },
        )
        if resp.status_code != 200:
            err = resp.json().get("error", {})
            print(f"Signup failed: {err.get('message', resp.text)}")
            sys.exit(1)
        data = resp.json()
        self.id_token = data["idToken"]
        self.refresh_token = data["refreshToken"]
        self.uid = data["localId"]
        self.email = data["email"]
        self.expires_at = time.time() + int(data["expiresIn"]) - 60
        self._save_token()
        print(f"Account created: {self.email} (uid: {self.uid})")

    def login_google(self):
        """Google Sign-In via local browser OAuth flow.

        Spins up a temporary localhost HTTP server to receive the OAuth callback,
        opens the browser to Google's authorization endpoint, exchanges the auth
        code for a Google ID token, then exchanges that for a Firebase ID token.
        """
        # Generate PKCE code verifier + challenge for security
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            hashlib.sha256(code_verifier.encode()).digest()
        )
        import base64
        code_challenge_b64 = base64.urlsafe_b64encode(code_challenge).rstrip(b"=").decode()

        state = secrets.token_urlsafe(32)
        redirect_port = 8914
        redirect_uri = f"http://localhost:{redirect_port}"

        # Mutable container for the callback result
        result = {"code": None, "error": None}
        server_ready = threading.Event()

        class OAuthHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)

                if "error" in params:
                    result["error"] = params["error"][0]
                elif "code" in params:
                    received_state = params.get("state", [None])[0]
                    if received_state != state:
                        result["error"] = "State mismatch — possible CSRF attack"
                    else:
                        result["code"] = params["code"][0]
                else:
                    result["error"] = "No code or error in callback"

                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                if result["code"]:
                    self.wfile.write(b"<html><body><h2>Login successful!</h2>"
                                    b"<p>You can close this tab.</p></body></html>")
                else:
                    msg = result["error"] or "Unknown error"
                    self.wfile.write(f"<html><body><h2>Login failed</h2>"
                                    f"<p>{msg}</p></body></html>".encode())

            def log_message(self, format, *args):
                pass  # Suppress request logging

        server = http.server.HTTPServer(("127.0.0.1", redirect_port), OAuthHandler)
        server.timeout = 120  # 2 minute timeout waiting for callback

        # Build Google OAuth URL
        auth_params = urllib.parse.urlencode({
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": code_challenge_b64,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        })
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{auth_params}"

        print(f"Opening browser for Google Sign-In...")
        print(f"If the browser doesn't open, visit:\n{auth_url}\n")
        webbrowser.open(auth_url)

        # Wait for the callback
        server.handle_request()
        server.server_close()

        if result["error"]:
            print(f"Google login failed: {result['error']}")
            sys.exit(1)
        if not result["code"]:
            print("No authorization code received.")
            sys.exit(1)

        # Exchange auth code for Google tokens
        token_resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": result["code"],
                "client_id": GOOGLE_OAUTH_CLIENT_ID,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )
        if token_resp.status_code != 200:
            print(f"Token exchange failed: {token_resp.text}")
            sys.exit(1)

        google_tokens = token_resp.json()
        google_id_token = google_tokens.get("id_token")
        if not google_id_token:
            print("No ID token in Google response.")
            sys.exit(1)

        # Exchange Google ID token for Firebase ID token
        firebase_resp = requests.post(
            f"{FIREBASE_AUTH_URL}:signInWithIdp?key={FIREBASE_API_KEY}",
            json={
                "postBody": f"id_token={google_id_token}&providerId=google.com",
                "requestUri": redirect_uri,
                "returnIdpCredential": True,
                "returnSecureToken": True,
            },
        )
        if firebase_resp.status_code != 200:
            err = firebase_resp.json().get("error", {})
            print(f"Firebase sign-in failed: {err.get('message', firebase_resp.text)}")
            sys.exit(1)

        data = firebase_resp.json()
        self.id_token = data["idToken"]
        self.refresh_token = data["refreshToken"]
        self.uid = data["localId"]
        self.email = data.get("email", "")
        self.expires_at = time.time() + int(data.get("expiresIn", 3600)) - 60
        self._save_token()
        print(f"Logged in as {self.email} (uid: {self.uid})")

    def _db_get(self, path: str):
        self._ensure_auth()
        url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"
        resp = requests.get(url)
        if resp.status_code == 401:
            self._refresh_auth()
            url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"
            resp = requests.get(url)
        if resp.status_code != 200:
            print(f"DB read failed ({path}): {resp.status_code} {resp.text}")
            return None
        return resp.json()

    def _db_put(self, path: str, data):
        self._ensure_auth()
        url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"
        resp = requests.put(url, json=data)
        if resp.status_code == 401:
            self._refresh_auth()
            url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"
            resp = requests.put(url, json=data)
        if resp.status_code != 200:
            print(f"DB write failed ({path}): {resp.status_code} {resp.text}")
            return None
        return resp.json()

    def _db_post(self, path: str, data):
        self._ensure_auth()
        url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"
        resp = requests.post(url, json=data)
        if resp.status_code == 401:
            self._refresh_auth()
            url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"
            resp = requests.post(url, json=data)
        if resp.status_code != 200:
            print(f"DB push failed ({path}): {resp.status_code} {resp.text}")
            return None
        return resp.json()

    def _db_patch(self, path: str, data):
        self._ensure_auth()
        url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"
        resp = requests.patch(url, json=data)
        if resp.status_code == 401:
            self._refresh_auth()
            url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"
            resp = requests.patch(url, json=data)
        if resp.status_code != 200:
            print(f"DB patch failed ({path}): {resp.status_code} {resp.text}")
            return None
        return resp.json()

    def _db_delete(self, path: str):
        self._ensure_auth()
        url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"
        resp = requests.delete(url)
        if resp.status_code == 401:
            self._refresh_auth()
            url = f"{FIREBASE_DB_URL}/{path}.json?auth={self.id_token}"
            resp = requests.delete(url)
        if resp.status_code != 200:
            print(f"DB delete failed ({path}): {resp.status_code} {resp.text}")
            return False
        return True

    # ── User commands ──

    def get_user(self):
        self._ensure_auth()
        data = self._db_get(f"users/{self.uid}")
        if data:
            print(json.dumps(data, indent=2))
        else:
            print("No user data found.")
        return data

    def whoami(self):
        self._ensure_auth()
        print(f"UID:   {self.uid}")
        print(f"Email: {self.email}")
        data = self._db_get(f"users/{self.uid}")
        if data:
            print(f"Name:  {data.get('name', 'N/A')}")
            print(f"Premium: {data.get('premium', False)}")
            packs = data.get("packs", [])
            if isinstance(packs, list):
                print(f"Packs: {len(packs)}")
            pets = data.get("pets", [])
            if isinstance(pets, list):
                print(f"Pets:  {len(pets)}")

    # ── Pack commands ──

    def list_packs(self):
        self._ensure_auth()
        user = self._db_get(f"users/{self.uid}")
        if not user or "packs" not in user:
            print("No packs found.")
            return
        packs = user["packs"]
        if isinstance(packs, list):
            pack_ids = [p for p in packs if p]
        else:
            pack_ids = list(packs.keys()) if isinstance(packs, dict) else []

        for pid in pack_ids:
            pack = self._db_get(f"packs/{pid}")
            if pack:
                name = pack.get("name", "Unnamed")
                mod = pack.get("mod", "?")
                print(f"  [{pid}] {name} (owner: {mod})")

    def get_pack(self, pack_id: str):
        data = self._db_get(f"packs/{pack_id}")
        if data:
            print(json.dumps(data, indent=2, default=str))
        else:
            print(f"Pack {pack_id} not found.")
        return data

    # ── Pet commands ──

    def list_pets(self, pack_id: str = None):
        self._ensure_auth()
        if pack_id:
            pets = self._db_get(f"packs/{pack_id}/pets")
        else:
            user = self._db_get(f"users/{self.uid}")
            if not user:
                print("No user data.")
                return
            pack_ids = user.get("packs", [])
            if isinstance(pack_ids, list):
                pack_ids = [p for p in pack_ids if p]
            else:
                pack_ids = list(pack_ids.keys()) if isinstance(pack_ids, dict) else []

            pets = {}
            for pid in pack_ids:
                pack_pets = self._db_get(f"packs/{pid}/pets")
                if pack_pets and isinstance(pack_pets, dict):
                    for k, v in pack_pets.items():
                        v["_pack"] = pid
                        pets[k] = v

        if not pets:
            print("No pets found.")
            return

        for pet_id, pet in pets.items():
            name = pet.get("name", "Unnamed") if isinstance(pet, dict) else str(pet)
            pack_info = f" (pack: {pet.get('_pack', '?')})" if isinstance(pet, dict) and "_pack" in pet else ""
            free = pet.get("free", "") if isinstance(pet, dict) else ""
            free_str = " [free]" if free else ""
            print(f"  [{pet_id}] {name}{free_str}{pack_info}")

    def get_pet_profile(self, pack_id: str, pet_id: str):
        profile = self._db_get(f"packs/{pack_id}/pets/{pet_id}/profile")
        if profile:
            print(json.dumps(profile, indent=2, default=str))
        else:
            print("No profile found.")
        return profile

    # ── Event commands ──

    def list_events(self, pack_id: str, pet_id: str = None, limit: int = 20, event_type: str = None):
        events = self._db_get(f"packs/{pack_id}/events")
        if not events:
            print("No events found.")
            return

        items = []
        if isinstance(events, dict):
            for eid, ev in events.items():
                if not isinstance(ev, dict):
                    continue
                if pet_id and ev.get("petId") != pet_id and ev.get("pet") != pet_id:
                    continue
                if event_type:
                    type_int = EVENT_NAME_TO_TYPE.get(event_type.upper())
                    if type_int is not None and ev.get("type") != type_int:
                        continue
                ev["_id"] = eid
                items.append(ev)

        items.sort(key=lambda e: e.get("date", 0), reverse=True)
        items = items[:limit]

        for ev in items:
            eid = ev.get("_id", "?")
            date_ms = ev.get("date", 0)
            if date_ms > 1e12:
                dt = datetime.fromtimestamp(date_ms / 1000, tz=timezone.utc)
            elif date_ms > 0:
                dt = datetime.fromtimestamp(date_ms, tz=timezone.utc)
            else:
                dt = None
            date_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "?"
            etype = EVENT_TYPES.get(ev.get("type", -1), f"type={ev.get('type')}")
            pet_name = ev.get("pet", ev.get("petId", "?"))
            user_name = ev.get("userName", ev.get("user", "?"))
            comment = ev.get("comment", "")
            comment_str = f' "{comment}"' if comment else ""
            print(f"  [{date_str}] {etype:<15} {pet_name:<12} by {user_name}{comment_str}")

    def log_event(self, pack_id: str, pet_id: str, event_type: str, comment: str = "",
                  pet_name: str = "", **kwargs):
        self._ensure_auth()
        type_int = EVENT_NAME_TO_TYPE.get(event_type.upper())
        if type_int is None:
            print(f"Unknown event type: {event_type}")
            print(f"Valid types: {', '.join(EVENT_TYPES.values())}")
            sys.exit(1)

        now_ms = int(time.time() * 1000)
        event = {
            "user": self.uid,
            "userName": self.email,
            "petId": pet_id,
            "pet": pet_name or pet_id,
            "date": now_ms,
            "type": type_int,
            "comment": comment,
            "visible": True,
            "photoevent": False,
        }

        # Optional fields
        for field in ["quantity", "quantityUnit", "weightKg", "weightPound", "weightMeasure",
                      "temperatureCelsius", "temperatureFahrenheit", "temperatureMeasure",
                      "vaccine", "glucose", "glucoseUnit", "medicineUnit", "stoolQualityUnit",
                      "startTime", "endTime"]:
            if field in kwargs and kwargs[field] is not None:
                event[field] = kwargs[field]

        result = self._db_post(f"packs/{pack_id}/events", event)
        if result:
            event_id = result.get("name", "?")
            print(f"Event logged: {EVENT_TYPES[type_int]} for {pet_name or pet_id} (id: {event_id})")
            return event_id
        return None

    def delete_event(self, pack_id: str, event_id: str):
        if self._db_delete(f"packs/{pack_id}/events/{event_id}"):
            print(f"Event {event_id} deleted.")

    # ── Content commands ──

    def get_breeds(self):
        data = self._db_get("content/breedValues")
        if data:
            if isinstance(data, dict):
                for k, v in sorted(data.items()):
                    print(f"  {v}" if isinstance(v, str) else f"  {k}: {v}")
            else:
                print(json.dumps(data, indent=2))
        else:
            print("No breed data found.")

    def get_foods(self):
        data = self._db_get("content/foodValues")
        if data:
            if isinstance(data, dict):
                for k, v in sorted(data.items()):
                    print(f"  {v}" if isinstance(v, str) else f"  {k}: {v}")
            else:
                print(json.dumps(data, indent=2))
        else:
            print("No food data found.")

    # ── Raw DB access ──

    def db_read(self, path: str):
        data = self._db_get(path)
        if data is not None:
            print(json.dumps(data, indent=2, default=str))
        else:
            print(f"No data at {path}")

    def db_write(self, path: str, value: str):
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            data = value
        result = self._db_put(path, data)
        if result is not None:
            print(f"Written to {path}")

    def logout(self):
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
        print("Logged out.")


def main():
    parser = argparse.ArgumentParser(
        description="DogLog CLI - interact with DogLog Firebase backend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s login --email user@example.com --password secret
  %(prog)s login-google
  %(prog)s whoami
  %(prog)s packs
  %(prog)s pets
  %(prog)s pets --pack PACK_ID
  %(prog)s events PACK_ID
  %(prog)s events PACK_ID --pet PET_ID --type WALK --limit 10
  %(prog)s log PACK_ID PET_ID FOOD --comment "Ate kibble"
  %(prog)s log PACK_ID PET_ID WEIGHT --weight-kg 25.5
  %(prog)s profile PACK_ID PET_ID
  %(prog)s breeds
  %(prog)s db-read users/SOME_UID
  %(prog)s logout
""",
    )

    sub = parser.add_subparsers(dest="command", help="Command")

    # login
    p_login = sub.add_parser("login", help="Login with email/password")
    p_login.add_argument("--email", required=True)
    p_login.add_argument("--password", required=True)

    # signup
    p_signup = sub.add_parser("signup", help="Create account with email/password")
    p_signup.add_argument("--email", required=True)
    p_signup.add_argument("--password", required=True)

    # login-google
    sub.add_parser("login-google", help="Login via Google Sign-In (opens browser)")

    # whoami
    sub.add_parser("whoami", help="Show current user info")

    # user
    sub.add_parser("user", help="Get raw user data")

    # packs
    p_packs = sub.add_parser("packs", help="List your packs")

    # pack
    p_pack = sub.add_parser("pack", help="Get pack details")
    p_pack.add_argument("pack_id")

    # pets
    p_pets = sub.add_parser("pets", help="List pets")
    p_pets.add_argument("--pack", dest="pack_id", help="Filter by pack ID")

    # profile
    p_profile = sub.add_parser("profile", help="Get pet profile")
    p_profile.add_argument("pack_id")
    p_profile.add_argument("pet_id")

    # events
    p_events = sub.add_parser("events", help="List events")
    p_events.add_argument("pack_id")
    p_events.add_argument("--pet", dest="pet_id")
    p_events.add_argument("--type", dest="event_type", choices=[v.lower() for v in EVENT_TYPES.values()])
    p_events.add_argument("--limit", type=int, default=20)

    # log
    p_log = sub.add_parser("log", help="Log an event")
    p_log.add_argument("pack_id")
    p_log.add_argument("pet_id")
    p_log.add_argument("event_type", choices=[v.lower() for v in EVENT_TYPES.values()])
    p_log.add_argument("--comment", default="")
    p_log.add_argument("--pet-name", default="")
    p_log.add_argument("--quantity", type=float)
    p_log.add_argument("--quantity-unit")
    p_log.add_argument("--weight-kg", type=float)
    p_log.add_argument("--weight-lb", type=float)
    p_log.add_argument("--temp-c", type=float)
    p_log.add_argument("--temp-f", type=float)
    p_log.add_argument("--vaccine")
    p_log.add_argument("--glucose", type=float)
    p_log.add_argument("--glucose-unit", choices=["mg/dL", "mmol/L"])

    # delete-event
    p_del = sub.add_parser("delete-event", help="Delete an event")
    p_del.add_argument("pack_id")
    p_del.add_argument("event_id")

    # breeds
    sub.add_parser("breeds", help="List breed database")

    # foods
    sub.add_parser("foods", help="List food database")

    # db-read
    p_dbr = sub.add_parser("db-read", help="Raw database read")
    p_dbr.add_argument("path")

    # db-write
    p_dbw = sub.add_parser("db-write", help="Raw database write")
    p_dbw.add_argument("path")
    p_dbw.add_argument("value")

    # logout
    sub.add_parser("logout", help="Clear saved credentials")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    client = DogLogClient()

    if args.command == "login":
        client.login(args.email, args.password)
    elif args.command == "signup":
        client.signup(args.email, args.password)
    elif args.command == "login-google":
        client.login_google()
    elif args.command == "logout":
        client.logout()
    elif args.command == "whoami":
        client.whoami()
    elif args.command == "user":
        client.get_user()
    elif args.command == "packs":
        client.list_packs()
    elif args.command == "pack":
        client.get_pack(args.pack_id)
    elif args.command == "pets":
        client.list_pets(args.pack_id)
    elif args.command == "profile":
        client.get_pet_profile(args.pack_id, args.pet_id)
    elif args.command == "events":
        client.list_events(args.pack_id, args.pet_id, args.limit,
                          args.event_type.upper() if args.event_type else None)
    elif args.command == "log":
        extra = {}
        if args.quantity is not None:
            extra["quantity"] = args.quantity
        if args.quantity_unit:
            extra["quantityUnit"] = args.quantity_unit
        if args.weight_kg is not None:
            extra["weightKg"] = args.weight_kg
            extra["weightMeasure"] = "Kilograms"
        if args.weight_lb is not None:
            extra["weightPound"] = args.weight_lb
            extra["weightMeasure"] = "Pounds"
        if args.temp_c is not None:
            extra["temperatureCelsius"] = args.temp_c
            extra["temperatureMeasure"] = "Celsius"
        if args.temp_f is not None:
            extra["temperatureFahrenheit"] = args.temp_f
            extra["temperatureMeasure"] = "Fahrenheit"
        if args.vaccine:
            extra["vaccine"] = args.vaccine
        if args.glucose is not None:
            extra["glucose"] = args.glucose
            extra["glucoseUnit"] = args.glucose_unit or "mg/dL"
        client.log_event(args.pack_id, args.pet_id, args.event_type.upper(),
                        args.comment, args.pet_name, **extra)
    elif args.command == "delete-event":
        client.delete_event(args.pack_id, args.event_id)
    elif args.command == "breeds":
        client.get_breeds()
    elif args.command == "foods":
        client.get_foods()
    elif args.command == "db-read":
        client.db_read(args.path)
    elif args.command == "db-write":
        client.db_write(args.path, args.value)


if __name__ == "__main__":
    main()
