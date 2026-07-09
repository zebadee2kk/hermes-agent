"""Regression tests for the api_server scoped port lock (#735/#871).

A profile gateway inherits ``API_SERVER_KEY`` from the main ~/.hermes/.env and
historically raced the main gateway for the single machine-wide api_server port
(default 8642) — whoever won the bind stole the port. ``connect()`` now acquires
a scoped lock (``gateway.status.acquire_scoped_lock``, scope ``api-server-port``,
identity = port) BEFORE binding. The loser must fail fast (return False) WITHOUT
creating the aiohttp app or binding the port, so there is never a double-bind.
"""

from unittest.mock import MagicMock, patch

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter

# 32 hex chars: clears _api_key_passes_startup_guard (has_usable_secret, >=16).
STRONG_KEY = "0123456789abcdef0123456789abcdef"


def _make_adapter():
    """Loopback + strong key so connect() clears the api-key startup guard and
    actually reaches the port-lock step (otherwise it would short-circuit earlier
    and the test would pass for the wrong reason)."""
    return APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={"host": "127.0.0.1", "key": STRONG_KEY, "port": 8642},
        )
    )


class TestApiServerScopedLock:
    @pytest.mark.asyncio
    async def test_lock_denied_skips_bind(self):
        """When the scoped lock is already held by another gateway, connect()
        returns False and never creates the app / binds the port."""
        adapter = _make_adapter()
        denied = MagicMock(return_value=(False, {"pid": 4321}))

        # _acquire_platform_lock does `from gateway.status import acquire_scoped_lock`
        # at call time, so patching the name on gateway.status intercepts it.
        with patch("gateway.status.acquire_scoped_lock", denied):
            result = await adapter.connect()

        assert result is False
        # Prove the lock step was actually reached and is what blocked us
        # (guards against the test passing because connect short-circuited
        # earlier, e.g. aiohttp missing or the api-key guard).
        denied.assert_called_once()
        args, _kwargs = denied.call_args
        assert args[0] == "api-server-port"
        assert args[1] == str(adapter._port)
        # No server created, no port bound — no double-bind possible.
        assert adapter._app is None
        assert adapter._runner is None
        assert adapter._background_tasks == set()

    @pytest.mark.asyncio
    async def test_lock_granted_proceeds_past_lock(self):
        """When the lock IS granted, connect() must proceed PAST the lock to the
        port/bind stage — proving the lock is not spuriously blocking a legit
        single owner. We stop at the port check (reported busy) to avoid a real
        bind, and confirm the failure came from the port, not the lock."""
        adapter = _make_adapter()
        granted = MagicMock(return_value=(True, None))

        with patch("gateway.status.acquire_scoped_lock", granted), \
                patch("gateway.status.release_scoped_lock", MagicMock()), \
                patch.object(APIServerAdapter, "_port_is_available", return_value=False):
            result = await adapter.connect()

        assert result is False  # blocked by the (mocked) busy port, not the lock
        granted.assert_called_once()
        assert adapter._app is None
