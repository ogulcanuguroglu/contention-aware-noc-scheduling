"""
Graph family benchmark generators for structured DAG workloads.

Provides deterministic, paper-like graph family generators for evaluating
scheduler behavior on structured workloads beyond random DAGs. Generated
graphs are valid DAGs compatible with DAGGraph validation from src.models.

Node attribute: 'computation_cost' (float, > 0)
Edge attribute: 'communication_volume' (float, >= 0)

CCR definition:
    CCR = total_communication_volume / total_computation_cost

Seed reproducibility:
    All generators accept a seed passed to numpy.default_rng(seed).
    Same inputs + same seed always produce identical graph attributes.

Implemented in Phase 14.
"""

import copy
import math
from collections.abc import Callable

import networkx as nx
import numpy as np

from src.models import DAGGraph


# ---------------------------------------------------------------------------
# Private validation helpers
# ---------------------------------------------------------------------------

def _validate_positive_int(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{name} must be a positive int, got {type(value).__name__}: {value!r}"
        )
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}")


def _validate_ccr_value(ccr: object) -> None:
    if isinstance(ccr, bool) or not isinstance(ccr, (int, float)):
        raise ValueError(
            f"ccr must be a numeric value, got {type(ccr).__name__}: {ccr!r}"
        )
    if not math.isfinite(ccr):
        raise ValueError(f"ccr must be finite, got {ccr}")
    if ccr < 0.0:
        raise ValueError(f"ccr must be non-negative, got {ccr}")


def _validate_ccr_opt(ccr: object) -> None:
    if ccr is not None:
        _validate_ccr_value(ccr)


def _validate_comp_range(comp_range: object) -> None:
    try:
        lo, hi = comp_range  # type: ignore[misc]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"comp_range must contain exactly two values, got {comp_range!r}"
        ) from exc
    for v in (lo, hi):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(
                f"comp_range values must be numeric, got {comp_range!r}"
            )
    lo_f, hi_f = float(lo), float(hi)
    if not math.isfinite(lo_f) or not math.isfinite(hi_f):
        raise ValueError(f"comp_range values must be finite, got ({lo_f}, {hi_f})")
    if lo_f <= 0 or hi_f <= 0:
        raise ValueError(f"comp_range values must be positive, got ({lo_f}, {hi_f})")
    if lo_f > hi_f:
        raise ValueError(
            f"comp_range[0] must be <= comp_range[1], got ({lo_f}, {hi_f})"
        )


def _validate_comm_range(comm_range: object) -> None:
    try:
        lo, hi = comm_range  # type: ignore[misc]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"comm_range must contain exactly two values, got {comm_range!r}"
        ) from exc
    for v in (lo, hi):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(
                f"comm_range values must be numeric, got {comm_range!r}"
            )
    lo_f, hi_f = float(lo), float(hi)
    if not math.isfinite(lo_f) or not math.isfinite(hi_f):
        raise ValueError(f"comm_range values must be finite, got ({lo_f}, {hi_f})")
    if lo_f < 0 or hi_f < 0:
        raise ValueError(f"comm_range values must be non-negative, got ({lo_f}, {hi_f})")
    if lo_f > hi_f:
        raise ValueError(
            f"comm_range[0] must be <= comm_range[1], got ({lo_f}, {hi_f})"
        )


# ---------------------------------------------------------------------------
# Public helper functions
# ---------------------------------------------------------------------------

def compute_total_computation(g: nx.DiGraph) -> float:
    """Return the sum of computation_cost over all nodes."""
    return sum(float(g.nodes[n]["computation_cost"]) for n in g.nodes)


def compute_total_communication(g: nx.DiGraph) -> float:
    """Return the sum of communication_volume over all edges."""
    return sum(float(g.edges[u, v]["communication_volume"]) for u, v in g.edges())


