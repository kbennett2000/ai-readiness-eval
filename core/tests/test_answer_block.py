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


# --- ADR-0014: the flow-sequence repair -------------------------------------
#
# A model naming a bracketed API parameter (`sortBy[0].name`) inside the flow
# sequence the prompt contract itself demonstrates produces invalid YAML. The
# repair rescues that answer; it must never rescue anything whose meaning it
# would have to guess at.

def _block(body: str) -> str:
    return (
        "```answer-summary\n"
        "endpoints:\n  - method: GET\n    path: /v3/accounts\n    api_version: v3\n"
        "auth_flow: OAuth2 bearer token\n"
        f"{body}\n"
        "```"
    )


def test_repairs_bracketed_parameter_names_in_a_flow_sequence():
    result = answer_block.parse(_block(
        "required_scopes: []\n"
        "key_parameters: [id, skip, take, sortBy[0].name, sortBy[0].direction]"
    ))
    assert not result.is_failure
    assert result.repaired is True
    assert result.summary.key_parameters == [
        "id", "skip", "take", "sortBy[0].name", "sortBy[0].direction",
    ]
    # The text that was actually parsed is retained, so the score is reproducible.
    assert "sortBy[0].name" in result.repaired_block_text


def test_repairs_empty_bracket_index_notation():
    result = answer_block.parse(_block(
        "key_parameters: [requestedFor, requestedItems, requestedItems[].type]"
    ))
    assert not result.is_failure
    assert result.repaired is True
    assert result.summary.key_parameters[-1] == "requestedItems[].type"


def test_repairs_scopes_as_well_as_parameters():
    result = answer_block.parse(_block(
        "required_scopes: [idn:accounts:read, sortBy[0].name]\nkey_parameters: [id]"
    ))
    assert not result.is_failure
    assert result.repaired is True
    assert result.summary.required_scopes == ["idn:accounts:read", "sortBy[0].name"]


def test_an_ordinary_parse_is_not_marked_repaired():
    result = answer_block.parse(PERFECT)
    assert not result.is_failure
    assert result.repaired is False
    assert result.repaired_block_text is None


def test_a_valid_flow_sequence_is_never_rewritten():
    """The repair only ever runs after YAML has already failed."""
    result = answer_block.parse(_block("key_parameters: [filters, id]"))
    assert not result.is_failure
    assert result.repaired is False


# --- must-not-repair: the score-manufacture cases ---------------------------
#
# `key_parameters` and `required_scopes` are both scored by CONTAINMENT, so
# splitting one item into several can only ever raise a score, never lower it.
# A repair that guessed at an item boundary would hand the scorer ground-truth
# names that valid YAML would never have produced. Every case below must stay a
# format failure.

def test_a_comma_inside_a_quoted_item_is_never_split():
    """The counterexample that decided the design: splitting here would score 1.0
    on key_parameters where valid YAML scores 0.0, for byte-identical content."""
    result = answer_block.parse(_block(
        'key_parameters: ["requestedFor, requestedItems", requestedItems[].id]'
    ))
    assert result.is_failure
    assert "not valid YAML" in result.failure.reason


def test_a_quoted_scope_sentence_is_never_split():
    result = answer_block.parse(_block(
        'required_scopes: ["one of idn:accounts:read, idn:accounts:manage", sortBy[0]]'
    ))
    assert result.is_failure


def test_prose_items_are_not_repaired():
    result = answer_block.parse(_block(
        'key_parameters: [filters: name eq "x", sortBy[0].name]'
    ))
    assert result.is_failure


def test_an_unterminated_quote_abandons_the_repair():
    result = answer_block.parse(_block(
        'key_parameters: [sortBy[0].name, "unterminated]'
    ))
    assert result.is_failure


def test_a_trailing_comment_containing_a_bracket_abandons_the_repair():
    result = answer_block.parse(_block(
        "key_parameters: [a[0], b] # note [see docs]"
    ))
    assert result.is_failure


def test_a_comma_inside_brackets_or_braces_is_not_a_separator():
    """Depth tracking covers braces too; an item it cannot vouch for is abandoned."""
    result = answer_block.parse(_block(
        "key_parameters: [body{type, id}, sortBy[0].name]"
    ))
    assert result.is_failure


