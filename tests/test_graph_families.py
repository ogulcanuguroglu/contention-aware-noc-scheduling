"""
Tests for src/graph_families.py.

Covers: validation helpers, cost assignment, CCR scaling, all graph family
generators, the dispatcher, and a scheduler compatibility smoke test.
Implemented in Phase 14.
"""

import networkx as nx
import pytest

from src.classical_dup_scheduler import ClassicalDuplicationScheduler
from src.contention_scheduler import ContentionAwareScheduler
from src.graph_families import (
    assign_random_costs,
    compute_total_communication,
    compute_total_computation,
    generate_chain_dag,
    generate_diamond_dag,
    generate_fork_dag,
    generate_fork_join_dag,
    generate_graph_family,
    generate_in_tree_dag,
    generate_join_dag,
    generate_out_tree_dag,
    scale_graph_to_ccr,
)
from src.heft_scheduler import HEFTScheduler
from src.metrics import schedule_summary
from src.models import DAGGraph
from src.noc import MeshNoC
from src.proposed_scheduler import ProposedScheduler


# ---------------------------------------------------------------------------
# 1. TestValidationHelpers
# ---------------------------------------------------------------------------

class TestValidationHelpers:
    def test_invalid_n_tasks_zero_rejected(self):
        with pytest.raises(ValueError):
            generate_chain_dag(n_tasks=0)

    def test_invalid_n_branches_zero_rejected(self):
        with pytest.raises(ValueError):
            generate_fork_dag(n_branches=0)
        with pytest.raises(ValueError):
            generate_join_dag(n_branches=0)
        with pytest.raises(ValueError):
            generate_fork_join_dag(n_branches=0, branch_length=1)

    def test_invalid_branch_length_zero_rejected(self):
        with pytest.raises(ValueError):
            generate_fork_join_dag(n_branches=2, branch_length=0)

    def test_invalid_depth_zero_rejected(self):
        with pytest.raises(ValueError):
            generate_in_tree_dag(depth=0, branching_factor=2)
        with pytest.raises(ValueError):
            generate_out_tree_dag(depth=0, branching_factor=2)
        with pytest.raises(ValueError):
            generate_diamond_dag(width=2, depth=0)

    def test_invalid_branching_factor_zero_rejected(self):
        with pytest.raises(ValueError):
            generate_in_tree_dag(depth=2, branching_factor=0)
        with pytest.raises(ValueError):
            generate_out_tree_dag(depth=2, branching_factor=0)

    def test_invalid_width_zero_rejected(self):
        with pytest.raises(ValueError):
            generate_diamond_dag(width=0, depth=2)

    def test_bools_rejected_as_ints(self):
        with pytest.raises(ValueError):
            generate_chain_dag(n_tasks=True)
        with pytest.raises(ValueError):
            generate_chain_dag(n_tasks=False)
        with pytest.raises(ValueError):
            generate_fork_dag(n_branches=True)
        with pytest.raises(ValueError):
            generate_fork_join_dag(n_branches=True, branch_length=2)
        with pytest.raises(ValueError):
            generate_fork_join_dag(n_branches=2, branch_length=True)
        with pytest.raises(ValueError):
            generate_in_tree_dag(depth=True, branching_factor=2)
        with pytest.raises(ValueError):
            generate_diamond_dag(width=True, depth=2)

    def test_non_numeric_ccr_rejected(self):
        with pytest.raises(ValueError):
            generate_chain_dag(n_tasks=5, ccr="bad")
        with pytest.raises(ValueError):
            scale_graph_to_ccr(generate_chain_dag(n_tasks=5), ccr="bad")  # type: ignore[arg-type]

    def test_nan_infinity_ccr_rejected(self):
        with pytest.raises(ValueError):
            generate_chain_dag(n_tasks=5, ccr=float("nan"))
        with pytest.raises(ValueError):
            generate_chain_dag(n_tasks=5, ccr=float("inf"))
        with pytest.raises(ValueError):
            generate_chain_dag(n_tasks=5, ccr=-float("inf"))

    def test_negative_ccr_rejected(self):
        with pytest.raises(ValueError):
            generate_chain_dag(n_tasks=5, ccr=-0.5)
        with pytest.raises(ValueError):
            scale_graph_to_ccr(generate_chain_dag(n_tasks=5), ccr=-1.0)

    def test_invalid_comp_range_rejected(self):
        with pytest.raises(ValueError):
            generate_chain_dag(n_tasks=5, comp_range=(-1, 100))
        with pytest.raises(ValueError):
            generate_chain_dag(n_tasks=5, comp_range=(0, 100))
        with pytest.raises(ValueError):
            generate_chain_dag(n_tasks=5, comp_range=(100, 10))
        with pytest.raises(ValueError):
            assign_random_costs(nx.DiGraph(), comp_range=(float("nan"), 10))

    def test_invalid_comm_range_rejected(self):
        with pytest.raises(ValueError):
            generate_chain_dag(n_tasks=5, comm_range=(-1, 10))
        with pytest.raises(ValueError):
            generate_chain_dag(n_tasks=5, comm_range=(10, 5))
        with pytest.raises(ValueError):
            assign_random_costs(nx.DiGraph(), comm_range=(float("inf"), 100))


