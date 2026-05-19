"""
Phase 18B Evaluation Extension — Experiment Runner
====================================================
Runs a 4-DAG-family × 4-CCR main experiment grid plus an alpha/hop-latency
sensitivity sweep using HEFT, CD-LS, and Proposed CA-D on a 4×4 MeshNoC.

Main grid  : alpha=0.0, beta=1.0, CCR=[0.1, 1.0, 5.0, 10.0]
Sensitivity: alpha=[0.0, 1.0, 5.0], beta=1.0, CCR=[1.0, 5.0]

Outputs:
  results/summary/phase18_eval_extension_main.csv
  results/summary/phase18_eval_extension_sensitivity.csv

Run from repository root:
    python scripts/run_phase18_eval_extension.py
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
from src.heft_scheduler import HEFTScheduler
from src.classical_dup_scheduler import ClassicalDuplicationScheduler
from src.proposed_scheduler import ProposedScheduler
from src.contention_replay import replay_under_contention
from src.metrics import (
    count_duplicate_tasks,
    task_instance_ratio,
    count_communication_instances,
    total_communication_time,
    max_link_utilization,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

COMP_RANGE = (5, 20)
COMM_RANGE = (1, 10)
SEED = 0
NOC_ROWS = 4
NOC_COLS = 4
BETA = 1.0

MAIN_ALPHA = 0.0
MAIN_CCR = [0.1, 1.0, 5.0, 10.0]

SENSITIVITY_ALPHA = [0.0, 1.0, 5.0]
SENSITIVITY_CCR = [1.0, 5.0]

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

SCHEDULER_KEYS = ["heft", "cdls", "cad"]
SCHEDULER_LABELS = {
    "heft": "HEFT",
    "cdls": "CD-LS",
    "cad": "Proposed CA-D",
}

CSV_FIELDS = [
    "dag_family", "dag_label", "n_tasks", "n_edges", "ccr",
    "alpha", "beta", "seed", "scheduler", "scheduler_label",
    "native_makespan", "replayed_makespan",
    "native_speedup_vs_heft", "replayed_speedup_vs_heft",
    "replay_overhead_ratio", "task_instance_ratio",
    "duplicate_count", "active_processor_count",
    "comm_count", "total_comm_time", "max_link_utilization",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _active_procs(state) -> set[int]:
    procs: set[int] = set()
    for insts in state.task_instances.values():
        for inst in insts:
            procs.add(inst.processor_id)
    return procs


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


def run_case(dag: DAGGraph, noc: MeshNoC) -> tuple[dict, dict]:
    """Schedule + replay all three schedulers. Returns (states, replayed)."""
    states: dict = {}
    states["heft"] = HEFTScheduler(noc).schedule(dag)
    states["cdls"] = ClassicalDuplicationScheduler(noc).schedule(dag)
    states["cad"] = ProposedScheduler(noc).schedule(dag)
    replayed: dict = {k: replay_under_contention(dag, v, noc) for k, v in states.items()}
    return states, replayed


def extract_rows(dag: DAGGraph, states: dict, replayed: dict,
                 dag_name: str, ccr: float, alpha: float, seed: int) -> list[dict]:
    cfg = DAG_CONFIGS[dag_name]
    heft_native = states["heft"].max_processor_finish_time()
    heft_replay = replayed["heft"].max_processor_finish_time()

    rows = []
    for key in SCHEDULER_KEYS:
        st = states[key]
        rp = replayed[key]
        native_ms = st.max_processor_finish_time()
        replay_ms = rp.max_processor_finish_time()
        rows.append({
            "dag_family": dag_name,
            "dag_label": cfg["label"],
            "n_tasks": dag.number_of_tasks(),
            "n_edges": dag.number_of_edges(),
            "ccr": ccr,
            "alpha": alpha,
            "beta": BETA,
            "seed": seed,
            "scheduler": key,
            "scheduler_label": SCHEDULER_LABELS[key],
            "native_makespan": round(native_ms, 4),
            "replayed_makespan": round(replay_ms, 4),
            "native_speedup_vs_heft": round(heft_native / native_ms, 6) if native_ms > 0 else 1.0,
            "replayed_speedup_vs_heft": round(heft_replay / replay_ms, 6) if replay_ms > 0 else 1.0,
            "replay_overhead_ratio": round(replay_ms / native_ms, 6) if native_ms > 0 else 1.0,
            "task_instance_ratio": round(task_instance_ratio(st), 6),
            "duplicate_count": count_duplicate_tasks(st),
            "active_processor_count": len(_active_procs(st)),
            "comm_count": count_communication_instances(st),
            "total_comm_time": round(total_communication_time(st), 4),
            "max_link_utilization": round(max_link_utilization(st), 6),
        })
    return rows


def save_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"  Saved {path.relative_to(ROOT)}  ({len(rows)} rows)", flush=True)


# ---------------------------------------------------------------------------
# Experiment loops
# ---------------------------------------------------------------------------

def run_main_grid() -> list[dict]:
    print(f"\n[Main grid] alpha={MAIN_ALPHA}, beta={BETA}", flush=True)
    print(f"  DAG families: {list(DAG_CONFIGS.keys())}", flush=True)
    print(f"  CCR values  : {MAIN_CCR}", flush=True)
    noc = MeshNoC(rows=NOC_ROWS, cols=NOC_COLS, alpha=MAIN_ALPHA, beta=BETA)
    all_rows: list[dict] = []

    for dag_name, cfg in DAG_CONFIGS.items():
        for ccr in MAIN_CCR:
            dag = build_dag(dag_name, ccr, SEED)
            states, replayed = run_case(dag, noc)
            rows = extract_rows(dag, states, replayed, dag_name, ccr, MAIN_ALPHA, SEED)
            all_rows.extend(rows)
            # One summary line per case
            cad = next(r for r in rows if r["scheduler"] == "cad")
            cdls = next(r for r in rows if r["scheduler"] == "cdls")
            print(
                f"  {cfg['label']:10s} CCR={ccr:5.1f} | "
                f"CA-D {cad['replayed_speedup_vs_heft']:.3f}x "
                f"(ovhd {cad['replay_overhead_ratio']:.3f}x) | "
                f"CD-LS {cdls['replayed_speedup_vs_heft']:.3f}x "
                f"(ovhd {cdls['replay_overhead_ratio']:.3f}x)",
                flush=True,
            )
    return all_rows


def run_sensitivity_grid() -> list[dict]:
    print(f"\n[Sensitivity] alpha={SENSITIVITY_ALPHA}, beta={BETA}", flush=True)
    print(f"  CCR values  : {SENSITIVITY_CCR}", flush=True)
    all_rows: list[dict] = []

    for alpha in SENSITIVITY_ALPHA:
        noc = MeshNoC(rows=NOC_ROWS, cols=NOC_COLS, alpha=alpha, beta=BETA)
        for dag_name, cfg in DAG_CONFIGS.items():
            for ccr in SENSITIVITY_CCR:
                dag = build_dag(dag_name, ccr, SEED)
                states, replayed = run_case(dag, noc)
                rows = extract_rows(dag, states, replayed, dag_name, ccr, alpha, SEED)
                all_rows.extend(rows)
                cad = next(r for r in rows if r["scheduler"] == "cad")
                print(
                    f"  alpha={alpha:.1f} {cfg['label']:10s} CCR={ccr:.1f} | "
                    f"CA-D {cad['replayed_speedup_vs_heft']:.3f}x",
                    flush=True,
                )
    return all_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    t0 = time.time()
    main_rows = run_main_grid()
    sens_rows = run_sensitivity_grid()
    elapsed = time.time() - t0

    print(f"\n[Saving CSVs]", flush=True)
    out = ROOT / "results" / "summary"
    save_csv(main_rows, out / "phase18_eval_extension_main.csv")
    save_csv(sens_rows, out / "phase18_eval_extension_sensitivity.csv")

    print(f"\n[Done] {elapsed:.1f}s | main={len(main_rows)} rows | sens={len(sens_rows)} rows",
          flush=True)


if __name__ == "__main__":
    main()
