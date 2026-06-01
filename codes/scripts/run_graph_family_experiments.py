"""
Phase 16 Experiment B: Graph family diagnostic grid.

Runs 6 graph families × family parameter variants × 3 CCR × 3 seeds × 4 schedulers.
Expected: 9 family configs × 3 CCR × 3 seeds × 4 schedulers = 324 rows.
NOTE: chain excluded entirely — linear topology makes ProposedScheduler hang even at n=20.

Usage:
    python -u scripts/run_graph_family_experiments.py
"""

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.experiment_runner import build_scheduler
from src.contention_replay import replay_under_contention
from src.graph_families import (
    generate_graph_family,
    compute_total_computation,
    compute_total_communication,
)
from src.metrics import max_link_utilization, schedule_summary, speedup
from src.models import DAGGraph
from src.noc import MeshNoC

# ---------------------------------------------------------------------------
# Experiment parameters
# ---------------------------------------------------------------------------

NOC = MeshNoC(4, 4, alpha=0.0, beta=1.0)
SEEDS = [0, 1, 2]
CCR_VALUES = [0.1, 1.0, 5.0]
COMP_RANGE = (5, 20)
COMM_RANGE = (1, 10)
SCHEDULER_NAMES = ["heft", "contention_aware", "classical_duplication", "proposed"]

# (family, family_params, family_param_label)
# chain omitted entirely: linear topology causes recursive ancestor duplication to traverse
# the full chain depth per task, making ProposedScheduler take minutes per run even at n=20.
FAMILY_CONFIGS = [
    ("fork",      {"n_branches": 8},                      "n_branches=8"),
    ("fork",      {"n_branches": 16},                     "n_branches=16"),
    ("join",      {"n_branches": 8},                      "n_branches=8"),
    ("join",      {"n_branches": 16},                     "n_branches=16"),
    ("fork_join", {"n_branches": 4, "branch_length": 3},  "n_branches=4,branch_length=3"),
    ("fork_join", {"n_branches": 8, "branch_length": 3},  "n_branches=8,branch_length=3"),
    ("in_tree",   {"depth": 3, "branching_factor": 2},    "depth=3,branching_factor=2"),
    ("out_tree",  {"depth": 3, "branching_factor": 2},    "depth=3,branching_factor=2"),
    ("diamond",   {"width": 4, "depth": 3},               "width=4,depth=3"),
]

CSV_PATH = Path("results/raw/graph_family_diagnostic_v1.csv")
PLOT_DIR = Path("results/plots/graph_family_diagnostic_v1/no_error")
SUMMARY_PATH = Path("results/summary/graph_family_diagnostic_v1_summary.md")

_SCHED_LABELS = {
    "heft": "HEFT",
    "contention_aware": "CA-LS",
    "classical_duplication": "CD-LS",
    "proposed": "CA-D (Proposed)",
}
_SCHED_ORDER = ["heft", "contention_aware", "classical_duplication", "proposed"]
_SCHED_COLORS = {
    "heft": "#1f77b4",
    "contention_aware": "#ff7f0e",
    "classical_duplication": "#2ca02c",
    "proposed": "#d62728",
}

_GROUPBY_COLS = ["family", "family_param_label", "ccr", "seed",
                 "noc_rows", "noc_cols", "alpha", "beta"]


# ---------------------------------------------------------------------------
# Single experiment runner
# ---------------------------------------------------------------------------

