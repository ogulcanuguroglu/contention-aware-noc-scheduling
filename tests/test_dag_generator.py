"""
Tests for src/dag_generator.py.

Covers: acyclicity, node/edge attributes, edge direction, weak connectivity,
CCR scaling, reproducibility, single-node case, and input validation.
Implemented in Phase 2.
"""

import networkx as nx
import pytest

from src.dag_generator import compute_ccr, generate_dag
from src.models import DAGGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_dag(**kwargs) -> nx.DiGraph:
    """Generate a small DAG with sensible defaults, overridable via kwargs."""
    params = dict(n_tasks=10, edge_prob=0.4, ccr=1.0, comp_range=(10, 100), seed=42)
    params.update(kwargs)
    return generate_dag(**params)


# ---------------------------------------------------------------------------
# 1. Basic generation
# ---------------------------------------------------------------------------

class TestBasicGeneration:
    def test_returns_digraph(self):
        g = _default_dag()
        assert isinstance(g, nx.DiGraph)

    def test_correct_node_count(self):
        for n in [1, 5, 20, 50]:
            g = generate_dag(n, 0.3, 1.0, (10, 100), seed=0)
            assert g.number_of_nodes() == n

    def test_acyclic(self):
        g = _default_dag()
        assert nx.is_directed_acyclic_graph(g)

    def test_passes_dagraph_validation(self):
        g = _default_dag()
        dag = DAGGraph(g)
        assert dag.number_of_tasks() == 10

    def test_acyclic_high_edge_prob(self):
        g = generate_dag(20, 1.0, 1.0, (10, 100), seed=7)
        assert nx.is_directed_acyclic_graph(g)

    def test_acyclic_low_edge_prob(self):
        g = generate_dag(20, 0.05, 1.0, (10, 100), seed=7)
        assert nx.is_directed_acyclic_graph(g)


# ---------------------------------------------------------------------------
# 2. Node attributes
# ---------------------------------------------------------------------------

class TestNodeAttributes:
    def test_every_node_has_computation_cost(self):
        g = _default_dag()
        for node in g.nodes:
            assert "computation_cost" in g.nodes[node]

    def test_computation_cost_within_range(self):
        g = generate_dag(20, 0.3, 1.0, (10, 100), seed=42)
        for node in g.nodes:
            cost = g.nodes[node]["computation_cost"]
            assert 10.0 <= cost <= 100.0

    def test_computation_cost_is_positive(self):
        g = _default_dag()
        for node in g.nodes:
            assert g.nodes[node]["computation_cost"] > 0

    def test_node_ids_are_zero_based_integers(self):
        n = 8
        g = generate_dag(n, 0.4, 1.0, (10, 100), seed=1)
        assert set(g.nodes) == set(range(n))


# ---------------------------------------------------------------------------
# 3. Edge attributes
# ---------------------------------------------------------------------------

class TestEdgeAttributes:
    def test_every_edge_has_communication_volume(self):
        g = _default_dag()
        for u, v in g.edges():
            assert "communication_volume" in g.edges[u, v]

    def test_communication_volume_non_negative(self):
        g = _default_dag()
        for u, v in g.edges():
            assert g.edges[u, v]["communication_volume"] >= 0.0

    def test_communication_volume_non_negative_high_ccr(self):
        g = generate_dag(15, 0.4, 5.0, (10, 100), seed=99)
        for u, v in g.edges():
            assert g.edges[u, v]["communication_volume"] >= 0.0


# ---------------------------------------------------------------------------
# 4. Edge direction: every edge must satisfy source < target
# ---------------------------------------------------------------------------

class TestEdgeDirection:
    def test_all_edges_forward(self):
        g = generate_dag(20, 0.5, 1.0, (10, 100), seed=42)
        for u, v in g.edges():
            assert u < v, f"edge ({u}, {v}) violates u < v"

    def test_all_edges_forward_full_density(self):
        g = generate_dag(10, 1.0, 1.0, (10, 100), seed=0)
        for u, v in g.edges():
            assert u < v


