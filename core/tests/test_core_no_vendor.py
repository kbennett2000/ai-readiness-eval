"""The guard: core/ is vendor-agnostic (ADR-0001, ADR-0002).

No file under core/ may name a vendor. If a vendor assumption creeps back into the engine, this test
fails. Vendor specifics must arrive through a loaded Pack, never a literal in core.
"""
import re
from pathlib import Path

import pytest

from core.pack import Pack

CORE_DIR = Path(__file__).resolve().parents[1]
ACME_PACK_DIR = CORE_DIR / "tests" / "fixtures" / "pack-acme"

# Tokens that would betray a hardcoded vendor. `pack-acme` is a synthetic, non-vendor identity used
# only by the tests, so it is allowed; a real vendor name is not.
VENDOR_TOKENS = re.compile(r"sailpoint|isc_spec_context|developer\.sailpoint|idn/", re.IGNORECASE)


def _core_py_files():
    for path in sorted(CORE_DIR.rglob("*.py")):
        # Skip this guard file itself: it legitimately spells out the vendor tokens as detector
        # patterns. Everything else under core/ is scanned.
        if path.resolve() == Path(__file__).resolve():
            continue
        yield path


def test_no_vendor_token_anywhere_in_core():
    offenders = []
    for path in _core_py_files():
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if VENDOR_TOKENS.search(line):
                offenders.append(f"{path.relative_to(CORE_DIR.parent)}:{i}: {line.strip()}")
    assert not offenders, (
        "core/ must carry no vendor token; found:\n" + "\n".join(offenders)
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
