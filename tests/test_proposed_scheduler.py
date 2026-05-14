"""
Tests for src/proposed_scheduler.py.

Covers: contention-aware duplication improves makespan vs CA-LS,
duplication rejected when not beneficial, tentative scheduling does not
mutate committed state on rejection, and local communication skips link reservation.
Implemented in Phase 8.
"""

import src.proposed_scheduler  # noqa: F401


def test_proposed_scheduler_importable():
    """Confirms src.proposed_scheduler is importable (Phase 0 stub check)."""
    assert src.proposed_scheduler is not None
