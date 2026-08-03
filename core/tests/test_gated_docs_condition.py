"""A filter on the User-Agent is a finding, and the column that prices it says what it said (ADR-0051).

Some documentation hosts decide what to return from the User-Agent string. Asked by this project's
plain self-identifying agent they answer 403; asked by a conventional self-identifying agent — the
`Mozilla/5.0 (compatible; <name>/<version>)` form crawlers have used for decades — they answer with
the document. The two answers are byte-different at the same address.

`public-docs` keeps asking with the plain agent and keeps injecting whatever arrives, which on such a
host is nothing, and that is a true finding rather than a defect to route around. `gated-docs` asks
the SAME URLs with a declared conventional agent and injects what arrives instead. Every other input
is held constant — same URLs, same budget, same prompt, same tasks — so the difference between the
two columns is the price of one header and nothing else.

The load-bearing tests here are the negative ones. `public-docs` must have no code path that reaches
`gated_pages`; a browser string must be refused as the declared agent; the two retrievals of one URL
must not share a cache file; and a pack scored against its own source must not be able to stay quiet.
"""
import shutil
from pathlib import Path

import pytest
import yaml

from core.conditions import (KNOWN_CONDITIONS, GatedDocsCondition, PublicDocsCondition,
                             audit_docs_truncation, audit_gated_truncation, build_registry,
                             check_gated_disclosure, gated_disclosure, get_condition)
from core.docs_fetch import GATED_KEY, INJECTED_KEY, cache_path_for, manifest_urls
from core.factory import check_disclosure, check_substitution
from core.pack import Pack

ACME = Path(__file__).resolve().parent / "fixtures" / "pack-acme"

# The SAME address, which is the whole point: one host, one URL, two bodies.
SHARED_URL = "https://docs.example.invalid/gadgets/fetch"
GATED_LABEL = "Acme's operation reference, as served to a conventional self-identifying agent"
HONEST_AGENT = "Mozilla/5.0 (compatible; ai-readiness-eval-docs/1.0)"
BROWSER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

REFUSAL_TEXT = "403 Forbidden"                       # what the plain agent receives
GATED_TEXT = ("GET /gadgets/{id} — UNIQUE-GATED-BODY-7b21 returns one gadget. "
              + "filler " * 80)                      # what the conventional agent receives


def _pack_with_gated_docs(tmp_path: Path, *, declare: bool = True, agent: str = HONEST_AGENT,
                          also_anchor: bool = False, reason: str | None = None,
                          gated_pages: bool = True) -> Pack:
    """A copy of the fixture pack whose `gadget-fetch` task carries a `gated_pages` entry.

    `also_anchor` cites that same URL as the task's ground-truth anchor — the overlap the disclosure
    gate exists for, and the EXPECTED case on a filtering host, because the withheld pages are also
    the only first-party artifact a citation can point at.
    """
    root = tmp_path / "pack-gated"
    shutil.copytree(ACME, root)

    manifest_path = root / "docs-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    entry = manifest["tasks"]["gadget-fetch"]
    if gated_pages:
        entry[GATED_KEY] = [{"url": SHARED_URL, "role": "api-reference",
                             "note": "served to a conventional self-identifying agent",
                             "byte_size": len(GATED_TEXT),
                             "fetched_with_user_agent": agent}]
    if also_anchor:
        entry["anchors"] = [{"url": SHARED_URL, "note": "cited", "byte_size": len(GATED_TEXT)}]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    cfg_path = root / "pack.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    if declare:
        block = {"source_label": GATED_LABEL, "user_agent": agent}
        if reason is not None:
            block["scored_against_own_source"] = {"gadget-fetch": reason}
        cfg["gated_docs"] = block
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))

    pack = Pack.load(root)
    cache = pack.cache_path_for("gadget-fetch", SHARED_URL, manifest_key=GATED_KEY)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(GATED_TEXT)
    return pack


# --- the condition exists, and only when the pack asked for it -------------- #

def test_the_condition_order_is_declared():
    assert KNOWN_CONDITIONS == ("no-context", "public-docs", "gated-docs", "raw-spec", "mcp")


def test_the_condition_is_registered_only_when_the_pack_declares_it(tmp_path):
    """A column is a claim. A manifest that grew a gated list by accident must not add one."""
    assert "gated-docs" in build_registry(_pack_with_gated_docs(tmp_path / "yes"))
    undeclared = build_registry(_pack_with_gated_docs(tmp_path / "no", declare=False))
    assert "gated-docs" not in undeclared, (
        "the manifest still carries gated_pages in this pack — registration must follow the pack's "
        "declaration, not the manifest's contents")


def test_every_existing_pack_is_untouched():
    registry = build_registry(Pack.load(ACME))
    assert "gated-docs" not in registry
    assert set(registry) == {"no-context", "public-docs", "mcp"}


