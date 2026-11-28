"""An unexpected failure while peeling the ``tool_call`` bridge keeps the wrapper fallback but
is no longer silent: it logs a warning naming the outer tool, call id and inner tool, and never
the argument values (they may carry secrets)."""

import logging
from types import SimpleNamespace

import pytest

from agent import tool_executor
from agent.tool_executor import _parse_tool_call, _unwrap_tool_search_call
from tools import tool_search

DESKTOP_SCOPE = ["coding", "desktop_ui", "project"]
SECRET = "sk-SENTINEL-do-not-log-4417"


class _Agent:
    def __init__(self, enabled):
        self.enabled_toolsets = enabled
        self.disabled_toolsets = None


def _args():
    return {"calls": [{"name": "drive_preview", "arguments": {"action": "elements", "token": SECRET}}]}


@pytest.fixture
def broken_validator(monkeypatch):
    def _boom(name, args):
        # The message echoes an argument value, as a real validator error might.
        raise RuntimeError(f"validator exploded on {args!r}")
    monkeypatch.setattr(tool_search, "validate_deferred_call_args", _boom)


def _unwrap_warnings(caplog):
    return [r for r in caplog.records
            if r.name == tool_executor.logger.name and r.levelno == logging.WARNING
            and "deferred_unwrap_error" in r.getMessage()]


def test_unexpected_unwrap_failure_warns_and_falls_back_to_wrapper(broken_validator, caplog):
    args = _args()
    with caplog.at_level(logging.WARNING, logger=tool_executor.logger.name):
        name, out_args, block = _unwrap_tool_search_call(
            _Agent(DESKTOP_SCOPE), "tool_call", args, call_id="call_abc123")

    assert (name, out_args, block) == ("tool_call", args, None)
    [record] = _unwrap_warnings(caplog)
    message = record.getMessage()
    assert "tool_call" in message and "call_abc123" in message and "drive_preview" in message
    assert "RuntimeError" in message and "_boom" in message  # type + frames for diagnosis
    assert record.exc_info is None  # exc_info would render str(exc), which echoes the args
    assert SECRET not in caplog.text


def test_parse_tool_call_threads_the_pairing_call_id_into_the_warning(broken_validator, caplog):
    import json

    tool_call = SimpleNamespace(id="chatcmpl-tool-77", type="function", function=SimpleNamespace(
        name="tool_call", arguments=json.dumps(_args())))
    with caplog.at_level(logging.WARNING, logger=tool_executor.logger.name):
        parsed = _parse_tool_call(_Agent(DESKTOP_SCOPE), tool_call)

    assert parsed.name == "tool_call" and parsed.args == _args() and parsed.scope_block is None
    [record] = _unwrap_warnings(caplog)
    assert "chatcmpl-tool-77" in record.getMessage()
    assert SECRET not in caplog.text


def test_successful_unwrap_logs_nothing(caplog):
    with caplog.at_level(logging.WARNING, logger=tool_executor.logger.name):
        name, _, block = _unwrap_tool_search_call(
            _Agent(DESKTOP_SCOPE), "tool_call",
            {"name": "drive_preview", "arguments": {"action": "elements"}})
    assert block is None and name == "drive_preview"
    assert _unwrap_warnings(caplog) == []
