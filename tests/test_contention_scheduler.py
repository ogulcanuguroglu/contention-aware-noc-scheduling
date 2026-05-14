"""
Tests for src/contention_scheduler.py.

Covers: contention delay on shared links, local communication cost zero,
precedence via communication arrival times, deterministic small DAG validity.
Implemented in Phase 6.
"""

import src.contention_scheduler  # noqa: F401


def test_contention_scheduler_importable():
    """Confirms src.contention_scheduler is importable (Phase 0 stub check)."""
    assert src.contention_scheduler is not None
