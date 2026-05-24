"""
Tests for src/experiment_runner.py — Phase 9.

Uses tiny configs (2-node NoC, 6-task DAGs, 1 seed) to keep runs fast.
"""

import tempfile
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.experiment_runner import (
    add_relative_metrics,
    build_scheduler,
    load_config,
    run_experiment_grid,
    run_from_config,
    run_single_experiment,
    save_results,
)
from src.noc import MeshNoC

# ---------------------------------------------------------------------------
# Shared tiny config
# ---------------------------------------------------------------------------

TINY_CONFIG = {
    "experiment": {"name": "test_run", "seeds": [0], "raw_dir": "results/raw"},
    "schedulers": ["heft", "proposed"],
    "dag": {
        "task_counts": [6],
        "edge_probabilities": [0.3],
        "ccr_values": [1.0],
        "computation_min": 10,
        "computation_max": 100,
    },
    "noc": {"sizes": [2], "alpha": 0.0, "beta": 1.0},
}

_EXPECTED_COLUMNS = {
    # Experiment parameters
    "scheduler",
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
    "runtime_ms",
    # Schedule metrics (from schedule_summary)
    "makespan",
    "primary_task_count",
    "duplicate_task_count",
    "duplication_ratio",
    "total_task_instance_count",
    "task_instance_ratio",
    "communication_count",
    "average_communication_latency",
    "total_communication_time",
    "average_link_utilization",
    "max_link_utilization",
    "average_processor_utilization",
    "max_processor_utilization",
    # Workload-level metrics (from run_single_experiment)
    "total_computation_work",
    "serial_speedup",
    # HEFT-relative metrics (from add_relative_metrics)
    "baseline_makespan_heft",
    "speedup_vs_heft",
    "normalized_makespan_vs_heft",
}


# ---------------------------------------------------------------------------
# TestBuildScheduler
# ---------------------------------------------------------------------------

class TestBuildScheduler:
    def _noc(self) -> MeshNoC:
        return MeshNoC(rows=2, cols=2, alpha=1.0, beta=0.1)

    def test_heft(self):
        s = build_scheduler("heft", self._noc())
        assert s is not None

    def test_contention_aware(self):
        s = build_scheduler("contention_aware", self._noc())
        assert s is not None

    def test_classical_duplication(self):
        s = build_scheduler("classical_duplication", self._noc())
        assert s is not None

    def test_proposed(self):
        s = build_scheduler("proposed", self._noc())
        assert s is not None

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="Unknown scheduler"):
            build_scheduler("nonexistent", self._noc())

    def test_invalid_noc_raises(self):
        with pytest.raises(ValueError, match="noc must be a MeshNoC"):
            build_scheduler("heft", "not_a_noc")


# ---------------------------------------------------------------------------
# TestRunSingleExperiment
# ---------------------------------------------------------------------------

class TestRunSingleExperiment:
    def _run(self, scheduler_name: str = "heft") -> dict:
        return run_single_experiment(
            scheduler_name=scheduler_name,
            n_tasks=6,
            edge_prob=0.3,
            ccr=1.0,
            comp_range=(10, 100),
            noc_rows=2,
            noc_cols=2,
            alpha=0.0,
            beta=1.0,
            seed=0,
        )

    def test_returns_dict(self):
        result = self._run()
        assert isinstance(result, dict)

    def test_has_parameter_fields(self):
        result = self._run()
        assert result["scheduler"] == "heft"
        assert result["n_tasks"] == 6
        assert result["edge_prob"] == pytest.approx(0.3)
        assert result["ccr"] == pytest.approx(1.0)
        assert result["comp_min"] == 10
        assert result["comp_max"] == 100
        assert result["noc_rows"] == 2
        assert result["noc_cols"] == 2
        assert result["processor_count"] == 4
        assert result["alpha"] == pytest.approx(0.0)
        assert result["beta"] == pytest.approx(1.0)
        assert result["seed"] == 0

    def test_has_metric_fields(self):
        result = self._run()
        for key in (
            "makespan",
            "primary_task_count",
            "duplicate_task_count",
            "duplication_ratio",
            "total_task_instance_count",
            "task_instance_ratio",
            "communication_count",
            "average_communication_latency",
            "total_communication_time",
            "average_link_utilization",
            "max_link_utilization",
            "average_processor_utilization",
            "max_processor_utilization",
            "achieved_ccr",
            "runtime_ms",
            "total_computation_work",
            "serial_speedup",
        ):
            assert key in result, f"missing key: {key}"

    def test_has_total_work_and_serial_speedup_fields(self):
        result = self._run()
        assert "total_computation_work" in result
        assert "serial_speedup" in result
        assert result["total_computation_work"] > 0
        assert result["serial_speedup"] >= 0

    def test_scheduler_name_preserved(self):
        for name in ("heft", "contention_aware", "classical_duplication", "proposed"):
            result = self._run(name)
            assert result["scheduler"] == name

    def test_runtime_ms_nonnegative(self):
        result = self._run()
        assert result["runtime_ms"] >= 0.0

    def test_makespan_nonnegative(self):
        result = self._run()
        assert result["makespan"] >= 0.0


