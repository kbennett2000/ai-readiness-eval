"""A specification is not documentation, and the column that injects one says so (ADR-0050).

`public-docs` means "the vendor's human documentation, as a fetcher retrieves it". For a vendor whose
documentation is a JavaScript shell and whose machine-readable specification is complete and free to
fetch, the tempting move is to inject the specification into that column. It would produce a number.
It would also silently change what the column means for one vendor, and every cross-vendor table
would compare two different things under one heading.

So the specification gets its own condition, its own column, and two rules that keep the answer
readable rather than flattering:

  * it spends the SAME budget as `public-docs`, so the comparison is artifact-vs-prose and not
    generous-vs-stingy; and
  * where the injected document is also the answer key's anchor, the pack must SAY SO, because the
    column is then a ceiling rather than a measurement.

The load-bearing tests here are the negative ones: `public-docs` must not be able to reach a spec
document, and a pack that is scored against its own source must not be able to stay quiet about it.
"""
import shutil
from pathlib import Path

import pytest
import yaml

from core.conditions import (KNOWN_CONDITIONS, PublicDocsCondition, RawSpecCondition,
                             audit_docs_truncation, audit_spec_truncation, build_registry,
                             check_spec_disclosure, get_condition, spec_disclosure)
from core.docs_fetch import SPEC_KEY, manifest_urls
from core.factory import check_disclosure
from core.pack import Pack

ACME = Path(__file__).resolve().parent / "fixtures" / "pack-acme"

SPEC_URL = "https://specs.example.invalid/gadgets-openapi.json"
PAGE_URL = "https://docs.example.invalid/gadgets"
SPEC_LABEL = "Acme's OpenAPI 3 documents"
# Long enough to be searchable, and carrying a string nothing else in the fixture has.
SPEC_TEXT = ('{"openapi":"3.0.1","paths":{"/gadgets/{id}":{"get":{"operationId":"UNIQUE-SPEC-BODY-'
             '9c4e"}}},"filler":"' + "x" * 400 + '"}')


def _pack_with_a_spec(tmp_path: Path, *, declare_raw_spec: bool = True,
                      also_anchor: bool = False, reason: str | None = None) -> Pack:
    """A copy of the fixture pack whose `gadget-fetch` task declares a spec document.

    `also_anchor` additionally cites that same document as the task's ground-truth anchor, which is
    the overlap the disclosure gate exists for. `reason` is what the pack says about it.
    """
    root = tmp_path / "pack-spec"
    shutil.copytree(ACME, root)

    manifest_path = root / "docs-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["tasks"]["gadget-fetch"][SPEC_KEY] = [
        {"url": SPEC_URL, "note": "the vendor's own machine-readable document",
         "byte_size": len(SPEC_TEXT)}
    ]
    if also_anchor:
        manifest["tasks"]["gadget-fetch"]["anchors"] = [
            {"url": SPEC_URL, "note": "cited", "byte_size": len(SPEC_TEXT)}
        ]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    cfg_path = root / "pack.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    if declare_raw_spec:
        block = {"source_label": SPEC_LABEL}
        if reason is not None:
            block["scored_against_own_source"] = {"gadget-fetch": reason}
        cfg["raw_spec"] = block
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))

    pack = Pack.load(root)
    cache = pack.cache_path_for("gadget-fetch", SPEC_URL)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(SPEC_TEXT)
    return pack


# --- the condition exists, and only when the pack asked for it -------------- #

def test_the_condition_is_registered_only_when_the_pack_declares_it(tmp_path):
    """A column is a claim. A manifest that grew a spec list by accident must not add one."""
    declared = build_registry(_pack_with_a_spec(tmp_path / "yes"))
    assert "raw-spec" in declared

    undeclared = build_registry(_pack_with_a_spec(tmp_path / "no", declare_raw_spec=False))
    assert "raw-spec" not in undeclared, (
        "the manifest still carries spec_documents in this pack — registration must follow the "
        "pack's declaration, not the manifest's contents")


def test_every_existing_pack_is_untouched():
    """The fixture pack declares no raw_spec, so its registry must be exactly what it was before —
    including the `mcp` it does declare, which is the point: adding a condition must not perturb the
    ones already there."""
    registry = build_registry(Pack.load(ACME))
    assert "raw-spec" not in registry
    assert set(registry) == {"no-context", "public-docs", "mcp"}


def test_asking_for_the_condition_on_a_pack_without_it_names_the_pack(tmp_path):
    pack = _pack_with_a_spec(tmp_path, declare_raw_spec=False)
    with pytest.raises(KeyError) as exc:
        get_condition("raw-spec", pack)
    assert "raw-spec" in str(exc.value)