# ---------------------------------------------------------------------------
# 2. TestCostAssignment
# ---------------------------------------------------------------------------

class TestCostAssignment:
    def _small_chain_topology(self) -> nx.DiGraph:
        g = nx.DiGraph()
        for i in range(4):
            g.add_node(i)
        for i in range(3):
            g.add_edge(i, i + 1)
        return g

    def test_adds_computation_cost_to_every_node(self):
        g = assign_random_costs(self._small_chain_topology(), seed=0)
        for node in g.nodes:
            assert "computation_cost" in g.nodes[node]
            assert g.nodes[node]["computation_cost"] > 0

    def test_adds_communication_volume_to_every_edge(self):
        g = assign_random_costs(self._small_chain_topology(), seed=0)
        for u, v in g.edges:
            assert "communication_volume" in g.edges[u, v]
            assert g.edges[u, v]["communication_volume"] >= 0

    def test_values_within_requested_ranges(self):
        comp_range = (5, 50)
        comm_range = (2, 20)
        g = assign_random_costs(
            self._small_chain_topology(),
            comp_range=comp_range,
            comm_range=comm_range,
            seed=42,
        )
        for node in g.nodes:
            cost = g.nodes[node]["computation_cost"]
            assert 5.0 <= cost <= 50.0
        for u, v in g.edges:
            vol = g.edges[u, v]["communication_volume"]
            assert 2.0 <= vol <= 20.0

    def test_same_seed_gives_same_result(self):
        t = self._small_chain_topology()
        g1 = assign_random_costs(t, seed=7)
        g2 = assign_random_costs(t, seed=7)
        for node in g1.nodes:
            assert g1.nodes[node]["computation_cost"] == g2.nodes[node]["computation_cost"]
        for u, v in g1.edges:
            assert g1.edges[u, v]["communication_volume"] == g2.edges[u, v]["communication_volume"]

    def test_different_seeds_usually_differ(self):
        t = self._small_chain_topology()
        g1 = assign_random_costs(t, seed=0)
        g2 = assign_random_costs(t, seed=999)
        costs1 = [g1.nodes[n]["computation_cost"] for n in sorted(g1.nodes)]
        costs2 = [g2.nodes[n]["computation_cost"] for n in sorted(g2.nodes)]
        assert costs1 != costs2

    def test_original_topology_is_preserved(self):
        t = self._small_chain_topology()
        original_edges = set(t.edges())
        g = assign_random_costs(t, seed=0)
        assert set(g.edges()) == original_edges
        assert g.number_of_nodes() == t.number_of_nodes()

    def test_returned_graph_is_a_copy(self):
        t = self._small_chain_topology()
        g = assign_random_costs(t, seed=0)
        assert g is not t
        # Mutating the copy should not affect the original
        g.nodes[0]["computation_cost"] = 99999.0
        assert "computation_cost" not in t.nodes[0]


# ---------------------------------------------------------------------------
# 3. TestCCRScaling
# ---------------------------------------------------------------------------

