"""Tests for the answer-summary parser (core/answer_block.py).

The parser is one of the two auditable cores; malformed input must classify as a
format_failure, never a silent zero or pass.
"""
from core import answer_block


PERFECT = """\
Here's how you'd do it.

```answer-summary
endpoints:
  - method: GET
    path: /v3/accounts
    api_version: v3
auth_flow: OAuth2 bearer token
required_scopes: [idn:accounts:read]
key_parameters: [filters]
```
"""


def test_parses_well_formed_block():
    result = answer_block.parse(PERFECT)
    assert not result.is_failure
    s = result.summary
    assert len(s.endpoints) == 1
    assert s.endpoints[0].method == "GET"
    assert s.endpoints[0].path == "/v3/accounts"
    assert s.endpoints[0].api_version == "v3"
    assert s.auth_flow == "OAuth2 bearer token"
    assert s.required_scopes == ["idn:accounts:read"]
    assert s.key_parameters == ["filters"]


def test_last_block_wins_when_example_echoed():
    text = (
        "Example of the format:\n"
        "```answer-summary\n"
        "endpoints:\n  - method: GET\n    path: /v3/example\n    api_version: v3\n"
        "auth_flow: x\nrequired_scopes: []\nkey_parameters: [a]\n```\n"
        "And here is my real answer:\n"
        "```answer-summary\n"
        "endpoints:\n  - method: POST\n    path: /v3/search\n    api_version: v3\n"
        "auth_flow: OAuth2 bearer token\nrequired_scopes: [sp:search:read]\nkey_parameters: [query]\n```\n"
    )
    result = answer_block.parse(text)
    assert not result.is_failure
    assert result.summary.endpoints[0].path == "/v3/search"
    assert result.summary.endpoints[0].method == "POST"


def test_missing_block_is_format_failure():
    result = answer_block.parse("Just prose, no fenced block at all.")
    assert result.is_failure
    assert "no ```answer-summary```" in result.failure.reason


def test_empty_response_is_format_failure():
    assert answer_block.parse("").is_failure
    assert answer_block.parse("   \n  ").is_failure


def test_malformed_yaml_is_format_failure():
    text = "```answer-summary\nendpoints: [ : : bad yaml\n```"
    result = answer_block.parse(text)
    assert result.is_failure
    assert "not valid YAML" in result.failure.reason
    assert result.failure.raw_block is not None


def test_non_mapping_block_is_format_failure():
    text = "```answer-summary\n- just\n- a\n- list\n```"
    result = answer_block.parse(text)
    assert result.is_failure
    assert "not a YAML mapping" in result.failure.reason


def test_missing_endpoints_is_format_failure():
    text = "```answer-summary\nauth_flow: OAuth2 bearer token\nrequired_scopes: []\n```"
    result = answer_block.parse(text)
    assert result.is_failure
    assert "endpoints" in result.failure.reason


def test_empty_endpoints_list_is_format_failure():
    text = "```answer-summary\nendpoints: []\nauth_flow: x\n```"
    result = answer_block.parse(text)
    assert result.is_failure


def test_endpoint_not_a_mapping_is_format_failure():
    text = "```answer-summary\nendpoints:\n  - just-a-string\nauth_flow: x\n```"
    result = answer_block.parse(text)
    assert result.is_failure
    assert "endpoints[0]" in result.failure.reason


def test_scalar_scopes_coerced_to_list():
    text = (
        "```answer-summary\n"
        "endpoints:\n  - method: GET\n    path: /v3/accounts\n    api_version: v3\n"
        "auth_flow: OAuth2 bearer token\n"
        "required_scopes: idn:accounts:read\n"   # scalar, not a list
        "key_parameters: filters\n"
        "```"
    )
    result = answer_block.parse(text)
    assert not result.is_failure
    assert result.summary.required_scopes == ["idn:accounts:read"]
    assert result.summary.key_parameters == ["filters"]


def test_missing_optional_fields_default_empty():
    text = (
        "```answer-summary\n"
        "endpoints:\n  - method: GET\n    path: /v3/accounts\n    api_version: v3\n"
        "```"
    )
    result = answer_block.parse(text)
    assert not result.is_failure
    assert result.summary.required_scopes == []
    assert result.summary.key_parameters == []
    assert result.summary.auth_flow is None