def test_building_the_condition_directly_still_refuses_an_undeclared_pack(tmp_path):
    """Bypassing the registry must not bypass the ruling: there is no default label, because a
    specification injected under a heading that says 'documentation' is the exact confusion this
    condition was created to prevent."""
    pack = _pack_with_a_spec(tmp_path, declare_raw_spec=False)
    with pytest.raises(ValueError) as exc:
        RawSpecCondition(pack)
    assert "no raw_spec block" in str(exc.value)


def test_the_condition_order_is_declared():
    assert KNOWN_CONDITIONS == ("no-context", "public-docs", "raw-spec", "mcp")


# --- what each condition can reach ------------------------------------------ #

def test_the_spec_reaches_the_prompt_under_raw_spec(tmp_path):
    pack = _pack_with_a_spec(tmp_path)
    task = pack.tasks_by_id()["gadget-fetch"]
    sent = RawSpecCondition(pack).build_messages(task)[0]["content"]
    assert "UNIQUE-SPEC-BODY-9c4e" in sent
    assert SPEC_LABEL in sent, "the block must be headed with the artifact's own name"


def test_a_spec_document_never_reaches_the_prompt_under_public_docs(tmp_path):
    """ADR-0034's guarantee, re-asserted against the third list. `public-docs` reads `pages` and
    nothing else — the key is fixed at class-definition time, so no manifest can widen it."""
    pack = _pack_with_a_spec(tmp_path)
    task = pack.tasks_by_id()["gadget-fetch"]
    sent = PublicDocsCondition(pack).build_messages(task)[0]["content"]
    assert SPEC_URL not in sent, "the spec document's URL reached the docs prompt"
    assert "UNIQUE-SPEC-BODY-9c4e" not in sent, "the spec document's CONTENT reached the docs prompt"
    assert PAGE_URL in sent, "and the real page must still be injected, or this proves nothing"


def test_the_unbudgeted_baseline_is_also_kept_apart(tmp_path):
    """`full_text` feeds the truncation audit. A spec leaking in here would report a path as
    'documented' on the strength of a document the docs condition never showed anyone."""
    pack = _pack_with_a_spec(tmp_path)
    assert "UNIQUE-SPEC-BODY-9c4e" not in PublicDocsCondition(pack).full_text("gadget-fetch")
    assert "UNIQUE-SPEC-BODY-9c4e" in RawSpecCondition(pack).full_text("gadget-fetch")


def test_the_two_conditions_read_different_manifest_keys(tmp_path):
    assert PublicDocsCondition.manifest_key == "pages"
    assert RawSpecCondition.manifest_key == "spec_documents"
    assert PublicDocsCondition.manifest_key != RawSpecCondition.manifest_key


def test_a_spec_document_is_still_a_manifest_url_for_anchoring(tmp_path):
    """It is fetched, hashed and robots-judged like every other URL — and `include_anchors=False`
    still means exactly `pages`, which is what public-docs depends on."""
    manifest = _pack_with_a_spec(tmp_path).docs_manifest()
    assert SPEC_URL in manifest_urls(manifest)
    assert SPEC_URL not in manifest_urls(manifest, include_anchors=False)


# --- the budget is shared, deliberately ------------------------------------- #

def test_raw_spec_spends_the_same_budget_as_public_docs(tmp_path):
    """No separate budget field exists, and that is the ruling. Give this column more room than the
    one beside it and the comparison measures our generosity."""
    pack = _pack_with_a_spec(tmp_path)
    assert RawSpecCondition(pack)._budget == PublicDocsCondition(pack)._budget
    assert not hasattr(pack.raw_spec, "budget_tokens"), (
        "a per-condition budget would let one column be bought rather than measured")


def test_the_shared_budget_actually_truncates_a_large_document(tmp_path):
    """Non-vacuity for the rule above: the budget must be capable of cropping this column, or
    'the budget is shared' would be a claim about a code path nothing exercises."""
    pack = _pack_with_a_spec(tmp_path)
    manifest = pack.docs_manifest()
    manifest["budget_tokens"] = 40  # 160 chars: the header fits, the document does not
    cond = RawSpecCondition(pack, manifest)
    injected = cond.build_context("gadget-fetch")
    assert "truncated to fit context budget" in injected
    assert len(injected) < len(cond.full_text("gadget-fetch"))


# --- the truncation audit covers it ----------------------------------------- #

