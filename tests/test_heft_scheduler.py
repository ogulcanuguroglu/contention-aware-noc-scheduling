"""
Tests for src/heft_scheduler.py.

Covers: single-task DAG, chain DAG, fork-join DAG, precedence constraints,
upward rank computation, and EFT-based processor selection.
Implemented in Phase 5.
"""

import src.heft_scheduler  # noqa: F401


def test_heft_scheduler_importable():
    """Confirms src.heft_scheduler is importable (Phase 0 stub check)."""
    assert src.heft_scheduler is not None
