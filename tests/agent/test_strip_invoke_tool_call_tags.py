"""Carry: models that emit MiniMax/Anthropic-style ``<invoke name=...>`` blocks as TEXT (seen on Telegram
2026-11-11 as ``<dots_function_call><invoke name="read_file">...``) must not leak that markup to the user."""
import types

import pytest

from agent.agent_runtime_helpers import strip_think_blocks

_AGENT = types.SimpleNamespace()


@pytest.mark.parametrize("text", [
    'Let me check.\n<dots_function_call><invoke name="read_file"><parameter name="path">/etc/hosts</parameter></invoke></dots_function_call>',
    'Let me check.\n<invoke name="read_file">\n<parameter name="path">/etc/hosts</parameter>\n</invoke>',
    'Let me check.\n<invoke name="read_file">\n<parameter name="path">/etc/hosts',
])
def test_invoke_markup_is_stripped(text):
    out = strip_think_blocks(_AGENT, text)
    assert "<invoke" not in out and "read_file" not in out
    assert out.strip().startswith("Let me check.")


def test_prose_mentioning_invoke_survives():
    text = "Use the <invoke> element in your XML schema to call it."
    assert strip_think_blocks(_AGENT, text) == text
