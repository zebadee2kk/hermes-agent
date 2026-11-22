"""The raw config editor must not expose or overwrite dashboard credentials."""

import hermes_yaml as yaml

from hermes_cli.web_routers.config_env import DASHBOARD_SECRET_PLACEHOLDER


_HASH = "scrypt$16384$8$1$c2FsdHNhbHQ$ZmFrZWhhc2hmYWtlaGFzaA"
_PASSWORD = "correct-horse-battery-staple"
_SECRET = "s" * 48
_OAUTH_SECRET = "oauth-client-secret-value-1234"


def _raw_yaml():
    return f"""# formatting must survive the redacted GET
agent: {{max_turns: 50}}  # inline comment
dashboard:
  basic_auth:
    username: richard
    password_hash: '{_HASH}'
    password: {_PASSWORD}
    secret: {_SECRET}
  oauth:
    client_id: agent:abc123
    nested:
      client_secret: {_OAUTH_SECRET}
"""


def _client_with_config():
    from starlette.testclient import TestClient

    from hermes_cli.config import get_config_path
    from hermes_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_raw_yaml(), encoding="utf-8")
    client = TestClient(app)
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return client, path


def test_raw_get_redacts_every_secret_without_reformatting():
    client, _ = _client_with_config()

    response = client.get("/api/config/raw")

    assert response.status_code == 200
    raw = response.json()["yaml"]
    for secret in (_HASH, _PASSWORD, _SECRET, _OAUTH_SECRET):
        assert secret not in response.text
    assert raw.startswith("# formatting must survive the redacted GET\n")
    assert "agent: {max_turns: 50}  # inline comment" in raw
    parsed = yaml.safe_load(raw)
    assert parsed["dashboard"]["basic_auth"]["username"] == "richard"
    assert parsed["dashboard"]["basic_auth"]["password_hash"] == DASHBOARD_SECRET_PLACEHOLDER
    assert parsed["dashboard"]["oauth"]["nested"]["client_secret"] == DASHBOARD_SECRET_PLACEHOLDER


def test_raw_put_round_trip_preserves_secrets():
    client, path = _client_with_config()
    raw = client.get("/api/config/raw").json()["yaml"]
    raw = raw.replace("max_turns: 50", "max_turns: 75")

    response = client.put("/api/config/raw", json={"yaml_text": raw})

    assert response.status_code == 200
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["agent"]["max_turns"] == 75
    assert saved["dashboard"]["basic_auth"]["password_hash"] == _HASH
    assert saved["dashboard"]["basic_auth"]["password"] == _PASSWORD
    assert saved["dashboard"]["basic_auth"]["secret"] == _SECRET
    assert saved["dashboard"]["oauth"]["nested"]["client_secret"] == _OAUTH_SECRET


def test_raw_put_new_secret_replaces_old_value():
    client, path = _client_with_config()
    parsed = yaml.safe_load(client.get("/api/config/raw").json()["yaml"])
    parsed["dashboard"]["basic_auth"]["secret"] = "replacement-secret-value"

    response = client.put("/api/config/raw", json={"yaml_text": yaml.safe_dump(parsed)})

    assert response.status_code == 200
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["dashboard"]["basic_auth"]["secret"] == "replacement-secret-value"
    assert saved["dashboard"]["basic_auth"]["password_hash"] == _HASH
    assert saved["dashboard"]["oauth"]["nested"]["client_secret"] == _OAUTH_SECRET
