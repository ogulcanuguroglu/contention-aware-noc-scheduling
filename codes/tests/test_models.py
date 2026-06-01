"""
Tests for src/models.py.

Covers: Task, Edge, Processor, Link, Interval, TaskInstance,
CommunicationInstance, NoCConfig, and DAGGraph.
Implemented in Phase 1.
"""

import pytest
import networkx as nx

from src.models import (
    CommunicationInstance,
    DAGGraph,
    Edge,
    Interval,
    Link,
    NoCConfig,
    Processor,
    Task,
    TaskInstance,
)


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class TestTask:
    def test_valid_construction(self):
        t = Task(task_id=0, computation_cost=50.0)
        assert t.task_id == 0
        assert t.computation_cost == 50.0

    def test_rejects_negative_task_id(self):
        with pytest.raises(ValueError):
            Task(task_id=-1, computation_cost=10.0)

    def test_rejects_zero_computation_cost(self):
        with pytest.raises(ValueError):
            Task(task_id=0, computation_cost=0.0)

    def test_rejects_negative_computation_cost(self):
        with pytest.raises(ValueError):
            Task(task_id=0, computation_cost=-5.0)


# ---------------------------------------------------------------------------
# Edge
# ---------------------------------------------------------------------------

class TestEdge:
    def test_valid_construction(self):
        e = Edge(source=0, target=1, communication_volume=10.0)
        assert e.source == 0
        assert e.target == 1
        assert e.communication_volume == 10.0

    def test_rejects_self_edge(self):
        with pytest.raises(ValueError):
            Edge(source=1, target=1, communication_volume=5.0)

    def test_rejects_negative_communication_volume(self):
        with pytest.raises(ValueError):
            Edge(source=0, target=1, communication_volume=-1.0)

    def test_allows_zero_communication_volume(self):
        e = Edge(source=0, target=1, communication_volume=0.0)
        assert e.communication_volume == 0.0


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------

class TestProcessor:
    def test_valid_construction(self):
        p = Processor(processor_id=0, x=1, y=2)
        assert p.processor_id == 0
        assert p.x == 1
        assert p.y == 2

    def test_rejects_negative_processor_id(self):
        with pytest.raises(ValueError):
            Processor(processor_id=-1, x=0, y=0)

    def test_rejects_negative_x(self):
        with pytest.raises(ValueError):
            Processor(processor_id=0, x=-1, y=0)

    def test_rejects_negative_y(self):
        with pytest.raises(ValueError):
            Processor(processor_id=0, x=0, y=-1)

    def test_zero_coordinates_allowed(self):
        p = Processor(processor_id=0, x=0, y=0)
        assert p.x == 0 and p.y == 0


# ---------------------------------------------------------------------------
# Link
# ---------------------------------------------------------------------------

class TestLink:
    def test_valid_construction(self):
        link = Link(source_processor=0, destination_processor=1)
        assert link.source_processor == 0
        assert link.destination_processor == 1

    def test_hashable_as_dict_key(self):
        link = Link(source_processor=0, destination_processor=1)
        d = {link: "value"}
        assert d[link] == "value"

    def test_equal_links_hash_equal(self):
        a = Link(source_processor=0, destination_processor=1)
        b = Link(source_processor=0, destination_processor=1)
        assert a == b
        assert hash(a) == hash(b)

    def test_distinct_links_in_set(self):
        a = Link(source_processor=0, destination_processor=1)
        b = Link(source_processor=0, destination_processor=1)
        c = Link(source_processor=1, destination_processor=2)
        assert len({a, b, c}) == 2

    def test_rejects_same_source_and_destination(self):
        with pytest.raises(ValueError):
            Link(source_processor=3, destination_processor=3)

    def test_rejects_negative_source(self):
        with pytest.raises(ValueError):
            Link(source_processor=-1, destination_processor=1)

    def test_rejects_negative_destination(self):
        with pytest.raises(ValueError):
            Link(source_processor=0, destination_processor=-1)


# ---------------------------------------------------------------------------
# Interval
# ---------------------------------------------------------------------------

class TestInterval:
    def test_valid_construction(self):
        iv = Interval(start_time=0.0, finish_time=10.0)
        assert iv.start_time == 0.0
        assert iv.finish_time == 10.0

    def test_duration_property(self):
        iv = Interval(start_time=2.0, finish_time=7.0)
        assert iv.duration == pytest.approx(5.0)

    def test_zero_duration_allowed(self):
        iv = Interval(start_time=5.0, finish_time=5.0)
        assert iv.duration == pytest.approx(0.0)

    def test_rejects_finish_before_start(self):
        with pytest.raises(ValueError):
            Interval(start_time=5.0, finish_time=3.0)

    def test_rejects_negative_start_time(self):
        with pytest.raises(ValueError):
            Interval(start_time=-1.0, finish_time=5.0)

    def test_optional_fields_default_none(self):
        iv = Interval(start_time=0.0, finish_time=1.0)
        assert iv.resource_id is None
        assert iv.metadata is None

    def test_optional_fields_set(self):
        iv = Interval(start_time=0.0, finish_time=1.0, resource_id=42, metadata={"task": 0})
        assert iv.resource_id == 42
        assert iv.metadata["task"] == 0


