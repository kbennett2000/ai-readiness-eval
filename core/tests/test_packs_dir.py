"""Packs load from anywhere — including a directory outside this repo's tree (a private packs repo).

Confirms the contract cycle 2 depends on: an external pack path loads, and a bare `--pack <name>`
resolves against `--packs-dir` / AIRE_PACKS_DIR.
"""
import argparse

from core import __main__ as m
from core.pack import Pack

MINIMAL_PACK_YAML = """\
vendor: { id: extern, display_name: External Co }
tasks_dir: tasks
mode: diagnosis
"""


def _write_pack(dir_path, name):
    root = dir_path / name
    (root / "tasks").mkdir(parents=True)
    (root / "pack.yaml").write_text(MINIMAL_PACK_YAML)
    return root


def test_pack_loads_from_external_absolute_path(tmp_path):
    root = _write_pack(tmp_path, "extern-pack")
    pack = Pack.load(root)
    assert pack.vendor_id == "extern"
    assert pack.mode == "diagnosis"
    assert pack.context_layer is None  # two-condition pack


def test_bare_pack_name_resolves_against_packs_dir(tmp_path):
    _write_pack(tmp_path, "mypack")
    args = argparse.Namespace(pack="mypack", packs_dir=str(tmp_path))
    pack = m._load_pack(args)
    assert pack.vendor_id == "extern"


def test_bare_pack_name_resolves_against_env(tmp_path, monkeypatch):
    _write_pack(tmp_path, "mypack")
    monkeypatch.setenv("AIRE_PACKS_DIR", str(tmp_path))
    args = argparse.Namespace(pack="mypack", packs_dir=None)
    pack = m._load_pack(args)
    assert pack.vendor_id == "extern"


def test_explicit_path_wins_over_packs_dir(tmp_path):
    root = _write_pack(tmp_path / "a", "realpack")
    _write_pack(tmp_path / "b", "realpack")  # a decoy with the same name under packs_dir
    args = argparse.Namespace(pack=str(root), packs_dir=str(tmp_path / "b"))
    pack = m._load_pack(args)
    assert pack.root == root.resolve()
