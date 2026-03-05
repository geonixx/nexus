"""Tests for M10: Security & Hardening.

Coverage areas
--------------
* security.py          — is_secret_value, mask_secret, scan_config_secrets,
                         file_permission_mode, is_too_permissive, is_git_tracked
* commands/security.py — _run_checks logic, nexus security CLI
* commands/config.py   — secret warning in config set, masking in config show,
                         chmod on save_config
* db.py                — chmod on __init__ and _init
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from nexus.cli import cli
from nexus.commands.config import CONFIG_PATH, save_config
from nexus.commands.security import _run_checks
from nexus.db import Database
from nexus.security import (
    file_permission_mode,
    is_git_tracked,
    is_secret_value,
    is_too_permissive,
    mask_secret,
    scan_config_secrets,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(path=tmp_path / "nexus.db")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def invoke(runner: CliRunner, db: Database, *args):
    return runner.invoke(cli, ["--db", str(db.path)] + list(args))


# ── is_secret_value ───────────────────────────────────────────────────────────


class TestIsSecretValue:
    def test_anthropic_key(self):
        assert is_secret_value("sk-ant-api03-abcdefghij1234567890")

    def test_openai_style_key(self):
        assert is_secret_value("sk-proj-abcdefghij1234567890ABCD")

    def test_github_pat(self):
        assert is_secret_value("ghp_abcdefghij1234567890ABCDEFGH")

    def test_github_oauth(self):
        assert is_secret_value("gho_abcdefghij1234567890ABCDEFGH")

    def test_github_server(self):
        assert is_secret_value("ghs_abcdefghij1234567890ABCDEFGH")

    def test_google_api_key(self):
        assert is_secret_value("AIzaSyAbcdefghij1234567890ABCDE")

    def test_aws_access_key(self):
        assert is_secret_value("AKIAabcdefghij1234567890")

    def test_gitlab_pat(self):
        assert is_secret_value("glpat-abcdefghij1234567890ABCD")

    def test_slack_bot_token(self):
        # Build at runtime so static secret scanners don't flag the test suite
        token = "-".join(["xoxb", "1234567890", "abcdefghij1234567890"])
        assert is_secret_value(token)

    def test_sendgrid_key(self):
        assert is_secret_value("SG.abcdefghij1234567890ABCDEFGH")

    def test_short_string_not_secret(self):
        assert not is_secret_value("hello")

    def test_normal_word_not_secret(self):
        assert not is_secret_value("my_project_name")

    def test_integer_not_secret(self):
        assert not is_secret_value(42)  # type: ignore[arg-type]

    def test_none_not_secret(self):
        assert not is_secret_value(None)  # type: ignore[arg-type]

    def test_empty_string_not_secret(self):
        assert not is_secret_value("")

    def test_long_but_no_prefix_not_secret(self):
        # Long string but no known secret prefix → not detected
        assert not is_secret_value("a" * 40)


# ── mask_secret ───────────────────────────────────────────────────────────────


class TestMaskSecret:
    def test_long_value_masked(self):
        result = mask_secret("sk-ant-api03-abcdef1234")
        assert result.startswith("sk-a")
        assert "****" in result
        assert result.endswith("1234")

    def test_short_value_fully_masked(self):
        assert mask_secret("abc") == "****"

    def test_exactly_eight_chars_masked(self):
        assert mask_secret("12345678") == "****"

    def test_nine_chars_shows_prefix_and_suffix(self):
        result = mask_secret("123456789")
        assert result.startswith("1234")
        assert result.endswith("6789")
        assert "****" in result


# ── scan_config_secrets ───────────────────────────────────────────────────────


class TestScanConfigSecrets:
    def test_no_secrets(self):
        cfg = {"default_project": 3, "ai_max_tokens": 1024}
        assert scan_config_secrets(cfg) == []

    def test_detects_api_key(self):
        cfg = {
            "default_project": 1,
            "ANTHROPIC_API_KEY": "sk-ant-api03-abcdefghij1234567890",
        }
        result = scan_config_secrets(cfg)
        assert "ANTHROPIC_API_KEY" in result

    def test_detects_multiple_secrets(self):
        cfg = {
            "a": "sk-ant-api03-abcdefghij1234567890",
            "b": "ghp_abcdefghij1234567890ABCDEFGH",
        }
        result = scan_config_secrets(cfg)
        assert sorted(result) == ["a", "b"]

    def test_empty_config(self):
        assert scan_config_secrets({}) == []


# ── file_permission_mode / is_too_permissive ──────────────────────────────────


class TestFilePermissions:
    def test_file_permission_mode_exists(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("x")
        os.chmod(f, 0o600)
        mode = file_permission_mode(f)
        assert mode is not None
        assert mode == 0o600

    def test_file_permission_mode_missing(self, tmp_path: Path):
        f = tmp_path / "nonexistent.txt"
        assert file_permission_mode(f) is None

    def test_is_too_permissive_true(self, tmp_path: Path):
        f = tmp_path / "wide.txt"
        f.write_text("x")
        os.chmod(f, 0o644)
        assert is_too_permissive(f, expected=0o600)

    def test_is_too_permissive_false(self, tmp_path: Path):
        f = tmp_path / "tight.txt"
        f.write_text("x")
        os.chmod(f, 0o600)
        assert not is_too_permissive(f, expected=0o600)

    def test_is_too_permissive_missing(self, tmp_path: Path):
        f = tmp_path / "ghost.txt"
        assert not is_too_permissive(f, expected=0o600)


# ── is_git_tracked ────────────────────────────────────────────────────────────


class TestIsGitTracked:
    def test_git_not_installed(self, tmp_path: Path):
        f = tmp_path / "f.txt"
        f.write_text("x")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert not is_git_tracked(f)

    def test_file_not_tracked(self, tmp_path: Path):
        import subprocess
        f = tmp_path / "f.txt"
        f.write_text("x")
        mock_result = subprocess.CompletedProcess(args=[], returncode=1)
        with patch("subprocess.run", return_value=mock_result):
            assert not is_git_tracked(f)

    def test_file_tracked(self, tmp_path: Path):
        import subprocess
        f = tmp_path / "f.txt"
        f.write_text("x")
        mock_result = subprocess.CompletedProcess(args=[], returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            assert is_git_tracked(f)


# ── _run_checks ────────────────────────────────────────────────────────────────


class TestRunChecks:
    def test_all_pass_when_permissions_tight(self, tmp_path: Path):
        db_path = tmp_path / "nexus.db"
        cfg_path = tmp_path / "config.json"
        nexus_dir = tmp_path

        # Create files with tight permissions
        db_path.write_text("db")
        cfg_path.write_text("{}")
        os.chmod(db_path, 0o600)
        os.chmod(cfg_path, 0o600)
        os.chmod(nexus_dir, 0o700)

        with patch("nexus.commands.security.load_config", return_value={}), \
             patch("nexus.commands.security.is_git_tracked", return_value=False):
            checks = _run_checks(db_path, cfg_path, fix=False)

        statuses = {c["name"]: c["status"] for c in checks}
        assert statuses["Nexus directory permissions"] == "pass"
        assert statuses["Database file permissions"] == "pass"
        assert statuses["Config file permissions"] == "pass"
        assert statuses["Secrets in config.json"] == "pass"
        assert statuses["Database git tracking"] == "pass"
        assert statuses["Config git tracking"] == "pass"

    def test_fails_when_db_too_permissive(self, tmp_path: Path):
        db_path = tmp_path / "nexus.db"
        cfg_path = tmp_path / "config.json"

        db_path.write_text("db")
        cfg_path.write_text("{}")
        os.chmod(db_path, 0o644)  # too open
        os.chmod(cfg_path, 0o600)
        os.chmod(tmp_path, 0o700)

        with patch("nexus.commands.security.load_config", return_value={}), \
             patch("nexus.commands.security.is_git_tracked", return_value=False):
            checks = _run_checks(db_path, cfg_path, fix=False)

        db_check = next(c for c in checks if c["name"] == "Database file permissions")
        assert db_check["status"] == "fail"

    def test_fix_corrects_permissions(self, tmp_path: Path):
        db_path = tmp_path / "nexus.db"
        cfg_path = tmp_path / "config.json"

        db_path.write_text("db")
        cfg_path.write_text("{}")
        os.chmod(db_path, 0o644)
        os.chmod(cfg_path, 0o644)
        os.chmod(tmp_path, 0o755)

        with patch("nexus.commands.security.load_config", return_value={}), \
             patch("nexus.commands.security.is_git_tracked", return_value=False):
            _run_checks(db_path, cfg_path, fix=True)

        assert stat.S_IMODE(db_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(cfg_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700

    def test_detects_secret_in_config(self, tmp_path: Path):
        db_path = tmp_path / "nexus.db"
        cfg_path = tmp_path / "config.json"
        db_path.write_text("db")
        cfg_path.write_text("{}")
        os.chmod(db_path, 0o600)
        os.chmod(cfg_path, 0o600)
        os.chmod(tmp_path, 0o700)

        secret_cfg = {"ANTHROPIC_API_KEY": "sk-ant-api03-abcdefghij1234567890"}
        with patch("nexus.commands.security.load_config", return_value=secret_cfg), \
             patch("nexus.commands.security.is_git_tracked", return_value=False):
            checks = _run_checks(db_path, cfg_path, fix=False)

        secret_check = next(c for c in checks if c["name"] == "Secrets in config.json")
        assert secret_check["status"] == "fail"

    def test_detects_git_tracked_db(self, tmp_path: Path):
        db_path = tmp_path / "nexus.db"
        cfg_path = tmp_path / "config.json"
        db_path.write_text("db")
        cfg_path.write_text("{}")
        os.chmod(db_path, 0o600)
        os.chmod(cfg_path, 0o600)
        os.chmod(tmp_path, 0o700)

        def mock_tracked(path):
            return path == db_path.resolve()

        with patch("nexus.commands.security.load_config", return_value={}), \
             patch("nexus.commands.security.is_git_tracked", side_effect=mock_tracked):
            checks = _run_checks(db_path, cfg_path, fix=False)

        git_check = next(c for c in checks if c["name"] == "Database git tracking")
        assert git_check["status"] == "fail"

    def test_pass_when_files_not_yet_created(self, tmp_path: Path):
        db_path = tmp_path / "nonexistent.db"
        cfg_path = tmp_path / "nonexistent.json"

        with patch("nexus.commands.security.load_config", return_value={}), \
             patch("nexus.commands.security.is_git_tracked", return_value=False):
            checks = _run_checks(db_path, cfg_path, fix=False)

        # Non-existent files should not fail
        db_check = next(c for c in checks if c["name"] == "Database file permissions")
        cfg_check = next(c for c in checks if c["name"] == "Config file permissions")
        assert db_check["status"] == "pass"
        assert cfg_check["status"] == "pass"


# ── nexus security CLI ────────────────────────────────────────────────────────


class TestSecurityCLI:
    def test_security_command_runs(self, db: Database, runner: CliRunner):
        with patch("nexus.commands.security.load_config", return_value={}), \
             patch("nexus.commands.security.is_git_tracked", return_value=False):
            result = invoke(runner, db, "security")
        assert "Security Check" in result.output

    def test_security_shows_pass_indicators(self, db: Database, runner: CliRunner):
        with patch("nexus.commands.security.load_config", return_value={}), \
             patch("nexus.commands.security.is_git_tracked", return_value=False):
            result = invoke(runner, db, "security")
        assert "✓" in result.output

    def test_security_exits_nonzero_on_failure(self, db: Database, runner: CliRunner):
        secret_cfg = {"KEY": "sk-ant-api03-abcdefghij1234567890"}
        with patch("nexus.commands.security.load_config", return_value=secret_cfg), \
             patch("nexus.commands.security.is_git_tracked", return_value=False):
            result = invoke(runner, db, "security")
        assert result.exit_code != 0

    def test_security_fix_flag_accepted(self, db: Database, runner: CliRunner):
        with patch("nexus.commands.security.load_config", return_value={}), \
             patch("nexus.commands.security.is_git_tracked", return_value=False):
            result = invoke(runner, db, "security", "--fix")
        assert result.exit_code == 0


# ── config set: secret warning ────────────────────────────────────────────────


class TestConfigSetSecretWarning:
    def test_blocks_api_key_storage(self, db: Database, runner: CliRunner, tmp_path: Path):
        cfg = tmp_path / "config.json"
        env = {"NEXUS_DB": str(db.path), "NEXUS_CONFIG": str(cfg)}
        with patch("nexus.commands.config.CONFIG_PATH", cfg):
            result = runner.invoke(
                cli,
                ["--db", str(db.path), "config", "set",
                 "ANTHROPIC_API_KEY", "sk-ant-api03-abcdefghij1234567890"],
            )
        assert result.exit_code != 0
        assert "Security warning" in result.output or "warning" in result.output.lower()

    def test_allows_normal_values(self, db: Database, runner: CliRunner, tmp_path: Path):
        cfg = tmp_path / "config.json"
        with patch("nexus.commands.config.CONFIG_PATH", cfg):
            result = runner.invoke(
                cli,
                ["--db", str(db.path), "config", "set", "default_project", "3"],
            )
        assert result.exit_code == 0

    def test_secret_not_written_to_disk(self, db: Database, runner: CliRunner, tmp_path: Path):
        cfg = tmp_path / "config.json"
        secret = "sk-ant-api03-abcdefghij1234567890"
        with patch("nexus.commands.config.CONFIG_PATH", cfg):
            runner.invoke(
                cli,
                ["--db", str(db.path), "config", "set", "MY_KEY", secret],
            )
        # Config file should not exist OR should not contain the secret
        if cfg.exists():
            assert secret not in cfg.read_text()


# ── config show: secret masking ───────────────────────────────────────────────


class TestConfigShowMasking:
    def test_masks_secret_values(self, db: Database, runner: CliRunner, tmp_path: Path):
        cfg = tmp_path / "config.json"
        secret = "sk-ant-api03-abcdefghij1234567890"
        cfg.write_text(json.dumps({"MY_KEY": secret}))
        with patch("nexus.commands.config.CONFIG_PATH", cfg):
            result = runner.invoke(cli, ["--db", str(db.path), "config", "show"])
        # Full secret must NOT appear in output
        assert secret not in result.output
        # Masked form should appear
        assert "****" in result.output

    def test_shows_normal_values_plainly(self, db: Database, runner: CliRunner, tmp_path: Path):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"default_project": 7}))
        with patch("nexus.commands.config.CONFIG_PATH", cfg):
            result = runner.invoke(cli, ["--db", str(db.path), "config", "show"])
        assert "7" in result.output
        # No masking warning for normal values
        assert "masked" not in result.output


# ── save_config: file permissions ────────────────────────────────────────────


class TestSaveConfigPermissions:
    def test_config_file_gets_chmod_600(self, tmp_path: Path):
        cfg = tmp_path / "config.json"
        save_config({"default_project": 1}, path=cfg)
        mode = stat.S_IMODE(cfg.stat().st_mode)
        assert mode == 0o600

    def test_config_content_is_correct(self, tmp_path: Path):
        cfg = tmp_path / "config.json"
        save_config({"foo": "bar"}, path=cfg)
        assert json.loads(cfg.read_text()) == {"foo": "bar"}


# ── DB permissions ────────────────────────────────────────────────────────────


class TestDatabasePermissions:
    def test_db_file_gets_chmod_600(self, tmp_path: Path):
        db = Database(path=tmp_path / "nexus.db")
        mode = stat.S_IMODE(db.path.stat().st_mode)
        assert mode == 0o600

    def test_db_directory_gets_chmod_700(self, tmp_path: Path):
        db_dir = tmp_path / "nexus_dir"
        Database(path=db_dir / "nexus.db")
        mode = stat.S_IMODE(db_dir.stat().st_mode)
        assert mode == 0o700