def test_asking_for_the_condition_on_a_pack_without_it_names_the_pack(tmp_path):
    with pytest.raises(KeyError) as exc:
        get_condition("gated-docs", _pack_with_gated_docs(tmp_path, declare=False))
    assert "gated-docs" in str(exc.value)


def test_building_the_condition_directly_still_refuses_an_undeclared_pack(tmp_path):
    """No default label and no default agent. The agent a column was retrieved with IS the finding
    that column exists to report, so it cannot be inherited from anywhere."""
    with pytest.raises(ValueError) as exc:
        GatedDocsCondition(_pack_with_gated_docs(tmp_path, declare=False))
    assert "no gated_docs block" in str(exc.value)


# --- the conduct rule, in code ---------------------------------------------- #

def test_a_browser_user_agent_is_refused(tmp_path):
    """The declared agent must NAME this project. A column obtained by claiming to be a browser
    measures what a vendor shows a reader it was deceived about."""
    with pytest.raises(ValueError) as exc:
        _pack_with_gated_docs(tmp_path, agent=BROWSER_AGENT)
    assert "impersonates a browser" in str(exc.value)


@pytest.mark.parametrize("agent", [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148",
    "Mozilla/5.0 (Windows NT 10.0) Edg/126.0.0.0",
    # No engine token at all, and still a claim to be a browser on an operating system: the
    # parenthetical does not open with `compatible;`.
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
])
def test_every_browser_shaped_agent_is_refused(tmp_path, agent):
    with pytest.raises(ValueError):
        _pack_with_gated_docs(tmp_path / agent[:12].replace("/", "_").replace(" ", "_"), agent=agent)


@pytest.mark.parametrize("agent", [
    "Mozilla/5.0 (compatible; ai-readiness-eval-docs/1.0)",
    "Mozilla/5.0 (compatible; ai-readiness-eval-docs/1.0; +https://example.invalid/bot)",
    "ai-readiness-eval-docs/1.0",
])
def test_a_self_identifying_agent_is_accepted(tmp_path, agent):
    """`Mozilla/5.0` alone must stay legal. It is a vestigial token every conventional crawler
    carries, and banning it would ban the one honest form that passes a filter of this kind —
    leaving impersonation as the only way through, which is the opposite of the ruling."""
    pack = _pack_with_gated_docs(tmp_path / str(abs(hash(agent))), agent=agent)
    assert pack.gated_docs.user_agent == agent


def test_a_gated_docs_block_without_an_agent_is_refused(tmp_path):
    root = tmp_path / "no-agent"
    shutil.copytree(ACME, root)
    cfg_path = root / "pack.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["gated_docs"] = {"source_label": GATED_LABEL}
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    with pytest.raises(ValueError) as exc:
        Pack.load(root)
    assert "without a user_agent" in str(exc.value)


# --- what each condition can reach ------------------------------------------ #

def test_the_gated_page_reaches_the_prompt_under_gated_docs(tmp_path):
    pack = _pack_with_gated_docs(tmp_path)
    task = pack.tasks_by_id()["gadget-fetch"]
    sent = GatedDocsCondition(pack).build_messages(task)[0]["content"]
    assert "UNIQUE-GATED-BODY-7b21" in sent
    assert GATED_LABEL in sent, "the block must be headed with what it is"


def test_a_gated_page_never_reaches_the_prompt_under_public_docs(tmp_path):
    """ADR-0034's guarantee, re-asserted against the fourth list — and this is the case where it
    matters most, because the two lists hold the SAME URL and different bodies. If `public-docs`
    could reach `gated_pages`, the column whose finding is that the document did not arrive would
    be injecting the document."""
    pack = _pack_with_gated_docs(tmp_path)
    task = pack.tasks_by_id()["gadget-fetch"]
    sent = PublicDocsCondition(pack).build_messages(task)[0]["content"]
    assert "UNIQUE-GATED-BODY-7b21" not in sent, "the gated page's CONTENT reached the docs prompt"
    assert PublicDocsCondition.manifest_key == INJECTED_KEY
    assert GatedDocsCondition.manifest_key == GATED_KEY


def test_the_manifest_key_is_fixed_at_class_definition_time():
    """No manifest, role string or config value can widen what a condition reads."""
    assert GatedDocsCondition.manifest_key == GATED_KEY
    assert GatedDocsCondition.manifest_key != INJECTED_KEY


def test_the_two_retrievals_of_one_url_do_not_share_a_cache_file(tmp_path):
    """The failure this prevents is silent and total: one file, written twice, and whichever list is
    fetched last decides what BOTH columns inject."""
    plain = cache_path_for(tmp_path, "gadget-fetch", SHARED_URL)
    gated = cache_path_for(tmp_path, "gadget-fetch", SHARED_URL, prefix=GATED_KEY)
    assert plain != gated
    assert gated.parent.name == GATED_KEY


