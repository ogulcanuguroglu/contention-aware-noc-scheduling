"""
Tests for Phase 13: Fair Contention Replay Metrics in Experiment Runner.

Verifies that replay-based metrics columns are correctly added to experiment
result DataFrames, that HEFT baseline semantics hold for the replayed model,
that cross-workload grouping is correct, and that all existing columns remain
present (backward compatibility).

Uses tiny deterministic configs to keep runtime short.
"""

import networkx as nx
import pandas as pd
import pytest

from src.contention_replay import replay_under_contention
from src.experiment_runner import (
    _GROUPBY_COLS,
    add_relative_metrics,
    add_replay_relative_metrics,
    run_experiment_grid,
    run_single_experiment,
)
from src.models import DAGGraph
from src.noc import MeshNoC
from src.schedule_state import ScheduleState


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TINY_CONFIG = {
    "experiment": {"name": "test_replay_metrics", "seeds": [0], "raw_dir": "results/raw"},
    "schedulers": ["heft", "contention_aware"],
    "dag": {
        "task_counts": [5],
        "edge_probabilities": [0.4],
        "ccr_values": [1.0],
        "computation_min": 10,
        "computation_max": 20,
    },
    "noc": {"sizes": [2], "alpha": 0.0, "beta": 1.0},
}

_NEW_REPLAY_COLUMNS = {
    "replayed_makespan",
    "replayed_speedup_vs_heft",
    "replayed_communication_count",
    "replayed_max_link_utilization",
    "replay_overhead_ratio",
    "replayed_vs_original_delta",
}

_WORKLOAD_DEFAULTS = {
    "n_tasks": 5,
    "edge_prob": 0.4,
    "ccr": 1.0,
    "comp_min": 10,
    "comp_max": 20,
    "noc_rows": 2,
    "noc_cols": 2,
    "processor_count": 4,
    "alpha": 0.0,
    "beta": 1.0,
    "seed": 0,
    "achieved_ccr": 1.0,
}


def _tiny_df() -> pd.DataFrame:
    """Return a cached tiny grid result for reuse across tests."""
    return run_experiment_grid(_TINY_CONFIG)


def _make_replay_df(
    schedulers: list[str],
    makespans: list[float],
    replayed_makespans: list[float],
    workload: dict | None = None,
) -> pd.DataFrame:
    """Build a minimal DataFrame with replay columns for testing add_replay_relative_metrics."""
    base = workload if workload is not None else _WORKLOAD_DEFAULTS
    rows = []
    for sched, ms, rms in zip(schedulers, makespans, replayed_makespans):
        row = dict(base)
        row["scheduler"] = sched
        row["makespan"] = ms
        row["replayed_makespan"] = rms
        row["replayed_communication_count"] = 0
        row["replayed_max_link_utilization"] = 0.0
        row["replay_overhead_ratio"] = rms / ms if ms > 0.0 else 1.0
        row["replayed_vs_original_delta"] = rms - ms
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 1. Experiment row contains all replay metric columns
# ---------------------------------------------------------------------------

class TestReplayColumnsPresent:
    def test_run_experiment_grid_has_replay_columns(self):
        df = _tiny_df()
        missing = _NEW_REPLAY_COLUMNS - set(df.columns)
        assert not missing, f"Missing replay columns: {missing}"

    def test_run_single_experiment_has_per_row_replay_columns(self):
        result = run_single_experiment(
            scheduler_name="heft",
            n_tasks=5,
            edge_prob=0.4,
            ccr=1.0,
            comp_range=(10, 20),
            noc_rows=2,
            noc_cols=2,
            alpha=0.0,
            beta=1.0,
            seed=0,
        )
        per_row_cols = {
            "replayed_makespan",
            "replayed_communication_count",
            "replayed_max_link_utilization",
            "replay_overhead_ratio",
            "replayed_vs_original_delta",
        }
        missing = per_row_cols - set(result.keys())
        assert not missing, f"Missing per-row replay keys: {missing}"


# ---------------------------------------------------------------------------
# 2. No NaN in replay metric columns
# ---------------------------------------------------------------------------