# --- ADR-0022: the trigger is the parser, not a punctuation test ------------
#
# ADR-0014 decided *which lines* to rewrite by looking for a square bracket,
# because the indexed-parameter notation is what it was written to repair. A
# brace placeholder is equally invalid YAML and carries no square bracket, so
# the guard skipped the only broken line in the block and the repair reported
# nothing to do. Both cases below are transcribed from real archived runs.

def test_repairs_a_brace_placeholder_in_a_scope_list():
    """The shape a model reaches for when it does not know a tenant-specific value."""
    result = answer_block.parse(_block(
        "required_scopes: [scp.pc.{registered_role_name}]\n"
        "key_parameters: [grant_type, client_id]"
    ))
    assert not result.is_failure
    assert result.repaired is True
    assert result.summary.required_scopes == ["scp.pc.{registered_role_name}"]


def test_the_rest_of_a_repaired_answer_survives_with_it():
    """The point of repairing at all: a format failure costs every dimension.

    The run this is transcribed from named the correct endpoint. Discarding it
    scored the model zero on endpoint, method, version and auth because of a
    brace in a *scope* list — four dimensions lost to a fifth.
    """
    result = answer_block.parse(
        "```answer-summary\n"
        "endpoints:\n  - method: GET\n    path: /common/v1/activities\n    api_version: v1\n"
        "auth_flow: OAuth2 client credentials bearer token\n"
        "required_scopes: [scp.pc.{your_registered_service_scope}]\n"
        "key_parameters: [grant_type, client_id, client_secret, scope]\n"
        "```"
    )
    assert not result.is_failure
    assert result.summary.endpoints[0].path == "/common/v1/activities"
    assert result.summary.auth_flow == "OAuth2 client credentials bearer token"


def test_a_valid_flow_sequence_is_still_never_rewritten():
    """The predicate must narrow to the broken line, not widen to every line."""
    assert answer_block._repair_flow_lists(
        "required_scopes: []\nkey_parameters: [id, skip, take]"
    ) is None


def test_the_trigger_asks_the_parser_rather_than_scanning_for_characters():
    """Pins the mechanism, not just the outcome (ADR-0022).

    A future edit that swaps the predicate back for a character test would keep
    every case above passing if it happened to list `{` — and would fail the next
    notation nobody enumerated. This asserts the question being asked.
    """
    assert answer_block._is_valid_yaml_line("key_parameters: [a, b]") is True
    assert answer_block._is_valid_yaml_line("key_parameters: [sortBy[0].name]") is False
    assert answer_block._is_valid_yaml_line("required_scopes: [scp.pc.{role}]") is False


# --- must-not-repair: scope boundaries, pinned deliberately -----------------

def test_a_multiline_flow_sequence_is_out_of_scope():
    """Never observed in 826 archived runs; tolerance is written against evidence."""
    result = answer_block.parse(_block(
        "key_parameters: [\n  id,\n  sortBy[0].name,\n]"
    ))
    assert result.is_failure


def test_other_keys_are_out_of_scope():
    result = answer_block.parse(
        "```answer-summary\n"
        "endpoints: [{method: GET, path: /v3/a[0], api_version: v3}]\n"
        "auth_flow: bearer\n```"
    )
    assert result.is_failure


def test_unrelated_yaml_damage_keeps_its_original_reason():
    result = answer_block.parse("```answer-summary\nendpoints: [ : : bad yaml\n```")
    assert result.is_failure
    assert "not valid YAML" in result.failure.reason
    assert result.repaired is False


def test_a_missing_block_is_not_repairable():
    result = answer_block.parse("I cannot answer that.")
    assert result.is_failure
    assert "no ```answer-summary``` block found" in result.failure.reason


def test_render_block_round_trips_a_bracketed_parameter_name():
    """render_block emits BLOCK sequences, so it can never produce the shape the
    repair exists to fix — which is exactly why the ADR-0010 round-trip control
    could not have caught this defect."""
    summary = answer_block.AnswerSummary(
        endpoints=[answer_block.Endpoint("GET", "/v3/a", "v3")],
        auth_flow="bearer",
        required_scopes=[],
        key_parameters=["id", "sortBy[0].name"],
    )
    rendered = answer_block.render_block(summary)
    assert "key_parameters: [" not in rendered
    result = answer_block.parse(rendered)
    assert not result.is_failure
    assert result.repaired is False
    assert result.summary.key_parameters == ["id", "sortBy[0].name"]
