"""The guards: the core ENGINE is vendor-agnostic, and the public repo names no prospect.

1. No core ENGINE module (`core/*.py`, excluding the test suite) may name a vendor — vendor specifics
   must arrive through a loaded Pack. The test suite MAY name SailPoint, which is the public reference
   pack (not a prospect) and is exercised for cross-pack coverage.
2. No tracked file in the public repo may name a measured prospect (they live in a private repo).
"""
import re
import subprocess
from pathlib import Path

import pytest

from core.pack import Pack

CORE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CORE_DIR.parent
ACME_PACK_DIR = CORE_DIR / "tests" / "fixtures" / "pack-acme"

# Tokens that would betray a hardcoded vendor in the engine. SailPoint is the public reference pack, so
# its name/spec-prefix are what the engine must NOT bake in (they belong in packs/sailpoint/, not core).
VENDOR_TOKENS = re.compile(r"sailpoint|isc_spec_context|developer\.sailpoint|idn/", re.IGNORECASE)

# Prospect names that must never appear anywhere tracked in the PUBLIC repo (privacy, cycle 2).
# Every prospect the factory has carded belongs here — the list went stale between cycles 2 and 6,
# which let a recon note naming two later prospects reach a commit before the guard objected.
PROSPECT_TOKENS = re.compile(r"saviynt|okta|cyberark|oneidentity|pingone", re.IGNORECASE)

# One prospect's name is also an ordinary phrase in this domain: the reference pack legitimately says
# "exactly one identity" and "one identity's accounts". Matching it case-insensitively would fire on
# those, so it is matched only as the capitalized proper noun.
PROSPECT_TOKENS_CASED = re.compile(r"One Identity")


def _engine_py_files():
    """Top-level engine modules — core/*.py, NOT core/tests/ (tests may name the reference pack)."""
    return sorted(CORE_DIR.glob("*.py"))


def test_no_vendor_token_in_core_engine():
    offenders = []
    for path in _engine_py_files():
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if VENDOR_TOKENS.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{i}: {line.strip()}")
    assert not offenders, (
        "the core engine must carry no vendor token; found:\n" + "\n".join(offenders)
    )


def test_public_repo_names_no_prospect():
    """Every tracked file (except this guard, which spells the tokens as patterns) is prospect-free."""
    try:
        tracked = subprocess.check_output(
            ["git", "ls-files"], cwd=REPO_ROOT, text=True
        ).splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")
    this_file = Path(__file__).resolve()
    offenders = []
    for rel in tracked:
        p = REPO_ROOT / rel
        if p.resolve() == this_file or not p.is_file():
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if PROSPECT_TOKENS.search(line) or PROSPECT_TOKENS_CASED.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()[:80]}")
    assert not offenders, (
        "the public repo must name no measured prospect (they live in the private packs repo); found:\n"
        + "\n".join(offenders)
    )


def test_no_vendor_token_in_pack_acme_fixture():
    # The test fixture itself must stay vendor-neutral, else the guard above would have to whitelist it.
    for path in sorted(ACME_PACK_DIR.rglob("*")):
        if path.is_file():
            assert not VENDOR_TOKENS.search(path.read_text()), f"vendor token leaked into {path}"


def test_conditions_use_pack_prefix_not_a_constant(acme_pack):
    """The mcp tool prefix is read from the pack, not baked into core — swap the pack, swap the prefix."""
    from core.conditions import McpCondition
    pol = McpCondition(acme_pack).cli_policy()
    assert pol.allowed_tools == ["mcp__acme__*", "ToolSearch"]
    # a differently-configured pack yields a different prefix, proving it is not a constant
    import copy
    other = copy.copy(acme_pack)
    other.context_layer = copy.copy(acme_pack.context_layer)
    other.context_layer.mcp_tool_prefix = "mcp__widgets__"
    assert McpCondition(other).cli_policy().allowed_tools == ["mcp__widgets__*", "ToolSearch"]


def test_preflight_marker_comes_from_pack(acme_pack):
    """The canary project marker is pack-supplied, not a module constant in core."""
    import core.preflight as preflight
    src = Path(preflight.__file__).read_text()
    assert "PROJECT_MARKER =" not in src, "core.preflight must not hardcode a project marker"
    assert acme_pack.project_marker == "acme-eval-project"


@pytest.mark.parametrize("token", ["sailpoint", "SailPoint", "isc_spec_context", "idn/"])
def test_guard_regex_actually_matches_known_vendor_tokens(token):
    # Guard the guard: ensure the detector would fire on the tokens it claims to catch.
    assert VENDOR_TOKENS.search(f"prefix {token} suffix")