# ---------------------------------------------------------------------------
# TestAllSchedulers
# ---------------------------------------------------------------------------

class TestAllSchedulers:
    @pytest.mark.parametrize(
        "scheduler_name",
        ["heft", "contention_aware", "classical_duplication", "proposed"],
    )
    def test_scheduler_completes(self, scheduler_name: str):
        result = run_single_experiment(
            scheduler_name=scheduler_name,
            n_tasks=6,
            edge_prob=0.3,
            ccr=1.0,
            comp_range=(10, 100),
            noc_rows=2,
            noc_cols=2,
            alpha=0.0,
            beta=1.0,
            seed=42,
        )
        assert result["makespan"] >= 0.0


# ---------------------------------------------------------------------------
# TestRunExperimentGrid
# ---------------------------------------------------------------------------

class TestRunExperimentGrid:
    def test_returns_dataframe(self):
        df = run_experiment_grid(TINY_CONFIG)
        assert isinstance(df, pd.DataFrame)

    def test_row_count(self):
        # 2 schedulers × 1 task_count × 1 edge_prob × 1 ccr × 1 noc_size × 1 seed = 2
        df = run_experiment_grid(TINY_CONFIG)
        assert len(df) == 2

    def test_required_columns(self):
        df = run_experiment_grid(TINY_CONFIG)
        missing = _EXPECTED_COLUMNS - set(df.columns)
        assert not missing, f"Missing columns: {missing}"

    def test_heft_row_relative_metrics(self):
        df = run_experiment_grid(TINY_CONFIG)
        heft_row = df[df["scheduler"] == "heft"].iloc[0]
        assert heft_row["speedup_vs_heft"] == pytest.approx(1.0)
        assert heft_row["normalized_makespan_vs_heft"] == pytest.approx(1.0)
        assert heft_row["baseline_makespan_heft"] == pytest.approx(heft_row["makespan"])

    def test_proposed_row_baseline_equals_heft_makespan(self):
        df = run_experiment_grid(TINY_CONFIG)
        heft_ms = float(df[df["scheduler"] == "heft"].iloc[0]["makespan"])
        prop_row = df[df["scheduler"] == "proposed"].iloc[0]
        assert prop_row["baseline_makespan_heft"] == pytest.approx(heft_ms)

    def test_proposed_row_speedup_vs_heft(self):
        df = run_experiment_grid(TINY_CONFIG)
        heft_ms = float(df[df["scheduler"] == "heft"].iloc[0]["makespan"])
        prop_row = df[df["scheduler"] == "proposed"].iloc[0]
        prop_ms = float(prop_row["makespan"])
        if prop_ms > 0:
            assert prop_row["speedup_vs_heft"] == pytest.approx(heft_ms / prop_ms)


# ---------------------------------------------------------------------------
# TestSaveResults
# ---------------------------------------------------------------------------

