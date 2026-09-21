"""#44: GET /api/config must not leak dashboard login secrets, and saving the
settings form (GET -> edit -> PUT) must not overwrite them with the placeholder."""

import pytest

from hermes_cli.web_routers.config_env import (
    DASHBOARD_SECRET_PLACEHOLDER,
    _redact_dashboard_secrets,
    _restore_dashboard_secrets,
)

_HASH = "scrypt$16384$8$1$c2FsdHNhbHQ$ZmFrZWhhc2hmYWtlaGFzaA"
_PASSWORD = "correct-horse-battery-staple"
_SECRET = "s" * 48
_OAUTH_SECRET = "oauth-client-secret-value-1234"


def _seed_config():
    return {
        "agent": {"max_turns": 50},
        "dashboard": {
            "theme": "default",
            "basic_auth": {
                "username": "richard",
                "password_hash": _HASH,
                "password": _PASSWORD,
                "secret": _SECRET,
                "session_ttl_seconds": 3600,
            },
            "oauth": {
                "client_id": "agent:abc123",
                "portal_url": "https://portal.example.test",
                "client_secret": _OAUTH_SECRET,
            },
        },
    }


class TestHelpers:
    def test_redacts_secret_leaves_only(self):
        red = _redact_dashboard_secrets(_seed_config())
        ba = red["dashboard"]["basic_auth"]
        assert ba["password_hash"] == DASHBOARD_SECRET_PLACEHOLDER
        assert ba["password"] == DASHBOARD_SECRET_PLACEHOLDER
        assert ba["secret"] == DASHBOARD_SECRET_PLACEHOLDER
        assert ba["username"] == "richard"
        assert ba["session_ttl_seconds"] == 3600
        oa = red["dashboard"]["oauth"]
        assert oa["client_secret"] == DASHBOARD_SECRET_PLACEHOLDER
        assert oa["client_id"] == "agent:abc123"
        assert red["dashboard"]["theme"] == "default"

    def test_empty_and_env_refs_stay_visible(self):
        cfg = {"dashboard": {"basic_auth": {"password": "", "secret": "${DASH_SECRET}"}}}
        red = _redact_dashboard_secrets(cfg)
        assert red["dashboard"]["basic_auth"] == {"password": "", "secret": "${DASH_SECRET}"}

    def test_does_not_mutate_input(self):
        cfg = _seed_config()
        _redact_dashboard_secrets(cfg)
        assert cfg["dashboard"]["basic_auth"]["password_hash"] == _HASH

    def test_restore_placeholder_and_explicit_change(self):
        existing = _seed_config()
        incoming = _redact_dashboard_secrets(_seed_config())
        incoming["dashboard"]["basic_auth"]["password"] = "new-password"
        restored = _restore_dashboard_secrets(incoming, existing)
        ba = restored["dashboard"]["basic_auth"]
        assert ba["password_hash"] == _HASH
        assert ba["secret"] == _SECRET
        assert ba["password"] == "new-password"
        assert restored["dashboard"]["oauth"]["client_secret"] == _OAUTH_SECRET

    def test_placeholder_without_stored_value_is_dropped(self):
        incoming = {"dashboard": {"basic_auth": {"secret": DASHBOARD_SECRET_PLACEHOLDER}}}
        restored = _restore_dashboard_secrets(incoming, {})
        assert "secret" not in restored["dashboard"]["basic_auth"]


class TestConfigEndpoint:
    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")
        from hermes_cli.config import save_config
        from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN
        self.client = TestClient(app)
        self.client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
        save_config(_seed_config())

    @pytest.mark.parametrize("include_defaults", [True, False])
    def test_get_redacts_dashboard_secrets(self, include_defaults):
        resp = self.client.get("/api/config", params={"include_defaults": include_defaults})
        assert resp.status_code == 200
        body = resp.text
        for secret in (_HASH, _PASSWORD, _SECRET, _OAUTH_SECRET):
            assert secret not in body
        ba = resp.json()["dashboard"]["basic_auth"]
        assert ba["password_hash"] == DASHBOARD_SECRET_PLACEHOLDER
        assert ba["password"] == DASHBOARD_SECRET_PLACEHOLDER
        assert ba["secret"] == DASHBOARD_SECRET_PLACEHOLDER
        assert ba["username"] == "richard"

    def test_put_round_trip_preserves_secrets(self):
        from hermes_cli.config import read_raw_config

        web_config = self.client.get("/api/config").json()
        web_config["agent"]["max_turns"] = 75
        resp = self.client.put("/api/config", json={"config": web_config})
        assert resp.status_code == 200

        on_disk = read_raw_config()
        assert on_disk["agent"]["max_turns"] == 75
        ba = on_disk["dashboard"]["basic_auth"]
        assert ba["password_hash"] == _HASH
        assert ba["password"] == _PASSWORD
        assert ba["secret"] == _SECRET
        assert ba["username"] == "richard"
        assert on_disk["dashboard"]["oauth"]["client_secret"] == _OAUTH_SECRET

    def test_put_omitting_secrets_preserves_them(self):
        from hermes_cli.config import read_raw_config

        resp = self.client.put(
            "/api/config",
            json={"config": {"dashboard": {"basic_auth": {"username": "richard2"}}}},
        )
        assert resp.status_code == 200
        ba = read_raw_config()["dashboard"]["basic_auth"]
        assert ba["username"] == "richard2"
        assert ba["password_hash"] == _HASH
        assert ba["secret"] == _SECRET

    def test_put_new_value_replaces_secret(self):
        from hermes_cli.config import read_raw_config

        web_config = self.client.get("/api/config").json()
        web_config["dashboard"]["basic_auth"]["secret"] = "t" * 48
        resp = self.client.put("/api/config", json={"config": web_config})
        assert resp.status_code == 200
        ba = read_raw_config()["dashboard"]["basic_auth"]
        assert ba["secret"] == "t" * 48
        assert ba["password_hash"] == _HASH
