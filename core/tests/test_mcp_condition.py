"""Tests for the mcp condition + per-condition tool policy and discipline assertion.

Uses the synthetic `pack-acme` (tool prefix `mcp__acme__`); core hardcodes no vendor prefix.
"""
from core import conditions
from core.conditions import McpCondition, NoContextCondition


def test_mcp_registered(acme_pack):
    assert "mcp" in conditions.available_conditions()
    assert isinstance(conditions.get_condition("mcp", acme_pack), McpCondition)


def test_two_condition_pack_omits_mcp(acme_pack, monkeypatch):
    # A pack with no context layer runs in two-condition mode: no mcp condition is built.
    monkeypatch.setattr(acme_pack, "context_layer", None)
    reg = conditions.build_registry(acme_pack)
    assert set(reg) == {"no-context", "public-docs"}


def test_no_context_policy_denies_everything():
    pol = NoContextCondition().cli_policy()
    assert pol.allowed_tools is None
    assert pol.mcp_config is None
    assert "ToolSearch" in pol.disallowed_tools     # discovery meta-tool denied too
    assert "WebFetch" in pol.disallowed_tools


def test_mcp_policy_allows_only_pack_prefix_and_discovery(acme_pack):
    pol = McpCondition(acme_pack).cli_policy()
    assert pol.allowed_tools == ["mcp__acme__*", "ToolSearch"]
    assert "ToolSearch" not in pol.disallowed_tools  # discovery must stay available
    assert "WebFetch" in pol.disallowed_tools        # everything else denied
    assert pol.mcp_config.endswith(".mcp.json")
    assert pol.strict_mcp is True
    assert pol.permission_mode == "bypassPermissions"


def test_no_context_check_tools():
    c = NoContextCondition()
    ok, _ = c.check_tools([])
    assert ok
    bad_ok, detail = c.check_tools([{"name": "WebFetch"}])
    assert not bad_ok and "WebFetch" in detail


def test_mcp_check_tools_allows_layer_tools_and_discovery(acme_pack):
    c = McpCondition(acme_pack)
    ok, detail = c.check_tools([{"name": "ToolSearch"},
                                {"name": "mcp__acme__get_scopes"}])
    assert ok and "1 call" in detail
    # zero context-layer calls is allowed (a finding, not a violation)
    ok2, detail2 = c.check_tools([])
    assert ok2 and "from memory" in detail2
    # a tool outside the context layer is a violation
    bad, detail3 = c.check_tools([{"name": "Bash"}])
    assert not bad and "Bash" in detail3
