"""
Tests for src/models.py.

Covers: Task, Edge, Processor, LinkId, Interval, TaskInstance,
CommunicationInstance, NoCConfig, and DAGGraph conventions.
Implemented in Phase 1.
"""

import src.models  # noqa: F401


def test_models_importable():
    """Confirms src.models is importable (Phase 0 stub check)."""
    assert src.models is not None
