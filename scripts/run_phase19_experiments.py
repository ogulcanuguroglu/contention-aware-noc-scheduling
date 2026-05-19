"""
Phase 19 Parts C+D+E — Multi-seed experiment runner
====================================================
Parts C+D: 4 DAGs × 4 CCR × 20 seeds × 3 schedulers with extended metrics.
Part E:    Alpha sensitivity: out-tree + fork-join, CCR=[1.0, 5.0],
           alpha=[0.0, 1.0, 5.0], seeds 0–9.

Extended metrics (Part C):
  duplication_efficiency        = (replayed_speedup_vs_heft - 1) / (TIR - 1)  [TIR > 1]
  makespan_reduction_per_dup    = (heft_replayed - replayed_makespan) / dup_count  [dup_count > 0]
  contention_penalty            = replayed_makespan - native_makespan
  normalized_contention_penalty = contention_penalty / native_makespan  [native > 0]
  link_total_busy_time          = sum of all link busy times in replayed state
  link_max_busy_time            = max single link busy time in replayed state
  link_mean_busy_time           = mean busy time over used links in replayed state
  link_load_imbalance           = (max - mean) / max over used links  [max > 0]
  n_used_links                  = number of links with busy time > 0

Outputs:
  results/summary/phase19_multiseed_main.csv
  results/summary/phase19_alpha_sensitivity.csv

Run from repository root:
    python scripts/run_phase19_experiments.py
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
    link_busy_time,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

COMP_RANGE = (5, 20)
COMM_RANGE = (1, 10)
NOC_ROWS = 4
NOC_COLS = 4
BETA = 1.0

MAIN_SEEDS = list(range(20))
MAIN_CCR = [0.1, 1.0, 5.0, 10.0]
MAIN_ALPHA = 0.0

SENS_SEEDS = list(range(10))
SENS_CCR = [1.0, 5.0]
SENS_ALPHA = [0.0, 1.0, 5.0]

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

SENS_DAGS = ["out_tree", "fork_join"]

SCHEDULER_KEYS = ["heft", "cdls", "cad"]
SCHEDULER_LABELS = {"heft": "HEFT", "cdls": "CD-LS", "cad": "Proposed CA-D"}

BASE_FIELDS = [
    "dag_family", "dag_label", "n_tasks", "n_edges", "ccr", "alpha", "beta", "seed",
    "scheduler", "scheduler_label",
]
PERF_FIELDS = [
    "native_makespan", "replayed_makespan",
    "native_speedup_vs_heft", "replayed_speedup_vs_heft",
    "replay_overhead_ratio",
    "contention_penalty", "normalized_contention_penalty",
]
DUP_FIELDS = [
    "duplicate_count", "task_instance_ratio",
    "duplication_efficiency", "makespan_reduction_per_dup",
]
COMM_FIELDS = [
    "comm_count", "total_comm_time",
]
LINK_FIELDS = [
    "link_total_busy_time", "link_max_busy_time", "link_mean_busy_time",
    "link_load_imbalance", "n_used_links",
]
CSV_FIELDS = BASE_FIELDS + PERF_FIELDS + DUP_FIELDS + COMM_FIELDS + LINK_FIELDS


# ---------------------------------------------------------------------------
# Link metric computation
# ---------------------------------------------------------------------------

def compute_link_metrics(replayed_state) -> dict:
    busy = link_busy_time(replayed_state)
    used = {lnk: t for lnk, t in busy.items() if t > 0}
    n_used = len(used)
    if n_used == 0:
        return {
            "link_total_busy_time": 0.0,
            "link_max_busy_time": 0.0,
            "link_mean_busy_time": 0.0,
            "link_load_imbalance": 0.0,
            "n_used_links": 0,
        }
    total = sum(used.values())
    max_val = max(used.values())
    mean_val = total / n_used
    imbalance = (max_val - mean_val) / max_val if max_val > 0 else 0.0
    return {
        "link_total_busy_time": round(total, 4),
        "link_max_busy_time": round(max_val, 4),
        "link_mean_busy_time": round(mean_val, 4),
        "link_load_imbalance": round(imbalance, 6),
        "n_used_links": n_used,
    }


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


def run_case(dag: DAGGraph, noc: MeshNoC) -> tuple[dict, dict]:
    states: dict = {}
    states["heft"] = HEFTScheduler(noc).schedule(dag)
    states["cdls"] = ClassicalDuplicationScheduler(noc).schedule(dag)
    states["cad"] = ProposedScheduler(noc).schedule(dag)
    replayed: dict = {k: replay_under_contention(dag, v, noc) for k, v in states.items()}
    return states, replayed


def extract_rows(
    dag: DAGGraph,
    states: dict,
    replayed: dict,
    dag_name: str,
    ccr: float,
    alpha: float,
    seed: int,
) -> list[dict]:
    cfg = DAG_CONFIGS[dag_name]
    heft_native = states["heft"].max_processor_finish_time()
    heft_replay = replayed["heft"].max_processor_finish_time()

    rows = []
    for key in SCHEDULER_KEYS:
        st = states[key]
        rp = replayed[key]
        native_ms = st.max_processor_finish_time()
        replay_ms = rp.max_processor_finish_time()
        dup_count = count_duplicate_tasks(st)
        tir = task_instance_ratio(st)

        # Replayed speedup vs HEFT
        replayed_speedup = (heft_replay / replay_ms) if replay_ms > 0 else 1.0
        native_speedup = (heft_native / native_ms) if native_ms > 0 else 1.0
        replay_overhead = (replay_ms / native_ms) if native_ms > 0 else 1.0

        # Contention penalty
        contention_penalty = replay_ms - native_ms
        norm_contention = (contention_penalty / native_ms) if native_ms > 0 else 0.0

        # Duplication efficiency = (replayed_speedup - 1) / (TIR - 1) when TIR > 1
        if tir > 1.0:
            dup_efficiency = (replayed_speedup - 1.0) / (tir - 1.0)
        else:
            dup_efficiency = float("nan")

        # Makespan reduction per duplicate
        if dup_count > 0:
            ms_reduction_per_dup = (heft_replay - replay_ms) / dup_count
        else:
            ms_reduction_per_dup = float("nan")

        link_metrics = compute_link_metrics(rp)

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
            "native_speedup_vs_heft": round(native_speedup, 6),
            "replayed_speedup_vs_heft": round(replayed_speedup, 6),
            "replay_overhead_ratio": round(replay_overhead, 6),
            "contention_penalty": round(contention_penalty, 4),
            "normalized_contention_penalty": round(norm_contention, 6),
            "duplicate_count": dup_count,
            "task_instance_ratio": round(tir, 6),
            "duplication_efficiency": round(dup_efficiency, 6) if dup_efficiency == dup_efficiency else "",
            "makespan_reduction_per_dup": round(ms_reduction_per_dup, 4) if ms_reduction_per_dup == ms_reduction_per_dup else "",
            "comm_count": count_communication_instances(st),
            "total_comm_time": round(total_communication_time(st), 4),
            **link_metrics,
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
# Part D: Main multi-seed grid
# ---------------------------------------------------------------------------

def run_main_grid() -> list[dict]:
    print(f"\n[Part D — Main grid] alpha={MAIN_ALPHA}, {len(MAIN_SEEDS)} seeds", flush=True)
    noc = MeshNoC(rows=NOC_ROWS, cols=NOC_COLS, alpha=MAIN_ALPHA, beta=BETA)
    all_rows: list[dict] = []
    total = len(DAG_CONFIGS) * len(MAIN_CCR) * len(MAIN_SEEDS)
    done = 0

    for dag_name in DAG_CONFIGS:
        for ccr in MAIN_CCR:
            for seed in MAIN_SEEDS:
                dag = build_dag(dag_name, ccr, seed)
                states, replayed = run_case(dag, noc)
                rows = extract_rows(dag, states, replayed, dag_name, ccr, MAIN_ALPHA, seed)
                all_rows.extend(rows)
                done += 1
                if done % 40 == 0 or done == total:
                    print(f"  {done}/{total} cases", flush=True)

    return all_rows


# ---------------------------------------------------------------------------
# Part E: Alpha sensitivity
# ---------------------------------------------------------------------------

def run_sensitivity_grid() -> list[dict]:
    print(f"\n[Part E — Alpha sensitivity] dags={SENS_DAGS}, alpha={SENS_ALPHA}", flush=True)
    all_rows: list[dict] = []
    total = len(SENS_DAGS) * len(SENS_CCR) * len(SENS_ALPHA) * len(SENS_SEEDS)
    done = 0

    for alpha in SENS_ALPHA:
        noc = MeshNoC(rows=NOC_ROWS, cols=NOC_COLS, alpha=alpha, beta=BETA)
        for dag_name in SENS_DAGS:
            for ccr in SENS_CCR:
                for seed in SENS_SEEDS:
                    dag = build_dag(dag_name, ccr, seed)
                    states, replayed = run_case(dag, noc)
                    rows = extract_rows(dag, states, replayed, dag_name, ccr, alpha, seed)
                    all_rows.extend(rows)
                    done += 1
                    if done % 20 == 0 or done == total:
                        print(f"  {done}/{total} cases", flush=True)

    return all_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    t0 = time.time()
    main_rows = run_main_grid()
    sens_rows = run_sensitivity_grid()
    elapsed = time.time() - t0

    out = ROOT / "results" / "summary"
    print("\n[Saving CSVs]", flush=True)
    save_csv(main_rows, out / "phase19_multiseed_main.csv")
    save_csv(sens_rows, out / "phase19_alpha_sensitivity.csv")

    print(f"\n[Done] {elapsed:.1f}s | main={len(main_rows)} rows | sens={len(sens_rows)} rows", flush=True)


if __name__ == "__main__":
    main()