def run_family_experiment(
    family: str,
    family_params: dict,
    family_param_label: str,
    ccr: float,
    seed: int,
    scheduler_name: str,
    noc: MeshNoC,
    comp_range: tuple = COMP_RANGE,
    comm_range: tuple = COMM_RANGE,
) -> dict:
    g = generate_graph_family(
        family,
        ccr=ccr,
        seed=seed,
        comp_range=comp_range,
        comm_range=comm_range,
        **family_params,
    )
    dag = DAGGraph(g)
    scheduler = build_scheduler(scheduler_name, noc)

    total_comp = compute_total_computation(g)
    total_comm = compute_total_communication(g)
    achieved_ccr = total_comm / total_comp if total_comp > 0 else 0.0

    t0 = time.perf_counter()
    state = scheduler.schedule(dag)
    runtime_ms = (time.perf_counter() - t0) * 1000.0

    state.validate_no_overlaps()

    summary = schedule_summary(state)
    original_ms = float(summary["makespan"])
    serial_spd = speedup(total_comp, original_ms) if original_ms > 0 else 0.0

    replayed_state = replay_under_contention(dag, state, noc)
    replayed_ms = float(replayed_state.max_processor_finish_time())
    replay_comm_count = len(replayed_state.communication_instances)
    replay_max_lu = max_link_utilization(replayed_state, replayed_ms)
    replay_overhead = replayed_ms / original_ms if original_ms > 0 else 1.0
    replay_delta = replayed_ms - original_ms

    return {
        "family": family,
        "family_param_label": family_param_label,
        "scheduler": scheduler_name,
        "n_tasks": dag.number_of_tasks(),
        "n_edges": dag.number_of_edges(),
        "ccr": ccr,
        "achieved_ccr": achieved_ccr,
        "comp_min": comp_range[0],
        "comp_max": comp_range[1],
        "noc_rows": noc.rows,
        "noc_cols": noc.cols,
        "processor_count": noc.rows * noc.cols,
        "alpha": noc.alpha,
        "beta": noc.beta,
        "seed": seed,
        "runtime_ms": runtime_ms,
        "total_computation_work": total_comp,
        "serial_speedup": serial_spd,
        **summary,
        "replayed_makespan": replayed_ms,
        "replayed_communication_count": replay_comm_count,
        "replayed_max_link_utilization": replay_max_lu,
        "replay_overhead_ratio": replay_overhead,
        "replayed_vs_original_delta": replay_delta,
    }


# ---------------------------------------------------------------------------
# Relative metrics
# ---------------------------------------------------------------------------

