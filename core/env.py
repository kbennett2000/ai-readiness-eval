"""Tiny zero-dependency .env reader.

We deliberately avoid a python-dotenv dependency (ADR-0004): the harness only
needs to read a couple of KEY=VALUE lines, and a reviewer can see exactly what it
does. Real process environment variables take precedence over the .env file, so
an operator can `export ANTHROPIC_API_KEY=...` without editing a file.

Never logs or echoes values — callers read specific keys and are responsible for
keeping secrets out of output.
"""
from __future__ import annotations

import os
from pathlib import Path

# Repo root is one level up from this file (core/env.py -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = REPO_ROOT / ".env"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a minimal KEY=VALUE .env file. Ignores blanks and `#` comments.

    Supports optional surrounding single/double quotes and a leading `export `.
    Does not do variable interpolation — this is intentionally simple.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key:
            values[key] = val
    return values


def load_env(path: Path | None = None) -> dict[str, str]:
    """Return a mapping of config keys, real environment overriding the .env file."""
    file_values = _parse_env_file(path or DEFAULT_ENV_PATH)
    merged = dict(file_values)
    merged.update({k: v for k, v in os.environ.items() if k in file_values or k in _KNOWN_KEYS})
    return merged


_KNOWN_KEYS = {"ANTHROPIC_API_KEY", "EVAL_MODEL"}

DEFAULT_MODEL = "claude-sonnet-4-6"


def get_config(path: Path | None = None) -> tuple[str | None, str]:
    """Return (api_key, model). api_key is None if unset/empty (→ live run BLOCKED)."""
    env = load_env(path)
    api_key = env.get("ANTHROPIC_API_KEY") or None
    model = env.get("EVAL_MODEL") or DEFAULT_MODEL
    return api_key, model