# ---------------------------------------------------------------------------
# TaskInstance
# ---------------------------------------------------------------------------

class TestTaskInstance:
    def test_valid_construction(self):
        ti = TaskInstance(task_id=0, processor_id=1, start_time=0.0, finish_time=20.0)
        assert ti.task_id == 0
        assert ti.processor_id == 1

    def test_duration_property(self):
        ti = TaskInstance(task_id=0, processor_id=0, start_time=5.0, finish_time=15.0)
        assert ti.duration == pytest.approx(10.0)

    def test_is_primary_defaults_true(self):
        ti = TaskInstance(task_id=1, processor_id=0, start_time=0.0, finish_time=10.0)
        assert ti.is_primary is True

    def test_non_primary_instance(self):
        ti = TaskInstance(task_id=1, processor_id=2, start_time=0.0, finish_time=10.0, is_primary=False)
        assert ti.is_primary is False

    def test_rejects_negative_task_id(self):
        with pytest.raises(ValueError):
            TaskInstance(task_id=-1, processor_id=0, start_time=0.0, finish_time=10.0)

    def test_rejects_negative_processor_id(self):
        with pytest.raises(ValueError):
            TaskInstance(task_id=0, processor_id=-1, start_time=0.0, finish_time=10.0)

    def test_rejects_finish_before_start(self):
        with pytest.raises(ValueError):
            TaskInstance(task_id=0, processor_id=0, start_time=10.0, finish_time=5.0)

    def test_rejects_negative_start_time(self):
        with pytest.raises(ValueError):
            TaskInstance(task_id=0, processor_id=0, start_time=-1.0, finish_time=5.0)


# ---------------------------------------------------------------------------
# CommunicationInstance
# ---------------------------------------------------------------------------

class TestCommunicationInstance:
    def _make_remote(self) -> CommunicationInstance:
        route = [Link(0, 1), Link(1, 5)]
        return CommunicationInstance(
            source_task=0,
            target_task=1,
            source_processor=0,
            destination_processor=5,
            route=route,
            start_time=0.0,
            finish_time=8.0,
            communication_volume=10.0,
        )

    def _make_local(self) -> CommunicationInstance:
        return CommunicationInstance(
            source_task=0,
            target_task=1,
            source_processor=3,
            destination_processor=3,
            route=[],
            start_time=5.0,
            finish_time=5.0,
            communication_volume=10.0,
        )

    def test_valid_remote_communication(self):
        ci = self._make_remote()
        assert len(ci.route) == 2
        assert ci.communication_volume == pytest.approx(10.0)

    def test_valid_local_communication_with_empty_route(self):
        ci = self._make_local()
        assert ci.route == []
        assert ci.source_processor == ci.destination_processor

    def test_rejects_remote_communication_with_empty_route(self):
        with pytest.raises(ValueError):
            CommunicationInstance(
                source_task=0,
                target_task=1,
                source_processor=0,
                destination_processor=5,
                route=[],
                start_time=0.0,
                finish_time=8.0,
                communication_volume=10.0,
            )

    def test_duration_property(self):
        ci = self._make_remote()
        assert ci.duration == pytest.approx(8.0)

    def test_local_duration_zero(self):
        ci = self._make_local()
        assert ci.duration == pytest.approx(0.0)

    def test_rejects_negative_communication_volume(self):
        with pytest.raises(ValueError):
            CommunicationInstance(
                source_task=0,
                target_task=1,
                source_processor=0,
                destination_processor=5,
                route=[Link(0, 1)],
                start_time=0.0,
                finish_time=5.0,
                communication_volume=-1.0,
            )

    def test_rejects_source_task_equal_target_task(self):
        with pytest.raises(ValueError):
            CommunicationInstance(
                source_task=2,
                target_task=2,
                source_processor=0,
                destination_processor=5,
                route=[Link(0, 1)],
                start_time=0.0,
                finish_time=5.0,
                communication_volume=10.0,
            )


# ---------------------------------------------------------------------------
# NoCConfig
# ---------------------------------------------------------------------------

class TestNoCConfig:
    def test_valid_construction_defaults(self):
        cfg = NoCConfig(rows=4, cols=4)
        assert cfg.rows == 4
        assert cfg.cols == 4
        assert cfg.alpha == pytest.approx(1.0)
        assert cfg.beta == pytest.approx(1.0)
        assert cfg.routing == "xy"

    def test_processor_count_4x4(self):
        assert NoCConfig(rows=4, cols=4).processor_count == 16

    def test_processor_count_8x8(self):
        assert NoCConfig(rows=8, cols=8).processor_count == 64

    def test_rejects_zero_rows(self):
        with pytest.raises(ValueError):
            NoCConfig(rows=0, cols=4)

    def test_rejects_zero_cols(self):
        with pytest.raises(ValueError):
            NoCConfig(rows=4, cols=0)

    def test_rejects_negative_alpha(self):
        with pytest.raises(ValueError):
            NoCConfig(rows=4, cols=4, alpha=-1.0)

    def test_rejects_negative_beta(self):
        with pytest.raises(ValueError):
            NoCConfig(rows=4, cols=4, beta=-0.5)

    def test_rejects_invalid_routing(self):
        with pytest.raises(ValueError):
            NoCConfig(rows=4, cols=4, routing="random")

    def test_zero_alpha_beta_allowed(self):
        cfg = NoCConfig(rows=4, cols=4, alpha=0.0, beta=0.0)
        assert cfg.alpha == 0.0
        assert cfg.beta == 0.0


