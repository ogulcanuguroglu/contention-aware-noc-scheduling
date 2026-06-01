"""
Tests for src/metrics.py.

Uses small, manually constructed ScheduleState objects built on a 2×2 mesh
(4 processors, 8 directed links) so expected values can be computed by hand.

Coordinate system (2×2 mesh, row-major: pid = y*cols + x):
    P0=(x=0,y=0)  P1=(x=1,y=0)
    P2=(x=0,y=1)  P3=(x=1,y=1)

Directed links (XY-routing neighbours):
    horizontal: Link(0,1), Link(1,0), Link(2,3), Link(3,2)
    vertical:   Link(0,2), Link(2,0), Link(1,3), Link(3,1)
    Total: 8 directed links.

With alpha=0, beta=1: comm_duration = vol.
Implemented in Phase 9.
"""

import pytest

from src.models import Link
from src.noc import MeshNoC
from src.schedule_state import ScheduleState
import src.metrics as metrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_noc(rows: int = 2, cols: int = 2,
             alpha: float = 0.0, beta: float = 1.0) -> MeshNoC:
    return MeshNoC(rows=rows, cols=cols, alpha=alpha, beta=beta)


def make_state(noc: MeshNoC | None = None) -> ScheduleState:
    return ScheduleState(noc if noc is not None else make_noc())


# ---------------------------------------------------------------------------
# 1. Empty state
# ---------------------------------------------------------------------------

class TestEmptyState:
    def test_makespan_zero(self):
        assert metrics.compute_makespan(make_state()) == pytest.approx(0.0)

    def test_primary_count_zero(self):
        assert metrics.count_primary_tasks(make_state()) == 0

    def test_duplicate_count_zero(self):
        assert metrics.count_duplicate_tasks(make_state()) == 0

    def test_duplication_ratio_zero(self):
        assert metrics.duplication_ratio(make_state()) == pytest.approx(0.0)

    def test_communication_count_zero(self):
        assert metrics.count_communication_instances(make_state()) == 0

    def test_average_latency_zero(self):
        assert metrics.average_communication_latency(make_state()) == pytest.approx(0.0)

    def test_total_comm_time_zero(self):
        assert metrics.total_communication_time(make_state()) == pytest.approx(0.0)

    def test_average_link_utilization_zero(self):
        assert metrics.average_link_utilization(make_state()) == pytest.approx(0.0)

    def test_max_link_utilization_zero(self):
        assert metrics.max_link_utilization(make_state()) == pytest.approx(0.0)

    def test_average_processor_utilization_zero(self):
        assert metrics.average_processor_utilization(make_state()) == pytest.approx(0.0)

    def test_max_processor_utilization_zero(self):
        assert metrics.max_processor_utilization(make_state()) == pytest.approx(0.0)

    def test_count_total_task_instances_zero(self):
        assert metrics.count_total_task_instances(make_state()) == 0

    def test_task_instance_ratio_zero(self):
        assert metrics.task_instance_ratio(make_state()) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 2. Task counts and duplication ratio
# ---------------------------------------------------------------------------

class TestTaskCounts:
    def test_primary_count_two_tasks(self):
        noc = make_noc()
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 5.0, is_primary=True)
        state.reserve_task(1, 1, 0.0, 3.0, is_primary=True)
        assert metrics.count_primary_tasks(state) == 2
        assert metrics.count_duplicate_tasks(state) == 0

    def test_duplicate_count(self):
        noc = make_noc()
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 5.0, is_primary=True)
        state.reserve_task(0, 1, 0.0, 5.0, is_primary=False)
        assert metrics.count_primary_tasks(state) == 1
        assert metrics.count_duplicate_tasks(state) == 1

    def test_duplication_ratio_half(self):
        # 2 primaries, 1 duplicate → ratio = 0.5
        noc = make_noc()
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 5.0, is_primary=True)
        state.reserve_task(1, 1, 0.0, 3.0, is_primary=True)
        state.reserve_task(0, 2, 0.0, 5.0, is_primary=False)
        assert metrics.duplication_ratio(state) == pytest.approx(0.5)

    def test_duplication_ratio_zero_no_primary(self):
        assert metrics.duplication_ratio(make_state()) == pytest.approx(0.0)

    def test_duplication_ratio_zero_no_dups(self):
        noc = make_noc()
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 5.0, is_primary=True)
        assert metrics.duplication_ratio(state) == pytest.approx(0.0)

    def test_duplication_ratio_one(self):
        # 1 primary, 1 duplicate → ratio = 1.0
        noc = make_noc()
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 5.0, is_primary=True)
        state.reserve_task(0, 1, 0.0, 5.0, is_primary=False)
        assert metrics.duplication_ratio(state) == pytest.approx(1.0)

    def test_instance_ratio_mixed(self):
        # 2 primaries, 1 duplicate →
        #   count_primary=2, count_duplicate=1, count_total=3
        #   duplication_ratio = 1/2 = 0.5
        #   task_instance_ratio = 3/2 = 1.5
        noc = make_noc()
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 5.0, is_primary=True)
        state.reserve_task(1, 1, 0.0, 3.0, is_primary=True)
        state.reserve_task(0, 2, 0.0, 5.0, is_primary=False)
        assert metrics.count_primary_tasks(state) == 2
        assert metrics.count_duplicate_tasks(state) == 1
        assert metrics.count_total_task_instances(state) == 3
        assert metrics.duplication_ratio(state) == pytest.approx(0.5)
        assert metrics.task_instance_ratio(state) == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# 3. Communication metrics
