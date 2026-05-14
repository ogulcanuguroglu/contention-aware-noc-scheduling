"""
Tests for src/noc.py.

Covers: XY routing correctness, link reservation, contention detection,
link utilization calculation.
Implemented in Phase 3.
"""

import src.noc  # noqa: F401


def test_noc_importable():
    """Confirms src.noc is importable (Phase 0 stub check)."""
    assert src.noc is not None