class TestCCRScaling:
    def test_achieves_target_ccr_for_graph_with_edges(self):
        g = generate_chain_dag(n_tasks=10, seed=0)
        target = 2.5
        scaled = scale_graph_to_ccr(g, target)
        actual = compute_total_communication(scaled) / compute_total_computation(scaled)
        assert actual == pytest.approx(target, rel=1e-9)

    def test_ccr_zero_sets_all_volumes_to_zero(self):
        g = generate_chain_dag(n_tasks=5, seed=0)
        scaled = scale_graph_to_ccr(g, 0.0)
        for u, v in scaled.edges():
            assert scaled.edges[u, v]["communication_volume"] == 0.0

    def test_no_edge_graph_with_ccr_positive_remains_valid(self):
        g = generate_chain_dag(n_tasks=1, seed=0)
        assert g.number_of_edges() == 0
        scaled = scale_graph_to_ccr(g, 1.0)
        assert scaled.number_of_edges() == 0
        assert compute_total_communication(scaled) == 0.0
        DAGGraph(scaled)  # still a valid graph

    def test_zero_raw_comm_but_edges_exist_achieves_target_ccr(self):
        # Generate a chain with ccr=0 so all volumes are 0, then scale up.
        g = generate_chain_dag(n_tasks=5, ccr=0.0, seed=0)
        assert g.number_of_edges() > 0
        assert compute_total_communication(g) == 0.0
        target = 1.0
        scaled = scale_graph_to_ccr(g, target)
        actual = compute_total_communication(scaled) / compute_total_computation(scaled)
        assert actual == pytest.approx(target, rel=1e-9)

    def test_original_graph_not_mutated(self):
        g = generate_chain_dag(n_tasks=5, seed=0)
        original_vols = {(u, v): g.edges[u, v]["communication_volume"] for u, v in g.edges()}
        _ = scale_graph_to_ccr(g, 5.0)
        for (u, v), vol in original_vols.items():
            assert g.edges[u, v]["communication_volume"] == vol


# ---------------------------------------------------------------------------
# 4. TestChainDAG
# ---------------------------------------------------------------------------

class TestChainDAG:
    def test_single_task_has_one_node_no_edges(self):
        g = generate_chain_dag(n_tasks=1, seed=0)
        assert g.number_of_nodes() == 1
        assert g.number_of_edges() == 0

    def test_five_tasks_has_correct_edges(self):
        g = generate_chain_dag(n_tasks=5, seed=0)
        assert g.number_of_nodes() == 5
        assert g.number_of_edges() == 4
        for i in range(4):
            assert g.has_edge(i, i + 1)

    def test_graph_is_dag(self):
        g = generate_chain_dag(n_tasks=20, seed=0)
        assert nx.is_directed_acyclic_graph(g)

    def test_dagraph_accepts_output(self):
        g = generate_chain_dag(n_tasks=10, seed=0)
        dag = DAGGraph(g)
        assert dag.number_of_tasks() == 10

    def test_ccr_approximately_matches(self):
        target = 2.0
        g = generate_chain_dag(n_tasks=10, ccr=target, seed=0)
        actual = compute_total_communication(g) / compute_total_computation(g)
        assert actual == pytest.approx(target, rel=1e-9)


# ---------------------------------------------------------------------------
# 5. TestForkDAG
# ---------------------------------------------------------------------------

class TestForkDAG:
    def test_four_branches_has_five_nodes(self):
        g = generate_fork_dag(n_branches=4, seed=0)
        assert g.number_of_nodes() == 5

    def test_four_branches_correct_edges(self):
        g = generate_fork_dag(n_branches=4, seed=0)
        for i in range(1, 5):
            assert g.has_edge(0, i)
        assert g.number_of_edges() == 4

    def test_graph_is_dag_and_valid(self):
        g = generate_fork_dag(n_branches=6, seed=1)
        assert nx.is_directed_acyclic_graph(g)
        DAGGraph(g)

    def test_ccr_scaling_works(self):
        target = 1.5
        g = generate_fork_dag(n_branches=4, ccr=target, seed=0)
        actual = compute_total_communication(g) / compute_total_computation(g)
        assert actual == pytest.approx(target, rel=1e-9)