# ---------------------------------------------------------------------------

class TestCommunicationMetrics:
    """
    P0→P1 remote comm.  alpha=0, beta=1 → duration = vol.
    task0 on P0 [0, 5]; task1 on P1 [0, 3]; comm P0→P1 vol=10 → dur=10, [5,15).
    """

    def _setup(self):
        noc = make_noc(alpha=0.0, beta=1.0)
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 5.0, is_primary=True)
        state.reserve_task(1, 1, 0.0, 3.0, is_primary=True)
        ci = state.reserve_communication(
            source_task=0, target_task=1,
            source_processor=0, destination_processor=1,
            ready_time=5.0, communication_volume=10.0,
        )
        return state, ci

    def test_communication_count(self):
        state, _ = self._setup()
        assert metrics.count_communication_instances(state) == 1

    def test_average_latency_equals_single_duration(self):
        state, ci = self._setup()
        assert metrics.average_communication_latency(state) == pytest.approx(ci.duration)

    def test_total_comm_time_equals_duration(self):
        state, ci = self._setup()
        assert metrics.total_communication_time(state) == pytest.approx(ci.duration)

    def test_two_comms_average_latency(self):
        noc = make_noc(alpha=0.0, beta=1.0)
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 5.0, is_primary=True)
        state.reserve_task(1, 1, 0.0, 3.0, is_primary=True)
        state.reserve_task(2, 2, 0.0, 3.0, is_primary=True)
        # comm 0→1 vol=10 dur=10, comm 0→2 vol=4 dur=4
        state.reserve_communication(0, 1, 0, 1, 5.0, 10.0)
        state.reserve_communication(0, 2, 0, 2, 5.0, 4.0)
        assert metrics.average_communication_latency(state) == pytest.approx(7.0)
        assert metrics.total_communication_time(state) == pytest.approx(14.0)

    def test_local_comm_has_zero_duration(self):
        # Local communication (same processor): vol is irrelevant, duration=0
        noc = make_noc(alpha=1.0, beta=1.0)
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 5.0, is_primary=True)
        state.reserve_task(1, 0, 5.0, 8.0, is_primary=True)
        ci = state.reserve_communication(0, 1, 0, 0, 5.0, 10.0)
        assert ci.duration == pytest.approx(0.0)
        assert metrics.average_communication_latency(state) == pytest.approx(0.0)
        assert metrics.total_communication_time(state) == pytest.approx(0.0)

    def test_no_comms_total_zero(self):
        assert metrics.total_communication_time(make_state()) == pytest.approx(0.0)

    def test_no_comms_average_zero(self):
        assert metrics.average_communication_latency(make_state()) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 4. Link utilization
# ---------------------------------------------------------------------------