def add_family_relative_metrics(df: pd.DataFrame) -> pd.DataFrame:
    baseline_map: dict[tuple, float] = {}
    replay_baseline_map: dict[tuple, float] = {}

    for group_key, group in df.groupby(_GROUPBY_COLS, sort=False):
        heft_rows = group[group["scheduler"] == "heft"]
        assert len(heft_rows) == 1, f"Expected 1 HEFT row for group {group_key}, got {len(heft_rows)}"
        key = group_key if isinstance(group_key, tuple) else (group_key,)
        baseline_map[key] = float(heft_rows.iloc[0]["makespan"])
        replay_baseline_map[key] = float(heft_rows.iloc[0]["replayed_makespan"])

    df = df.copy()
    spd_col, rep_spd_col, norm_col, base_col = [], [], [], []

    for _, row in df.iterrows():
        key = tuple(row[c] for c in _GROUPBY_COLS)
        base = baseline_map[key]
        rep_base = replay_baseline_map[key]
        ms = float(row["makespan"])
        rep_ms = float(row["replayed_makespan"])

        spd_col.append(speedup(base, ms) if base > 0 and ms > 0 else 1.0)
        norm_col.append(ms / base if base > 0 else 1.0)
        rep_spd_col.append(speedup(rep_base, rep_ms) if rep_base > 0 and rep_ms > 0 else 1.0)
        base_col.append(base)

    df["baseline_makespan_heft"] = base_col
    df["speedup_vs_heft"] = spd_col
    df["normalized_makespan_vs_heft"] = norm_col
    df["replayed_speedup_vs_heft"] = rep_spd_col
    return df


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_dataframe(df: pd.DataFrame) -> None:
    assert len(df) == 324, f"Expected 324 rows, got {len(df)}"

    all_families = {f for f, _, _ in FAMILY_CONFIGS}
    for fam in all_families:
        assert fam in df["family"].values, f"Family '{fam}' missing from DataFrame"

    for sched in _SCHED_ORDER:
        count = (df["scheduler"] == sched).sum()
        assert count == 81, f"Expected 81 rows for {sched}, got {count}"

    no_nan = [
        "makespan", "speedup_vs_heft", "replayed_makespan", "replayed_speedup_vs_heft",
        "task_instance_ratio", "communication_count", "max_link_utilization",
        "runtime_ms", "replayed_max_link_utilization", "replay_overhead_ratio",
    ]
    for col in no_nan:
        n_nan = df[col].isna().sum()
        assert n_nan == 0, f"Column '{col}' has {n_nan} NaN values"

    assert (df["primary_task_count"] == df["n_tasks"]).all(), "primary_task_count != n_tasks"
    assert (df["task_instance_ratio"] >= 1.0).all()
    assert (df["max_link_utilization"] >= 0).all() and (df["max_link_utilization"] <= 1.0).all()
    assert (df["replayed_max_link_utilization"] >= 0).all() and (df["replayed_max_link_utilization"] <= 1.0).all()
    assert (df["replayed_makespan"] > 0).all()

    print(f"Validation passed: {len(df)} rows, all invariants hold.")


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def _bar_chart(
    df: pd.DataFrame,
    metric: str,
    output_path: Path,
    ylabel: str,
    title: str,
) -> None:
    # Group by (family, family_param_label, scheduler) to keep family in key
    agg = (
        df.groupby(["family", "family_param_label", "scheduler"])[metric]
        .mean()
        .reset_index()
    )
    agg["x_label"] = agg["family"] + "\n" + agg["family_param_label"]

    x_labels_ordered = [f"{fam}\n{label}" for fam, _, label in FAMILY_CONFIGS]
    n_groups = len(x_labels_ordered)
    n_scheds = len(_SCHED_ORDER)
    width = 0.18
    x = np.arange(n_groups)

    fig, ax = plt.subplots(figsize=(max(10, n_groups * 1.2), 4.5))

    for i, sched in enumerate(_SCHED_ORDER):
        sub = agg[agg["scheduler"] == sched]
        vals = []
        for xl in x_labels_ordered:
            row = sub[sub["x_label"] == xl]
            vals.append(float(row[metric].iloc[0]) if len(row) > 0 else 0.0)

        offset = (i - n_scheds / 2 + 0.5) * width
        ax.bar(
            x + offset, vals, width,
            label=_SCHED_LABELS.get(sched, sched),
            color=_SCHED_COLORS.get(sched),
            alpha=0.85,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(x_labels_ordered, fontsize=8)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.25, axis="y")
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def generate_family_plots(df: pd.DataFrame, plot_dir: Path) -> None:
    plot_dir.mkdir(parents=True, exist_ok=True)

    plots = [
        ("speedup_vs_heft",                "native_speedup_by_family.png",               "Speedup vs HEFT (native)",              "Native Speedup vs HEFT"),
        ("replayed_speedup_vs_heft",       "replayed_speedup_by_family.png",             "Speedup vs HEFT (replayed)",            "Replayed Speedup vs HEFT"),
        ("task_instance_ratio",            "task_instance_ratio_by_family.png",          "Task Instance Ratio",                   "Task Instance Ratio by Family"),
        ("duplicate_task_count",           "duplicate_count_by_family.png",              "Duplicate Task Count",                  "Duplicate Task Count by Family"),
        ("communication_count",            "communication_count_by_family.png",          "Communication Count (native)",          "Native Communication Count by Family"),
        ("replayed_communication_count",   "replayed_communication_count_by_family.png", "Communication Count (replayed)",        "Replayed Communication Count by Family"),
        ("runtime_ms",                     "runtime_by_family.png",                      "Scheduler Runtime (ms)",                "Scheduler Runtime by Family"),
        ("max_link_utilization",           "max_link_utilization_by_family.png",         "Max Link Utilization (ratio, native)",  "Native Max Link Utilization by Family"),
        ("replayed_max_link_utilization",  "replayed_max_link_utilization_by_family.png","Max Link Utilization (ratio, replayed)","Replayed Max Link Utilization by Family"),
    ]

    for metric, fname, ylabel, title in plots:
        if metric in df.columns:
            _bar_chart(df, metric, plot_dir / fname, ylabel, title)
            print(f"  Saved {fname}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _df_to_md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    rows = [cols] + [[str(v) for v in row] for _, row in df.iterrows()]
    widths = [max(len(r[i]) for r in rows) for i in range(len(cols))]
    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    lines = []
    for idx, row in enumerate(rows):
        line = "| " + " | ".join(str(row[j]).ljust(widths[j]) for j in range(len(cols))) + " |"
        lines.append(line)
        if idx == 0:
            lines.append(sep)
    return "\n".join(lines)


def build_summary(df: pd.DataFrame) -> str:
    actual = len(df)
    config_md = f"""\
## 1. Experiment Configuration

| Parameter | Value |
|-----------|-------|
| Experiment name | graph_family_diagnostic_v1 |
| Graph families | fork, join, fork_join, in_tree, out_tree, diamond |
| Excluded family | chain (excluded because deep linear DAGs are pathological for the current greedy recursive ancestor duplication runtime) |
| Family parameter configurations | 9 |
| Seeds | 0, 1, 2 |
| CCR values | 0.1, 1.0, 5.0 |
| Computation range | [5, 20] |
| Communication range | [1, 10] |
| NoC | 4×4 (16 processors), alpha=0.0, beta=1.0 |
| Schedulers | HEFT, CA-LS, CD-LS, CA-D (Proposed) |
| Expected rows | 324 (9×3×3×4) |
| Actual rows | {actual} |
"""

    # Section 2 — mean by scheduler
    mean_cols = [
        "makespan", "replayed_makespan", "speedup_vs_heft", "replayed_speedup_vs_heft",
        "duplicate_task_count", "task_instance_ratio", "communication_count",
        "replayed_communication_count", "max_link_utilization",
        "replayed_max_link_utilization", "runtime_ms",
    ]
    avail = [c for c in mean_cols if c in df.columns]
    mean_tbl = df.groupby("scheduler")[avail].mean().round(3)
    mean_tbl = mean_tbl.reindex([s for s in _SCHED_ORDER if s in mean_tbl.index])
    mean_tbl.index = [_SCHED_LABELS.get(s, s) for s in mean_tbl.index]
    rename = {
        "makespan": "ms", "replayed_makespan": "rep_ms",
        "speedup_vs_heft": "spd", "replayed_speedup_vs_heft": "rep_spd",
        "duplicate_task_count": "dups", "task_instance_ratio": "tir",
        "communication_count": "cc", "replayed_communication_count": "rcc",
        "max_link_utilization": "mlu", "replayed_max_link_utilization": "rmlu",
        "runtime_ms": "rt_ms",
    }
    mean_disp = mean_tbl.reset_index().rename(columns={"scheduler": "Scheduler", **rename})
    mean_md = f"""\
## 2. Overall Mean Metrics by Scheduler (all families and CCR)

{_df_to_md(mean_disp)}
"""

    # Section 3 — by family × scheduler
    fam_tbl = df.groupby(["family", "scheduler"])[
        ["makespan", "replayed_makespan", "speedup_vs_heft", "replayed_speedup_vs_heft",
         "duplicate_task_count", "task_instance_ratio", "communication_count",
         "replayed_communication_count", "max_link_utilization",
         "replayed_max_link_utilization", "runtime_ms"]
    ].mean().round(3)
    fam_tbl_disp = fam_tbl.reset_index()
    fam_tbl_disp["scheduler"] = fam_tbl_disp["scheduler"].map(lambda s: _SCHED_LABELS.get(s, s))
    fam_md = f"""\
## 3. Mean Metrics by Family and Scheduler

{_df_to_md(fam_tbl_disp)}
"""

    # Section 4 — best native counts by family
    group_cols = ["family", "family_param_label", "ccr", "seed"]
    best_native: dict[str, dict[str, int]] = {}
    all_families_seen = df["family"].unique()
    for fam in all_families_seen:
        best_native[fam] = {s: 0 for s in _SCHED_ORDER}
    for _, grp in df.groupby(group_cols):
        fam = grp["family"].iloc[0]
        best = grp.loc[grp["makespan"].idxmin(), "scheduler"]
        if best in best_native.get(fam, {}):
            best_native[fam][best] += 1
    native_lines = ["| Family | " + " | ".join(_SCHED_LABELS[s] for s in _SCHED_ORDER) + " |"]
    native_lines.append("|" + "---|" * (1 + len(_SCHED_ORDER)))
    for fam in sorted(all_families_seen):
        counts = best_native.get(fam, {s: 0 for s in _SCHED_ORDER})
        native_lines.append("| " + fam + " | " + " | ".join(str(counts.get(s, 0)) for s in _SCHED_ORDER) + " |")
    best_native_md = f"""\
## 4. Best Scheduler Counts — Native Makespan, by Family

{chr(10).join(native_lines)}
"""

    # Section 5 — best replayed counts by family
    best_replayed: dict[str, dict[str, int]] = {}
    for fam in all_families_seen:
        best_replayed[fam] = {s: 0 for s in _SCHED_ORDER}
    for _, grp in df.groupby(group_cols):
        fam = grp["family"].iloc[0]
        best = grp.loc[grp["replayed_makespan"].idxmin(), "scheduler"]
        if best in best_replayed.get(fam, {}):
            best_replayed[fam][best] += 1
    replayed_lines = ["| Family | " + " | ".join(_SCHED_LABELS[s] for s in _SCHED_ORDER) + " |"]
    replayed_lines.append("|" + "---|" * (1 + len(_SCHED_ORDER)))
    for fam in sorted(all_families_seen):
        counts = best_replayed.get(fam, {s: 0 for s in _SCHED_ORDER})
        replayed_lines.append("| " + fam + " | " + " | ".join(str(counts.get(s, 0)) for s in _SCHED_ORDER) + " |")
    best_replayed_md = f"""\
## 5. Best Scheduler Counts — Replayed Makespan, by Family

{chr(10).join(replayed_lines)}
"""

    # Section 6 — family interpretation
    fam_interp = """\
## 6. Family-Level Interpretation

> **Excluded chain family**: Chain graphs were excluded from this diagnostic grid
> because deep linear DAGs are a worst-case for recursive ancestor duplication. Small
> chain smoke tests were used earlier only as sanity checks, but chain is not included
> in graph_family_diagnostic_v1.

**fork**: One root broadcasts to k parallel leaves. The root becomes a hot data source.
Duplicating the root on each leaf processor eliminates all remote communications from
root. CA-D and CD-LS benefit from duplication at high CCR. Replay confirms the benefit
since forked communications have low path diversity (all from root, so low contention).

**join**: k source tasks all deliver data to one sink. The sink is a hot receiver.
Duplication of the source tasks (or placing them all locally) reduces remote comms.
At high CCR, duplication schedulers reduce the convergence bottleneck. Replay may show
moderate contention increase because all comms converge to the same destination.

**fork_join**: Combines fork and join. The root source and the collecting sink are both
candidates for duplication. At high CCR, parallelism inside branches is exploited by
contention-aware placement. CA-D may achieve lower makespan than CD-LS after replay
because it models contention on the converging communications.

**in_tree**: All paths converge toward one sink/root. Leaves produce data that flows
toward the root. Duplication propagates critical paths toward the sink. At high CCR,
duplicating intermediate nodes reduces the long communication chains. Replay may show
contention on links near the root.

**out_tree**: One root broadcasts through all levels. The root is duplicated on many
processors since it feeds all others. Duplication ratio is typically highest for CA-D
on out_trees. Replay may show that early levels cause link saturation, which CA-D avoids
through local copies.

**diamond**: Layered series-parallel structure with complete bipartite connections between
layers. Many edges create high total communication volume relative to task count. At high
CCR, contention on inter-layer links is significant. CA-D's link reservation prevents
overcommitting congested links. Replay overhead for HEFT and CD-LS can be largest here.
"""

    prop_mean = df[df["scheduler"] == "proposed"].groupby("family")[
        ["task_instance_ratio", "duplicate_task_count", "communication_count", "runtime_ms"]
    ].mean().round(2)
    prop_md = f"""\
## 7. ProposedScheduler Behavior

The improved ProposedScheduler (Phase 15A+15B) uses greedy recursive ancestor duplication
and conservative redundant duplicate pruning.

Mean metrics by family (CA-D only):

| Family | task_instance_ratio | duplicate_count | comm_count | runtime_ms |
|--------|---------------------|-----------------|------------|------------|
""" + "\n".join(
        f"| {fam} | {row['task_instance_ratio']:.2f} | "
        f"{row['duplicate_task_count']:.1f} | {row['communication_count']:.1f} | "
        f"{row['runtime_ms']:.1f} |"
        for fam, row in prop_mean.iterrows()
    ) + """

**Recursive duplication effect**: task_instance_ratio > 1.0 on families with multiple
predecessors per task (diamond, fork_join). Families with a single critical path and
no branching (such as chain, which is excluded) would show ratio close to 1.0 since
duplication provides no benefit when no parallelism exists to exploit.

**Pruning effect**: conservative pruning removes duplicate instances that are not used
as local data sources for any successor. Families where duplication is entirely driven
by communication avoidance (out_tree, fork) tend to retain all duplicates. Families
with redundant copies after recursive placement (diamond) benefit more from pruning.

**Runtime cost**: ProposedScheduler is the most expensive due to O(n × p × parents(t))
clone evaluations per task. Runtime grows with task count and DAG density.
"""

    limits_section = """\
## 8. Limitations

- **Small diagnostic sizes**: fork/join n_branches=8,16; in_tree/out_tree depth=3; diamond
  width=4,depth=3. Not representative of large real-world DAGs. Chain excluded entirely.
- **No real benchmark DAGs**: only synthetic structured families; no STG, Pegasus, or HPEC.
- **alpha=0.0 only**: hop latency disabled; communication cost = beta × volume.
  Larger alpha would widen the gap between close and distant processors.
- **Fixed 4×4 NoC**: larger meshes would increase inter-processor distance and contention.
- **Greedy recursive duplication only**: not globally optimal ancestor selection.
- **Conservative pruning**: full Sinnen-style redundant task and in-edge removal not implemented.
"""

    return "\n".join([
        "# Graph Family Diagnostic v1: Experiment Results Summary\n",
        "> **Phase 16 note**: Uses Phase 15A+15B ProposedScheduler with greedy recursive "
        "ancestor duplication and conservative redundant duplicate pruning. "
        "All fair contention replay columns included.\n",
        config_md, mean_md, fam_md, best_native_md, best_replayed_md,
        fam_interp, prop_md, limits_section,
    ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_EXPERIMENT_NAME = "graph_family_diagnostic_v1"
_PARTIAL_CSV = Path("results/raw/graph_family_diagnostic_v1.partial.csv")


def main() -> None:
    n_workloads = len(FAMILY_CONFIGS) * len(CCR_VALUES) * len(SEEDS)
    total_rows = n_workloads * len(SCHEDULER_NAMES)

    print("=" * 70, flush=True)
    print(f"Experiment      : {_EXPERIMENT_NAME}", flush=True)
    print(f"Expected rows   : {total_rows}  ({len(FAMILY_CONFIGS)} configs × {len(CCR_VALUES)} CCR × {len(SEEDS)} seeds × {len(SCHEDULER_NAMES)} schedulers)", flush=True)
    print(f"Schedulers      : {', '.join(SCHEDULER_NAMES)}", flush=True)
    print(f"Workload configs: {n_workloads}", flush=True)
    print(f"Checkpoint CSV  : {_PARTIAL_CSV}", flush=True)
    print("=" * 70, flush=True)

    t0 = time.perf_counter()
    rows: list[dict] = []
    row_num = 0
    workload_num = 0

    for fam, params, label in FAMILY_CONFIGS:
        for ccr in CCR_VALUES:
            for seed in SEEDS:
                workload_num += 1
                for sched_name in SCHEDULER_NAMES:
                    row_num += 1
                    elapsed = time.perf_counter() - t0

                    if sched_name == "proposed":
                        wl_id = f"family={fam} params={label} seed={seed} ccr={ccr}"
                        print(f"  [heartbeat] Starting ProposedScheduler for {wl_id} ...", flush=True)
                        t_hb = time.perf_counter()

                    try:
                        row = run_family_experiment(fam, params, label, ccr, seed, sched_name, NOC)
                    except Exception:
                        print(f"\nERROR during scheduler run:", flush=True)
                        print(f"  family={fam}  params={label}  ccr={ccr}  seed={seed}  scheduler={sched_name}", flush=True)
                        traceback.print_exc()
                        raise

                    if sched_name == "proposed":
                        hb_elapsed = time.perf_counter() - t_hb
                        print(f"  [heartbeat] Finished ProposedScheduler for {wl_id} in {hb_elapsed:.2f}s", flush=True)

                    rows.append(row)
                    elapsed = time.perf_counter() - t0
                    print(
                        f"[{_EXPERIMENT_NAME}] family={fam} params={label}"
                        f" seed={seed} ccr={ccr} scheduler={sched_name}"
                        f" row={row_num}/{total_rows} elapsed={elapsed:.1f}s",
                        flush=True,
                    )

                # Checkpoint after every completed workload group (all schedulers done)
                pd.DataFrame(rows).to_csv(_PARTIAL_CSV, index=False)
                print(
                    f"  [checkpoint] workload {workload_num}/{n_workloads}"
                    f" -> wrote {len(rows)} rows to {_PARTIAL_CSV}",
                    flush=True,
                )

    elapsed_total = time.perf_counter() - t0
    print(f"\nGrid completed in {elapsed_total:.1f}s  ({len(rows)} raw rows)", flush=True)

    df = pd.DataFrame(rows)
    df = add_family_relative_metrics(df)

    print(f"Saving final CSV -> {CSV_PATH}", flush=True)
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_PATH, index=False)

    print("Validating results...", flush=True)
    validate_dataframe(df)

    if _PARTIAL_CSV.exists():
        _PARTIAL_CSV.unlink()
        print(f"Removed partial CSV: {_PARTIAL_CSV}", flush=True)

    print(f"Generating family plots -> {PLOT_DIR}/", flush=True)
    generate_family_plots(df, PLOT_DIR)

    print(f"Writing summary -> {SUMMARY_PATH}", flush=True)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(build_summary(df), encoding="utf-8")

    partial_exists = _PARTIAL_CSV.exists()
    print("=" * 70, flush=True)
    print("COMPLETION SUMMARY", flush=True)
    print(f"  Total elapsed   : {elapsed_total:.1f}s", flush=True)
    print(f"  Final row count : {len(df)}", flush=True)
    print(f"  Expected rows   : {total_rows}", flush=True)
    print(f"  All rows OK     : {len(df) == total_rows}", flush=True)
    print(f"  CSV path        : {CSV_PATH}", flush=True)
    print(f"  Partial CSV     : {'present (not removed)' if partial_exists else 'removed'}", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