class TestNoNaNReplayColumns:
    def test_no_nan_in_replayed_makespan(self):
        df = _tiny_df()
        assert df["replayed_makespan"].isna().sum() == 0

    def test_no_nan_in_replayed_speedup_vs_heft(self):
        df = _tiny_df()
        assert df["replayed_speedup_vs_heft"].isna().sum() == 0

    def test_no_nan_in_replayed_communication_count(self):
        df = _tiny_df()
        assert df["replayed_communication_count"].isna().sum() == 0

    def test_no_nan_in_replayed_max_link_utilization(self):
        df = _tiny_df()
        assert df["replayed_max_link_utilization"].isna().sum() == 0

    def test_no_nan_in_replay_overhead_ratio(self):
        df = _tiny_df()
        assert df["replay_overhead_ratio"].isna().sum() == 0

    def test_no_nan_in_replayed_vs_original_delta(self):
        df = _tiny_df()
        assert df["replayed_vs_original_delta"].isna().sum() == 0


# ---------------------------------------------------------------------------
# 3. HEFT replay speedup baseline == 1.0
# ---------------------------------------------------------------------------

class TestHEFTReplaySpeedupBaseline:
    def test_heft_replayed_speedup_vs_heft_is_one(self):
        df = _tiny_df()
        heft_rows = df[df["scheduler"] == "heft"]
        assert len(heft_rows) > 0, "No HEFT rows found"
        for _, row in heft_rows.iterrows():
            assert row["replayed_speedup_vs_heft"] == pytest.approx(1.0), (
                f"HEFT replayed_speedup_vs_heft = {row['replayed_speedup_vs_heft']}, expected 1.0"
            )

    def test_add_replay_relative_metrics_heft_speedup_is_one(self):
        df = _make_replay_df(["heft", "contention_aware"], [100.0, 90.0], [120.0, 100.0])
        result = add_replay_relative_metrics(df)
        heft_row = result[result["scheduler"] == "heft"].iloc[0]
        assert heft_row["replayed_speedup_vs_heft"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 4. Existing speedup_vs_heft is unchanged
# ---------------------------------------------------------------------------

class TestExistingSpeedupUnchanged:
    def test_speedup_vs_heft_column_still_present(self):
        df = _tiny_df()
        assert "speedup_vs_heft" in df.columns

    def test_heft_speedup_vs_heft_still_one(self):
        df = _tiny_df()
        heft_rows = df[df["scheduler"] == "heft"]
        for _, row in heft_rows.iterrows():
            assert row["speedup_vs_heft"] == pytest.approx(1.0)

    def test_baseline_makespan_heft_still_present(self):
        df = _tiny_df()
        assert "baseline_makespan_heft" in df.columns

    def test_normalized_makespan_vs_heft_still_present(self):
        df = _tiny_df()
        assert "normalized_makespan_vs_heft" in df.columns


# ---------------------------------------------------------------------------
# 5. Classic schedule replay materializes communication
# ---------------------------------------------------------------------------

class TestClassicReplayMaterializesComm:
    """HEFT uses the classic model (no CommunicationInstance objects).
    When replay runs on a HEFT state with remote tasks, it creates comms.
    """

    def test_heft_communication_count_is_zero(self):
        """HEFT never creates CommunicationInstance objects by design."""
        result = run_single_experiment(
            "heft", n_tasks=5, edge_prob=0.4, ccr=1.0,
            comp_range=(10, 20), noc_rows=2, noc_cols=2, alpha=0.0, beta=1.0, seed=0,
        )
        assert result["communication_count"] == 0

    def test_replay_on_heft_like_state_adds_comms(self):
        """Directly verify: replay on a HEFT-like state (remote tasks, no comms)
        creates CommunicationInstances that the original state does not have."""
        noc = MeshNoC(rows=2, cols=2, alpha=0.0, beta=1.0)
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=5.0)
        g.add_edge(0, 1, communication_volume=5.0)
        dag = DAGGraph(g)

        state = ScheduleState(noc)
        state.reserve_task(0, 0, 0, 10, True)
        state.reserve_task(1, 1, 10, 15, True)

        assert len(state.communication_instances) == 0

        replayed = replay_under_contention(dag, state, noc)
        assert len(replayed.communication_instances) > 0

    def test_replayed_communication_count_geq_original(self):
        """replayed_communication_count >= communication_count for all schedulers."""
        df = _tiny_df()
        for _, row in df.iterrows():
            assert row["replayed_communication_count"] >= row["communication_count"], (
                f"scheduler={row['scheduler']}: replayed_comm_count "
                f"{row['replayed_communication_count']} < comm_count {row['communication_count']}"
            )


