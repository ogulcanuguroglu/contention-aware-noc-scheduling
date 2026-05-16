"""
Batch experiment execution engine.

Iterates over all combinations of scheduler, DAG configuration, and random seed.
Collects metrics and saves results as CSV to results/raw/.
Implemented in Phase 9.

Expected config structure (YAML / dict):

    experiment:
      name: <string>          # used as CSV filename stem
      seeds: [42, 123, ...]
      raw_dir: results/raw

    schedulers:
      - heft
      - contention_aware
      - classical_duplication
      - proposed

    dag:
      task_counts: [20, 50, 100]
      edge_probabilities: [0.15, 0.30]
      ccr_values: [0.1, 1.0, 5.0]
      computation_min: 10
      computation_max: 100

    noc:
      sizes: [4, 8]       # square meshes; size S → rows=S, cols=S
      alpha: 1.0
      beta: 0.1

Scheduler name mapping:
    "heft"                 → HEFTScheduler
    "contention_aware"     → ContentionAwareScheduler
    "classical_duplication"→ ClassicalDuplicationScheduler
    "proposed"             → ProposedScheduler
"""

import itertools
import time
from pathlib import Path

import pandas as pd
import yaml

from src.classical_dup_scheduler import ClassicalDuplicationScheduler
from src.contention_replay import replay_under_contention
from src.contention_scheduler import ContentionAwareScheduler
from src.dag_generator import compute_ccr, generate_dag
from src.heft_scheduler import HEFTScheduler
from src.metrics import max_link_utilization, schedule_summary, speedup
from src.models import DAGGraph
from src.noc import MeshNoC
from src.proposed_scheduler import ProposedScheduler

# Workload-defining columns used to match HEFT baseline rows to other scheduler
# rows when computing HEFT-relative metrics.  Scheduler name, raw timing, and
# computed schedule metrics are intentionally excluded from this key.
_GROUPBY_COLS: list[str] = [
    "n_tasks",
    "edge_prob",
    "ccr",
    "comp_min",
    "comp_max",
    "noc_rows",
    "noc_cols",
    "processor_count",
    "alpha",
    "beta",
    "seed",
    "achieved_ccr",
]