# ---------------------------------------------------------------------------
# 5. Reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_same_seed_same_costs(self):
        g1 = generate_dag(10, 0.3, 1.0, (10, 100), seed=42)
        g2 = generate_dag(10, 0.3, 1.0, (10, 100), seed=42)
        for i in range(10):
            assert g1.nodes[i]["computation_cost"] == g2.nodes[i]["computation_cost"]

    def test_same_seed_same_edges(self):
        g1 = generate_dag(10, 0.3, 1.0, (10, 100), seed=42)
        g2 = generate_dag(10, 0.3, 1.0, (10, 100), seed=42)
        assert set(g1.edges()) == set(g2.edges())

    def test_same_seed_same_volumes(self):
        g1 = generate_dag(10, 0.3, 1.0, (10, 100), seed=42)
        g2 = generate_dag(10, 0.3, 1.0, (10, 100), seed=42)
        for u, v in g1.edges():
            assert g1.edges[u, v]["communication_volume"] == g2.edges[u, v]["communication_volume"]

    def test_none_seed_is_allowed(self):
        # Should not raise; result is non-deterministic but must be a valid graph
        g = generate_dag(5, 0.4, 1.0, (10, 100), seed=None)
        assert isinstance(g, nx.DiGraph)
        assert g.number_of_nodes() == 5


# ---------------------------------------------------------------------------
# 6. Different seeds produce different graphs
# ---------------------------------------------------------------------------

class TestDifferentSeeds:
    def test_different_seeds_produce_different_results(self):
        """
        Compare seed=42 against 5 other seeds. Uses n_tasks=15 so that the
        probability of any two seeds producing identical floating-point costs
        AND identical edge sets is negligible. Requires at least 4 out of 5
        comparisons to differ (the one-in-a-trillion collision budget).
        Each candidate seed calls generate_dag exactly once.
        """
        n = 15
        g_ref = generate_dag(n, 0.3, 1.0, (10, 100), seed=42)
        ref_costs = [g_ref.nodes[i]["computation_cost"] for i in range(n)]
        ref_edges = set(g_ref.edges())

        n_different = 0
        for s in [0, 1, 7, 123, 999]:
            g = generate_dag(n, 0.3, 1.0, (10, 100), seed=s)
            costs = [g.nodes[i]["computation_cost"] for i in range(n)]
            if costs != ref_costs or set(g.edges()) != ref_edges:
                n_different += 1

        assert n_different >= 4, f"Only {n_different}/5 seeds produced different results"


# ---------------------------------------------------------------------------
# 7. CCR scaling
# ---------------------------------------------------------------------------

class TestCCRScaling:
    @pytest.mark.parametrize("ccr", [0.1, 0.5, 1.0, 2.0, 5.0])
    def test_achieved_ccr_matches_requested(self, ccr):
        g = generate_dag(20, 0.4, ccr, (10, 100), seed=42)
        assert g.number_of_edges() > 0
        achieved = compute_ccr(g)
        assert achieved == pytest.approx(ccr, rel=1e-6)

    def test_ccr_scaling_small_graph(self):
        g = generate_dag(5, 0.8, 2.0, (10, 100), seed=7)
        assert compute_ccr(g) == pytest.approx(2.0, rel=1e-6)

    def test_compute_ccr_helper_matches_manual(self):
        g = _default_dag(ccr=1.0, seed=42)
        total_comp = sum(g.nodes[n]["computation_cost"] for n in g.nodes)
        total_comm = sum(g.edges[u, v]["communication_volume"] for u, v in g.edges())
        expected = total_comm / total_comp
        assert compute_ccr(g) == pytest.approx(expected, rel=1e-12)


# ---------------------------------------------------------------------------
# 8. CCR zero
# ---------------------------------------------------------------------------