# ---------------------------------------------------------------------------
# 6. replay_overhead_ratio correctness
# ---------------------------------------------------------------------------

class TestReplayOverheadRatio:
    def test_overhead_ratio_formula_in_grid(self):
        df = _tiny_df()
        for _, row in df.iterrows():
            ms = float(row["makespan"])
            rms = float(row["replayed_makespan"])
            expected = rms / ms if ms > 0.0 else 1.0
            assert row["replay_overhead_ratio"] == pytest.approx(expected, rel=1e-9), (
                f"scheduler={row['scheduler']}: ratio={row['replay_overhead_ratio']}, "
                f"expected={expected}"
            )

    def test_overhead_ratio_from_run_single(self):
        result = run_single_experiment(
            "heft", n_tasks=5, edge_prob=0.4, ccr=1.0,
            comp_range=(10, 20), noc_rows=2, noc_cols=2, alpha=0.0, beta=1.0, seed=0,
        )
        ms = result["makespan"]
        rms = result["replayed_makespan"]
        expected = rms / ms if ms > 0.0 else 1.0
        assert result["replay_overhead_ratio"] == pytest.approx(expected)

    def test_overhead_ratio_geq_zero(self):
        df = _tiny_df()
        assert (df["replay_overhead_ratio"] >= 0.0).all()


# ---------------------------------------------------------------------------
# 7. replayed_vs_original_delta correctness
# ---------------------------------------------------------------------------

