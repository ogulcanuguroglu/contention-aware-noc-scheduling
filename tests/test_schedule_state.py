"""
Tests for src/schedule_state.py.

Covers: construction, earliest_slot, reserve_task, task instance queries,
earliest_route_slot, reserve_route, reserve_communication, availability
helpers, clone, and validate_no_overlaps.
Implemented in Phase 4.
"""

import pytest

from src.models import Interval, Link, TaskInstance
from src.noc import MeshNoC
from src.schedule_state import ScheduleState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_noc() -> MeshNoC:
    return MeshNoC(rows=4, cols=4)


def make_state() -> ScheduleState:
    return ScheduleState(make_noc())


def _reserve(state: ScheduleState, task_id: int, proc: int, start: float, finish: float) -> TaskInstance:
    return state.reserve_task(task_id, proc, start, finish)


# ---------------------------------------------------------------------------
# 1. Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_valid_construction(self):
        state = make_state()
        assert state is not None

    def test_processor_intervals_initialized_for_all_processors(self):
        noc = make_noc()
        state = ScheduleState(noc)
        assert set(state.processor_intervals.keys()) == set(noc.processor_ids())
        for pid in noc.processor_ids():
            assert state.processor_intervals[pid] == []

    def test_link_intervals_initialized_for_all_directed_links(self):
        noc = make_noc()
        state = ScheduleState(noc)
        expected_links = set(noc.all_directed_links())
        assert set(state.link_intervals.keys()) == expected_links
        for link in noc.all_directed_links():
            assert state.link_intervals[link] == []

    def test_task_instances_empty(self):
        assert make_state().task_instances == {}

    def test_communication_instances_empty(self):
        assert make_state().communication_instances == []

    def test_rejects_non_meshnoc_input(self):
        with pytest.raises(ValueError):
            ScheduleState("not a noc")  # type: ignore[arg-type]

    def test_rejects_none_input(self):
        with pytest.raises(ValueError):
            ScheduleState(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. earliest_slot
# ---------------------------------------------------------------------------

class TestEarliestSlot:
    def test_empty_processor_returns_not_before(self):
        state = make_state()
        assert state.earliest_slot(0, 5.0, 0.0) == pytest.approx(0.0)

    def test_empty_processor_respects_not_before(self):
        state = make_state()
        assert state.earliest_slot(0, 5.0, 3.0) == pytest.approx(3.0)

    def test_after_one_interval_returns_finish(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        assert state.earliest_slot(0, 5.0, 0.0) == pytest.approx(10.0)

    def test_gap_fitting_works(self):
        # intervals [0,5), [10,15), duration=3, not_before=5 -> 5
        state = make_state()
        _reserve(state, 0, 0, 0.0, 5.0)
        _reserve(state, 1, 0, 10.0, 15.0)
        assert state.earliest_slot(0, 3.0, 5.0) == pytest.approx(5.0)

    def test_gap_too_small_skips_to_later(self):
        # intervals [0,5), [7,10), duration=3, not_before=5 -> 10
        state = make_state()
        _reserve(state, 0, 0, 0.0, 5.0)
        _reserve(state, 1, 0, 7.0, 10.0)
        assert state.earliest_slot(0, 3.0, 5.0) == pytest.approx(10.0)

    def test_back_to_back_allowed(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        assert state.earliest_slot(0, 5.0, 0.0) == pytest.approx(10.0)
        _reserve(state, 1, 0, 10.0, 15.0)
        assert state.earliest_slot(0, 5.0, 0.0) == pytest.approx(15.0)

    def test_not_before_inside_existing_interval_moves_to_finish(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        # not_before=5 is inside [0,10), so must wait until 10
        assert state.earliest_slot(0, 5.0, 5.0) == pytest.approx(10.0)

    def test_zero_duration_returns_not_before_when_possible(self):
        state = make_state()
        assert state.earliest_slot(0, 0.0, 3.0) == pytest.approx(3.0)

    def test_zero_duration_at_boundary(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 5.0)
        # zero-duration at 5 does not overlap [0,5)
        assert state.earliest_slot(0, 0.0, 5.0) == pytest.approx(5.0)

    def test_zero_duration_inside_existing_interval_returns_not_before(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        # zero-duration is empty, never conflicts
        assert state.earliest_slot(0, 0.0, 5.0) == pytest.approx(5.0)

    def test_invalid_processor_rejected(self):
        with pytest.raises(ValueError):
            make_state().earliest_slot(99, 5.0)

    def test_negative_duration_rejected(self):
        with pytest.raises(ValueError):
            make_state().earliest_slot(0, -1.0)

    def test_nan_duration_rejected(self):
        with pytest.raises(ValueError):
            make_state().earliest_slot(0, float("nan"))

    def test_infinity_duration_rejected(self):
        with pytest.raises(ValueError):
            make_state().earliest_slot(0, float("inf"))

    def test_negative_not_before_rejected(self):
        with pytest.raises(ValueError):
            make_state().earliest_slot(0, 5.0, -1.0)

    def test_bool_duration_rejected(self):
        with pytest.raises(ValueError):
            make_state().earliest_slot(0, True)  # type: ignore[arg-type]

    def test_bool_not_before_rejected(self):
        with pytest.raises(ValueError):
            make_state().earliest_slot(0, 5.0, True)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. reserve_task
# ---------------------------------------------------------------------------

class TestReserveTask:
    def test_returns_task_instance(self):
        ti = _reserve(make_state(), 0, 0, 0.0, 10.0)
        assert isinstance(ti, TaskInstance)

    def test_task_instance_fields(self):
        ti = _reserve(make_state(), 3, 2, 5.0, 15.0)
        assert ti.task_id == 3
        assert ti.processor_id == 2
        assert ti.start_time == pytest.approx(5.0)
        assert ti.finish_time == pytest.approx(15.0)
        assert ti.is_primary is True

    def test_adds_processor_interval(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        assert len(state.processor_intervals[0]) == 1
        iv = state.processor_intervals[0][0]
        assert iv.start_time == pytest.approx(0.0)
        assert iv.finish_time == pytest.approx(10.0)

    def test_adds_task_instance(self):
        state = make_state()
        _reserve(state, 7, 1, 0.0, 5.0)
        assert 7 in state.task_instances
        assert len(state.task_instances[7]) == 1

    def test_keeps_intervals_sorted(self):
        state = make_state()
        _reserve(state, 0, 0, 10.0, 20.0)
        _reserve(state, 1, 0, 0.0, 5.0)
        starts = [iv.start_time for iv in state.processor_intervals[0]]
        assert starts == sorted(starts)

    def test_rejects_overlapping_interval(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        with pytest.raises(ValueError):
            _reserve(state, 1, 0, 5.0, 15.0)

    def test_rejects_contained_interval(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 20.0)
        with pytest.raises(ValueError):
            _reserve(state, 1, 0, 5.0, 10.0)

    def test_allows_back_to_back_interval(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        ti = _reserve(state, 1, 0, 10.0, 20.0)
        assert ti.start_time == pytest.approx(10.0)

    def test_allows_zero_duration_task_interval(self):
        state = make_state()
        ti = _reserve(state, 0, 0, 5.0, 5.0)
        assert ti.start_time == pytest.approx(5.0)
        assert ti.finish_time == pytest.approx(5.0)

    def test_zero_duration_inside_existing_interval_succeeds(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        # [5,5) is empty — no overlap with [0,10)
        ti = _reserve(state, 1, 0, 5.0, 5.0)
        assert ti.start_time == pytest.approx(5.0)

    def test_zero_duration_inside_existing_interval_passes_validate(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        _reserve(state, 1, 0, 5.0, 5.0)
        state.validate_no_overlaps()  # must not raise

    def test_rejects_negative_task_id(self):
        with pytest.raises(ValueError):
            make_state().reserve_task(-1, 0, 0.0, 10.0)

    def test_rejects_bool_task_id(self):
        with pytest.raises(ValueError):
            make_state().reserve_task(True, 0, 0.0, 10.0)  # type: ignore[arg-type]

    def test_rejects_invalid_processor(self):
        with pytest.raises(ValueError):
            make_state().reserve_task(0, 99, 0.0, 10.0)

    def test_rejects_finish_before_start(self):
        with pytest.raises(ValueError):
            make_state().reserve_task(0, 0, 10.0, 5.0)

    def test_rejects_nan_start(self):
        with pytest.raises(ValueError):
            make_state().reserve_task(0, 0, float("nan"), 10.0)

    def test_rejects_nan_finish(self):
        with pytest.raises(ValueError):
            make_state().reserve_task(0, 0, 0.0, float("nan"))

    def test_rejects_infinity_start(self):
        with pytest.raises(ValueError):
            make_state().reserve_task(0, 0, float("inf"), float("inf"))

    def test_rejects_infinity_finish(self):
        with pytest.raises(ValueError):
            make_state().reserve_task(0, 0, 0.0, float("inf"))

    def test_non_primary_instance(self):
        state = make_state()
        ti = state.reserve_task(0, 0, 0.0, 10.0, is_primary=False)
        assert ti.is_primary is False

    def test_processor_interval_metadata(self):
        state = make_state()
        _reserve(state, 5, 2, 0.0, 10.0)
        iv = state.processor_intervals[2][0]
        assert iv.metadata["task_id"] == 5
        assert iv.metadata["type"] == "task"


# ---------------------------------------------------------------------------
# 4. Task instance queries
# ---------------------------------------------------------------------------

class TestTaskInstanceQueries:
    def test_has_task_instance_true(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        assert state.has_task_instance(0) is True

    def test_has_task_instance_false(self):
        assert make_state().has_task_instance(42) is False

    def test_has_task_instance_with_processor_filter_true(self):
        state = make_state()
        _reserve(state, 0, 3, 0.0, 10.0)
        assert state.has_task_instance(0, processor_id=3) is True

    def test_has_task_instance_with_processor_filter_false(self):
        state = make_state()
        _reserve(state, 0, 3, 0.0, 10.0)
        assert state.has_task_instance(0, processor_id=5) is False

    def test_get_task_instances_returns_copy(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        instances = state.get_task_instances(0)
        instances.clear()
        # Original must not be affected
        assert len(state.task_instances[0]) == 1

    def test_get_task_instances_empty_for_unknown_task(self):
        assert make_state().get_task_instances(99) == []

    def test_get_primary_instance_returns_primary(self):
        state = make_state()
        ti = _reserve(state, 0, 0, 0.0, 10.0)
        assert state.get_primary_instance(0) is ti

    def test_get_primary_instance_rejects_missing(self):
        with pytest.raises(ValueError):
            make_state().get_primary_instance(0)

    def test_get_primary_instance_rejects_multiple_primaries(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        # Manually add a second primary
        ti2 = TaskInstance(task_id=0, processor_id=1, start_time=0.0, finish_time=5.0, is_primary=True)
        state.task_instances[0].append(ti2)
        with pytest.raises(ValueError):
            state.get_primary_instance(0)

    def test_get_primary_instance_ignores_non_primary(self):
        state = make_state()
        ti_primary = _reserve(state, 0, 0, 0.0, 10.0)
        # Add duplicate non-primary on another processor
        state.reserve_task(0, 1, 0.0, 8.0, is_primary=False)
        assert state.get_primary_instance(0) is ti_primary

    def test_get_finish_time_primary(self):
        state = make_state()
        _reserve(state, 0, 0, 5.0, 15.0)
        assert state.get_finish_time(0) == pytest.approx(15.0)

    def test_get_finish_time_by_processor(self):
        state = make_state()
        _reserve(state, 0, 2, 3.0, 13.0)
        assert state.get_finish_time(0, processor_id=2) == pytest.approx(13.0)

    def test_get_finish_time_rejects_missing_task(self):
        with pytest.raises(ValueError):
            make_state().get_finish_time(99)

    def test_get_finish_time_rejects_missing_on_processor(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        with pytest.raises(ValueError):
            state.get_finish_time(0, processor_id=5)

    def test_get_finish_time_rejects_multiple_instances_on_same_processor(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        # Manually insert a second instance on the same processor (abnormal state)
        ti2 = TaskInstance(task_id=0, processor_id=0, start_time=15.0, finish_time=20.0, is_primary=False)
        state.task_instances[0].append(ti2)
        with pytest.raises(ValueError):
            state.get_finish_time(0, processor_id=0)


# ---------------------------------------------------------------------------
# 5. earliest_route_slot
# ---------------------------------------------------------------------------

class TestEarliestRouteSlot:
    def test_empty_route_returns_not_before(self):
        state = make_state()
        assert state.earliest_route_slot([], 5.0, 3.0) == pytest.approx(3.0)

    def test_free_route_returns_not_before(self):
        state = make_state()
        route = [Link(0, 1), Link(1, 5)]
        assert state.earliest_route_slot(route, 5.0, 2.0) == pytest.approx(2.0)

    def test_one_busy_link_delays_route(self):
        state = make_state()
        route = [Link(0, 1)]
        state.reserve_route(route, 0.0, 10.0)
        assert state.earliest_route_slot(route, 5.0, 0.0) == pytest.approx(10.0)

    def test_conflict_on_any_route_link_delays_entire_route(self):
        state = make_state()
        # Reserve only the second link
        state.reserve_route([Link(1, 5)], 0.0, 8.0)
        route = [Link(0, 1), Link(1, 5)]
        # Full route cannot start until Link(1,5) is free at t=8
        assert state.earliest_route_slot(route, 5.0, 0.0) == pytest.approx(8.0)

    def test_back_to_back_allowed_on_route(self):
        state = make_state()
        route = [Link(0, 1)]
        state.reserve_route(route, 0.0, 5.0)
        # duration=3, not_before=5 -> candidate=5, [0,5) does not conflict
        assert state.earliest_route_slot(route, 3.0, 5.0) == pytest.approx(5.0)

    def test_multiple_conflicts_handled_correctly(self):
        state = make_state()
        route = [Link(0, 1), Link(1, 5)]
        # Two occupying intervals on Link(0,1): [0,5) and [8,12)
        state.reserve_route([Link(0, 1)], 0.0, 5.0)
        state.reserve_route([Link(0, 1)], 8.0, 12.0)
        # duration=3, not_before=0: candidate=0->5 (conflict [0,5)), then
        # 5+3=8<=8 fits; but check [8,12) on Link(0,1): 8<8? no. Return 5.
        assert state.earliest_route_slot(route, 3.0, 0.0) == pytest.approx(5.0)

    def test_multiple_overlapping_conflicts_chain(self):
        state = make_state()
        route = [Link(0, 1)]
        # Consecutive busy slots: [0,5) and [5,10)
        state.reserve_route(route, 0.0, 5.0)
        state.reserve_route(route, 5.0, 10.0)
        # duration=3, not_before=0: must wait until 10
        assert state.earliest_route_slot(route, 3.0, 0.0) == pytest.approx(10.0)

    def test_invalid_link_rejected(self):
        state = make_state()
        with pytest.raises(ValueError):
            state.earliest_route_slot([Link(0, 15)], 5.0, 0.0)

    def test_negative_duration_rejected(self):
        with pytest.raises(ValueError):
            make_state().earliest_route_slot([Link(0, 1)], -1.0)

    def test_nan_duration_rejected(self):
        with pytest.raises(ValueError):
            make_state().earliest_route_slot([Link(0, 1)], float("nan"))

    def test_bool_duration_rejected(self):
        with pytest.raises(ValueError):
            make_state().earliest_route_slot([Link(0, 1)], True)  # type: ignore[arg-type]

    def test_zero_duration_inside_busy_link_returns_not_before(self):
        state = make_state()
        state.reserve_route([Link(0, 1)], 0.0, 10.0)
        # zero-duration never conflicts
        assert state.earliest_route_slot([Link(0, 1)], 0.0, 5.0) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# 6. reserve_route
# ---------------------------------------------------------------------------

class TestReserveRoute:
    def test_reserves_interval_on_every_link(self):
        state = make_state()
        route = [Link(0, 1), Link(1, 5)]
        state.reserve_route(route, 0.0, 10.0)
        assert len(state.link_intervals[Link(0, 1)]) == 1
        assert len(state.link_intervals[Link(1, 5)]) == 1

    def test_keeps_link_intervals_sorted(self):
        state = make_state()
        route = [Link(0, 1)]
        state.reserve_route(route, 10.0, 15.0)
        state.reserve_route(route, 0.0, 5.0)
        starts = [iv.start_time for iv in state.link_intervals[Link(0, 1)]]
        assert starts == sorted(starts)

    def test_rejects_overlap_on_any_link(self):
        state = make_state()
        state.reserve_route([Link(0, 1)], 0.0, 10.0)
        with pytest.raises(ValueError):
            state.reserve_route([Link(0, 1)], 5.0, 15.0)

    def test_allows_back_to_back_intervals(self):
        state = make_state()
        route = [Link(0, 1)]
        state.reserve_route(route, 0.0, 5.0)
        state.reserve_route(route, 5.0, 10.0)
        assert len(state.link_intervals[Link(0, 1)]) == 2

    def test_preserves_metadata(self):
        state = make_state()
        meta = {"type": "communication", "task_id": 7}
        state.reserve_route([Link(0, 1)], 0.0, 5.0, metadata=meta)
        iv = state.link_intervals[Link(0, 1)][0]
        assert iv.metadata == meta

    def test_none_metadata_allowed(self):
        state = make_state()
        state.reserve_route([Link(0, 1)], 0.0, 5.0, metadata=None)
        iv = state.link_intervals[Link(0, 1)][0]
        assert iv.metadata is None

    def test_invalid_link_rejected(self):
        with pytest.raises(ValueError):
            make_state().reserve_route([Link(0, 15)], 0.0, 5.0)

    def test_zero_duration_inside_existing_link_interval_succeeds(self):
        state = make_state()
        state.reserve_route([Link(0, 1)], 0.0, 10.0)
        # [5,5) is empty — no overlap with [0,10)
        state.reserve_route([Link(0, 1)], 5.0, 5.0)
        assert len(state.link_intervals[Link(0, 1)]) == 2

    def test_zero_duration_route_passes_validate(self):
        state = make_state()
        state.reserve_route([Link(0, 1)], 0.0, 10.0)
        state.reserve_route([Link(0, 1)], 5.0, 5.0)
        state.validate_no_overlaps()  # must not raise

    def test_atomic_reservation_no_partial_commit(self):
        state = make_state()
        # Reserve Link(1,5) so second link in route will conflict
        state.reserve_route([Link(1, 5)], 0.0, 10.0)
        with pytest.raises(ValueError):
            state.reserve_route([Link(0, 1), Link(1, 5)], 0.0, 5.0)
        # Link(0,1) must NOT have been reserved (atomic check)
        assert len(state.link_intervals[Link(0, 1)]) == 0


# ---------------------------------------------------------------------------
# 7. reserve_communication
# ---------------------------------------------------------------------------

class TestReserveCommunication:
    def test_local_communication_zero_duration(self):
        state = make_state()
        ci = state.reserve_communication(0, 1, 3, 3, 5.0, 2.0)
        assert ci.start_time == pytest.approx(5.0)
        assert ci.finish_time == pytest.approx(5.0)
        assert ci.duration == pytest.approx(0.0)

    def test_local_communication_does_not_reserve_links(self):
        state = make_state()
        state.reserve_communication(0, 1, 3, 3, 0.0, 2.0)
        for link, intervals in state.link_intervals.items():
            assert intervals == [], f"Link {link} unexpectedly has intervals"

    def test_local_communication_added_to_instances(self):
        state = make_state()
        state.reserve_communication(0, 1, 3, 3, 0.0, 1.0)
        assert len(state.communication_instances) == 1

    def test_remote_communication_uses_noc_route(self):
        state = make_state()
        noc = make_noc()
        ci = state.reserve_communication(0, 1, 0, 5, 0.0, 1.0)
        # 0=(0,0) -> 5=(1,1): XY route is [Link(0,1), Link(1,5)]
        expected_route = noc.get_route(0, 5)
        assert ci.route == expected_route

    def test_remote_communication_reserves_all_route_links(self):
        state = make_state()
        state.reserve_communication(0, 1, 0, 5, 0.0, 1.0)
        assert len(state.link_intervals[Link(0, 1)]) == 1
        assert len(state.link_intervals[Link(1, 5)]) == 1

    def test_remote_communication_start_respects_ready_time(self):
        state = make_state()
        ci = state.reserve_communication(0, 1, 0, 5, 10.0, 1.0)
        assert ci.start_time >= 10.0

    def test_remote_communication_duration_formula(self):
        # alpha=1, beta=1, hops=2 (0->5), volume=1.0 -> duration=3
        state = make_state()
        ci = state.reserve_communication(0, 1, 0, 5, 0.0, 1.0)
        assert ci.finish_time - ci.start_time == pytest.approx(3.0)

    def test_remote_communication_delayed_by_link_contention(self):
        state = make_state()
        ci1 = state.reserve_communication(0, 1, 0, 5, 0.0, 1.0)
        ci2 = state.reserve_communication(2, 3, 0, 5, 0.0, 1.0)
        assert ci2.start_time >= ci1.finish_time

    def test_communication_instances_appended(self):
        state = make_state()
        state.reserve_communication(0, 1, 0, 5, 0.0, 1.0)
        state.reserve_communication(2, 3, 1, 2, 0.0, 1.0)
        assert len(state.communication_instances) == 2

    def test_rejects_source_task_equal_target_task(self):
        with pytest.raises(ValueError):
            make_state().reserve_communication(2, 2, 0, 5, 0.0, 1.0)

    def test_rejects_invalid_source_processor(self):
        with pytest.raises(ValueError):
            make_state().reserve_communication(0, 1, 99, 5, 0.0, 1.0)

    def test_rejects_invalid_destination_processor(self):
        with pytest.raises(ValueError):
            make_state().reserve_communication(0, 1, 0, 99, 0.0, 1.0)

    def test_rejects_negative_ready_time(self):
        with pytest.raises(ValueError):
            make_state().reserve_communication(0, 1, 0, 5, -1.0, 1.0)

    def test_rejects_negative_communication_volume(self):
        with pytest.raises(ValueError):
            make_state().reserve_communication(0, 1, 0, 5, 0.0, -1.0)

    def test_rejects_nan_communication_volume(self):
        with pytest.raises(ValueError):
            make_state().reserve_communication(0, 1, 0, 5, 0.0, float("nan"))

    def test_rejects_bool_communication_volume(self):
        with pytest.raises(ValueError):
            make_state().reserve_communication(0, 1, 0, 5, 0.0, True)  # type: ignore[arg-type]

    def test_rejects_bool_source_task(self):
        with pytest.raises(ValueError):
            make_state().reserve_communication(True, 1, 0, 5, 0.0, 1.0)  # type: ignore[arg-type]

    def test_rejects_bool_target_task(self):
        with pytest.raises(ValueError):
            make_state().reserve_communication(0, True, 0, 5, 0.0, 1.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 8. Availability and max finish helpers
# ---------------------------------------------------------------------------

class TestAvailabilityHelpers:
    def test_processor_available_time_empty_returns_zero(self):
        assert make_state().processor_available_time(0) == pytest.approx(0.0)

    def test_processor_available_time_after_one_reservation(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        assert state.processor_available_time(0) == pytest.approx(10.0)

    def test_processor_available_time_after_two_reservations(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        _reserve(state, 1, 0, 10.0, 25.0)
        assert state.processor_available_time(0) == pytest.approx(25.0)

    def test_link_available_time_empty_returns_zero(self):
        assert make_state().link_available_time(Link(0, 1)) == pytest.approx(0.0)

    def test_link_available_time_after_route_reservation(self):
        state = make_state()
        state.reserve_route([Link(0, 1), Link(1, 5)], 0.0, 7.0)
        assert state.link_available_time(Link(0, 1)) == pytest.approx(7.0)
        assert state.link_available_time(Link(1, 5)) == pytest.approx(7.0)

    def test_max_processor_finish_time_empty_returns_zero(self):
        assert make_state().max_processor_finish_time() == pytest.approx(0.0)

    def test_max_processor_finish_time_after_reservations(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        _reserve(state, 1, 1, 0.0, 25.0)
        _reserve(state, 2, 2, 0.0, 5.0)
        assert state.max_processor_finish_time() == pytest.approx(25.0)

    def test_max_link_finish_time_empty_returns_zero(self):
        assert make_state().max_link_finish_time() == pytest.approx(0.0)

    def test_max_link_finish_time_after_reservations(self):
        state = make_state()
        state.reserve_route([Link(0, 1)], 0.0, 10.0)
        state.reserve_route([Link(1, 5)], 0.0, 20.0)
        assert state.max_link_finish_time() == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# 9. clone
# ---------------------------------------------------------------------------

class TestClone:
    def test_clone_has_same_content_initially(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        clone = state.clone()
        assert clone.get_finish_time(0) == pytest.approx(10.0)

    def test_modifying_clone_does_not_affect_original(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        clone = state.clone()
        _reserve(clone, 1, 1, 0.0, 15.0)
        # Task 1 must not appear in original
        assert not state.has_task_instance(1)
        # Processor 1 intervals in original must remain empty
        assert state.processor_intervals[1] == []

    def test_modifying_original_does_not_affect_clone(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        clone = state.clone()
        _reserve(state, 2, 2, 0.0, 8.0)
        # Clone must not see task 2
        assert not clone.has_task_instance(2)

    def test_clone_communication_instances_independent(self):
        state = make_state()
        state.reserve_communication(0, 1, 0, 5, 0.0, 1.0)
        clone = state.clone()
        state.reserve_communication(2, 3, 1, 2, 0.0, 1.0)
        # Clone should still have only 1 communication instance
        assert len(clone.communication_instances) == 1


# ---------------------------------------------------------------------------
# 10. validate_no_overlaps
# ---------------------------------------------------------------------------

class TestValidateNoOverlaps:
    def test_passes_for_valid_schedule(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        _reserve(state, 1, 0, 10.0, 20.0)
        state.validate_no_overlaps()  # must not raise

    def test_passes_on_empty_state(self):
        make_state().validate_no_overlaps()  # must not raise

    def test_detects_processor_overlap_if_manually_inserted(self):
        state = make_state()
        _reserve(state, 0, 0, 0.0, 10.0)
        # Bypass reserve_task to inject an overlapping interval
        state.processor_intervals[0].append(
            Interval(start_time=5.0, finish_time=15.0)
        )
        with pytest.raises(ValueError):
            state.validate_no_overlaps()

    def test_detects_link_overlap_if_manually_inserted(self):
        state = make_state()
        state.reserve_route([Link(0, 1)], 0.0, 10.0)
        state.link_intervals[Link(0, 1)].append(
            Interval(start_time=5.0, finish_time=15.0)
        )
        with pytest.raises(ValueError):
            state.validate_no_overlaps()

    def test_zero_duration_on_processor_does_not_trigger_overlap(self):
        state = make_state()
        state.processor_intervals[0].append(Interval(start_time=0.0, finish_time=10.0))
        state.processor_intervals[0].append(Interval(start_time=5.0, finish_time=5.0))
        state.validate_no_overlaps()  # must not raise

    def test_zero_duration_on_link_does_not_trigger_overlap(self):
        state = make_state()
        state.link_intervals[Link(0, 1)].append(Interval(start_time=0.0, finish_time=10.0))
        state.link_intervals[Link(0, 1)].append(Interval(start_time=5.0, finish_time=5.0))
        state.validate_no_overlaps()  # must not raise
