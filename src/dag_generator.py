"""
Synthetic Directed Acyclic Graph (DAG) generator.

Generates random DAGs with controllable Communication-to-Computation Ratio (CCR),
task count, and graph density. Implemented in Phase 2.

Acyclicity guarantee:
    Edges are only added from node i to node j where i < j, which is a sufficient
    condition for acyclicity in a graph with integer node IDs 0..n-1.

CCR definition:
    CCR = total_communication_volume / total_computation_cost

    Communication volumes are first drawn uniformly from [1.0, 2.0], then scaled
    globally so the achieved CCR equals the requested value exactly (up to floating-
    point rounding, relative error < 1e-12 for graphs up to 100 tasks).

Connectivity policy:
    When ensure_weakly_connected=True, the graph is checked for weak connectivity
    after random edge generation. If the graph is already weakly connected, no extra
    edges are added. If it is disconnected, all missing chain edges i -> i+1 are added
    in one pass (i = 0 .. n-2), which guarantees a spanning forward path and therefore
    weak connectivity. Chain edges use the same pre-generated raw volumes as ordinary
    random edges and are subject to the same CCR scaling, so output is fully
    reproducible. Adding chain edges preserves acyclicity because i < i+1 for every
    chain edge.

Reproducibility:
    All random values (computation costs, edge decisions, raw communication volumes)
    are drawn from a numpy Generator seeded with `seed` in a single deterministic
    sequence. The same seed and parameters always produce identical output.
"""

import math

import networkx as nx
import numpy as np


def generate_dag(
    n_tasks: int,
    edge_prob: float,
    ccr: float,
    comp_range: tuple[int | float, int | float],
    seed: int | None = None,
    ensure_weakly_connected: bool = True,
) -> nx.DiGraph:
    """
    Generate a reproducible synthetic DAG.

    Args:
        n_tasks: Number of task nodes. Must be positive.
        edge_prob: Independent probability for each candidate edge i->j (i<j).
                   Must be in [0.0, 1.0].
        ccr: Target Communication-to-Computation Ratio. Must be non-negative.
             If 0.0, all edge volumes are set to 0.0.
        comp_range: (comp_min, comp_max) for uniform computation cost sampling.
                    Both values must be positive and comp_min <= comp_max.
        seed: Integer seed for the numpy random generator. None uses system entropy.
        ensure_weakly_connected: If True, add missing chain edges i->i+1 after
                                 random generation to guarantee weak connectivity.

    Returns:
        nx.DiGraph with:
          - node attribute 'computation_cost' (float, > 0)
          - edge attribute 'communication_volume' (float, >= 0)
        The graph passes DAGGraph validation from src.models.

    Raises:
        ValueError: On any invalid input parameter.
    """
    _validate_inputs(n_tasks, edge_prob, ccr, comp_range)
    comp_min, comp_max = float(comp_range[0]), float(comp_range[1])

    rng = np.random.default_rng(seed)

    # Pre-generate all random values in a single deterministic sequence:
    #   1. computation costs for all nodes
    #   2. edge-inclusion decisions for all n*(n-1)/2 candidate edges
    #   3. raw communication volumes for all candidate edges
    n_potential = n_tasks * (n_tasks - 1) // 2
    costs = rng.uniform(comp_min, comp_max, n_tasks)
    edge_decisions = rng.random(n_potential)
    raw_volumes = rng.uniform(1.0, 2.0, n_potential)

    # Build graph: add nodes
    g = nx.DiGraph()
    for i in range(n_tasks):
        g.add_node(i, computation_cost=float(costs[i]))

    # Single-node graph: no edges possible, CCR cannot be enforced
    if n_tasks == 1:
        return g

    # Build a lookup from potential edge (i, j) to its flat array index
    flat_idx: dict[tuple[int, int], int] = {}
    k = 0
    for i in range(n_tasks):
        for j in range(i + 1, n_tasks):
            flat_idx[(i, j)] = k
            k += 1

    # Add random edges
    for (i, j), k in flat_idx.items():
        if edge_decisions[k] < edge_prob:
            g.add_edge(i, j, communication_volume=float(raw_volumes[k]))

    # Ensure weak connectivity by adding all missing chain edges i -> i+1
    if ensure_weakly_connected and not nx.is_weakly_connected(g):
        for i in range(n_tasks - 1):
            if not g.has_edge(i, i + 1):
                k = flat_idx[(i, i + 1)]
                g.add_edge(i, i + 1, communication_volume=float(raw_volumes[k]))

    # Scale communication volumes to achieve the target CCR
    _scale_for_ccr(g, ccr)

    return g