def test_the_audit_runs_against_whichever_condition_it_is_given(tmp_path):
    pack = _pack_with_a_spec(tmp_path)
    docs = audit_docs_truncation(pack)
    spec = audit_spec_truncation(pack)
    assert {r["condition"] for r in docs} == {"public-docs"}
    assert {r["condition"] for r in spec} == {"raw-spec"}


def test_the_spec_audit_is_empty_for_a_pack_that_declares_no_condition(tmp_path):
    assert audit_spec_truncation(_pack_with_a_spec(tmp_path, declare_raw_spec=False)) == []


def test_the_audit_reports_what_did_not_fit(tmp_path):
    """The operator's requirement: declare what was injected and what did not. `injected_len`
    against `full_len` is that declaration, computed rather than described."""
    pack = _pack_with_a_spec(tmp_path)
    manifest = pack.docs_manifest()
    manifest["budget_tokens"] = 40
    records = [r for r in audit_docs_truncation(pack, RawSpecCondition(pack, manifest))
               if r["task_id"] == "gadget-fetch" and "full_len" in r]
    assert records, "the audit produced no records for the task with a spec, so it asserts nothing"
    assert all(r["injected_len"] < r["full_len"] for r in records)


# --- the disclosure ---------------------------------------------------------- #

def test_no_overlap_needs_no_disclosure(tmp_path):
    pack = _pack_with_a_spec(tmp_path)  # spec document, no anchor
    records = spec_disclosure(pack)
    assert records and not any(r["scored_against_own_source"] for r in records)
    ok, detail = check_spec_disclosure(pack)
    assert ok and "injects no document its answer key cites" in detail


def test_an_undeclared_overlap_is_refused(tmp_path):
    """The sharp case issue #54 named. The condition is scored against its own source and the pack
    says nothing, so the column would be published as a measurement."""
    pack = _pack_with_a_spec(tmp_path, also_anchor=True)
    records = spec_disclosure(pack)
    assert [r["overlapping_anchors"] for r in records if r["task_id"] == "gadget-fetch"] \
        == [[SPEC_URL]]
    ok, detail = check_spec_disclosure(pack)
    assert not ok
    assert "scored against its own source" in detail and "gadget-fetch" in detail


def test_a_declared_overlap_passes(tmp_path):
    pack = _pack_with_a_spec(tmp_path, also_anchor=True,
                             reason="the vendor publishes no other citable first-party artifact")
    ok, detail = check_spec_disclosure(pack)
    assert ok, detail
    assert "1/" in detail


def test_an_empty_reason_is_not_a_reason(tmp_path):
    """A written reason, never a boolean: whitespace is what a flag looks like once it is a string."""
    pack = _pack_with_a_spec(tmp_path, also_anchor=True, reason="   ")
    ok, _ = check_spec_disclosure(pack)
    assert not ok


def test_a_disclosure_that_is_not_true_is_refused(tmp_path):
    """A stale declaration is worse than none — it teaches a reader to discount the real ones."""
    pack = _pack_with_a_spec(tmp_path, also_anchor=False, reason="left over from an earlier layout")
    ok, detail = check_spec_disclosure(pack)
    assert not ok
    assert "do not overlap" in detail


# --- the gate ---------------------------------------------------------------- #

def test_the_gate_passes_a_pack_with_no_raw_spec(tmp_path):
    ok, detail = check_disclosure(_pack_with_a_spec(tmp_path, declare_raw_spec=False))
    assert ok and "nothing to disclose" in detail


def test_the_gate_refuses_an_undeclared_overlap(tmp_path):
    ok, _ = check_disclosure(_pack_with_a_spec(tmp_path, also_anchor=True))
    assert not ok


def test_the_gate_refuses_a_condition_that_would_inject_nothing(tmp_path):
    """A declared column with no documents behind it is a second copy of no-context under a
    different heading, and it would be published as a third condition."""
    pack = _pack_with_a_spec(tmp_path)
    manifest_path = pack.root / "docs-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    for entry in manifest["tasks"].values():
        entry.pop(SPEC_KEY, None)
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    ok, detail = check_disclosure(Pack.load(pack.root))
    assert not ok
    assert "would inject nothing" in detail


def test_the_gate_passes_the_shape_this_was_built_for(tmp_path):
    ok, detail = check_disclosure(_pack_with_a_spec(
        tmp_path, also_anchor=True,
        reason="the specification is the only citable first-party artifact this vendor publishes"))
    assert ok, detail
    assert "truncated away" in detail, "the gate must report the loss even when it passes"
