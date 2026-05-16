"""
Tests for src/plots.py — Phase 10.

Uses synthetic DataFrames and pytest's tmp_path fixture.
No full experiment runs are required; all inputs are constructed in-memory.

Synthetic DataFrame schema matches the CSV produced by
src.experiment_runner.run_experiment_grid:
  4 schedulers × 3 CCR values × 2 n_tasks × 2 seeds = 48 rows.
"""

import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

import src.plots as plots


# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

_SCHEDULERS = ["heft", "contention_aware", "classical_duplication", "proposed"]
_CCR_VALUES = [0.1, 1.0, 5.0]
_N_TASKS_VALUES = [12, 20]
_SEEDS = [0, 1]

_EXPECTED_PLOT_NAMES = [
    "makespan_vs_ccr.png",
    "speedup_vs_ccr.png",
    "task_instance_ratio_vs_ccr.png",
    "communication_count_vs_ccr.png",
    "max_link_utilization_vs_ccr.png",
    "runtime_vs_task_count.png",
]


def make_results_df() -> pd.DataFrame:
    """
    Build a minimal synthetic results DataFrame that matches the CSV schema
    produced by src.experiment_runner.  Values are deterministic but realistic
    enough to drive all plot functions.

    Layout: 4 schedulers × 3 CCR × 2 n_tasks × 2 seeds = 48 rows.
    """
    rows = []
    for sched in _SCHEDULERS:
        for ccr in _CCR_VALUES:
            for n_tasks in _N_TASKS_VALUES:
                for seed in _SEEDS:
                    heft_makespan = 100.0 + seed * 10.0 + n_tasks * 2.0
                    if sched == "heft":
                        makespan = heft_makespan
                    elif sched == "contention_aware":
                        makespan = heft_makespan * (1.05 + ccr * 0.02)
                    elif sched == "classical_duplication":
                        makespan = heft_makespan * max(0.80, 0.98 - ccr * 0.03)
                    else:  # proposed
                        makespan = heft_makespan * max(0.82, 0.97 - ccr * 0.02)

                    dup_count = (
                        0 if sched in ("heft", "contention_aware")
                        else int(ccr * 2 + 1)
                    )
                    comm_count = (
                        0 if sched in ("heft", "classical_duplication")
                        else int(ccr * 5 + 2)
                    )
                    link_util = (
                        0.0 if sched in ("heft", "classical_duplication")
                        else min(0.9, ccr * 0.08)
                    )
                    sched_idx = _SCHEDULERS.index(sched)
                    runtime = 10.0 + n_tasks * 0.5 * (sched_idx + 1) + seed * 2.0

                    rows.append({
                        "scheduler": sched,
                        "n_tasks": n_tasks,
                        "edge_prob": 0.3,
                        "ccr": ccr,
                        "comp_min": 5,
                        "comp_max": 20,
                        "noc_rows": 4,
                        "noc_cols": 4,
                        "processor_count": 16,
                        "alpha": 0.0,
                        "beta": 1.0,
                        "seed": seed,
                        "achieved_ccr": ccr,
                        "runtime_ms": runtime,
                        "total_computation_work": n_tasks * 12.5,
                        "serial_speedup": n_tasks * 12.5 / makespan,
                        "makespan": makespan,
                        "primary_task_count": n_tasks,
                        "duplicate_task_count": dup_count,
                        "total_task_instance_count": n_tasks + dup_count,
                        "duplication_ratio": dup_count / n_tasks,
                        "task_instance_ratio": (n_tasks + dup_count) / n_tasks,
                        "communication_count": comm_count,
                        "average_communication_latency": ccr * 2.0 if comm_count > 0 else 0.0,
                        "total_communication_time": ccr * comm_count,
                        "average_link_utilization": link_util * 0.5,
                        "max_link_utilization": link_util,
                        "average_processor_utilization": 0.4,
                        "max_processor_utilization": 0.8,
                        "baseline_makespan_heft": heft_makespan,
                        "speedup_vs_heft": heft_makespan / makespan,
                        "normalized_makespan_vs_heft": makespan / heft_makespan,
                    })
    return pd.DataFrame(rows)


