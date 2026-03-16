"""Tests for pydoglog.auth — token refresh logic (mocked HTTP)."""

import json

import pytest
import responses

from pydoglog.auth import refresh_id_token, load_config, save_config
from pydoglog.exceptions import DogLogAuthError

REFRESH_URL = "https://securetoken.googleapis.com/v1/token?key=AIzaSyCBNSh63pQeV7qB1igqF_QK56xTXuAS-zE"


class TestRefreshIdToken:
    @responses.activate
    def test_success(self):
        responses.post(REFRESH_URL, json={
            "id_token": "new-id-token",
            "refresh_token": "new-refresh-token",
            "expires_in": "3600",
        })

        result = refresh_id_token("old-refresh-token")
        assert result["id_token"] == "new-id-token"
        assert result["refresh_token"] == "new-refresh-token"
        assert result["expires_at"] > 0

        # Verify the request payload
        body = json.loads(responses.calls[0].request.body)
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "old-refresh-token"

    @responses.activate
    def test_failure_raises_auth_error(self):
        responses.post(REFRESH_URL, json={"error": "invalid"}, status=400)

        with pytest.raises(DogLogAuthError, match="Token refresh failed"):
            refresh_id_token("bad-token")


class TestLoadSaveConfig:
    def test_load_missing_file(self, tmp_path):
        assert load_config(tmp_path / "nope.json") == {}

    def test_round_trip(self, tmp_path):
        path = tmp_path / "cfg.json"
        data = {"id_token": "tok", "uid": "u1"}
        save_config(data, path)

        loaded = load_config(path)
        assert loaded["id_token"] == "tok"
        assert loaded["uid"] == "u1"

        # Check file permissions
        assert oct(path.stat().st_mode)[-3:] == "600"

    def test_load_corrupt_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{invalid json")
        assert load_config(path) == {}
