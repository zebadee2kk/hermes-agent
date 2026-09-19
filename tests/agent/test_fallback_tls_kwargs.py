"""Fallback client rebuilds must keep the fallback provider's per-provider TLS settings.

A private-CA endpoint (``providers.<name>.ssl_ca_cert``) reached as a *fallback* was rebuilt from
``{"api_key", "base_url"}`` only (the timeout apply rebuild), so every later request failed
CERTIFICATE_VERIFY_FAILED even though the primary path for the same provider worked.
"""
import os
from pathlib import Path
from types import SimpleNamespace

import yaml
from openai import OpenAI

from agent.client_lifecycle import _swap_fallback_clients


def _write_config(tmp: Path, providers: dict) -> None:
    home = Path(os.environ["HERMES_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(yaml.safe_dump({"providers": providers}))


def test_fallback_kwargs_carry_provider_ssl_ca_cert(tmp_path):
    ca = tmp_path / "private-root.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----\nplaceholder\n-----END CERTIFICATE-----\n")
    _write_config(tmp_path, {"privgw": {"base_url": "https://gw.internal.example/v1", "key_env": "X",
                                        "api_mode": "chat_completions", "ssl_ca_cert": str(ca)}})
    client = OpenAI(api_key="k", base_url="https://gw.internal.example/v1")
    agent = SimpleNamespace()
    try:
        _swap_fallback_clients(agent, client, "privgw", "m", str(client.base_url), "chat_completions")
        assert agent._client_kwargs.get("ssl_ca_cert") == str(ca)
        assert agent._client_kwargs["base_url"].rstrip("/") == "https://gw.internal.example/v1"
    finally:
        client.close()


def test_fallback_kwargs_unchanged_without_tls_config(tmp_path):
    _write_config(tmp_path, {"other": {"base_url": "https://elsewhere.example/v1", "key_env": "X"}})
    client = OpenAI(api_key="k", base_url="https://public.example/v1")
    agent = SimpleNamespace()
    try:
        _swap_fallback_clients(agent, client, "public", "m", str(client.base_url), "chat_completions")
        assert "ssl_ca_cert" not in agent._client_kwargs
        assert "ssl_verify" not in agent._client_kwargs
    finally:
        client.close()
