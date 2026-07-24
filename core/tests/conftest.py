"""Shared fixtures for the core test suite: the synthetic `pack-acme` vendor pack.

The core engine is vendor-agnostic, so its tests run against a synthetic pack that carries no real
vendor identity — keeping the `test_core_no_vendor` guard clean while still exercising every
pack-parameterized path.
"""
from pathlib import Path

import pytest

from core.pack import Pack

ACME_PACK_DIR = Path(__file__).resolve().parent / "fixtures" / "pack-acme"


@pytest.fixture
def acme_pack() -> Pack:
    return Pack.load(ACME_PACK_DIR)