# ---------------------------------------------------------------------------
# DAGGraph
# ---------------------------------------------------------------------------

def _make_valid_dag() -> nx.DiGraph:
    """Simple 3-node fork DAG: 0 -> 1, 0 -> 2."""
    g = nx.DiGraph()
    g.add_node(0, computation_cost=10.0)
    g.add_node(1, computation_cost=20.0)
    g.add_node(2, computation_cost=15.0)
    g.add_edge(0, 1, communication_volume=5.0)
    g.add_edge(0, 2, communication_volume=3.0)
    return g


class TestDAGGraph:
    def test_valid_wrapper(self):
        dag = DAGGraph(_make_valid_dag())
        assert dag.number_of_tasks() == 3
        assert dag.number_of_edges() == 2

    def test_task_ids(self):
        dag = DAGGraph(_make_valid_dag())
        assert set(dag.task_ids()) == {0, 1, 2}

    def test_edge_ids(self):
        dag = DAGGraph(_make_valid_dag())
        assert set(dag.edge_ids()) == {(0, 1), (0, 2)}

    def test_computation_cost(self):
        dag = DAGGraph(_make_valid_dag())
        assert dag.computation_cost(0) == pytest.approx(10.0)
        assert dag.computation_cost(1) == pytest.approx(20.0)

    def test_communication_volume(self):
        dag = DAGGraph(_make_valid_dag())
        assert dag.communication_volume(0, 1) == pytest.approx(5.0)
        assert dag.communication_volume(0, 2) == pytest.approx(3.0)

    def test_predecessors_of_root(self):
        dag = DAGGraph(_make_valid_dag())
        assert dag.predecessors(0) == []

    def test_predecessors_of_child(self):
        dag = DAGGraph(_make_valid_dag())
        assert dag.predecessors(1) == [0]

    def test_successors_of_root(self):
        dag = DAGGraph(_make_valid_dag())
        assert set(dag.successors(0)) == {1, 2}

    def test_successors_of_leaf(self):
        dag = DAGGraph(_make_valid_dag())
        assert dag.successors(1) == []

    def test_rejects_cyclic_graph(self):
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=10.0)
        g.add_edge(0, 1, communication_volume=5.0)
        g.add_edge(1, 0, communication_volume=5.0)
        with pytest.raises(ValueError, match="acyclic"):
            DAGGraph(g)

    def test_rejects_undirected_graph(self):
        g = nx.Graph()
        g.add_node(0, computation_cost=10.0)
        with pytest.raises(ValueError, match="directed"):
            DAGGraph(g)

    def test_rejects_missing_computation_cost(self):
        g = nx.DiGraph()
        g.add_node(0)  # no computation_cost
        with pytest.raises(ValueError, match="computation_cost"):
            DAGGraph(g)

    def test_rejects_missing_communication_volume(self):
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=10.0)
        g.add_edge(0, 1)  # no communication_volume
        with pytest.raises(ValueError, match="communication_volume"):
            DAGGraph(g)

    def test_single_node_dag(self):
        g = nx.DiGraph()
        g.add_node(0, computation_cost=42.0)
        dag = DAGGraph(g)
        assert dag.number_of_tasks() == 1
        assert dag.number_of_edges() == 0
        assert dag.predecessors(0) == []
        assert dag.successors(0) == []

    def test_rejects_zero_computation_cost(self):
        g = nx.DiGraph()
        g.add_node(0, computation_cost=0.0)
        with pytest.raises(ValueError, match="computation_cost"):
            DAGGraph(g)

    def test_rejects_negative_computation_cost(self):
        g = nx.DiGraph()
        g.add_node(0, computation_cost=-5.0)
        with pytest.raises(ValueError, match="computation_cost"):
            DAGGraph(g)

    def test_rejects_negative_communication_volume(self):
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=10.0)
        g.add_edge(0, 1, communication_volume=-1.0)
        with pytest.raises(ValueError, match="communication_volume"):
            DAGGraph(g)

    def test_rejects_non_integer_node_id(self):
        g = nx.DiGraph()
        g.add_node("task_0", computation_cost=10.0)
        with pytest.raises(ValueError, match="int"):
            DAGGraph(g)

    def test_rejects_negative_node_id(self):
        g = nx.DiGraph()
        g.add_node(-1, computation_cost=10.0)
        with pytest.raises(ValueError, match="non-negative"):
            DAGGraph(g)