class TestLinkUtilization:
    """
    task0 on P0 [0,10].  Comm P0→P1 vol=10 dur=10, route=[Link(0,1)], [10,20).
    Makespan = 20 (comm finish dominates).
    2×2 mesh has 8 directed links.
    Only Link(0,1) is busy for 10 units; all others idle.
    avg_util = 10 / (8 * 20) = 10/160 = 0.0625
    max_util = 10 / 20 = 0.5
    """

    def _setup(self):
        noc = make_noc(alpha=0.0, beta=1.0)
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 10.0, is_primary=True)
        state.reserve_task(1, 1, 20.0, 23.0, is_primary=True)
        ci = state.reserve_communication(
            source_task=0, target_task=1,
            source_processor=0, destination_processor=1,
            ready_time=10.0, communication_volume=10.0,
        )
        return state, ci, noc

    def test_link_busy_time_non_zero_for_used_link(self):
        state, ci, noc = self._setup()
        busy = metrics.link_busy_time(state)
        link_01 = Link(0, 1)
        assert busy[link_01] == pytest.approx(ci.duration)

    def test_link_busy_time_zero_for_unused_links(self):
        state, ci, noc = self._setup()
        busy = metrics.link_busy_time(state)
        for link, val in busy.items():
            if link != Link(0, 1):
                assert val == pytest.approx(0.0)

    def test_link_busy_time_all_links_present(self):
        state, _, noc = self._setup()
        busy = metrics.link_busy_time(state)
        assert set(busy.keys()) == set(noc.all_directed_links())

    def test_average_link_utilization_value(self):
        state, ci, noc = self._setup()
        ms = metrics.compute_makespan(state)
        n_links = len(list(noc.all_directed_links()))
        expected = ci.duration / (n_links * ms)
        assert metrics.average_link_utilization(state) == pytest.approx(expected)

    def test_max_link_utilization_value(self):
        state, ci, noc = self._setup()
        ms = metrics.compute_makespan(state)
        expected = ci.duration / ms
        assert metrics.max_link_utilization(state) == pytest.approx(expected)

    def test_explicit_makespan_respected(self):
        state, ci, noc = self._setup()
        n_links = len(list(noc.all_directed_links()))
        ms = 100.0
        expected_avg = ci.duration / (n_links * ms)
        assert metrics.average_link_utilization(state, makespan=ms) == pytest.approx(expected_avg)
        assert metrics.max_link_utilization(state, makespan=ms) == pytest.approx(ci.duration / ms)

    def test_zero_makespan_returns_zero(self):
        state = make_state()
        assert metrics.average_link_utilization(state, makespan=0.0) == pytest.approx(0.0)
        assert metrics.max_link_utilization(state, makespan=0.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 5. Processor utilization
# ---------------------------------------------------------------------------

class TestProcessorUtilization:
    """
    P0 has two tasks: [0,10] and [10,15] → busy=15.
    P1 has one task:  [0,5]             → busy=5.
    P2, P3 idle → busy=0.
    Makespan = 15.
    avg_proc_util = (15+5+0+0) / (4 * 15) = 20/60 ≈ 0.3333
    max_proc_util = 15/15 = 1.0
    """

    def _setup(self):
        noc = make_noc()
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 10.0, is_primary=True)
        state.reserve_task(1, 0, 10.0, 15.0, is_primary=True)
        state.reserve_task(2, 1, 0.0, 5.0, is_primary=True)
        return state

    def test_processor_busy_time_values(self):
        state = self._setup()
        busy = metrics.processor_busy_time(state)
        assert busy[0] == pytest.approx(15.0)
        assert busy[1] == pytest.approx(5.0)
        assert busy[2] == pytest.approx(0.0)
        assert busy[3] == pytest.approx(0.0)

    def test_processor_busy_time_all_procs_present(self):
        state = self._setup()
        busy = metrics.processor_busy_time(state)
        assert set(busy.keys()) == {0, 1, 2, 3}

    def test_average_processor_utilization(self):
        state = self._setup()
        ms = metrics.compute_makespan(state)
        n_procs = 4
        expected = (15.0 + 5.0 + 0.0 + 0.0) / (n_procs * ms)
        assert metrics.average_processor_utilization(state) == pytest.approx(expected)

    def test_max_processor_utilization(self):
        state = self._setup()
        ms = metrics.compute_makespan(state)
        expected = 15.0 / ms  # P0 is fully utilized
        assert metrics.max_processor_utilization(state) == pytest.approx(expected)

    def test_explicit_makespan_respected(self):
        state = self._setup()
        ms = 100.0
        n_procs = 4
        expected_avg = (15.0 + 5.0) / (n_procs * ms)
        assert metrics.average_processor_utilization(state, makespan=ms) == pytest.approx(expected_avg)
        assert metrics.max_processor_utilization(state, makespan=ms) == pytest.approx(15.0 / ms)

    def test_zero_makespan_returns_zero(self):
        state = make_state()
        assert metrics.average_processor_utilization(state, makespan=0.0) == pytest.approx(0.0)
        assert metrics.max_processor_utilization(state, makespan=0.0) == pytest.approx(0.0)

    def test_duplicate_intervals_included_in_busy_time(self):
        # Duplicate tasks also consume processor time
        noc = make_noc()
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 10.0, is_primary=True)
        state.reserve_task(0, 1, 0.0, 10.0, is_primary=False)  # dup
        busy = metrics.processor_busy_time(state)
        assert busy[0] == pytest.approx(10.0)
        assert busy[1] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 6. Speedup