# ---------------------------------------------------------------------------
# 6. TestJoinDAG
# ---------------------------------------------------------------------------

class TestJoinDAG:
    def test_four_branches_has_five_nodes(self):
        g = generate_join_dag(n_branches=4, seed=0)
        assert g.number_of_nodes() == 5

    def test_four_branches_correct_edges(self):
        g = generate_join_dag(n_branches=4, seed=0)
        sink = 4
        for i in range(4):
            assert g.has_edge(i, sink)
        assert g.number_of_edges() == 4

    def test_graph_is_dag_and_valid(self):
        g = generate_join_dag(n_branches=5, seed=2)
        assert nx.is_directed_acyclic_graph(g)
        DAGGraph(g)

    def test_ccr_scaling_works(self):
        target = 3.0
        g = generate_join_dag(n_branches=4, ccr=target, seed=0)
        actual = compute_total_communication(g) / compute_total_computation(g)
        assert actual == pytest.approx(target, rel=1e-9)


# ---------------------------------------------------------------------------
# 7. TestForkJoinDAG
# ---------------------------------------------------------------------------

class TestForkJoinDAG:
    def test_expected_node_count(self):
        for n_branches, branch_length in [(2, 2), (3, 3), (4, 1), (1, 5)]:
            g = generate_fork_join_dag(n_branches, branch_length, seed=0)
            expected = 2 + n_branches * branch_length
            assert g.number_of_nodes() == expected

    def test_source_has_out_degree_n_branches(self):
        g = generate_fork_join_dag(n_branches=4, branch_length=3, seed=0)
        assert g.out_degree(0) == 4

    def test_sink_has_in_degree_n_branches(self):
        n_branches, branch_length = 3, 2
        g = generate_fork_join_dag(n_branches=n_branches, branch_length=branch_length, seed=0)
        sink_id = 1 + n_branches * branch_length
        assert g.in_degree(sink_id) == n_branches

    def test_each_branch_connected_source_to_sink(self):
        n_branches, branch_length = 3, 2
        g = generate_fork_join_dag(n_branches=n_branches, branch_length=branch_length, seed=0)
        sink_id = 1 + n_branches * branch_length
        for b in range(n_branches):
            first = 1 + b * branch_length
            assert g.has_edge(0, first)
            last = first + branch_length - 1
            assert g.has_edge(last, sink_id)

    def test_graph_is_dag_and_valid(self):
        g = generate_fork_join_dag(n_branches=4, branch_length=3, seed=0)
        assert nx.is_directed_acyclic_graph(g)
        DAGGraph(g)

    def test_deterministic_with_seed(self):
        g1 = generate_fork_join_dag(n_branches=3, branch_length=2, seed=42)
        g2 = generate_fork_join_dag(n_branches=3, branch_length=2, seed=42)
        for node in g1.nodes:
            assert g1.nodes[node]["computation_cost"] == g2.nodes[node]["computation_cost"]
        for u, v in g1.edges:
            assert g1.edges[u, v]["communication_volume"] == g2.edges[u, v]["communication_volume"]


# ---------------------------------------------------------------------------
# 8. TestInTreeDAG
# ---------------------------------------------------------------------------

class TestInTreeDAG:
    def test_root_sink_in_degree_equals_branching_factor_depth1(self):
        for bf in [1, 2, 3, 4]:
            g = generate_in_tree_dag(depth=1, branching_factor=bf, seed=0)
            # Root is node 0 (sink); its in-degree should equal bf
            assert g.in_degree(0) == bf

    def test_root_is_sink_no_outgoing_edges(self):
        g = generate_in_tree_dag(depth=2, branching_factor=3, seed=0)
        assert g.out_degree(0) == 0

    def test_graph_is_dag_and_valid(self):
        g = generate_in_tree_dag(depth=3, branching_factor=2, seed=0)
        assert nx.is_directed_acyclic_graph(g)
        DAGGraph(g)

    def test_expected_node_count_balanced_tree(self):
        for depth, bf in [(1, 2), (2, 2), (1, 3), (2, 3), (3, 2)]:
            g = generate_in_tree_dag(depth=depth, branching_factor=bf, seed=0)
            expected = sum(bf ** level for level in range(depth + 1))
            assert g.number_of_nodes() == expected

    def test_edges_point_toward_root(self):
        # For in-tree, all edges go child→parent. Since BFS assigns lower IDs
        # to shallower nodes, every edge (u→v) satisfies u > v.
        g = generate_in_tree_dag(depth=3, branching_factor=2, seed=0)
        for u, v in g.edges():
            assert u > v, f"Expected edge from higher-ID to lower-ID, got {u}→{v}"


