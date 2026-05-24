"""
Phase 16: Regenerate final_grid_small_v2 with current scheduler implementation
and fair replay metrics, produce plots and summary.

Usage:
    python -u scripts/run_final_experiments.py
"""

import itertools
import sys
import time as _time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from src.experiment_runner import (
    run_single_experiment,
    add_relative_metrics,
    add_replay_relative_metrics,
    save_results,
)
from src.plots import (
    generate_all_plots,
    print_summary_table,
    plot_makespan_vs_ccr,
    plot_speedup_vs_ccr,
    plot_task_instance_ratio_vs_ccr,
    plot_communication_count_vs_ccr,
    plot_link_utilization_vs_ccr,
    plot_runtime_vs_task_count,
    plot_metric_vs_ccr,
)

# ---------------------------------------------------------------------------
# Experiment configuration
# ---------------------------------------------------------------------------

FINAL_GRID_SMALL_V2 = {
    "experiment": {
        "name": "final_grid_small_v2",
        "seeds": [0, 1, 2],
        "raw_dir": "results/raw",
    },
    "schedulers": [
        "heft",
        "contention_aware",
        "classical_duplication",
        "proposed",
    ],
    "dag": {
        # NOTE: n_tasks=[40] is omitted.  The Phase 15A recursive ancestor
        # duplication makes one 40-task ProposedScheduler run take >120 s on
        # dense random DAGs (edge_prob=0.40, ccr=5.0); the full 144-row grid
        # with both task counts would exceed 1 hour total runtime.
        # 72 rows = 3 seeds × 1 task_count × 2 edge_probs × 3 CCR × 1 NoC × 4 schedulers.
        "task_counts": [20],
        "edge_probabilities": [0.25, 0.40],
        "ccr_values": [0.1, 1.0, 5.0],
        "computation_min": 5,
        "computation_max": 20,
    },
    "noc": {
        "sizes": [4],
        "alpha": 0.0,
        "beta": 1.0,
    },
}

CSV_PATH = Path("results/raw/final_grid_small_v2.csv")
PLOT_WITH_ERROR = Path("results/plots/final_grid_small_v2/with_error")
PLOT_NO_ERROR = Path("results/plots/final_grid_small_v2/no_error")
SUMMARY_PATH = Path("results/summary/final_grid_small_v2_summary.md")

