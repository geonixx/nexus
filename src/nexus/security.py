"""Security utilities for Nexus.

All functions here are pure (no side effects beyond the file system operations
explicitly requested) and are designed to be independently testable.

Topics covered
--------------
* Secret detection  — spot API keys / tokens in arbitrary strings
* File permissions  — check and fix Unix permission bits
* Git tracking      — detect if a path is tracked by a git repo
* Config scanning   — find config keys with secret-looking values
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Optional


# ── Secret-value detection ─────────────────────────────────────────────────────

# Well-known API-key prefixes for common services
_SECRET_PREFIXES: list[re.Pattern[str]] = [
    re.compile(r"^sk-ant-"),          # Anthropic API key
    re.compile(r"^sk-[a-zA-Z0-9]"),   # OpenAI-style key
    re.compile(r"^ghp_"),             # GitHub personal access token
    re.compile(r"^gho_"),             # GitHub OAuth token
    re.compile(r"^ghs_"),             # GitHub server-to-server token
    re.compile(r"^ghr_"),             # GitHub refresh token
    re.compile(r"^AIza"),             # Google API key
    re.compile(r"^ya29\."),           # Google OAuth access token
    re.compile(r"^AKIA"),             # AWS access key ID
    re.compile(r"^glpat-"),           # GitLab personal access token
    re.compile(r"^xoxb-"),            # Slack bot token
    re.compile(r"^xoxp-"),            # Slack user token
    re.compile(r"^SG\."),             # SendGrid API key
    re.compile(r"^key-"),             # Mailgun API key
]

# Minimum length before we even test entropy
_MIN_SECRET_LEN = 20


def is_secret_value(value: str) -> bool:
    """Return True if *value* looks like an API key or secret token.

    Checks against a list of well-known prefixes for popular services.
    Short values (< 20 chars) are always considered safe to avoid
    false-positives on things like project names or short strings.
    """
    if not isinstance(value, str) or len(value) < _MIN_SECRET_LEN:
        return False
    for pattern in _SECRET_PREFIXES:
        if pattern.match(value):
            return True
    return False


def mask_secret(value: str) -> str:
    """Return a redacted version of a secret for safe display.

    Examples
    --------
    "sk-ant-api03-abc123xyz"  →  "sk-a****xyz"
    "short"                   →  "****"
    """
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]


# ── File permission checks ─────────────────────────────────────────────────────

def file_permission_mode(path: Path) -> Optional[int]:
    """Return the Unix permission bits for *path*, or None if it doesn't exist."""
    if not path.exists():
        return None
    return stat.S_IMODE(path.stat().st_mode)


def is_too_permissive(path: Path, *, expected: int) -> bool:
    """Return True if *path* has permission bits set beyond *expected*.

    For example, if *expected* is 0o600 and the file is 0o644, this returns
    True because the group-read bit (0o004) is set unexpectedly.
    """
    mode = file_permission_mode(path)
    if mode is None:
        return False
    return bool(mode & ~expected)


def fix_permissions(path: Path, mode: int) -> None:
    """Set Unix permission bits on *path* to *mode*."""
    os.chmod(path, mode)


# ── Git tracking detection ─────────────────────────────────────────────────────

def is_git_tracked(path: Path) -> bool:
    """Return True if *path* is currently tracked in a git repository.

    Runs ``git ls-files --error-unmatch <path>``; a zero exit code means the
    file is tracked.  Returns False if git is not installed, the path is not
    inside a git repo, or the command times out.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path.resolve())],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


# ── Config scanning ────────────────────────────────────────────────────────────

def scan_config_secrets(config: dict) -> list[str]:
    """Return a list of config keys whose values look like secrets.

    Example
    -------
    >>> scan_config_secrets({"foo": "sk-ant-abc123...longvalue", "bar": 42})
    ["foo"]
    """
    return [k for k, v in config.items() if is_secret_value(str(v))]