def scale_graph_to_ccr(g: nx.DiGraph, ccr: float) -> nx.DiGraph:
    """
    Return a copy of g with communication_volume values scaled to achieve the
    target CCR (= total_communication / total_computation).

    The input graph must already contain ``computation_cost`` node attributes
    (float > 0) and ``communication_volume`` edge attributes (float >= 0) on
    all nodes and edges, as required by DAGGraph validation.

    Returns a copy; the original graph is never mutated.

    Special cases:
    - ccr == 0.0: all communication_volume values set to 0.0.
    - No edges and ccr > 0: volumes remain 0.0 (CCR cannot be enforced on
      edge-free graphs; the returned copy is valid but has no communications).
    - All edge volumes are 0.0 but edges exist and ccr > 0: volumes are set to
      equal positive values so the target CCR is achieved.

    Raises:
        ValueError: If ccr is not numeric, not finite, or is negative.
    """
    _validate_ccr_value(ccr)
    result = copy.deepcopy(g)

    if ccr == 0.0:
        for u, v in result.edges():
            result.edges[u, v]["communication_volume"] = 0.0
        return result

    if result.number_of_edges() == 0:
        return result

    total_comp = compute_total_computation(result)
    if total_comp == 0.0:
        return result

    target_comm = ccr * total_comp
    current_comm = compute_total_communication(result)

    if current_comm == 0.0:
        per_edge = target_comm / result.number_of_edges()
        for u, v in result.edges():
            result.edges[u, v]["communication_volume"] = per_edge
    else:
        scale = target_comm / current_comm
        for u, v in result.edges():
            result.edges[u, v]["communication_volume"] = (
                result.edges[u, v]["communication_volume"] * scale
            )

    return result


def assign_random_costs(
    g: nx.DiGraph,
    comp_range: tuple = (10, 100),
    comm_range: tuple = (1, 10),
    seed: int | None = None,
) -> nx.DiGraph:
    """
    Return a copy of g with computation_cost and communication_volume attributes
    assigned by uniform random sampling.

    Computation costs are sampled from Uniform(comp_range[0], comp_range[1]).
    Communication volumes are sampled from Uniform(comm_range[0], comm_range[1]).

    Returns a copy; the original graph is never mutated.

    Nodes are visited in insertion order; edges are visited in insertion order.
    The same seed always produces identical attribute values for the same topology.

    Raises:
        ValueError: If comp_range or comm_range are invalid.
    """
    _validate_comp_range(comp_range)
    _validate_comm_range(comm_range)

    result = copy.deepcopy(g)
    rng = np.random.default_rng(seed)

    comp_lo, comp_hi = float(comp_range[0]), float(comp_range[1])
    comm_lo, comm_hi = float(comm_range[0]), float(comm_range[1])

    n_nodes = result.number_of_nodes()
    n_edges = result.number_of_edges()

    costs = rng.uniform(comp_lo, comp_hi, n_nodes)
    volumes = rng.uniform(comm_lo, comm_hi, n_edges) if n_edges > 0 else []

    for i, node in enumerate(result.nodes()):
        result.nodes[node]["computation_cost"] = float(costs[i])

    for i, (u, v) in enumerate(result.edges()):
        result.edges[u, v]["communication_volume"] = float(volumes[i])

    return result


# ---------------------------------------------------------------------------
# Private topology helper
# ---------------------------------------------------------------------------

def _build_balanced_tree(
    depth: int,
    branching_factor: int,
    *,
    reverse_edges: bool,
) -> nx.DiGraph:
    """
    Build a balanced k-ary tree topology with integer node IDs assigned in
    BFS order starting from the root (node 0).

    reverse_edges=True:  edges go child → parent (in-tree, toward root/sink).
    reverse_edges=False: edges go parent → child (out-tree, away from root/source).

    No computation_cost or communication_volume attributes are set; call
    assign_random_costs() on the result before using with DAGGraph.
    """
    g = nx.DiGraph()
    g.add_node(0)
    node_id = 1
    current_level = [0]

    for _ in range(depth):
        next_level = []
        for parent in current_level:
            for _ in range(branching_factor):
                child = node_id
                node_id += 1
                g.add_node(child)
                next_level.append(child)
                if reverse_edges:
                    g.add_edge(child, parent)
                else:
                    g.add_edge(parent, child)
        current_level = next_level

    return g