# ---------------------------------------------------------------------------

class TestSpeedup:
    def test_normal_case(self):
        assert metrics.speedup(100.0, 50.0) == pytest.approx(2.0)

    def test_equal_gives_one(self):
        assert metrics.speedup(50.0, 50.0) == pytest.approx(1.0)

    def test_zero_zero_gives_one(self):
        assert metrics.speedup(0.0, 0.0) == pytest.approx(1.0)

    def test_scheduler_zero_nonzero_baseline_raises(self):
        with pytest.raises(ValueError):
            metrics.speedup(100.0, 0.0)

    def test_negative_baseline_raises(self):
        with pytest.raises(ValueError):
            metrics.speedup(-1.0, 50.0)

    def test_negative_scheduler_raises(self):
        with pytest.raises(ValueError):
            metrics.speedup(100.0, -1.0)

    def test_nan_baseline_raises(self):
        with pytest.raises(ValueError):
            metrics.speedup(float("nan"), 50.0)

    def test_inf_scheduler_raises(self):
        with pytest.raises(ValueError):
            metrics.speedup(100.0, float("inf"))

    def test_bool_rejected(self):
        with pytest.raises(ValueError):
            metrics.speedup(True, 50.0)

    def test_string_rejected(self):
        with pytest.raises(ValueError):
            metrics.speedup("100", 50.0)  # type: ignore[arg-type]

    def test_slower_scheduler_less_than_one(self):
        # scheduler is slower than baseline → speedup < 1
        assert metrics.speedup(50.0, 100.0) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 7. schedule_summary
# ---------------------------------------------------------------------------

class TestScheduleSummary:
    _REQUIRED_KEYS = [
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
    ]

    def test_empty_state_has_all_keys(self):
        summary = metrics.schedule_summary(make_state())
        for key in self._REQUIRED_KEYS:
            assert key in summary, f"Missing key: {key}"

    def test_values_match_individual_functions(self):
        noc = make_noc(alpha=0.0, beta=1.0)
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 10.0, is_primary=True)
        state.reserve_task(1, 1, 0.0, 5.0, is_primary=True)
        state.reserve_task(0, 2, 0.0, 10.0, is_primary=False)
        state.reserve_communication(0, 1, 0, 1, 10.0, 5.0)

        summary = metrics.schedule_summary(state)
        ms = metrics.compute_makespan(state)

        assert summary["makespan"] == pytest.approx(ms)
        assert summary["primary_task_count"] == metrics.count_primary_tasks(state)
        assert summary["duplicate_task_count"] == metrics.count_duplicate_tasks(state)
        assert summary["duplication_ratio"] == pytest.approx(metrics.duplication_ratio(state))
        assert summary["communication_count"] == metrics.count_communication_instances(state)
        assert summary["average_communication_latency"] == pytest.approx(
            metrics.average_communication_latency(state)
        )
        assert summary["total_communication_time"] == pytest.approx(
            metrics.total_communication_time(state)
        )
        assert summary["average_link_utilization"] == pytest.approx(
            metrics.average_link_utilization(state, ms)
        )
        assert summary["max_link_utilization"] == pytest.approx(
            metrics.max_link_utilization(state, ms)
        )
        assert summary["average_processor_utilization"] == pytest.approx(
            metrics.average_processor_utilization(state, ms)
        )
        assert summary["max_processor_utilization"] == pytest.approx(
            metrics.max_processor_utilization(state, ms)
        )
        assert summary["total_task_instance_count"] == metrics.count_total_task_instances(state)
        assert summary["task_instance_ratio"] == pytest.approx(metrics.task_instance_ratio(state))

    def test_rejects_non_state(self):
        with pytest.raises(ValueError):
            metrics.schedule_summary("not a state")  # type: ignore[arg-type]

    def test_compute_makespan_rejects_non_state(self):
        with pytest.raises(ValueError):
            metrics.compute_makespan(42)  # type: ignore[arg-type]