def make_csv(tmp_path: Path) -> Path:
    """Write make_results_df() to a temporary CSV and return its path."""
    p = tmp_path / "results.csv"
    make_results_df().to_csv(p, index=False)
    return p


# ---------------------------------------------------------------------------
# 1. TestLoadResults
# ---------------------------------------------------------------------------

class TestLoadResults:
    def test_loads_valid_csv(self, tmp_path):
        csv_path = make_csv(tmp_path)
        df = plots.load_results(csv_path)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == len(_SCHEDULERS) * len(_CCR_VALUES) * len(_N_TASKS_VALUES) * len(_SEEDS)

    def test_accepts_path_object(self, tmp_path):
        csv_path = make_csv(tmp_path)
        df = plots.load_results(Path(csv_path))
        assert isinstance(df, pd.DataFrame)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            plots.load_results(tmp_path / "nonexistent.csv")

    def test_missing_required_columns_raises(self, tmp_path):
        bad = pd.DataFrame({"foo": [1, 2], "bar": [3, 4]})
        bad_path = tmp_path / "bad.csv"
        bad.to_csv(bad_path, index=False)
        with pytest.raises(ValueError, match="[Mm]issing"):
            plots.load_results(bad_path)


# ---------------------------------------------------------------------------
# 2. TestAggregateResults
# ---------------------------------------------------------------------------

class TestAggregateResults:
    def test_aggregates_makespan_by_scheduler_ccr(self):
        df = make_results_df()
        agg = plots.aggregate_results(df, "makespan")
        assert "makespan_mean" in agg.columns
        assert "scheduler" in agg.columns
        assert "ccr" in agg.columns
        # 4 schedulers × 3 CCR values
        assert len(agg) == len(_SCHEDULERS) * len(_CCR_VALUES)

    def test_output_has_mean_std_count_columns(self):
        df = make_results_df()
        agg = plots.aggregate_results(df, "makespan")
        assert "makespan_mean" in agg.columns
        assert "makespan_std" in agg.columns
        assert "makespan_count" in agg.columns

    def test_count_reflects_number_of_seeds_and_task_counts(self):
        df = make_results_df()
        agg = plots.aggregate_results(df, "makespan")
        # Each (scheduler, ccr) group has len(_SEEDS) * len(_N_TASKS_VALUES) rows
        expected_count = len(_SEEDS) * len(_N_TASKS_VALUES)
        assert (agg["makespan_count"] == expected_count).all()

    def test_rejects_missing_metric(self):
        df = make_results_df()
        with pytest.raises(ValueError, match="[Mm]etric"):
            plots.aggregate_results(df, "nonexistent_column")

    def test_custom_group_by_scheduler_and_n_tasks(self):
        df = make_results_df()
        agg = plots.aggregate_results(df, "runtime_ms", group_by=["scheduler", "n_tasks"])
        assert "n_tasks" in agg.columns
        assert "runtime_ms_mean" in agg.columns
        assert len(agg) == len(_SCHEDULERS) * len(_N_TASKS_VALUES)

    def test_default_group_by_is_scheduler_ccr(self):
        df = make_results_df()
        agg = plots.aggregate_results(df, "makespan")
        # Default group_by = ["scheduler", "ccr"]
        assert set(agg.columns) >= {"scheduler", "ccr", "makespan_mean"}


# ---------------------------------------------------------------------------
# 3. TestPlotMetricVsCCR
# ---------------------------------------------------------------------------