# ---------------------------------------------------------------------------
# Graph family generators
# ---------------------------------------------------------------------------

def generate_chain_dag(
    n_tasks: int,
    comp_range: tuple = (10, 100),
    comm_range: tuple = (1, 10),
    ccr: float | None = None,
    seed: int | None = None,
) -> nx.DiGraph:
    """
    Generate a linear chain DAG: 0 → 1 → 2 → ... → n_tasks-1.

    For n_tasks == 1, the graph has one node and no edges.

    Raises:
        ValueError: If n_tasks < 1 or parameters are invalid.
    """
    _validate_positive_int("n_tasks", n_tasks)
    _validate_comp_range(comp_range)
    _validate_comm_range(comm_range)
    _validate_ccr_opt(ccr)

    g = nx.DiGraph()
    for i in range(n_tasks):
        g.add_node(i)
    for i in range(n_tasks - 1):
        g.add_edge(i, i + 1)

    g = assign_random_costs(g, comp_range=comp_range, comm_range=comm_range, seed=seed)
    if ccr is not None:
        g = scale_graph_to_ccr(g, ccr)

    DAGGraph(g)
    return g


def generate_fork_dag(
    n_branches: int,
    comp_range: tuple = (10, 100),
    comm_range: tuple = (1, 10),
    ccr: float | None = None,
    seed: int | None = None,
) -> nx.DiGraph:
    """
    Generate a fork DAG: one root (node 0) connected to n_branches leaf tasks.

    Structure: 0 → i for i in 1..n_branches.
    Total nodes: n_branches + 1.

    Raises:
        ValueError: If n_branches < 1 or parameters are invalid.
    """
    _validate_positive_int("n_branches", n_branches)
    _validate_comp_range(comp_range)
    _validate_comm_range(comm_range)
    _validate_ccr_opt(ccr)

    g = nx.DiGraph()
    for i in range(n_branches + 1):
        g.add_node(i)
    for i in range(1, n_branches + 1):
        g.add_edge(0, i)

    g = assign_random_costs(g, comp_range=comp_range, comm_range=comm_range, seed=seed)
    if ccr is not None:
        g = scale_graph_to_ccr(g, ccr)

    DAGGraph(g)
    return g


def generate_join_dag(
    n_branches: int,
    comp_range: tuple = (10, 100),
    comm_range: tuple = (1, 10),
    ccr: float | None = None,
    seed: int | None = None,
) -> nx.DiGraph:
    """
    Generate a join DAG: n_branches source tasks all connecting to one sink.

    Structure: i → n_branches for i in 0..n_branches-1.
    Total nodes: n_branches + 1.

    Raises:
        ValueError: If n_branches < 1 or parameters are invalid.
    """
    _validate_positive_int("n_branches", n_branches)
    _validate_comp_range(comp_range)
    _validate_comm_range(comm_range)
    _validate_ccr_opt(ccr)

    sink = n_branches
    g = nx.DiGraph()
    for i in range(n_branches + 1):
        g.add_node(i)
    for i in range(n_branches):
        g.add_edge(i, sink)

    g = assign_random_costs(g, comp_range=comp_range, comm_range=comm_range, seed=seed)
    if ccr is not None:
        g = scale_graph_to_ccr(g, ccr)

    DAGGraph(g)
    return g


