"""
Phase 19 Part A — Duplication Behavior Diagnostics Runner
==========================================================
Runs InstrumentedCDLS and InstrumentedCAD on all DAG families × CCR values
and saves diagnostic counters to results/summary/phase19_duplication_diagnostics.csv.

Run from repository root:
    python scripts/diagnose_duplication_behavior.py
"""

import sys
import csv
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.noc import MeshNoC
from src.models import DAGGraph
from src.graph_families import (
    generate_chain_dag,
    generate_fork_dag,
    generate_out_tree_dag,
    generate_fork_join_dag,
)
from scripts.instrumented_schedulers import InstrumentedCDLS, InstrumentedCAD

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

COMP_RANGE = (5, 20)
COMM_RANGE = (1, 10)
NOC_ROWS = 4
NOC_COLS = 4
ALPHA = 0.0
BETA = 1.0
SEEDS = list(range(20))
CCR_VALUES = [0.1, 1.0, 5.0, 10.0]

DAG_CONFIGS: dict[str, dict] = {
    "chain": {
        "label": "Chain",
        "func": generate_chain_dag,
        "kwargs": {"n_tasks": 10},
    },
    "fork": {
        "label": "Fork",
        "func": generate_fork_dag,
        "kwargs": {"n_branches": 8},
    },
    "out_tree": {
        "label": "Out-tree",
        "func": generate_out_tree_dag,
        "kwargs": {"depth": 2, "branching_factor": 2},
    },
    "fork_join": {
        "label": "Fork-join",
        "func": generate_fork_join_dag,
        "kwargs": {"n_branches": 4, "branch_length": 3},
    },
}

CSV_FIELDS = [
    "dag_family", "dag_label", "n_tasks", "n_edges", "ccr", "seed",
    "scheduler",
    "direct_dup_attempts",
    "direct_dup_accepted",
    "direct_dup_rejected",
    "total_new_placements",
    "recursive_ancestor_placements",
    "prune_candidates",
    "prune_removed",
    "native_makespan",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_dag(dag_name: str, ccr: float, seed: int) -> DAGGraph:
    cfg = DAG_CONFIGS[dag_name]
    g = cfg["func"](
        **cfg["kwargs"],
        comp_range=COMP_RANGE,
        comm_range=COMM_RANGE,
        ccr=ccr,
        seed=seed,
    )
    return DAGGraph(g)


def run_one(dag: DAGGraph, noc: MeshNoC, dag_name: str, ccr: float, seed: int) -> list[dict]:
    cfg = DAG_CONFIGS[dag_name]
    rows = []

    cdls = InstrumentedCDLS(noc)
    cdls_state = cdls.schedule(dag)
    rows.append({
        "dag_family": dag_name,
        "dag_label": cfg["label"],
        "n_tasks": dag.number_of_tasks(),
        "n_edges": dag.number_of_edges(),
        "ccr": ccr,
        "seed": seed,
        "scheduler": "CD-LS",
        "direct_dup_attempts": cdls.diag.direct_dup_attempts,
        "direct_dup_accepted": cdls.diag.direct_dup_accepted,
        "direct_dup_rejected": cdls.diag.direct_dup_rejected,
        "total_new_placements": cdls.diag.total_new_placements,
        "recursive_ancestor_placements": cdls.diag.recursive_ancestor_placements,
        "prune_candidates": cdls.diag.prune_candidates,
        "prune_removed": cdls.diag.prune_removed,
        "native_makespan": round(cdls_state.max_processor_finish_time(), 4),
    })

    cad = InstrumentedCAD(noc)
    cad_state = cad.schedule(dag)
    rows.append({
        "dag_family": dag_name,
        "dag_label": cfg["label"],
        "n_tasks": dag.number_of_tasks(),
        "n_edges": dag.number_of_edges(),
        "ccr": ccr,
        "seed": seed,
        "scheduler": "CA-D",
        "direct_dup_attempts": cad.diag.direct_dup_attempts,
        "direct_dup_accepted": cad.diag.direct_dup_accepted,
        "direct_dup_rejected": cad.diag.direct_dup_rejected,
        "total_new_placements": cad.diag.total_new_placements,
        "recursive_ancestor_placements": cad.diag.recursive_ancestor_placements,
        "prune_candidates": cad.diag.prune_candidates,
        "prune_removed": cad.diag.prune_removed,
        "native_makespan": round(cad_state.max_processor_finish_time(), 4),
    })

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    t0 = time.time()
    noc = MeshNoC(rows=NOC_ROWS, cols=NOC_COLS, alpha=ALPHA, beta=BETA)
    all_rows: list[dict] = []

    total_cases = len(DAG_CONFIGS) * len(CCR_VALUES) * len(SEEDS)
    done = 0

    for dag_name in DAG_CONFIGS:
        for ccr in CCR_VALUES:
            for seed in SEEDS:
                dag = build_dag(dag_name, ccr, seed)
                rows = run_one(dag, noc, dag_name, ccr, seed)
                all_rows.extend(rows)
                done += 1
                if done % 20 == 0 or done == total_cases:
                    print(f"  {done}/{total_cases} cases done", flush=True)

    out_path = ROOT / "results" / "summary" / "phase19_duplication_diagnostics.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(all_rows)

    elapsed = time.time() - t0
    print(f"\n[Done] {elapsed:.1f}s | {len(all_rows)} rows saved to {out_path.relative_to(ROOT)}", flush=True)

    # Print quick summary
    print("\n=== Quick Summary (seed=0 only) ===", flush=True)
    seed0 = [r for r in all_rows if r["seed"] == 0]
    for row in seed0:
        print(
            f"  {row['dag_label']:10s} CCR={row['ccr']:5.1f} {row['scheduler']:6s}"
            f" | attempts={row['direct_dup_attempts']:3d}"
            f" accepted={row['direct_dup_accepted']:3d}"
            f" rejected={row['direct_dup_rejected']:3d}"
            f" total_placements={row['total_new_placements']:3d}"
            f" recursive={row['recursive_ancestor_placements']:3d}"
            f" prune_cand={row['prune_candidates']:3d}"
            f" prune_rem={row['prune_removed']:3d}",
            flush=True,
        )


if __name__ == "__main__":
    main()