class TestReplayedVsOriginalDelta:
    def test_delta_formula_in_grid(self):
        df = _tiny_df()
        for _, row in df.iterrows():
            expected = float(row["replayed_makespan"]) - float(row["makespan"])
            assert row["replayed_vs_original_delta"] == pytest.approx(expected, rel=1e-9), (
                f"scheduler={row['scheduler']}: delta={row['replayed_vs_original_delta']}, "
                f"expected={expected}"
            )

    def test_delta_from_run_single(self):
        result = run_single_experiment(
            "contention_aware", n_tasks=5, edge_prob=0.4, ccr=1.0,
            comp_range=(10, 20), noc_rows=2, noc_cols=2, alpha=0.0, beta=1.0, seed=0,
        )
        expected = result["replayed_makespan"] - result["makespan"]
        assert result["replayed_vs_original_delta"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 8. Group baseline correctness (replayed_speedup_vs_heft per workload group)
# ---------------------------------------------------------------------------

class TestGroupBaselineCorrectness:
    """replayed_speedup_vs_heft must be computed against HEFT of the SAME workload."""

    def test_two_workload_groups_use_separate_baselines(self):
        workload1 = dict(_WORKLOAD_DEFAULTS, n_tasks=5, seed=0, achieved_ccr=1.0)
        workload2 = dict(_WORKLOAD_DEFAULTS, n_tasks=6, seed=0, achieved_ccr=1.0)

        df = pd.DataFrame([
            {**workload1, "scheduler": "heft", "makespan": 100.0,
             "replayed_makespan": 110.0, "replayed_communication_count": 0,
             "replayed_max_link_utilization": 0.0, "replay_overhead_ratio": 1.1,
             "replayed_vs_original_delta": 10.0},
            {**workload1, "scheduler": "contention_aware", "makespan": 90.0,
             "replayed_makespan": 88.0, "replayed_communication_count": 2,
             "replayed_max_link_utilization": 0.1, "replay_overhead_ratio": 0.978,
             "replayed_vs_original_delta": -2.0},
            {**workload2, "scheduler": "heft", "makespan": 200.0,
             "replayed_makespan": 240.0, "replayed_communication_count": 0,
             "replayed_max_link_utilization": 0.0, "replay_overhead_ratio": 1.2,
             "replayed_vs_original_delta": 40.0},
            {**workload2, "scheduler": "contention_aware", "makespan": 180.0,
             "replayed_makespan": 200.0, "replayed_communication_count": 3,
             "replayed_max_link_utilization": 0.15, "replay_overhead_ratio": 1.11,
             "replayed_vs_original_delta": 20.0},
        ])

        result = add_replay_relative_metrics(df)

        grp1 = result[result["n_tasks"] == 5]
        grp2 = result[result["n_tasks"] == 6]

        heft1_replayed = 110.0
        heft2_replayed = 240.0

        ca_1 = grp1[grp1["scheduler"] == "contention_aware"].iloc[0]
        ca_2 = grp2[grp2["scheduler"] == "contention_aware"].iloc[0]

        assert ca_1["replayed_speedup_vs_heft"] == pytest.approx(heft1_replayed / 88.0)
        assert ca_2["replayed_speedup_vs_heft"] == pytest.approx(heft2_replayed / 200.0)

    def test_replayed_speedup_formula_against_heft_row(self):
        df = _tiny_df()
        heft_rms = float(df[df["scheduler"] == "heft"].iloc[0]["replayed_makespan"])
        for _, row in df.iterrows():
            expected_spd = heft_rms / float(row["replayed_makespan"])
            assert row["replayed_speedup_vs_heft"] == pytest.approx(expected_spd, rel=1e-9)


# ---------------------------------------------------------------------------
# 9. Local-only case: replayed_communication_count == 0
# ---------------------------------------------------------------------------

class TestLocalOnlyReplayComm:
    def test_local_schedule_replay_produces_no_comms(self):
        """When all tasks are on the same processor, replay creates zero comms."""
        noc = MeshNoC(rows=2, cols=2, alpha=0.0, beta=1.0)
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=5.0)
        g.add_edge(0, 1, communication_volume=5.0)
        dag = DAGGraph(g)

        state = ScheduleState(noc)
        state.reserve_task(0, 0, 0, 10, True)
        state.reserve_task(1, 0, 10, 15, True)

        assert len(state.communication_instances) == 0
        replayed = replay_under_contention(dag, state, noc)
        assert len(replayed.communication_instances) == 0

    def test_local_schedule_replay_delta_is_zero(self):
        """For an all-local schedule, replayed makespan == original makespan."""
        noc = MeshNoC(rows=2, cols=2, alpha=0.0, beta=1.0)
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=5.0)
        g.add_edge(0, 1, communication_volume=5.0)
        dag = DAGGraph(g)

        state = ScheduleState(noc)
        state.reserve_task(0, 0, 0, 10, True)
        state.reserve_task(1, 0, 10, 15, True)

        replayed = replay_under_contention(dag, state, noc)
        assert replayed.max_processor_finish_time() == pytest.approx(15.0)
        assert state.max_processor_finish_time() == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# 10. Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    _ORIGINAL_COLUMNS = {
        "scheduler", "n_tasks", "edge_prob", "ccr", "comp_min", "comp_max",
        "noc_rows", "noc_cols", "processor_count", "alpha", "beta", "seed",
        "achieved_ccr", "runtime_ms",
        "makespan", "primary_task_count", "duplicate_task_count",
        "duplication_ratio", "total_task_instance_count", "task_instance_ratio",
        "communication_count", "average_communication_latency",
        "total_communication_time", "average_link_utilization",
        "max_link_utilization", "average_processor_utilization",
        "max_processor_utilization",
        "total_computation_work", "serial_speedup",
        "baseline_makespan_heft", "speedup_vs_heft", "normalized_makespan_vs_heft",
    }

    def test_all_original_columns_still_present(self):
        df = _tiny_df()
        missing = self._ORIGINAL_COLUMNS - set(df.columns)
        assert not missing, f"Original columns missing after Phase 13: {missing}"

    def test_heft_original_speedup_still_one(self):
        df = _tiny_df()
        heft = df[df["scheduler"] == "heft"].iloc[0]
        assert heft["speedup_vs_heft"] == pytest.approx(1.0)

    def test_row_count_unchanged(self):
        df = _tiny_df()
        # 2 schedulers × 1 task_count × 1 edge_prob × 1 ccr × 1 noc × 1 seed = 2
        assert len(df) == 2

    def test_add_replay_relative_metrics_raises_without_heft(self):
        df = _make_replay_df(["contention_aware"], [100.0], [110.0])
        with pytest.raises(ValueError, match="[Hh][Ee][Ff][Tt]"):
            add_replay_relative_metrics(df)