# ---------------------------------------------------------------------------
# 9. TestOutTreeDAG
# ---------------------------------------------------------------------------

class TestOutTreeDAG:
    def test_root_source_out_degree_equals_branching_factor_depth1(self):
        for bf in [1, 2, 3, 4]:
            g = generate_out_tree_dag(depth=1, branching_factor=bf, seed=0)
            # Root is node 0 (source); its out-degree should equal bf
            assert g.out_degree(0) == bf

    def test_root_is_source_no_incoming_edges(self):
        g = generate_out_tree_dag(depth=2, branching_factor=3, seed=0)
        assert g.in_degree(0) == 0

    def test_graph_is_dag_and_valid(self):
        g = generate_out_tree_dag(depth=3, branching_factor=2, seed=0)
        assert nx.is_directed_acyclic_graph(g)
        DAGGraph(g)

    def test_expected_node_count_balanced_tree(self):
        for depth, bf in [(1, 2), (2, 2), (1, 3), (2, 3), (3, 2)]:
            g = generate_out_tree_dag(depth=depth, branching_factor=bf, seed=0)
            expected = sum(bf ** level for level in range(depth + 1))
            assert g.number_of_nodes() == expected

    def test_edges_point_away_from_root(self):
        # For out-tree, all edges go parent→child. Since BFS assigns lower IDs
        # to shallower nodes, every edge (u→v) satisfies u < v.
        g = generate_out_tree_dag(depth=3, branching_factor=2, seed=0)
        for u, v in g.edges():
            assert u < v, f"Expected edge from lower-ID to higher-ID, got {u}→{v}"


# ---------------------------------------------------------------------------
# 10. TestDiamondDAG
# ---------------------------------------------------------------------------

class TestDiamondDAG:
    def test_node_count_equals_formula(self):
        for width, depth in [(2, 2), (3, 1), (1, 4), (4, 3)]:
            g = generate_diamond_dag(width=width, depth=depth, seed=0)
            assert g.number_of_nodes() == 2 + width * depth

    def test_source_connects_to_all_first_layer_nodes(self):
        width, depth = 3, 2
        g = generate_diamond_dag(width=width, depth=depth, seed=0)
        # First layer: nodes 1..width
        for v in range(1, width + 1):
            assert g.has_edge(0, v), f"Source should connect to node {v}"
        assert g.out_degree(0) == width

    def test_all_last_layer_nodes_connect_to_sink(self):
        width, depth = 3, 2
        g = generate_diamond_dag(width=width, depth=depth, seed=0)
        sink_id = 1 + depth * width
        last_layer_start = 1 + (depth - 1) * width
        for u in range(last_layer_start, last_layer_start + width):
            assert g.has_edge(u, sink_id), f"Node {u} should connect to sink"

    def test_consecutive_layers_are_complete_bipartite(self):
        width, depth = 2, 3
        g = generate_diamond_dag(width=width, depth=depth, seed=0)
        for d in range(1, depth):
            layer_d = list(range(1 + (d - 1) * width, 1 + d * width))
            layer_d1 = list(range(1 + d * width, 1 + (d + 1) * width))
            for u in layer_d:
                for v in layer_d1:
                    assert g.has_edge(u, v), f"Missing bipartite edge {u}→{v}"

    def test_graph_is_dag_and_valid(self):
        g = generate_diamond_dag(width=4, depth=3, seed=0)
        assert nx.is_directed_acyclic_graph(g)
        DAGGraph(g)