class TestCCRZero:
    def test_zero_ccr_all_volumes_zero(self):
        g = generate_dag(10, 0.4, 0.0, (10, 100), seed=42)
        for u, v in g.edges():
            assert g.edges[u, v]["communication_volume"] == 0.0

    def test_zero_ccr_passes_dagraph(self):
        g = generate_dag(10, 0.4, 0.0, (10, 100), seed=42)
        DAGGraph(g)  # must not raise

    def test_compute_ccr_returns_zero_for_zero_volumes(self):
        g = generate_dag(10, 0.4, 0.0, (10, 100), seed=42)
        assert compute_ccr(g) == 0.0


# ---------------------------------------------------------------------------
# 9. Weak connectivity
# ---------------------------------------------------------------------------

class TestWeakConnectivity:
    def test_weakly_connected_by_default(self):
        # With any edge_prob, ensure_weakly_connected=True must produce a connected graph
        for seed in [0, 1, 42, 99]:
            g = generate_dag(10, 0.0, 1.0, (10, 100), seed=seed)
            assert nx.is_weakly_connected(g), f"graph not weakly connected for seed={seed}"

    def test_weakly_connected_with_low_edge_prob(self):
        g = generate_dag(20, 0.05, 1.0, (10, 100), seed=42)
        assert nx.is_weakly_connected(g)

    def test_weakly_connected_with_zero_edge_prob(self):
        # edge_prob=0 adds no random edges; chain edges must connect the graph
        g = generate_dag(5, 0.0, 1.0, (10, 100), seed=1)
        assert nx.is_weakly_connected(g)

    def test_not_forced_when_disabled(self):
        # With ensure_weakly_connected=False and edge_prob=0, no edges are added
        g = generate_dag(5, 0.0, 1.0, (10, 100), seed=1, ensure_weakly_connected=False)
        assert g.number_of_edges() == 0

    def test_passes_dagraph_after_connectivity_fix(self):
        g = generate_dag(15, 0.0, 1.0, (10, 100), seed=42)
        DAGGraph(g)  # must not raise


# ---------------------------------------------------------------------------
# 10. Single-node case
# ---------------------------------------------------------------------------

class TestSingleNode:
    def test_single_node_has_one_node(self):
        g = generate_dag(1, 0.5, 1.0, (10, 100), seed=0)
        assert g.number_of_nodes() == 1

    def test_single_node_has_zero_edges(self):
        g = generate_dag(1, 0.5, 1.0, (10, 100), seed=0)
        assert g.number_of_edges() == 0

    def test_single_node_passes_dagraph(self):
        g = generate_dag(1, 0.5, 1.0, (10, 100), seed=0)
        dag = DAGGraph(g)
        assert dag.number_of_tasks() == 1

    def test_single_node_computation_cost_in_range(self):
        g = generate_dag(1, 0.5, 1.0, (10, 100), seed=7)
        assert 10.0 <= g.nodes[0]["computation_cost"] <= 100.0


