"""Tests for the pack validator (core/validate.py).

Green on the acme fixture (and, via the repo layout, the sailpoint pack). Catches the mistakes an
answer key grows: a bad job_category, a missing anchor, an id that doesn't match its filename.
"""
import shutil
from pathlib import Path

import pytest
import yaml

from core.pack import Pack
from core.validate import validate_file, validate_pack, build_schema

REPO_ROOT = Path(__file__).resolve().parents[2]


def _errors(results: dict) -> list[str]:
    return [e for errs in results.values() for e in errs]


def test_acme_pack_is_valid(acme_pack):
    results = validate_pack(acme_pack)
    assert _errors(results) == [], results


def test_sailpoint_pack_is_valid():
    pack = Pack.load(REPO_ROOT / "packs" / "sailpoint")
    results = validate_pack(pack)
    assert _errors(results) == [], results


@pytest.fixture
def mutable_pack(acme_pack, tmp_path):
    """A writable copy of the acme pack so a test can corrupt one task."""
    dst = tmp_path / "pack"
    shutil.copytree(acme_pack.root, dst)
    return Pack.load(dst)


def _task_path(pack, name):
    return pack.tasks_dir / name


def test_catches_bad_job_category(mutable_pack):
    p = _task_path(mutable_pack, "widget-list.yaml")
    data = yaml.safe_load(p.read_text())
    data["job_category"] = "not-a-real-category"
    p.write_text(yaml.safe_dump(data))
    results = validate_pack(mutable_pack)
    assert any("job_category" in e for e in results["widget-list.yaml"])


def test_catches_missing_anchor(mutable_pack):
    p = _task_path(mutable_pack, "widget-list.yaml")
    data = yaml.safe_load(p.read_text())
    # strip the spec_ref and add no doc_ref -> endpoint is unanchored
    data["ground_truth"]["endpoints"][0].pop("spec_ref", None)
    p.write_text(yaml.safe_dump(data))
    results = validate_pack(mutable_pack)
    assert results["widget-list.yaml"], "unanchored endpoint should fail"


def test_catches_id_mismatch(mutable_pack):
    p = _task_path(mutable_pack, "widget-list.yaml")
    data = yaml.safe_load(p.read_text())
    data["id"] = "something-else"
    p.write_text(yaml.safe_dump(data))
    results = validate_pack(mutable_pack)
    assert any("does not match filename stem" in e for e in results["widget-list.yaml"])


def test_catches_na_category_use(mutable_pack, monkeypatch):
    # A task mapped to a category the pack marked N/A is an error.
    monkeypatch.setattr(mutable_pack, "na_categories", {"search-filter": "no product analog"})
    results = validate_pack(mutable_pack)
    assert any("marked N/A" in e for e in results["widget-list.yaml"])


def test_spec_ref_prefix_is_enforced(mutable_pack):
    p = _task_path(mutable_pack, "widget-list.yaml")
    data = yaml.safe_load(p.read_text())
    data["ground_truth"]["endpoints"][0]["spec_ref"]["file"] = "elsewhere/foo.yaml"  # violates widgets/
    p.write_text(yaml.safe_dump(data))
    results = validate_pack(mutable_pack)
    assert results["widget-list.yaml"], "spec_ref.file outside the prefix should fail"


def test_doc_only_anchor_is_accepted():
    # An endpoint anchored by coverage: doc-only + doc_ref (no spec_ref) is valid.
    schema = build_schema(spec_ref_file_prefix="idn/")
    task = {
        "id": "t", "category": "foundational", "job_category": "authenticate",
        "prompt": "p",
        "ground_truth": {
            "endpoints": [{
                "method": "POST", "path": "/oauth/token", "api_version": "oauth",
                "operation_id": "createToken", "coverage": "doc-only",
                "doc_ref": {"url": "https://example.com/auth"},
            }],
            "auth_flow": "OAuth2", "required_scopes": [],
            "key_parameters": [{"name": "grant_type", "in": "body", "required": True}],
            "success_shape": "200 OK", "common_failure_modes": ["x"],
        },
    }
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.yaml"
        p.write_text(yaml.safe_dump(task))
        assert validate_file(p, schema) == []
