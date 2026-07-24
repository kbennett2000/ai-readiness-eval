"""Tests for the job taxonomy (core/taxonomy.py, ADR-0003)."""
from core import taxonomy
from core.pack import Pack
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_categories_are_unique_and_nonempty():
    assert len(taxonomy.CATEGORIES) == len(set(taxonomy.CATEGORIES))
    assert all(c and c == c.strip().lower() for c in taxonomy.CATEGORIES)


def test_is_category():
    assert taxonomy.is_category("authenticate")
    assert not taxonomy.is_category("nonsense")


def test_sailpoint_tasks_all_map_to_a_valid_category():
    pack = Pack.load(REPO_ROOT / "packs" / "sailpoint")
    tasks = pack.load_tasks()
    assert len(tasks) == 11
    for t in tasks:
        assert taxonomy.is_category(t["job_category"]), t["id"]
    # the 11 SailPoint tasks retro-map 1:1 onto 11 distinct categories
    mapped = {t["job_category"] for t in tasks}
    assert mapped == set(taxonomy.CATEGORIES)