def test_every_other_key_resolves_to_the_path_it_always_did(tmp_path):
    """No cached snapshot on disk may be invalidated and no committed `cache_file` may move."""
    base = cache_path_for(tmp_path, "t", SHARED_URL)
    for key in (None, INJECTED_KEY, "anchors", "spec_documents"):
        assert cache_path_for(tmp_path, "t", SHARED_URL, prefix=key) == base


def test_a_gated_page_is_still_a_manifest_url(tmp_path):
    """Anchoring resolves against every URL the manifest names, and that must include this list."""
    pack = _pack_with_gated_docs(tmp_path)
    assert SHARED_URL in manifest_urls(pack.docs_manifest())
    assert SHARED_URL not in manifest_urls(pack.docs_manifest(), include_anchors=False), \
        "include_anchors=False means exactly what public-docs injects"


def test_the_budget_is_the_one_public_docs_spends(tmp_path):
    """Any budget difference between two columns drawn from the same URLs would be
    indistinguishable from the effect being measured."""
    pack = _pack_with_gated_docs(tmp_path)
    assert GatedDocsCondition(pack)._budget == PublicDocsCondition(pack)._budget
    assert not hasattr(pack.gated_docs, "budget_tokens")


# --- the disclosure, computed rather than remembered ------------------------ #

def test_no_overlap_needs_no_declaration(tmp_path):
    records = gated_disclosure(_pack_with_gated_docs(tmp_path))
    assert [r["scored_against_own_source"] for r in records] == [False] * len(records)
    ok, why = check_gated_disclosure(_pack_with_gated_docs(tmp_path / "b"))
    assert ok and "injects no document its answer key cites" in why


def test_an_undeclared_overlap_is_refused(tmp_path):
    pack = _pack_with_gated_docs(tmp_path, also_anchor=True)
    ok, why = check_gated_disclosure(pack)
    assert not ok
    assert "gadget-fetch" in why and "scored against its own source" in why


def test_a_declared_overlap_passes_and_names_the_count(tmp_path):
    pack = _pack_with_gated_docs(tmp_path, also_anchor=True,
                                 reason="the withheld operation page is the only first-party "
                                        "artifact this operation is documented in")
    ok, why = check_gated_disclosure(pack)
    assert ok and "1/" in why


def test_a_disclosure_that_is_not_true_is_refused(tmp_path):
    """A stale declaration teaches a reader to discount the ones that are real."""
    pack = _pack_with_gated_docs(tmp_path, also_anchor=False, reason="stale, nothing overlaps")
    ok, why = check_gated_disclosure(pack)
    assert not ok and "do not overlap" in why


@pytest.mark.parametrize("reason", ["", "   ", None])
def test_a_blank_reason_does_not_satisfy_the_gate(tmp_path, reason):
    """A written reason, never a boolean (ADR-0031, ADR-0045)."""
    pack = _pack_with_gated_docs(tmp_path / str(reason), also_anchor=True, reason=reason)
    ok, _ = check_gated_disclosure(pack)
    assert not ok


def test_the_stage_gate_refuses_a_condition_that_would_inject_nothing(tmp_path):
    """Three conditions on the card and two experiments in the data is the thing being prevented."""
    pack = _pack_with_gated_docs(tmp_path, gated_pages=False)
    ok, why = check_disclosure(pack)
    assert not ok and "inject nothing" in why


def test_the_stage_gate_covers_both_optional_columns(tmp_path):
    """`disclosure` is one stage; a pack failing either half must fail it."""
    ok, why = check_disclosure(_pack_with_gated_docs(tmp_path, also_anchor=True))
    assert not ok and "gated-docs" in why


# --- the truncation audit reaches this column too --------------------------- #

def test_the_truncation_audit_labels_its_records_with_this_condition(tmp_path):
    pack = _pack_with_gated_docs(tmp_path)
    records = audit_gated_truncation(pack)
    assert records and {r["condition"] for r in records} == {"gated-docs"}


def test_the_audit_is_empty_for_a_pack_that_does_not_declare_the_column(tmp_path):
    assert audit_gated_truncation(_pack_with_gated_docs(tmp_path, declare=False)) == []


def test_the_two_audits_are_reported_apart(tmp_path):
    """On a filtering host the two corpora differ maximally — one is a refusal stub, the other is
    the document. Averaging them would describe neither."""
    pack = _pack_with_gated_docs(tmp_path)
    docs = {r["condition"] for r in audit_docs_truncation(pack)}
    gated = {r["condition"] for r in audit_gated_truncation(pack)}
    assert docs == {"public-docs"} and gated == {"gated-docs"}


# --- and the substitution gate, which this shape of host makes likely -------- #

def test_a_pack_whose_two_lists_hold_one_url_does_not_trip_the_substitution_gate(tmp_path):
    """The same URL in two lists is the DESIGN here, and their bodies differ. The gate keys on
    identical text at different URLs, so it must not fire on this."""
    pack = _pack_with_gated_docs(tmp_path, also_anchor=True, reason="declared")
    ok, why = check_substitution(pack)
    assert ok, why
