"""Firebase authentication helpers for the pydoglog library."""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.parse
from pathlib import Path

import requests

from .exceptions import DogLogAuthError

# Firebase config extracted from the DogLog APK
FIREBASE_API_KEY = "AIzaSyCBNSh63pQeV7qB1igqF_QK56xTXuAS-zE"
FIREBASE_AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts"
GOOGLE_OAUTH_CLIENT_ID = "727208592142-3bvib9btsl71ddapj9b6pgn9ppvd8ov9.apps.googleusercontent.com"

# Android app identity headers required by Firebase API key restrictions.
# Extracted from the DogLog APK signing certificate.
ANDROID_PACKAGE = "com.mobikode.dog"
ANDROID_CERT_SHA1 = "A82BA788006FD9FA0C45882A10210A07FDAD8CEB"
ANDROID_HEADERS = {
    "X-Android-Package": ANDROID_PACKAGE,
    "X-Android-Cert": ANDROID_CERT_SHA1,
}

DEFAULT_CONFIG_DIR = Path.home() / ".doglog"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"


def load_config(config_path: Path | str | None = None) -> dict:
    """Load saved credentials from a JSON config file.

    Returns an empty dict if the file doesn't exist or is invalid.

    In tests, always pass an explicit ``config_path`` (e.g. from a tmp_path
    fixture) so that the real ``~/.doglog/config.json`` is never read.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(data: dict, config_path: Path | str | None = None) -> None:
    """Persist credentials to a JSON config file (mode 0600).

    In tests, always pass an explicit ``config_path`` so that the real
    ``~/.doglog/config.json`` is never written.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)


def refresh_id_token(refresh_token: str, api_key: str = FIREBASE_API_KEY) -> dict:
    """Exchange a Firebase refresh token for a fresh ID token.

    Returns a dict with keys: id_token, refresh_token, expires_at.
    Raises DogLogAuthError on failure.
    """
    resp = requests.post(
        f"https://securetoken.googleapis.com/v1/token?key={api_key}",
        json={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        headers=ANDROID_HEADERS,
    )
    if resp.status_code != 200:
        raise DogLogAuthError(f"Token refresh failed: {resp.text}")
    data = resp.json()
    return {
        "id_token": data["id_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": time.time() + int(data["expires_in"]) - 60,
    }


def login_email_password(email: str, password: str, api_key: str = FIREBASE_API_KEY) -> dict:
    """Sign in with email/password via Firebase Auth.

    Returns a dict with keys: id_token, refresh_token, uid, email, expires_at.
    """
    resp = requests.post(
        f"{FIREBASE_AUTH_URL}:signInWithPassword?key={api_key}",
        json={"email": email, "password": password, "returnSecureToken": True},
        headers=ANDROID_HEADERS,
    )
    if resp.status_code != 200:
        err = resp.json().get("error", {})
        raise DogLogAuthError(f"Login failed: {err.get('message', resp.text)}")
    data = resp.json()
    return {
        "id_token": data["idToken"],
        "refresh_token": data["refreshToken"],
        "uid": data["localId"],
        "email": data["email"],
        "expires_at": time.time() + int(data["expiresIn"]) - 60,
    }


def signup_email_password(email: str, password: str, api_key: str = FIREBASE_API_KEY) -> dict:
    """Create a new account with email/password via Firebase Auth.

    Returns the same dict shape as login_email_password.
    """
    resp = requests.post(
        f"{FIREBASE_AUTH_URL}:signUp?key={api_key}",
        json={"email": email, "password": password, "returnSecureToken": True},
        headers=ANDROID_HEADERS,
    )
    if resp.status_code != 200:
        err = resp.json().get("error", {})
        raise DogLogAuthError(f"Signup failed: {err.get('message', resp.text)}")
    data = resp.json()
    return {
        "id_token": data["idToken"],
        "refresh_token": data["refreshToken"],
        "uid": data["localId"],
        "email": data["email"],
        "expires_at": time.time() + int(data["expiresIn"]) - 60,
    }


def run_oauth_flow(
    api_key: str = FIREBASE_API_KEY,
    client_id: str = GOOGLE_OAUTH_CLIENT_ID,
    config_path: Path | str | None = None,
    redirect_port: int = 8914,
    open_browser: bool = True,
) -> dict:
    """Run the full Google OAuth PKCE flow via a local HTTP server.

    Opens the browser, waits for the OAuth callback, exchanges the code
    for Google tokens, then exchanges those for Firebase tokens.

    Returns a dict with keys: id_token, refresh_token, uid, email, expires_at.
    The result is also saved to config_path.
    """
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge_b64 = base64.urlsafe_b64encode(code_challenge).rstrip(b"=").decode()

    state = secrets.token_urlsafe(32)
    redirect_uri = f"http://localhost:{redirect_port}"

    result: dict[str, str | None] = {"code": None, "error": None}

    class OAuthHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)

            if "error" in params:
                result["error"] = params["error"][0]
            elif "code" in params:
                received_state = params.get("state", [None])[0]
                if received_state != state:
                    result["error"] = "State mismatch - possible CSRF attack"
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
            pass

    server = http.server.HTTPServer(("127.0.0.1", redirect_port), OAuthHandler)
    server.timeout = 120

    auth_params = urllib.parse.urlencode({
        "client_id": client_id,
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

    if open_browser:
        import webbrowser
        webbrowser.open(auth_url)

    server.handle_request()
    server.server_close()

    if result["error"]:
        raise DogLogAuthError(f"Google login failed: {result['error']}")
    if not result["code"]:
        raise DogLogAuthError("No authorization code received.")

    # Exchange auth code for Google tokens
    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": result["code"],
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        },
    )
    if token_resp.status_code != 200:
        raise DogLogAuthError(f"Token exchange failed: {token_resp.text}")

    google_tokens = token_resp.json()
    google_id_token = google_tokens.get("id_token")
    if not google_id_token:
        raise DogLogAuthError("No ID token in Google response.")

    # Exchange Google ID token for Firebase ID token
    firebase_resp = requests.post(
        f"{FIREBASE_AUTH_URL}:signInWithIdp?key={api_key}",
        json={
            "postBody": f"id_token={google_id_token}&providerId=google.com",
            "requestUri": redirect_uri,
            "returnIdpCredential": True,
            "returnSecureToken": True,
        },
    )
    if firebase_resp.status_code != 200:
        err = firebase_resp.json().get("error", {})
        raise DogLogAuthError(f"Firebase sign-in failed: {err.get('message', firebase_resp.text)}")

    data = firebase_resp.json()
    creds = {
        "id_token": data["idToken"],
        "refresh_token": data["refreshToken"],
        "uid": data["localId"],
        "email": data.get("email", ""),
        "expires_at": time.time() + int(data.get("expiresIn", 3600)) - 60,
    }

    save_config(creds, config_path)
    return creds