def generate_fork_join_dag(
    n_branches: int,
    branch_length: int,
    comp_range: tuple = (10, 100),
    comm_range: tuple = (1, 10),
    ccr: float | None = None,
    seed: int | None = None,
) -> nx.DiGraph:
    """
    Generate a fork-join DAG with parallel branches.

    Structure for n_branches=3, branch_length=2:
        root → b0_0 → b0_1 → sink
        root → b1_0 → b1_1 → sink
        root → b2_0 → b2_1 → sink

    Node numbering: root=0, branch b node p = 1 + b*branch_length + p,
    sink = 1 + n_branches * branch_length.
    Total nodes: 2 + n_branches * branch_length.

    Raises:
        ValueError: If n_branches < 1, branch_length < 1, or parameters invalid.
    """
    _validate_positive_int("n_branches", n_branches)
    _validate_positive_int("branch_length", branch_length)
    _validate_comp_range(comp_range)
    _validate_comm_range(comm_range)
    _validate_ccr_opt(ccr)

    root_id = 0
    sink_id = 1 + n_branches * branch_length
    total_nodes = sink_id + 1

    g = nx.DiGraph()
    for i in range(total_nodes):
        g.add_node(i)

    for b in range(n_branches):
        first = 1 + b * branch_length
        last = first + branch_length - 1
        g.add_edge(root_id, first)
        for pos in range(first, last):
            g.add_edge(pos, pos + 1)
        g.add_edge(last, sink_id)

    g = assign_random_costs(g, comp_range=comp_range, comm_range=comm_range, seed=seed)
    if ccr is not None:
        g = scale_graph_to_ccr(g, ccr)

    DAGGraph(g)
    return g


def generate_in_tree_dag(
    depth: int,
    branching_factor: int,
    comp_range: tuple = (10, 100),
    comm_range: tuple = (1, 10),
    ccr: float | None = None,
    seed: int | None = None,
) -> nx.DiGraph:
    """
    Generate an in-tree (reduction tree) DAG where edges point toward the root.

    Node 0 is the root/sink (no outgoing edges). Leaves are sources. All paths
    converge toward node 0. Nodes are assigned in BFS order from the root, so
    every edge goes from a higher-ID child to a lower-ID parent.

    For depth=1: one root plus branching_factor leaves, all connected to the root.
    Total nodes: sum(branching_factor**level for level in range(depth + 1)).

    Raises:
        ValueError: If depth < 1, branching_factor < 1, or parameters invalid.
    """
    _validate_positive_int("depth", depth)
    _validate_positive_int("branching_factor", branching_factor)
    _validate_comp_range(comp_range)
    _validate_comm_range(comm_range)
    _validate_ccr_opt(ccr)

    g = _build_balanced_tree(depth, branching_factor, reverse_edges=True)

    g = assign_random_costs(g, comp_range=comp_range, comm_range=comm_range, seed=seed)
    if ccr is not None:
        g = scale_graph_to_ccr(g, ccr)

    DAGGraph(g)
    return g


def generate_out_tree_dag(
    depth: int,
    branching_factor: int,
    comp_range: tuple = (10, 100),
    comm_range: tuple = (1, 10),
    ccr: float | None = None,
    seed: int | None = None,
) -> nx.DiGraph:
    """
    Generate an out-tree (broadcast tree) DAG where edges point away from root.

    Node 0 is the root/source (no incoming edges). Leaves are sinks. All paths
    originate from node 0. Nodes are assigned in BFS order from the root, so
    every edge goes from a lower-ID parent to a higher-ID child.

    For depth=1: root plus branching_factor children, connected from root.
    Total nodes: sum(branching_factor**level for level in range(depth + 1)).

    Raises:
        ValueError: If depth < 1, branching_factor < 1, or parameters invalid.
    """
    _validate_positive_int("depth", depth)
    _validate_positive_int("branching_factor", branching_factor)
    _validate_comp_range(comp_range)
    _validate_comm_range(comm_range)
    _validate_ccr_opt(ccr)

    g = _build_balanced_tree(depth, branching_factor, reverse_edges=False)

    g = assign_random_costs(g, comp_range=comp_range, comm_range=comm_range, seed=seed)
    if ccr is not None:
        g = scale_graph_to_ccr(g, ccr)

    DAGGraph(g)
    return g


