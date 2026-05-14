"""
Tests for src/schedule_state.py.

Covers: task reservation, communication reservation, contention ordering,
Data Ready Time (DRT) calculation, and clone correctness.
Implemented in Phase 4.
"""

import src.schedule_state  # noqa: F401


def test_schedule_state_importable():
    """Confirms src.schedule_state is importable (Phase 0 stub check)."""
    assert src.schedule_state is not None
