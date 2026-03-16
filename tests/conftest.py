"""Shared test fixtures."""

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_events():
    """Load the sample Firebase events fixture."""
    return json.loads((FIXTURES_DIR / "sample_events.json").read_text())


@pytest.fixture
def fake_config(tmp_path):
    """Create a temporary config file with fake credentials."""
    config = {
        "id_token": "fake-id-token",
        "refresh_token": "fake-refresh-token",
        "uid": "uid_abc123",
        "email": "test@example.com",
        "expires_at": 9999999999,  # far future
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    return config_path


@pytest.fixture
def expired_config(tmp_path):
    """Create a config file with an expired token."""
    config = {
        "id_token": "expired-id-token",
        "refresh_token": "valid-refresh-token",
        "uid": "uid_abc123",
        "email": "test@example.com",
        "expires_at": 0,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    return config_path