class TestSaveResults:
    def test_file_created(self, tmp_path):
        df = run_experiment_grid(TINY_CONFIG)
        output = str(tmp_path / "sub" / "out.csv")
        save_results(df, output)
        assert Path(output).exists()

    def test_csv_loadable_and_correct_rows(self, tmp_path):
        df = run_experiment_grid(TINY_CONFIG)
        output = str(tmp_path / "out.csv")
        save_results(df, output)
        loaded = pd.read_csv(output)
        assert len(loaded) == len(df)


# ---------------------------------------------------------------------------
# TestLoadConfig
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_loads_yaml(self, tmp_path):
        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text(yaml.dump(TINY_CONFIG), encoding="utf-8")
        loaded = load_config(str(cfg_path))
        assert loaded["experiment"]["name"] == "test_run"
        assert loaded["schedulers"] == ["heft", "proposed"]

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "nonexistent.yaml"))


# ---------------------------------------------------------------------------
# TestRunFromConfig
# ---------------------------------------------------------------------------

class TestRunFromConfig:
    def test_runs_saves_and_returns_dataframe(self, tmp_path):
        cfg = dict(TINY_CONFIG)
        cfg["experiment"] = {
            "name": "runner_test",
            "seeds": [0],
            "raw_dir": str(tmp_path / "raw"),
        }
        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text(yaml.dump(cfg), encoding="utf-8")

        df = run_from_config(str(cfg_path))

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2  # 2 schedulers × 1 everything else
        expected_csv = tmp_path / "raw" / "runner_test.csv"
        assert expected_csv.exists()


# ---------------------------------------------------------------------------
# TestAddRelativeMetrics
# ---------------------------------------------------------------------------

# Workload-defining columns required by add_relative_metrics; values chosen to
# be consistent (processor_count = noc_rows * noc_cols = 1).
_WORKLOAD_DEFAULTS = {
    "n_tasks": 6,
    "edge_prob": 0.3,
    "ccr": 1.0,
    "comp_min": 10,
    "comp_max": 100,
    "noc_rows": 1,
    "noc_cols": 1,
    "processor_count": 1,
    "alpha": 0.0,
    "beta": 1.0,
    "seed": 0,
    "achieved_ccr": 1.0,
}


def _make_minimal_df(
    schedulers: list[str],
    makespan_values: list[float],
    workload: dict | None = None,
) -> pd.DataFrame:
    """Build a minimal DataFrame with the required groupby columns."""
    base = workload if workload is not None else _WORKLOAD_DEFAULTS
    rows = []
    for sched, ms in zip(schedulers, makespan_values):
        row = dict(base)
        row["scheduler"] = sched
        row["makespan"] = ms
        rows.append(row)
    return pd.DataFrame(rows)


class TestAddRelativeMetrics:
    def test_add_relative_metrics_adds_expected_columns(self):
        df = _make_minimal_df(["heft", "proposed"], [100.0, 80.0])
        result = add_relative_metrics(df)
        assert "baseline_makespan_heft" in result.columns
        assert "speedup_vs_heft" in result.columns
        assert "normalized_makespan_vs_heft" in result.columns

    def test_missing_heft_baseline_raises(self):
        df = _make_minimal_df(["proposed", "contention_aware"], [100.0, 120.0])
        with pytest.raises(ValueError, match="[Nn]o.*[Hh][Ee][Ff][Tt]|[Hh][Ee][Ff][Tt].*[Nn]o"):
            add_relative_metrics(df)

    def test_duplicate_heft_baseline_raises(self):
        # Two HEFT rows for the same workload group → ValueError
        df = _make_minimal_df(["heft", "heft", "proposed"], [100.0, 105.0, 80.0])
        with pytest.raises(ValueError, match="[Mm]ultiple"):
            add_relative_metrics(df)

    def test_heft_speedup_is_one(self):
        df = _make_minimal_df(["heft", "proposed"], [100.0, 80.0])
        result = add_relative_metrics(df)
        heft_row = result[result["scheduler"] == "heft"].iloc[0]
        assert heft_row["speedup_vs_heft"] == pytest.approx(1.0)
        assert heft_row["normalized_makespan_vs_heft"] == pytest.approx(1.0)
        assert heft_row["baseline_makespan_heft"] == pytest.approx(100.0)