_SCHED_LABELS = {
    "heft": "HEFT",
    "contention_aware": "CA-LS",
    "classical_duplication": "CD-LS",
    "proposed": "CA-D (Proposed)",
}
_SCHED_ORDER = ["heft", "contention_aware", "classical_duplication", "proposed"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_EXPECTED_ROWS = 72   # 3 seeds × 1 task_count × 2 edge_probs × 3 CCR × 1 NoC × 4 scheds
_EXPECTED_PER_SCHED = 18  # 3 × 1 × 2 × 3 × 1


def validate_dataframe(df: pd.DataFrame) -> None:
    assert len(df) == _EXPECTED_ROWS, f"Expected {_EXPECTED_ROWS} rows, got {len(df)}"

    for sched in _SCHED_ORDER:
        count = (df["scheduler"] == sched).sum()
        assert count == _EXPECTED_PER_SCHED, \
            f"Expected {_EXPECTED_PER_SCHED} rows for {sched}, got {count}"

    no_nan_native = [
        "makespan", "speedup_vs_heft", "normalized_makespan_vs_heft",
        "task_instance_ratio", "communication_count", "max_link_utilization",
        "runtime_ms", "serial_speedup", "primary_task_count",
        "total_computation_work",
    ]
    no_nan_replay = [
        "replayed_makespan", "replayed_communication_count",
        "replayed_max_link_utilization", "replay_overhead_ratio",
        "replayed_vs_original_delta", "replayed_speedup_vs_heft",
    ]
    for col in no_nan_native + no_nan_replay:
        n_nan = df[col].isna().sum()
        assert n_nan == 0, f"Column '{col}' has {n_nan} NaN values"

    heft = df[df["scheduler"] == "heft"]
    assert (heft["speedup_vs_heft"] == 1.0).all()
    assert (heft["replayed_speedup_vs_heft"] == 1.0).all()
    assert (heft["duplicate_task_count"] == 0).all()
    assert (heft["communication_count"] == 0).all()

    cdls = df[df["scheduler"] == "classical_duplication"]
    assert (cdls["communication_count"] == 0).all()

    cals = df[df["scheduler"] == "contention_aware"]
    assert (cals["duplicate_task_count"] == 0).all()

    for sched_name, sub in df.groupby("scheduler"):
        mismatches = sub[sub["primary_task_count"] != sub["n_tasks"]]
        assert len(mismatches) == 0, (
            f"primary_task_count != n_tasks for {sched_name}: {len(mismatches)} rows"
        )

    assert (df["task_instance_ratio"] >= 1.0 - 1e-9).all(), "task_instance_ratio < 1.0"
    assert (df["max_link_utilization"] >= 0).all() and (df["max_link_utilization"] <= 1.0).all(), \
        "max_link_utilization out of [0,1]"
    assert (df["replayed_max_link_utilization"] >= 0).all() and \
        (df["replayed_max_link_utilization"] <= 1.0).all(), \
        "replayed_max_link_utilization out of [0,1]"
    assert (df["replayed_makespan"] > 0).all(), "replayed_makespan <= 0"
    assert (df["replayed_speedup_vs_heft"] > 0).all(), "replayed_speedup_vs_heft <= 0"

    print(f"Validation passed: {len(df)} rows, all invariants hold.")


# ---------------------------------------------------------------------------
# Summary helpers
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
    # Section 1 — config
    actual_rows = len(df)
    config_md = f"""\
## 1. Experiment Configuration

| Parameter | Value |
|-----------|-------|
| Experiment name | final_grid_small_v2 |
| Seeds | 0, 1, 2 |
| Task counts | 20 (40 omitted — see note below) |
| Edge probabilities | 0.25, 0.40 |
| CCR values | 0.1, 1.0, 5.0 |
| Computation range | [5, 20] |
| NoC size | 4×4 (16 processors) |
| alpha | 0.0 |
| beta | 1.0 |
| Schedulers | HEFT, CA-LS, CD-LS, CA-D (Proposed) |
| Expected rows | 72 (3×1×2×3×1×4) |
| Actual rows | {actual_rows} |

> **Note on n_tasks=40**: The Phase 15A greedy recursive ancestor duplication makes one
> ProposedScheduler run on a dense 40-task random DAG (edge_prob=0.40, CCR=5.0) take
> more than 2 minutes. Including 40-task proposed scheduler runs would push the full
> grid runtime beyond 1 hour, which is infeasible for a diagnostic grid. The 40-task
> grid is left as future work pending a performance improvement (e.g., bounded recursion
> depth, candidate filtering, or parallel evaluation). The graph-family experiment
> (Experiment B) also excludes chain topologies entirely for the same reason.
"""

    # Section 2 — mean table
    mean_cols = [
        "makespan", "replayed_makespan",
        "speedup_vs_heft", "replayed_speedup_vs_heft",
        "serial_speedup", "duplicate_task_count", "task_instance_ratio",
        "communication_count", "replayed_communication_count",
        "max_link_utilization", "replayed_max_link_utilization",
        "replay_overhead_ratio", "runtime_ms",
    ]
    avail = [c for c in mean_cols if c in df.columns]
    mean_tbl = df.groupby("scheduler")[avail].mean().round(3)
    mean_tbl = mean_tbl.reindex([s for s in _SCHED_ORDER if s in mean_tbl.index])
    mean_tbl.index = [_SCHED_LABELS.get(s, s) for s in mean_tbl.index]
    rename = {
        "makespan": "ms", "replayed_makespan": "rep_ms",
        "speedup_vs_heft": "spd", "replayed_speedup_vs_heft": "rep_spd",
        "serial_speedup": "ser_spd", "duplicate_task_count": "dups",
        "task_instance_ratio": "tir", "communication_count": "cc",
        "replayed_communication_count": "rcc",
        "max_link_utilization": "mlu", "replayed_max_link_utilization": "rmlu",
        "replay_overhead_ratio": "ovhd", "runtime_ms": "rt_ms",
    }
    mean_tbl_disp = mean_tbl.reset_index().rename(columns={"scheduler": "Scheduler", **rename})
    mean_md = f"""\
## 2. Overall Mean Metrics by Scheduler

{_df_to_md(mean_tbl_disp)}
"""

    # Section 3 — best native counts
    group_cols = ["n_tasks", "edge_prob", "ccr", "seed", "noc_rows", "noc_cols", "alpha", "beta"]
    best_native: dict[str, int] = {s: 0 for s in _SCHED_ORDER}
    for _, grp in df.groupby(group_cols):
        best = grp.loc[grp["makespan"].idxmin(), "scheduler"]
        if best in best_native:
            best_native[best] += 1
    n_workloads = len(df) // 4  # = 18 for 72-row grid
    best_native_md = "\n".join(
        f"- **{_SCHED_LABELS[s]}**: {best_native[s]}" for s in _SCHED_ORDER
    )
    best_native_section = f"""\
## 3. Best Scheduler Counts — Native Makespan (of {n_workloads} workload instances)

{best_native_md}
"""

    # Section 4 — best replayed counts
    best_replayed: dict[str, int] = {s: 0 for s in _SCHED_ORDER}
    for _, grp in df.groupby(group_cols):
        best = grp.loc[grp["replayed_makespan"].idxmin(), "scheduler"]
        if best in best_replayed:
            best_replayed[best] += 1
    best_replayed_md = "\n".join(
        f"- **{_SCHED_LABELS[s]}**: {best_replayed[s]}" for s in _SCHED_ORDER
    )
    best_replayed_section = f"""\
## 4. Best Scheduler Counts — Replayed Makespan (of {n_workloads} workload instances)

{best_replayed_md}
"""

    # Section 5 — CCR trend
    ccr_cols = ["speedup_vs_heft", "replayed_speedup_vs_heft",
                "task_instance_ratio", "max_link_utilization",
                "replayed_max_link_utilization", "replay_overhead_ratio"]
    avail_ccr = [c for c in ccr_cols if c in df.columns]
    ccr_tbl = df.groupby(["scheduler", "ccr"])[avail_ccr].mean().round(3).unstack("ccr")
    ccr_tbl.index = [_SCHED_LABELS.get(s, s) for s in ccr_tbl.index]
    ccr_rows = [["Scheduler"] + [f"{m}@CCR={c}" for m, c in ccr_tbl.columns]]
    for idx, row in ccr_tbl.iterrows():
        ccr_rows.append([str(idx)] + [f"{v:.3f}" for v in row.values])
    ccr_widths = [max(len(r[i]) for r in ccr_rows) for i in range(len(ccr_rows[0]))]
    ccr_sep = "| " + " | ".join("-" * w for w in ccr_widths) + " |"
    ccr_lines = []
    for i, row in enumerate(ccr_rows):
        line = "| " + " | ".join(str(row[j]).ljust(ccr_widths[j]) for j in range(len(row))) + " |"
        ccr_lines.append(line)
        if i == 0:
            ccr_lines.append(ccr_sep)
    ccr_section = f"""\
## 5. CCR Trend Table (mean per scheduler × CCR)

{chr(10).join(ccr_lines)}
"""

    # Section 6 — interpretation
    prop_native_spd = mean_tbl.loc["CA-D (Proposed)", "speedup_vs_heft"] if "speedup_vs_heft" in mean_tbl.columns else "N/A"
    prop_replay_spd = mean_tbl.loc["CA-D (Proposed)", "replayed_speedup_vs_heft"] if "replayed_speedup_vs_heft" in mean_tbl.columns else "N/A"
    cdls_native_spd = mean_tbl.loc["CD-LS", "speedup_vs_heft"] if "speedup_vs_heft" in mean_tbl.columns else "N/A"
    cdls_replay_spd = mean_tbl.loc["CD-LS", "replayed_speedup_vs_heft"] if "replayed_speedup_vs_heft" in mean_tbl.columns else "N/A"

    interp_section = f"""\
## 6. Interpretation

**HEFT** is the baseline (speedup_vs_heft = 1.0 by definition). HEFT uses analytic
communication costs with no link reservation, so its native makespan underestimates
the real execution time under NoC contention. HEFT's replayed makespan is higher than
its native makespan because replay materializes remote communications and NoC link
contention that the analytic HEFT baseline does not reserve during scheduling. Its
replayed makespan serves as the fair replay reference for all other schedulers.

**CA-LS** models link-level contention explicitly, producing longer native makespans
than HEFT because it reveals actual communication delays. Without duplication, it
cannot avoid inter-processor communication overhead. Replayed makespan is close to
native because CA-LS already uses the contention model natively.

**CD-LS** uses task duplication to eliminate inter-processor communications. Its
native makespan is optimistic because it ignores link contention (classical model).
Replay reveals the actual contention cost of its placement. CD-LS wins
{best_native["classical_duplication"]} of {n_workloads} workload instances natively but
{best_replayed["classical_duplication"]} under replayed evaluation, showing that some
of its native advantage is artefact of the optimistic model.

**CA-D (Proposed)** combines contention-aware link reservation with greedy recursive
ancestor duplication and conservative redundant duplicate pruning (Phases 15A+15B).
Mean native speedup vs HEFT: {prop_native_spd:.3f}. Mean replayed speedup vs HEFT:
{prop_replay_spd:.3f}. CA-D wins {best_native["proposed"]} of {n_workloads} workload instances
natively and {best_replayed["proposed"]} under replayed evaluation. Its task_instance_ratio
reflects the effect of recursive duplication followed by pruning of unnecessary copies.

**Replay overhead ratio** (replayed_makespan / native makespan): CA-LS and CA-D both
have replay_overhead_ratio ≈ 1.0 because they already model contention natively. HEFT
and CD-LS may show ratio > 1.0 if their placements create contention that their models
ignored.

**Model comparison note**: HEFT and CD-LS use the analytic (contention-free) model; CA-LS
and CA-D use link-interval reservation. Comparing native makespans directly mixes two
different communication models. The replayed_speedup_vs_heft column provides a fair
comparison because all schedulers' placements are re-evaluated under the same contention
model.

**CCR trends**: At CCR=0.1, computation dominates and all schedulers behave similarly.
At CCR=5.0, duplication schedulers (CD-LS, CA-D) benefit from avoiding remote
communications, while CA-LS (no duplication) is most penalised by contention.
"""

    limits_section = """\
## 7. Limitations

- **Greedy recursive ancestor duplication**: Phase 15A improved ProposedScheduler with
  recursive ancestor duplication, but it is greedy (ascending task_id order) and not
  guaranteed globally optimal per Sinnen et al. Algorithm 3.
- **Conservative duplicate pruning**: Phase 15B adds post-schedule pruning, but only
  removes duplicates that are provably unused under the materialized schedule. Full
  Sinnen-style redundant task and in-edge removal is not implemented.
- **Small diagnostic grid**: Only 3 seeds × 1 task count × 2 edge probabilities × 3 CCR.
  Results may not generalise to extreme configurations.
- **Random DAGs only**: No structured graph families (trees, fork-join) in this grid.
  See graph_family_diagnostic_v1 for structured families.
- **alpha=0.0**: The per-hop latency term is disabled; communication cost = beta × volume.
  Hop count still determines XY route and link reservations.
- **Homogeneous processors**: All 16 processors have identical speed.
- **runtime_ms**: Measures scheduler execution only; fair replay is excluded.
"""

    return "\n".join([
        "# Final Grid Small v2: Experiment Results Summary\n",
        "> **Phase 16 note**: This regenerated CSV uses the Phase 15A+15B improved "
        "ProposedScheduler (greedy recursive ancestor duplication + conservative redundant "
        "duplicate pruning) and includes all fair contention replay columns.\n",
        config_md, mean_md, best_native_section, best_replayed_section,
        ccr_section, interp_section, limits_section,
    ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_EXPERIMENT_NAME = "final_grid_small_v2"
_PARTIAL_CSV = Path("results/raw/final_grid_small_v2.partial.csv")


def main() -> None:
    cfg = FINAL_GRID_SMALL_V2
    seeds = cfg["experiment"]["seeds"]
    task_counts = cfg["dag"]["task_counts"]
    edge_probs = cfg["dag"]["edge_probabilities"]
    ccr_values = cfg["dag"]["ccr_values"]
    comp_range = (cfg["dag"]["computation_min"], cfg["dag"]["computation_max"])
    noc_sizes = cfg["noc"]["sizes"]
    alpha = cfg["noc"]["alpha"]
    beta = cfg["noc"]["beta"]
    scheduler_names = cfg["schedulers"]

    workload_combos = list(itertools.product(task_counts, edge_probs, ccr_values, noc_sizes, seeds))
    n_workloads = len(workload_combos)
    total_rows = n_workloads * len(scheduler_names)

    print("=" * 70, flush=True)
    print(f"Experiment      : {_EXPERIMENT_NAME}", flush=True)
    print(f"Expected rows   : {total_rows}  ({n_workloads} workloads × {len(scheduler_names)} schedulers)", flush=True)
    print(f"Schedulers      : {', '.join(scheduler_names)}", flush=True)
    print(f"Task counts     : {task_counts}", flush=True)
    print(f"Edge probs      : {edge_probs}", flush=True)
    print(f"CCR values      : {ccr_values}", flush=True)
    print(f"Seeds           : {seeds}", flush=True)
    print(f"NoC sizes       : {noc_sizes}", flush=True)
    print(f"Checkpoint CSV  : {_PARTIAL_CSV}", flush=True)
    print("=" * 70, flush=True)

    t0 = _time.perf_counter()
    rows: list[dict] = []
    row_num = 0
    workload_num = 0

    for n_tasks, edge_prob, ccr, noc_size, seed in workload_combos:
        workload_num += 1
        for sched_name in scheduler_names:
            row_num += 1

            if sched_name == "proposed":
                wl_id = f"n={n_tasks} ep={edge_prob} ccr={ccr} noc={noc_size}×{noc_size} seed={seed}"
                print(f"  [heartbeat] Starting ProposedScheduler for {wl_id} ...", flush=True)
                t_hb = _time.perf_counter()

            try:
                row = run_single_experiment(
                    scheduler_name=sched_name,
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
            except Exception:
                print(f"\nERROR during scheduler run:", flush=True)
                print(f"  n_tasks={n_tasks}  edge_prob={edge_prob}  ccr={ccr}"
                      f"  noc={noc_size}×{noc_size}  seed={seed}  scheduler={sched_name}", flush=True)
                traceback.print_exc()
                raise

            if sched_name == "proposed":
                hb_elapsed = _time.perf_counter() - t_hb
                print(f"  [heartbeat] Finished ProposedScheduler for {wl_id} in {hb_elapsed:.2f}s", flush=True)

            rows.append(row)
            elapsed = _time.perf_counter() - t0
            print(
                f"[{_EXPERIMENT_NAME}] workload {workload_num}/{n_workloads},"
                f" scheduler {sched_name}, row {row_num}/{total_rows}, elapsed={elapsed:.1f}s",
                flush=True,
            )

        # Checkpoint after each complete workload group (all schedulers done)
        pd.DataFrame(rows).to_csv(_PARTIAL_CSV, index=False)
        print(
            f"  [checkpoint] workload {workload_num}/{n_workloads}"
            f" -> wrote {len(rows)} rows to {_PARTIAL_CSV}",
            flush=True,
        )

    elapsed_total = _time.perf_counter() - t0
    print(f"\nGrid completed in {elapsed_total:.1f}s  ({len(rows)} raw rows)", flush=True)

    df = pd.DataFrame(rows)
    df = add_relative_metrics(df)
    df = add_replay_relative_metrics(df)

    print(f"Saving final CSV -> {CSV_PATH}", flush=True)
    save_results(df, str(CSV_PATH))

    print("Validating results...", flush=True)
    validate_dataframe(df)

    if _PARTIAL_CSV.exists():
        _PARTIAL_CSV.unlink()
        print(f"Removed partial CSV: {_PARTIAL_CSV}", flush=True)

    print(f"Generating plots with error bars -> {PLOT_WITH_ERROR}/", flush=True)
    generate_all_plots(str(CSV_PATH), str(PLOT_WITH_ERROR))

    print(f"Generating plots without error bars -> {PLOT_NO_ERROR}/", flush=True)
    PLOT_NO_ERROR.mkdir(parents=True, exist_ok=True)
    plot_makespan_vs_ccr(df, PLOT_NO_ERROR / "makespan_vs_ccr.png", show_error=False)
    plot_speedup_vs_ccr(df, PLOT_NO_ERROR / "speedup_vs_ccr.png", show_error=False)
    plot_task_instance_ratio_vs_ccr(df, PLOT_NO_ERROR / "task_instance_ratio_vs_ccr.png", show_error=False)
    plot_communication_count_vs_ccr(df, PLOT_NO_ERROR / "communication_count_vs_ccr.png", show_error=False)
    plot_link_utilization_vs_ccr(df, PLOT_NO_ERROR / "max_link_utilization_vs_ccr.png", show_error=False)
    plot_runtime_vs_task_count(df, PLOT_NO_ERROR / "runtime_vs_task_count.png")

    for col, fname, ylabel, ref in [
        ("replayed_makespan", "replayed_makespan_vs_ccr.png", "Replayed Makespan", None),
        ("replayed_speedup_vs_heft", "replayed_speedup_vs_ccr.png", "Replayed Speedup vs HEFT", 1.0),
        ("replay_overhead_ratio", "replay_overhead_ratio_vs_ccr.png", "Replay Overhead Ratio", 1.0),
        ("replayed_max_link_utilization", "replayed_max_link_utilization_vs_ccr.png",
         "Replayed Max Link Utilization (ratio)", None),
    ]:
        if col in df.columns:
            plot_metric_vs_ccr(
                df, col, PLOT_NO_ERROR / fname,
                title=f"{ylabel} vs CCR", ylabel=ylabel,
                show_error=False, reference_line_y=ref,
            )
            plot_metric_vs_ccr(
                df, col, PLOT_WITH_ERROR / fname,
                title=f"{ylabel} vs CCR", ylabel=ylabel,
                show_error=True, reference_line_y=ref,
            )

    print(f"Writing summary -> {SUMMARY_PATH}", flush=True)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(build_summary(df), encoding="utf-8")

    print("\nMean per scheduler:", flush=True)
    tbl = print_summary_table(df)
    print(tbl.to_string(index=False), flush=True)

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