def generate_diamond_dag(
    width: int,
    depth: int,
    comp_range: tuple = (10, 100),
    comm_range: tuple = (1, 10),
    ccr: float | None = None,
    seed: int | None = None,
) -> nx.DiGraph:
    """
    Generate a diamond (layered series-parallel) DAG.

    Structure:
    - Node 0: source
    - depth middle layers, each containing width nodes
    - Last node: sink
    - Source → all first-layer nodes
    - Complete bipartite edges between consecutive layers
    - All last-layer nodes → sink

    Node numbering: source=0, layer d (1-indexed) uses nodes
    [1 + (d-1)*width, ..., d*width], sink = 1 + depth*width.
    Total nodes: 2 + width * depth.

    Raises:
        ValueError: If width < 1, depth < 1, or parameters invalid.
    """
    _validate_positive_int("width", width)
    _validate_positive_int("depth", depth)
    _validate_comp_range(comp_range)
    _validate_comm_range(comm_range)
    _validate_ccr_opt(ccr)

    source_id = 0
    sink_id = 1 + depth * width
    total_nodes = sink_id + 1

    g = nx.DiGraph()
    for i in range(total_nodes):
        g.add_node(i)

    def _layer(d: int) -> list[int]:
        return list(range(1 + (d - 1) * width, 1 + d * width))

    # Source to first layer
    for v in _layer(1):
        g.add_edge(source_id, v)

    # Complete bipartite between consecutive layers
    for d in range(1, depth):
        for u in _layer(d):
            for v in _layer(d + 1):
                g.add_edge(u, v)

    # Last layer to sink
    for u in _layer(depth):
        g.add_edge(u, sink_id)

    g = assign_random_costs(g, comp_range=comp_range, comm_range=comm_range, seed=seed)
    if ccr is not None:
        g = scale_graph_to_ccr(g, ccr)

    DAGGraph(g)
    return g


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_FAMILY_GENERATORS: dict[str, Callable[..., nx.DiGraph]] = {
    "chain": generate_chain_dag,
    "fork": generate_fork_dag,
    "join": generate_join_dag,
    "fork_join": generate_fork_join_dag,
    "in_tree": generate_in_tree_dag,
    "out_tree": generate_out_tree_dag,
    "diamond": generate_diamond_dag,
}


def generate_graph_family(
    family: str,
    *,
    seed: int | None = None,
    ccr: float | None = None,
    comp_range: tuple = (10, 100),
    comm_range: tuple = (1, 10),
    **kwargs,
) -> nx.DiGraph:
    """
    Generate a graph from a named family using the corresponding generator.

    Supported families: "chain", "fork", "join", "fork_join", "in_tree",
    "out_tree", "diamond".

    Common parameters (comp_range, comm_range, ccr, seed) are forwarded to the
    selected generator. Family-specific parameters are passed via **kwargs
    (e.g., n_tasks=10 for "chain", n_branches=4 for "fork" or "join",
    n_branches and branch_length for "fork_join", depth and branching_factor
    for "in_tree" and "out_tree", width and depth for "diamond").

    Raises:
        ValueError: If family is not a str or is not one of the supported names.
    """
    if not isinstance(family, str):
        raise ValueError(
            f"family must be a str, got {type(family).__name__}: {family!r}"
        )
    if family not in _FAMILY_GENERATORS:
        raise ValueError(
            f"Unknown graph family '{family}'. "
            f"Supported families: {sorted(_FAMILY_GENERATORS)}"
        )
    fn = _FAMILY_GENERATORS[family]
    return fn(
        comp_range=comp_range,
        comm_range=comm_range,
        ccr=ccr,
        seed=seed,
        **kwargs,
    )