_SCHEDULER_MAP: dict[str, type] = {
    "heft": HEFTScheduler,
    "contention_aware": ContentionAwareScheduler,
    "classical_duplication": ClassicalDuplicationScheduler,
    "proposed": ProposedScheduler,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_scheduler(name: str, noc: MeshNoC):
    """
    Return a scheduler instance for the given name and NoC.

    Supported names: "heft", "contention_aware", "classical_duplication",
    "proposed".

    Raises ValueError for unknown scheduler names or invalid noc.
    """
    if not isinstance(noc, MeshNoC):
        raise ValueError(
            f"noc must be a MeshNoC instance, got {type(noc).__name__}"
        )
    if name not in _SCHEDULER_MAP:
        raise ValueError(
            f"Unknown scheduler '{name}'. Valid choices: {sorted(_SCHEDULER_MAP)}"
        )
    return _SCHEDULER_MAP[name](noc)


def add_relative_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add HEFT-relative metrics to an experiment result DataFrame.

    For each workload configuration and seed (grouped by _GROUPBY_COLS), the
    row where scheduler == "heft" is used as the baseline makespan.

    Adds three columns:
        baseline_makespan_heft      — HEFT makespan for the same workload/seed
        speedup_vs_heft             — baseline_makespan_heft / row.makespan
        normalized_makespan_vs_heft — row.makespan / baseline_makespan_heft

    Special cases:
        If both HEFT and row makespan are 0: speedup=1.0, normalized=1.0.
        If HEFT makespan is 0 and row makespan > 0: raises ValueError.

    Raises ValueError if:
        - No "heft" row exists anywhere in the DataFrame.
        - Any workload group has no HEFT row.
        - Any workload group has more than one HEFT row.
        - HEFT baseline is 0 but the row makespan is positive.
    """
    if "heft" not in df["scheduler"].values:
        raise ValueError(
            "No 'heft' rows found in DataFrame: cannot compute HEFT-relative metrics."
        )

    # Build a map from workload group key → HEFT baseline makespan.
    baseline_map: dict[tuple, float] = {}
    for group_key, group in df.groupby(_GROUPBY_COLS, sort=False):
        heft_rows = group[group["scheduler"] == "heft"]
        if len(heft_rows) == 0:
            raise ValueError(
                f"No HEFT baseline row found for workload group: {group_key}"
            )
        if len(heft_rows) > 1:
            raise ValueError(
                f"Multiple HEFT baseline rows ({len(heft_rows)}) found "
                f"for workload group: {group_key}"
            )
        key = group_key if isinstance(group_key, tuple) else (group_key,)
        baseline_map[key] = float(heft_rows.iloc[0]["makespan"])

    df = df.copy()
    baseline_col: list[float] = []
    speedup_col: list[float] = []
    norm_col: list[float] = []

    for _, row in df.iterrows():
        key = tuple(row[col] for col in _GROUPBY_COLS)
        baseline = baseline_map[key]
        row_makespan = float(row["makespan"])

        if baseline == 0.0 and row_makespan > 0.0:
            raise ValueError(
                f"baseline_makespan_heft is 0.0 but row makespan is "
                f"{row_makespan}: normalized_makespan_vs_heft is undefined"
            )
        if baseline == 0.0:
            # Both zero: ratio is 1 by convention.
            spd = 1.0
            norm = 1.0
        else:
            norm = row_makespan / baseline
            spd = speedup(baseline, row_makespan)

        baseline_col.append(baseline)
        speedup_col.append(spd)
        norm_col.append(norm)

    df["baseline_makespan_heft"] = baseline_col
    df["speedup_vs_heft"] = speedup_col
    df["normalized_makespan_vs_heft"] = norm_col
    return df


def add_replay_relative_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add HEFT-replayed-makespan-relative metrics to an experiment result DataFrame.

    For each workload configuration and seed (grouped by _GROUPBY_COLS), the
    row where scheduler == "heft" is used as the fair replay baseline makespan.

    Adds one column:
        replayed_speedup_vs_heft  — heft_replayed_makespan / row.replayed_makespan

    Special cases:
        Both HEFT and row replayed_makespan are 0: speedup = 1.0.
        HEFT replayed_makespan is 0 but row > 0: raises ValueError.

    Requires column "replayed_makespan" to be present in df.
    Raises ValueError if any workload group is missing a HEFT row or has > 1.
    """
    if "heft" not in df["scheduler"].values:
        raise ValueError(
            "No 'heft' rows found in DataFrame: cannot compute replay-relative metrics."
        )

    baseline_map: dict[tuple, float] = {}
    for group_key, group in df.groupby(_GROUPBY_COLS, sort=False):
        heft_rows = group[group["scheduler"] == "heft"]
        if len(heft_rows) == 0:
            raise ValueError(
                f"No HEFT baseline row found for workload group: {group_key}"
            )
        if len(heft_rows) > 1:
            raise ValueError(
                f"Multiple HEFT baseline rows ({len(heft_rows)}) found "
                f"for workload group: {group_key}"
            )
        key = group_key if isinstance(group_key, tuple) else (group_key,)
        baseline_map[key] = float(heft_rows.iloc[0]["replayed_makespan"])

    df = df.copy()
    speedup_col: list[float] = []

    for _, row in df.iterrows():
        key = tuple(row[col] for col in _GROUPBY_COLS)
        baseline = baseline_map[key]
        row_ms = float(row["replayed_makespan"])

        if baseline == 0.0 and row_ms > 0.0:
            raise ValueError(
                f"HEFT replayed_makespan is 0.0 but row replayed_makespan is "
                f"{row_ms}: replayed_speedup_vs_heft is undefined"
            )
        if baseline == 0.0:
            spd = 1.0
        else:
            spd = speedup(baseline, row_ms)

        speedup_col.append(spd)

    df["replayed_speedup_vs_heft"] = speedup_col
    return df


def run_single_experiment(
    scheduler_name: str,
    n_tasks: int,
    edge_prob: float,
    ccr: float,
    comp_range: tuple[int | float, int | float],
    noc_rows: int,
    noc_cols: int,
    alpha: float,
    beta: float,
    seed: int,
) -> dict:
    """
    Run one scheduler on one generated DAG and return a flat result dict.

    Steps:
      1. Generate DAG with generate_dag().
      2. Wrap with DAGGraph.
      3. Create MeshNoC.
      4. Build the scheduler.
      5. Time scheduler.schedule(dag) with time.perf_counter().
      6. Validate state.validate_no_overlaps().
      7. Compute metrics via schedule_summary().
      8. Return combined parameter + metric dict.

    Returned keys include all experiment parameters and all schedule_summary
    keys plus: achieved_ccr, runtime_ms, processor_count, comp_min, comp_max,
    total_computation_work, serial_speedup.

    total_computation_work is the sum of all node computation costs.
    serial_speedup = total_computation_work / makespan (sequential / parallel).
    """
    g = generate_dag(
        n_tasks=n_tasks,
        edge_prob=edge_prob,
        ccr=ccr,
        comp_range=comp_range,
        seed=seed,
    )
    dag = DAGGraph(g)
    noc = MeshNoC(rows=noc_rows, cols=noc_cols, alpha=alpha, beta=beta)
    scheduler = build_scheduler(scheduler_name, noc)

    total_computation_work = sum(
        data["computation_cost"] for _, data in g.nodes(data=True)
    )

    t_start = time.perf_counter()
    state = scheduler.schedule(dag)
    t_end = time.perf_counter()
    runtime_ms = (t_end - t_start) * 1000.0

    state.validate_no_overlaps()

    summary = schedule_summary(state)
    achieved = compute_ccr(g)
    serial_spd = speedup(total_computation_work, summary["makespan"])

    replayed_state = replay_under_contention(dag, state, noc)
    replayed_ms = float(replayed_state.max_processor_finish_time())
    original_ms = float(summary["makespan"])
    replay_comm_count = len(replayed_state.communication_instances)
    replay_max_lu = max_link_utilization(replayed_state, replayed_ms)
    replay_overhead = replayed_ms / original_ms if original_ms > 0.0 else 1.0
    replay_delta = replayed_ms - original_ms

    return {
        "scheduler": scheduler_name,
        "n_tasks": n_tasks,
        "edge_prob": edge_prob,
        "ccr": ccr,
        "comp_min": comp_range[0],
        "comp_max": comp_range[1],
        "noc_rows": noc_rows,
        "noc_cols": noc_cols,
        "processor_count": noc_rows * noc_cols,
        "alpha": alpha,
        "beta": beta,
        "seed": seed,
        "achieved_ccr": achieved,
        "runtime_ms": runtime_ms,
        "total_computation_work": total_computation_work,
        "serial_speedup": serial_spd,
        **summary,
        "replayed_makespan": replayed_ms,
        "replayed_communication_count": replay_comm_count,
        "replayed_max_link_utilization": replay_max_lu,
        "replay_overhead_ratio": replay_overhead,
        "replayed_vs_original_delta": replay_delta,
    }


def run_experiment_grid(config: dict) -> pd.DataFrame:
    """
    Run all scheduler × DAG × seed combinations defined in config.

    Iteration order: scheduler → n_tasks → edge_prob → ccr → noc_size → seed
    (via itertools.product for full Cartesian product).

    After all runs complete, add_relative_metrics() is called to append
    HEFT-relative columns, then add_replay_relative_metrics() appends
    replayed_speedup_vs_heft.  config["schedulers"] must include "heft".

    Returns a pandas DataFrame where each row is one experimental run.
    """
    seeds = config["experiment"]["seeds"]
    task_counts = config["dag"]["task_counts"]
    edge_probabilities = config["dag"]["edge_probabilities"]
    ccr_values = config["dag"]["ccr_values"]
    comp_min = config["dag"]["computation_min"]
    comp_max = config["dag"]["computation_max"]
    noc_sizes = config["noc"]["sizes"]
    alpha = config["noc"]["alpha"]
    beta = config["noc"]["beta"]
    scheduler_names = config["schedulers"]

    comp_range = (comp_min, comp_max)
    rows = []

    for sched, n_tasks, edge_prob, ccr, noc_size, seed in itertools.product(
        scheduler_names,
        task_counts,
        edge_probabilities,
        ccr_values,
        noc_sizes,
        seeds,
    ):
        row = run_single_experiment(
            scheduler_name=sched,
            n_tasks=n_tasks,
            edge_prob=edge_prob,
            ccr=ccr,
            comp_range=comp_range,
            noc_rows=noc_size,
            noc_cols=noc_size,
            alpha=alpha,
            beta=beta,
            seed=seed,
        )
        rows.append(row)

    df = add_relative_metrics(pd.DataFrame(rows))
    df = add_replay_relative_metrics(df)
    return df


def save_results(df: pd.DataFrame, output_path: str) -> None:
    """
    Write df to a CSV file at output_path.

    Creates parent directories if they do not exist.
    Overwrites any existing file at output_path.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)


def load_config(config_path: str) -> dict:
    """
    Parse a YAML config file and return the resulting dict.

    Raises FileNotFoundError if the file does not exist.
    """
    p = Path(config_path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(p) as f:
        return yaml.safe_load(f)


def run_from_config(config_path: str) -> pd.DataFrame:
    """
    Load config, run the full experiment grid, save CSV, and return DataFrame.

    Output path: {config["experiment"]["raw_dir"]}/{config["experiment"]["name"]}.csv
    """
    config = load_config(config_path)
    df = run_experiment_grid(config)
    raw_dir = config["experiment"]["raw_dir"]
    name = config["experiment"]["name"]
    output_path = str(Path(raw_dir) / f"{name}.csv")
    save_results(df, output_path)
    return df