class TestPlotMetricVsCCR:
    def test_returns_path(self, tmp_path):
        df = make_results_df()
        out = tmp_path / "test.png"
        result = plots.plot_metric_vs_ccr(df, "makespan", out)
        assert result == out

    def test_file_exists(self, tmp_path):
        df = make_results_df()
        out = tmp_path / "test.png"
        plots.plot_metric_vs_ccr(df, "makespan", out)
        assert out.exists()

    def test_file_size_nonzero(self, tmp_path):
        df = make_results_df()
        out = tmp_path / "test.png"
        plots.plot_metric_vs_ccr(df, "makespan", out)
        assert out.stat().st_size > 0

    def test_creates_parent_directory(self, tmp_path):
        df = make_results_df()
        out = tmp_path / "subdir" / "nested" / "plot.png"
        plots.plot_metric_vs_ccr(df, "makespan", out)
        assert out.exists()

    def test_missing_scheduler_skipped_gracefully(self, tmp_path):
        df = make_results_df()
        df_partial = df[df["scheduler"] != "proposed"].copy()
        out = tmp_path / "partial.png"
        plots.plot_metric_vs_ccr(df_partial, "makespan", out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_custom_title_and_ylabel(self, tmp_path):
        df = make_results_df()
        out = tmp_path / "titled.png"
        result = plots.plot_metric_vs_ccr(
            df, "makespan", out,
            title="My Title", ylabel="My Y Label",
        )
        assert result.exists()

    def test_custom_scheduler_order(self, tmp_path):
        df = make_results_df()
        out = tmp_path / "ordered.png"
        plots.plot_metric_vs_ccr(
            df, "makespan", out,
            scheduler_order=["proposed", "heft"],
        )
        assert out.exists() and out.stat().st_size > 0


# ---------------------------------------------------------------------------
# 4. TestWrapperPlots
# ---------------------------------------------------------------------------

class TestWrapperPlots:
    def test_plot_makespan_vs_ccr(self, tmp_path):
        df = make_results_df()
        out = plots.plot_makespan_vs_ccr(df, tmp_path / "makespan.png")
        assert out.exists() and out.stat().st_size > 0

    def test_plot_speedup_vs_ccr(self, tmp_path):
        df = make_results_df()
        out = plots.plot_speedup_vs_ccr(df, tmp_path / "speedup.png")
        assert out.exists() and out.stat().st_size > 0

    def test_plot_task_instance_ratio_vs_ccr(self, tmp_path):
        df = make_results_df()
        out = plots.plot_task_instance_ratio_vs_ccr(df, tmp_path / "tir.png")
        assert out.exists() and out.stat().st_size > 0

    def test_plot_communication_count_vs_ccr(self, tmp_path):
        df = make_results_df()
        out = plots.plot_communication_count_vs_ccr(df, tmp_path / "comm.png")
        assert out.exists() and out.stat().st_size > 0

    def test_plot_link_utilization_vs_ccr(self, tmp_path):
        df = make_results_df()
        out = plots.plot_link_utilization_vs_ccr(df, tmp_path / "link.png")
        assert out.exists() and out.stat().st_size > 0


# ---------------------------------------------------------------------------
# 5. TestPlotRuntimeVsTaskCount
# ---------------------------------------------------------------------------

class TestPlotRuntimeVsTaskCount:
    def test_returns_path(self, tmp_path):
        df = make_results_df()
        out = tmp_path / "runtime.png"
        result = plots.plot_runtime_vs_task_count(df, out)
        assert result == out

    def test_file_exists_and_nonzero(self, tmp_path):
        df = make_results_df()
        out = tmp_path / "runtime.png"
        plots.plot_runtime_vs_task_count(df, out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_log_y_true(self, tmp_path):
        df = make_results_df()
        out = tmp_path / "runtime_log.png"
        plots.plot_runtime_vs_task_count(df, out, log_y=True)
        assert out.exists() and out.stat().st_size > 0

    def test_log_y_false(self, tmp_path):
        df = make_results_df()
        out = tmp_path / "runtime_linear.png"
        plots.plot_runtime_vs_task_count(df, out, log_y=False)
        assert out.exists() and out.stat().st_size > 0

    def test_custom_scheduler_order(self, tmp_path):
        df = make_results_df()
        out = tmp_path / "runtime_custom.png"
        plots.plot_runtime_vs_task_count(
            df, out, scheduler_order=["heft", "proposed"]
        )
        assert out.exists() and out.stat().st_size > 0


# ---------------------------------------------------------------------------
# 6. TestGenerateAllPlots
# ---------------------------------------------------------------------------

class TestGenerateAllPlots:
    def test_returns_list_of_path_objects(self, tmp_path):
        csv_path = make_csv(tmp_path)
        result = plots.generate_all_plots(csv_path, tmp_path / "plots")
        assert isinstance(result, list)
        for p in result:
            assert isinstance(p, Path)

    def test_returns_correct_count(self, tmp_path):
        csv_path = make_csv(tmp_path)
        result = plots.generate_all_plots(csv_path, tmp_path / "plots")
        assert len(result) == len(_EXPECTED_PLOT_NAMES)

    def test_creates_all_expected_filenames(self, tmp_path):
        csv_path = make_csv(tmp_path)
        out_dir = tmp_path / "plots"
        plots.generate_all_plots(csv_path, out_dir)
        for name in _EXPECTED_PLOT_NAMES:
            assert (out_dir / name).exists(), f"Missing: {name}"

    def test_all_returned_paths_exist_and_nonzero(self, tmp_path):
        csv_path = make_csv(tmp_path)
        result = plots.generate_all_plots(csv_path, tmp_path / "plots")
        for p in result:
            assert p.exists(), f"Path does not exist: {p}"
            assert p.stat().st_size > 0, f"Zero-size file: {p}"

    def test_creates_output_directory(self, tmp_path):
        csv_path = make_csv(tmp_path)
        out_dir = tmp_path / "new" / "nested" / "plots"
        plots.generate_all_plots(csv_path, out_dir)
        assert out_dir.exists()


# ---------------------------------------------------------------------------
# 7. TestPrintSummaryTable
# ---------------------------------------------------------------------------

class TestPrintSummaryTable:
    def test_returns_dataframe(self):
        df = make_results_df()
        summary = plots.print_summary_table(df)
        assert isinstance(summary, pd.DataFrame)

    def test_default_group_by_gives_one_row_per_scheduler(self):
        df = make_results_df()
        summary = plots.print_summary_table(df)
        assert len(summary) == len(_SCHEDULERS)

    def test_scheduler_column_present(self):
        df = make_results_df()
        summary = plots.print_summary_table(df)
        assert "scheduler" in summary.columns

    def test_expected_summary_metrics_present(self):
        df = make_results_df()
        summary = plots.print_summary_table(df)
        for col in ("makespan", "speedup_vs_heft", "runtime_ms"):
            assert col in summary.columns, f"Missing summary column: {col}"

    def test_custom_group_by_scheduler_and_ccr(self):
        df = make_results_df()
        summary = plots.print_summary_table(df, group_by=["scheduler", "ccr"])
        assert "ccr" in summary.columns
        assert len(summary) == len(_SCHEDULERS) * len(_CCR_VALUES)

    def test_values_are_means(self):
        df = make_results_df()
        summary = plots.print_summary_table(df)
        # For HEFT, speedup_vs_heft must always be 1.0 → mean = 1.0
        heft_row = summary[summary["scheduler"] == "heft"].iloc[0]
        assert abs(heft_row["speedup_vs_heft"] - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# 8. TestCLI
# ---------------------------------------------------------------------------

class TestCLI:
    def test_exit_code_zero(self, tmp_path):
        csv_path = make_csv(tmp_path)
        out_dir = tmp_path / "cli_out"
        result = subprocess.run(
            [sys.executable, "-m", "src.plots",
             "--csv", str(csv_path),
             "--out", str(out_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"CLI exited non-zero.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_cli_creates_all_plot_files(self, tmp_path):
        csv_path = make_csv(tmp_path)
        out_dir = tmp_path / "cli_out"
        subprocess.run(
            [sys.executable, "-m", "src.plots",
             "--csv", str(csv_path),
             "--out", str(out_dir)],
            capture_output=True,
        )
        for name in _EXPECTED_PLOT_NAMES:
            assert (out_dir / name).exists(), f"CLI did not create: {name}"