# ---------------------------------------------------------------------------
# 11. Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_rejects_zero_n_tasks(self):
        with pytest.raises(ValueError, match="n_tasks"):
            generate_dag(0, 0.3, 1.0, (10, 100))

    def test_rejects_negative_n_tasks(self):
        with pytest.raises(ValueError, match="n_tasks"):
            generate_dag(-1, 0.3, 1.0, (10, 100))

    def test_rejects_edge_prob_below_zero(self):
        with pytest.raises(ValueError, match="edge_prob"):
            generate_dag(5, -0.1, 1.0, (10, 100))

    def test_rejects_edge_prob_above_one(self):
        with pytest.raises(ValueError, match="edge_prob"):
            generate_dag(5, 1.1, 1.0, (10, 100))

    def test_rejects_negative_ccr(self):
        with pytest.raises(ValueError, match="ccr"):
            generate_dag(5, 0.3, -1.0, (10, 100))

    def test_rejects_comp_range_too_short(self):
        with pytest.raises(ValueError):
            generate_dag(5, 0.3, 1.0, (10,))

    def test_rejects_comp_range_too_long(self):
        with pytest.raises(ValueError):
            generate_dag(5, 0.3, 1.0, (10, 50, 100))

    def test_rejects_none_comp_range(self):
        with pytest.raises(ValueError):
            generate_dag(5, 0.3, 1.0, None)  # type: ignore[arg-type]

    def test_rejects_zero_comp_min(self):
        with pytest.raises(ValueError):
            generate_dag(5, 0.3, 1.0, (0, 100))

    def test_rejects_negative_comp_min(self):
        with pytest.raises(ValueError):
            generate_dag(5, 0.3, 1.0, (-10, 100))

    def test_rejects_negative_comp_max(self):
        with pytest.raises(ValueError):
            generate_dag(5, 0.3, 1.0, (10, -5))

    def test_rejects_comp_min_greater_than_comp_max(self):
        with pytest.raises(ValueError):
            generate_dag(5, 0.3, 1.0, (100, 10))

    def test_allows_comp_min_equal_comp_max(self):
        # comp_min == comp_max is valid: all tasks get exactly that cost
        g = generate_dag(5, 0.3, 1.0, (50, 50), seed=1)
        for node in g.nodes:
            assert g.nodes[node]["computation_cost"] == pytest.approx(50.0)

    def test_allows_zero_edge_prob(self):
        g = generate_dag(5, 0.0, 1.0, (10, 100), seed=1)
        assert isinstance(g, nx.DiGraph)

    def test_allows_one_edge_prob(self):
        g = generate_dag(5, 1.0, 1.0, (10, 100), seed=1)
        assert isinstance(g, nx.DiGraph)

    def test_allows_zero_ccr(self):
        g = generate_dag(5, 0.4, 0.0, (10, 100), seed=1)
        assert isinstance(g, nx.DiGraph)

    # --- new: type and finiteness validation ---

    def test_rejects_float_n_tasks(self):
        with pytest.raises(ValueError, match="n_tasks"):
            generate_dag(5.5, 0.3, 1.0, (10, 100))  # type: ignore[arg-type]

    def test_rejects_bool_n_tasks(self):
        with pytest.raises(ValueError, match="n_tasks"):
            generate_dag(True, 0.3, 1.0, (10, 100))  # type: ignore[arg-type]

    def test_rejects_non_numeric_edge_prob(self):
        with pytest.raises(ValueError, match="edge_prob"):
            generate_dag(5, "0.5", 1.0, (10, 100))  # type: ignore[arg-type]

    def test_rejects_nan_edge_prob(self):
        with pytest.raises(ValueError, match="edge_prob"):
            generate_dag(5, float("nan"), 1.0, (10, 100))

    def test_rejects_infinity_edge_prob(self):
        with pytest.raises(ValueError, match="edge_prob"):
            generate_dag(5, float("inf"), 1.0, (10, 100))

    def test_rejects_non_numeric_ccr(self):
        with pytest.raises(ValueError, match="ccr"):
            generate_dag(5, 0.3, "1.0", (10, 100))  # type: ignore[arg-type]

    def test_rejects_nan_ccr(self):
        with pytest.raises(ValueError, match="ccr"):
            generate_dag(5, 0.3, float("nan"), (10, 100))

    def test_rejects_infinity_ccr(self):
        with pytest.raises(ValueError, match="ccr"):
            generate_dag(5, 0.3, float("inf"), (10, 100))

    def test_rejects_nan_comp_range_value(self):
        with pytest.raises(ValueError):
            generate_dag(5, 0.3, 1.0, (float("nan"), 100))

    def test_rejects_infinity_comp_range_value(self):
        with pytest.raises(ValueError):
            generate_dag(5, 0.3, 1.0, (float("inf"), 100))
