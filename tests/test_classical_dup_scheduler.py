"""
Tests for src/classical_dup_scheduler.py.

Covers: duplication improves makespan on high-communication DAG,
duplication rejected when Delta_EFT <= 0, exactly one primary instance
per original task, and duplication ratio on deterministic schedule.
Implemented in Phase 7.
"""

import src.classical_dup_scheduler  # noqa: F401


def test_classical_dup_scheduler_importable():
    """Confirms src.classical_dup_scheduler is importable (Phase 0 stub check)."""
    assert src.classical_dup_scheduler is not None