# ---------------------------------------------------------------------------
# 11. TestDispatcher
# ---------------------------------------------------------------------------

_FAMILY_PARAMS = {
    "chain": {"n_tasks": 8},
    "fork": {"n_branches": 4},
    "join": {"n_branches": 4},
    "fork_join": {"n_branches": 3, "branch_length": 2},
    "in_tree": {"depth": 2, "branching_factor": 3},
    "out_tree": {"depth": 2, "branching_factor": 3},
    "diamond": {"width": 3, "depth": 2},
}


class TestDispatcher:
    @pytest.mark.parametrize("family", list(_FAMILY_PARAMS.keys()))
    def test_works_for_all_supported_families(self, family):
        kwargs = _FAMILY_PARAMS[family]
        g = generate_graph_family(family, seed=0, **kwargs)
        assert isinstance(g, nx.DiGraph)
        assert nx.is_directed_acyclic_graph(g)
        DAGGraph(g)

    def test_unknown_family_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown graph family"):
            generate_graph_family("nonexistent_family", n_tasks=5)

    def test_non_string_family_raises_value_error(self):
        with pytest.raises(ValueError, match="family must be a str"):
            generate_graph_family(42, n_tasks=5)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="family must be a str"):
            generate_graph_family(None, n_tasks=5)  # type: ignore[arg-type]

    def test_family_specific_kwargs_are_passed(self):
        g_chain = generate_graph_family("chain", n_tasks=15, seed=0)
        assert g_chain.number_of_nodes() == 15

        g_fork = generate_graph_family("fork", n_branches=7, seed=0)
        assert g_fork.number_of_nodes() == 8

        g_diamond = generate_graph_family("diamond", width=3, depth=2, seed=0)
        assert g_diamond.number_of_nodes() == 2 + 3 * 2

    def test_dispatcher_output_is_deterministic_with_seed(self):
        g1 = generate_graph_family("fork_join", n_branches=3, branch_length=2, seed=99)
        g2 = generate_graph_family("fork_join", n_branches=3, branch_length=2, seed=99)
        for node in g1.nodes:
            assert g1.nodes[node]["computation_cost"] == g2.nodes[node]["computation_cost"]
        for u, v in g1.edges:
            assert g1.edges[u, v]["communication_volume"] == g2.edges[u, v]["communication_volume"]


# ---------------------------------------------------------------------------
# 12. TestSchedulerCompatibilitySmoke
# ---------------------------------------------------------------------------

_SMOKE_NOC = MeshNoC(rows=2, cols=2, alpha=0.0, beta=1.0)

_SMOKE_GRAPHS = [
    ("chain", {"n_tasks": 5}),
    ("fork_join", {"n_branches": 2, "branch_length": 2}),
    ("diamond", {"width": 2, "depth": 2}),
]

_SMOKE_SCHEDULERS = [
    ("heft", HEFTScheduler),
    ("contention_aware", ContentionAwareScheduler),
    ("classical_duplication", ClassicalDuplicationScheduler),
    ("proposed", ProposedScheduler),
]


class TestSchedulerCompatibilitySmoke:
    """All four schedulers run without errors on small graph family instances."""

    @pytest.mark.parametrize("family,fkwargs", _SMOKE_GRAPHS)
    @pytest.mark.parametrize("sched_name,sched_cls", _SMOKE_SCHEDULERS)
    def test_schedule_is_valid(self, family, fkwargs, sched_name, sched_cls):
        g = generate_graph_family(family, seed=0, **fkwargs)
        dag = DAGGraph(g)
        scheduler = sched_cls(_SMOKE_NOC)
        state = scheduler.schedule(dag)

        state.validate_no_overlaps()

        summary = schedule_summary(state)
        assert summary["primary_task_count"] == dag.number_of_tasks(), (
            f"{sched_name} on {family}: primary_task_count should equal n_tasks"
        )
        assert summary["makespan"] > 0, (
            f"{sched_name} on {family}: makespan should be positive"
        )
