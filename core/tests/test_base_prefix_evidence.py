"""ADR-0055 — an endpoint-base tolerance must cite the artifact that writes the address that way.

`auth_flow_alternates` has carried an evidence requirement since ADR-0023, gated at `roundtrip`.
`endpoint_base_prefix` carried none: a bare list of strings beside a prose argument. A cohort-wide
audit measured what that asymmetry was worth — 46 of 57 alternates held up against the vendor's own
bytes, while 3 of 20 base prefixes had no first-party artifact writing them at all, one of them in a
pack that had already written down, in the same file, that no readable artifact did.

These tests break each rule on purpose in BOTH directions: a malformed entry must block, and a
well-formed one must not. The must-not-inflate test at the end is the one that keeps the new shape
free — an entry that carries its citation may not match anything the bare string did not.
"""
import pytest

from core import roundtrip, scorer
from core.answer_block import Endpoint
from core.pack import Pack

VALID_NOTE = ("The vendor's own reference page prints the address with this leading segment, "
              "immediately after the host.")
VALID = {"prefix": "/gateway", "evidence": "https://developer.example.test/reference",
         "note": VALID_NOTE}


def problems(raw):
    return scorer.base_prefix_problems(raw)


# --------------------------------------------------------------------------------------------- #
# The gate accepts what it should.
# --------------------------------------------------------------------------------------------- #

def test_a_well_formed_entry_blocks_nothing():
    assert problems([VALID]) == []


def test_several_well_formed_entries_block_nothing():
    second = dict(VALID, prefix="/api", evidence="https://developer.example.test/other")
    assert problems([VALID, second]) == []


def test_no_declaration_at_all_is_not_a_problem():
    """The default. Most packs declare no tolerance and must stay unaffected by this rule."""
    assert problems(None) == []
    assert problems([]) == []
    assert problems("") == []


# --------------------------------------------------------------------------------------------- #
# Each rule, broken on purpose.
# --------------------------------------------------------------------------------------------- #

def test_a_bare_string_blocks():
    """The shape the whole cohort used, and the shape that let three uncited entries stand."""
    out = problems("/gateway")
    assert len(out) == 1 and "bare string" in out[0]


def test_a_bare_list_blocks_every_entry_not_just_the_first():
    out = problems(["/gateway", "/api"])
    assert len(out) == 2
    assert "[0]" in out[0] and "[1]" in out[1]


def test_evidence_on_a_rehosting_host_blocks():
    out = problems([dict(VALID, evidence="https://web.archive.org/web/2020/https://v.test/x")])
    assert any("rehosts rather than publishes" in p for p in out)


def test_evidence_that_is_not_a_url_blocks():
    out = problems([dict(VALID, evidence="developer.example.test/reference")])
    assert any("needs an `evidence:` URL" in p for p in out)


def test_a_missing_evidence_key_blocks_even_when_a_note_is_present():
    out = problems([{"prefix": "/gateway", "note": VALID_NOTE}])
    assert any("needs an `evidence:` URL" in p for p in out)


@pytest.mark.parametrize("note", ["", "   ", "too short to be a reason", None])
def test_a_note_under_forty_characters_blocks(note):
    out = problems([dict(VALID, note=note)])
    assert any("at least 40 characters" in p for p in out)


def test_a_prefix_that_is_not_a_path_blocks():
    assert any("must begin with '/'" in p for p in problems([dict(VALID, prefix="gateway")]))


def test_a_missing_prefix_blocks():
    out = problems([{"evidence": VALID["evidence"], "note": VALID_NOTE}])
    assert any("needs a `prefix:` string" in p for p in out)


def test_a_duplicate_prefix_blocks():
    out = problems([VALID, dict(VALID, evidence="https://developer.example.test/elsewhere")])
    assert any("declared more than once" in p for p in out)


def test_an_entry_of_the_wrong_type_blocks_rather_than_raising():
    """The gate loop has no exception handling around it; a crash would skip the block entirely."""
    assert any("needs a `prefix:` string" in p for p in problems([42]))


# --------------------------------------------------------------------------------------------- #
# The new shape must not widen matching. This is the property that makes ADR-0055 free.
# --------------------------------------------------------------------------------------------- #

def _ep(path):
    return Endpoint(method="GET", path=path, api_version="v1")


def test_the_cited_shape_matches_exactly_what_the_bare_shape_matched(tmp_path):
    """Same prefixes, two notations, identical segments — so no archived score can move."""
    bare = scorer.declared_prefix_entries(["/gateway", "/api"])
    cited = scorer.declared_prefix_entries([VALID, dict(VALID, prefix="/api")])
    assert [e["prefix"] for e in bare] == [e["prefix"] for e in cited]


def test_a_pack_declaring_the_cited_shape_produces_the_same_segments(tmp_path, acme_pack):
    """Through `Pack`, not just the helper — `base_prefix_segments` is what the scorer is given."""
    import shutil

    import yaml
    for shape in (["/gateway", "/api"], [VALID, dict(VALID, prefix="/api")]):
        d = tmp_path / f"pack-{len(str(shape))}"
        shutil.copytree(acme_pack.root, d)
        cfg = yaml.safe_load((d / "pack.yaml").read_text())
        cfg["endpoint_base_prefix"] = shape
        (d / "pack.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
        assert Pack.load(d).base_prefix_segments == [["gateway"], ["api"]]


def test_evidence_cannot_make_two_different_resources_compare_equal():
    """The must-not-inflate property, restated for the cited shape (ADR-0017/0039 pinned it)."""
    prefixes = [e["prefix"] for e in scorer.declared_prefix_entries([VALID])]
    segs = [scorer.normalize_path(p) for p in prefixes]
    gt = {"method": "GET", "path": "/gateway/widgets", "api_version": "v1"}
    records = scorer._match_endpoints([gt], [_ep("/gateway/gadgets")], segs)
    assert not records[0]["matched"], "the tolerance made two different resources equal"


# --------------------------------------------------------------------------------------------- #
# It blocks at the gate, not merely in a helper nobody calls.
# --------------------------------------------------------------------------------------------- #

def test_roundtrip_blocks_a_pack_whose_tolerance_is_uncited(tmp_path, acme_pack):
    import shutil

    import yaml
    d = tmp_path / "uncited"
    shutil.copytree(acme_pack.root, d)
    cfg = yaml.safe_load((d / "pack.yaml").read_text())
    cfg["endpoint_base_prefix"] = "/gateway"
    (d / "pack.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))

    control = next(c for c in roundtrip.check_pack(Pack.load(d))
                   if c.task_id == "(endpoint-base-evidence)")
    assert not control.ok
    assert any("bare string" in p for p in control.problems)


def test_roundtrip_passes_a_pack_whose_tolerance_is_cited(tmp_path, acme_pack):
    import shutil

    import yaml
    d = tmp_path / "cited"
    shutil.copytree(acme_pack.root, d)
    cfg = yaml.safe_load((d / "pack.yaml").read_text())
    cfg["endpoint_base_prefix"] = [VALID]
    (d / "pack.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))

    control = next(c for c in roundtrip.check_pack(Pack.load(d))
                   if c.task_id == "(endpoint-base-evidence)")
    assert control.ok and control.problems == []


def test_the_control_is_present_even_when_no_tolerance_is_declared(acme_pack):
    """A control that only appears when it has something to say cannot be seen to be absent."""
    ids = [c.task_id for c in roundtrip.check_pack(acme_pack)]
    assert ids.count("(endpoint-base-evidence)") == 1