def compute_ccr(g: nx.DiGraph) -> float:
    """
    Compute the actual CCR of a graph.

    Returns total_communication_volume / total_computation_cost.
    Returns 0.0 when the graph has no nodes, no edges, or zero total computation cost.
    """
    if g.number_of_nodes() == 0:
        return 0.0
    total_comp = sum(g.nodes[n]["computation_cost"] for n in g.nodes)
    if total_comp == 0.0:
        return 0.0
    total_comm = sum(g.edges[u, v]["communication_volume"] for u, v in g.edges())
    return total_comm / total_comp


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_inputs(
    n_tasks: int,
    edge_prob: float,
    ccr: float,
    comp_range: object,
) -> None:
    # n_tasks: must be a plain int (bool is a subclass of int — reject explicitly)
    if isinstance(n_tasks, bool) or not isinstance(n_tasks, int):
        raise ValueError(
            f"n_tasks must be an int, got {type(n_tasks).__name__}: {n_tasks!r}"
        )
    if n_tasks <= 0:
        raise ValueError(f"n_tasks must be positive, got {n_tasks}")

    # edge_prob: must be a numeric (int or float) finite value
    if not isinstance(edge_prob, (int, float)) or isinstance(edge_prob, bool):
        raise ValueError(
            f"edge_prob must be numeric, got {type(edge_prob).__name__}: {edge_prob!r}"
        )
    if not math.isfinite(edge_prob):
        raise ValueError(f"edge_prob must be finite, got {edge_prob}")
    if not (0.0 <= edge_prob <= 1.0):
        raise ValueError(f"edge_prob must be in [0.0, 1.0], got {edge_prob}")

    # ccr: must be a numeric finite non-negative value
    if not isinstance(ccr, (int, float)) or isinstance(ccr, bool):
        raise ValueError(
            f"ccr must be numeric, got {type(ccr).__name__}: {ccr!r}"
        )
    if not math.isfinite(ccr):
        raise ValueError(f"ccr must be finite, got {ccr}")
    if ccr < 0.0:
        raise ValueError(f"ccr must be non-negative, got {ccr}")

    # comp_range: must unpack to exactly two values
    try:
        comp_min, comp_max = comp_range  # type: ignore[misc]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"comp_range must contain exactly two numeric values, got {comp_range!r}"
        ) from exc

    # comp_range values: must convert to float
    try:
        comp_min = float(comp_min)
        comp_max = float(comp_max)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"comp_range values must be numeric, got {comp_range!r}"
        ) from exc

    # comp_range values: must be finite (catches NaN and infinity)
    if not math.isfinite(comp_min) or not math.isfinite(comp_max):
        raise ValueError(
            f"comp_range values must be finite, got ({comp_min}, {comp_max})"
        )
    if comp_min <= 0 or comp_max <= 0:
        raise ValueError(
            f"comp_range values must be positive, got ({comp_min}, {comp_max})"
        )
    if comp_min > comp_max:
        raise ValueError(
            f"comp_range[0] must be <= comp_range[1], got ({comp_min}, {comp_max})"
        )


def _scale_for_ccr(g: nx.DiGraph, ccr: float) -> None:
    """Scale all edge communication_volume values in-place to match the target CCR."""
    if ccr == 0.0:
        for u, v in g.edges():
            g.edges[u, v]["communication_volume"] = 0.0
        return

    total_comp = sum(g.nodes[n]["computation_cost"] for n in g.nodes)
    current_comm = sum(g.edges[u, v]["communication_volume"] for u, v in g.edges())

    if current_comm == 0.0:
        # No edges to scale; CCR cannot be enforced (e.g. ensure_weakly_connected=False
        # with edge_prob=0 produced a graph with no edges).
        return

    scale = (ccr * total_comp) / current_comm
    for u, v in g.edges():
        g.edges[u, v]["communication_volume"] = g.edges[u, v]["communication_volume"] * scale
