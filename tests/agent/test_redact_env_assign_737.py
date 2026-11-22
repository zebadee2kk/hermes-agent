"""hermes-mgmt#737: env-dump multi-word secret values are masked to end of line (carry)."""
import pytest


class TestEnvDumpMultiWord737:
    # ── env-dump multi-word values (hermes-mgmt#737) ──

    @pytest.mark.parametrize("line", [
        'N8N_MCP_AUTHORIZATION="Bearer live-token-should-not-leak"',
        "N8N_MCP_AUTHORIZATION=Bearer live-token-should-not-leak",
        'export N8N_MCP_AUTHORIZATION="Bearer live-token-should-not-leak"',
        "N8N_MCP_AUTHORIZATION='Bearer live-token-should-not-leak'",
    ])
    def test_env_dump_masks_multi_word_secret_value_to_eol(self, line):
        from agent.redact import redact_terminal_output
        red = redact_terminal_output(f"{line}\nPATH=/usr/bin\nHOME=/home/u", "env", force=True)
        assert "live-token-should-not-leak" not in red
        assert "N8N_MCP_AUTHORIZATION=***" in red
        assert "PATH=/usr/bin" in red and "HOME=/home/u" in red

    def test_env_file_read_masks_multi_word_secret_value(self):
        from agent.redact import redact_terminal_output
        red = redact_terminal_output('N8N_MCP_AUTHORIZATION="Bearer live-token-should-not-leak"\n', "cat .env", force=True)
        assert "live-token-should-not-leak" not in red

    def test_env_dump_keeps_rc_references_readable(self):
        from agent.redact import redact_terminal_output
        out = ("SSH_AUTH_SOCK=/run/user/1000/keyring/ssh\n"
               "export SSH_AUTH_SOCK=$(gpgconf --list-dirs agent-ssh-socket)\n"
               "XAUTHORITY=/run/user/1000/gdm/Xauthority\n"
               "GNOME_KEYRING_CONTROL=/run/user/1000/keyring\n"
               "MAX_TOKENS=100\n")
        assert redact_terminal_output(out, "env", force=True) == out

    def test_non_env_command_leaves_multi_word_assignment_alone(self):
        from agent.redact import redact_terminal_output
        # The to-end-of-line pass is opt-in: source/prose output is not an env dump.
        text = 'DESCRIPTION_AUTH_NOTE="see the docs for more"'
        assert redact_terminal_output(text, "python app.py", force=True) == text

