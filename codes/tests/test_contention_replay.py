"""
Tests for src/contention_replay.py.

Phase 12: Contention replay evaluator for fair multi-scheduler comparison.

Covers:
  1. Construction / API
  2. Single task
  3. Local dependency (no CommunicationInstance)
  4. Remote dependency (one CommunicationInstance, route link reserved)
  5. Link contention (two comms sharing a link, serialized)
  6. Preserves placement (task -> processor mapping)
  7. Preserves duplicates (is_primary flag)
  8. Validation — exactly one primary per DAG task
  9. Original state isolation
  10. HEFT / CD-LS fair replay (materializes comms even if original had none)
  11. CA-LS / CA-D compatibility (works when state already has comms)
  12. Validation edge cases

All scenarios use a 2x2 NoC with alpha=0, beta=1 unless otherwise noted.
Processor layout (row-major): P0=(x=0,y=0), P1=(x=1,y=0), P2=(x=0,y=1), P3=(x=1,y=1).
Route P0->P1: [Link(0,1)], 1 hop, comm_duration = beta * vol = vol.
Route P0->P2: [Link(0,2)], 1 hop, comm_duration = vol.
"""

import networkx as nx
import pytest

from src.models import DAGGraph, Link, TaskInstance
from src.noc import MeshNoC
from src.schedule_state import ScheduleState
from src.contention_replay import (
    replay_under_contention,
    contention_replayed_makespan,
    summarize_replay,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_noc(rows: int = 2, cols: int = 2, alpha: float = 0.0, beta: float = 1.0) -> MeshNoC:
    return MeshNoC(rows=rows, cols=cols, alpha=alpha, beta=beta)


def _dag(nodes: dict[int, float], edges: list[tuple[int, int, float]]) -> DAGGraph:
    """Build a DAGGraph from dicts: nodes={task_id: cost}, edges=[(u, v, vol)]."""
    g = nx.DiGraph()
    for tid, cost in nodes.items():
        g.add_node(tid, computation_cost=cost)
    for u, v, vol in edges:
        g.add_edge(u, v, communication_volume=vol)
    return DAGGraph(g)


def _state(noc: MeshNoC, placements: list[tuple]) -> ScheduleState:
    """Build a ScheduleState with manually specified task placements.

    placements: list of (task_id, proc_id, start, finish, is_primary)
    """
    state = ScheduleState(noc)
    for task_id, proc_id, start, finish, is_primary in placements:
        state.reserve_task(task_id, proc_id, start, finish, is_primary)
    return state


# ---------------------------------------------------------------------------
# Group 1: Construction / API
# ---------------------------------------------------------------------------

class TestAPI:
    def test_returns_schedule_state(self):
        noc = make_noc()
        dag = _dag({0: 10.0}, [])
        state = _state(noc, [(0, 0, 0, 10, True)])
        assert isinstance(replay_under_contention(dag, state, noc), ScheduleState)

    def test_makespan_returns_float(self):
        noc = make_noc()
        dag = _dag({0: 10.0}, [])
        state = _state(noc, [(0, 0, 0, 10, True)])
        assert isinstance(contention_replayed_makespan(dag, state, noc), float)

    def test_summarize_replay_has_five_keys(self):
        noc = make_noc()
        dag = _dag({0: 10.0}, [])
        original = _state(noc, [(0, 0, 0, 10, True)])
        replayed = replay_under_contention(dag, original, noc)
        summary = summarize_replay(original, replayed)
        assert set(summary.keys()) == {
            "original_makespan",
            "replayed_makespan",
            "original_comm_count",
            "replayed_comm_count",
            "task_instance_count",
        }

    def test_summarize_replay_values_are_numeric(self):
        noc = make_noc()
        dag = _dag({0: 10.0}, [])
        original = _state(noc, [(0, 0, 0, 10, True)])
        replayed = replay_under_contention(dag, original, noc)
        for v in summarize_replay(original, replayed).values():
            assert isinstance(v, (int, float))

    def test_rejects_raw_digraph_as_dag(self):
        noc = make_noc()
        dag = _dag({0: 10.0}, [])
        state = _state(noc, [(0, 0, 0, 10, True)])
        raw_g = nx.DiGraph()
        raw_g.add_node(0, computation_cost=10.0)
        with pytest.raises(ValueError, match="DAGGraph"):
            replay_under_contention(raw_g, state, noc)

    def test_rejects_non_schedule_state(self):
        noc = make_noc()
        dag = _dag({0: 10.0}, [])
        with pytest.raises(ValueError, match="ScheduleState"):
            replay_under_contention(dag, object(), noc)

    def test_rejects_non_mesh_noc(self):
        noc = make_noc()
        dag = _dag({0: 10.0}, [])
        state = _state(noc, [(0, 0, 0, 10, True)])
        with pytest.raises(ValueError, match="MeshNoC"):
            replay_under_contention(dag, state, object())


# ---------------------------------------------------------------------------
# Group 2: Single task
# ---------------------------------------------------------------------------

class TestSingleTask:
    """One task, one processor. Verify minimal replay behavior."""

    @pytest.fixture
    def setup(self):
        noc = make_noc()
        dag = _dag({0: 10.0}, [])
        original = _state(noc, [(0, 0, 0, 10, True)])
        return dag, noc, original, replay_under_contention(dag, original, noc)

    def test_one_task_instance_created(self, setup):
        _, _, _, replayed = setup
        assert len(replayed.get_task_instances(0)) == 1

    def test_instance_is_primary(self, setup):
        _, _, _, replayed = setup
        assert replayed.get_task_instances(0)[0].is_primary is True

    def test_makespan_equals_computation_cost(self, setup):
        _, _, _, replayed = setup
        assert replayed.max_processor_finish_time() == pytest.approx(10.0)

    def test_no_communication_instances(self, setup):
        _, _, _, replayed = setup
        assert len(replayed.communication_instances) == 0

    def test_no_link_intervals(self, setup):
        _, _, _, replayed = setup
        assert all(len(ivs) == 0 for ivs in replayed.link_intervals.values())


# ---------------------------------------------------------------------------
# Group 3: Local dependency (same processor)
# ---------------------------------------------------------------------------

class TestLocalDependency:
    """Two-task chain on the same processor — no CommunicationInstance created.

    DAG: 0->1, vol=5. Both placed on P0. Task 0 cost=10, task 1 cost=5.
    Replay: task 0 [0,10), task 1 [10,15). No comm needed (local).
    """

    @pytest.fixture
    def replayed(self):
        noc = make_noc()
        dag = _dag({0: 10.0, 1: 5.0}, [(0, 1, 5.0)])
        original = _state(noc, [
            (0, 0, 0, 10, True),
            (1, 0, 10, 15, True),
        ])
        return replay_under_contention(dag, original, noc)

    def test_no_communication_instances(self, replayed):
        assert len(replayed.communication_instances) == 0

    def test_no_link_intervals(self, replayed):
        assert all(len(ivs) == 0 for ivs in replayed.link_intervals.values())

    def test_child_starts_after_parent_finish(self, replayed):
        parent = replayed.get_task_instances(0)[0]
        child = replayed.get_task_instances(1)[0]
        assert child.start_time >= parent.finish_time

    def test_child_finish_time(self, replayed):
        child = replayed.get_task_instances(1)[0]
        assert child.finish_time == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Group 4: Remote dependency
# ---------------------------------------------------------------------------

class TestRemoteDependency:
    """Two-task chain on different processors — one CommunicationInstance.

    DAG: 0->1, vol=5. Task 0 on P0 (cost=10), task 1 on P1 (cost=5).
    2x2 NoC, alpha=0, beta=1. Route P0->P1: [Link(0,1)], 1 hop.
    Comm duration = beta * vol = 5. Comm window: [10, 15).
    Task 1: start=15, finish=20.
    """

    @pytest.fixture
    def setup(self):
        noc = make_noc()
        dag = _dag({0: 10.0, 1: 5.0}, [(0, 1, 5.0)])
        original = _state(noc, [
            (0, 0, 0, 10, True),
            (1, 1, 15, 20, True),
        ])
        replayed = replay_under_contention(dag, original, noc)
        return noc, replayed

    def test_one_communication_instance(self, setup):
        _, replayed = setup
        assert len(replayed.communication_instances) == 1

    def test_communication_instance_source_target(self, setup):
        _, replayed = setup
        ci = replayed.communication_instances[0]
        assert ci.source_task == 0
        assert ci.target_task == 1

    def test_communication_instance_processors(self, setup):
        _, replayed = setup
        ci = replayed.communication_instances[0]
        assert ci.source_processor == 0
        assert ci.destination_processor == 1

    def test_communication_instance_volume(self, setup):
        _, replayed = setup
        ci = replayed.communication_instances[0]
        assert ci.communication_volume == pytest.approx(5.0)

    def test_child_starts_after_communication_finish(self, setup):
        _, replayed = setup
        ci = replayed.communication_instances[0]
        child = replayed.get_task_instances(1)[0]
        assert child.start_time >= ci.finish_time

    def test_child_start_time(self, setup):
        _, replayed = setup
        child = replayed.get_task_instances(1)[0]
        assert child.start_time == pytest.approx(15.0)

    def test_child_finish_time(self, setup):
        _, replayed = setup
        child = replayed.get_task_instances(1)[0]
        assert child.finish_time == pytest.approx(20.0)

    def test_route_link_reserved(self, setup):
        _, replayed = setup
        link = Link(source_processor=0, destination_processor=1)
        assert len(replayed.link_intervals[link]) == 1

    def test_route_link_interval_timing(self, setup):
        _, replayed = setup
        link = Link(source_processor=0, destination_processor=1)
        iv = replayed.link_intervals[link][0]
        assert iv.start_time == pytest.approx(10.0)
        assert iv.finish_time == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Group 5: Link contention
# ---------------------------------------------------------------------------

class TestLinkContention:
    """Two communications sharing one link are serialized.

    DAG: 0->2 vol=5, 1->2 vol=5. Tasks 0 and 1 on P0, task 2 on P1.
    Task costs: 0->1, 1->1, 2->20. 2x2 NoC, alpha=0, beta=1.
    Route P0->P1: [Link(0,1)], 1 hop, comm_duration = 5.

    Replay ordering (by original start_time):
      1. Task 0 on P0: [0, 1).
      2. Task 1 on P0: [1, 2)  (earliest_slot after [0,1)).
      3. Task 2 on P1 (both preds replayed):
           pred 0: probe Link(0,1) free -> reserve [1,6), arrival=6
           pred 1: probe Link(0,1) busy until 6 -> reserve [6,11), arrival=11
           DRT=11. Task 2: start=11, finish=31.
    """

    @pytest.fixture
    def replayed(self):
        noc = make_noc()
        dag = _dag({0: 1.0, 1: 1.0, 2: 20.0}, [(0, 2, 5.0), (1, 2, 5.0)])
        original = _state(noc, [
            (0, 0, 0, 1, True),
            (1, 0, 1, 2, True),
            (2, 1, 99, 119, True),
        ])
        return replay_under_contention(dag, original, noc)

    def test_two_communication_instances(self, replayed):
        assert len(replayed.communication_instances) == 2

    def test_task2_start_time(self, replayed):
        child = replayed.get_task_instances(2)[0]
        assert child.start_time == pytest.approx(11.0)

    def test_task2_finish_time(self, replayed):
        child = replayed.get_task_instances(2)[0]
        assert child.finish_time == pytest.approx(31.0)

    def test_shared_link_has_two_intervals(self, replayed):
        link = Link(source_processor=0, destination_processor=1)
        assert len(replayed.link_intervals[link]) == 2

    def test_link_intervals_are_serialized(self, replayed):
        """The two intervals on Link(0,1) are back-to-back (no gap, no overlap)."""
        link = Link(source_processor=0, destination_processor=1)
        ivs = sorted(replayed.link_intervals[link], key=lambda iv: iv.start_time)
        assert ivs[0].start_time == pytest.approx(1.0)
        assert ivs[0].finish_time == pytest.approx(6.0)
        assert ivs[1].start_time == pytest.approx(6.0)
        assert ivs[1].finish_time == pytest.approx(11.0)


# ---------------------------------------------------------------------------
# Group 6: Preserves placement (task -> processor mapping)
# ---------------------------------------------------------------------------

class TestPreservesPlacement:
    """Replay preserves task-to-processor assignment from original_state."""

    def test_processor_ids_match_original(self):
        noc = make_noc()
        dag = _dag(
            {0: 10.0, 1: 8.0, 2: 6.0, 3: 12.0},
            [(0, 1, 3.0), (0, 2, 3.0), (1, 3, 4.0), (2, 3, 4.0)],
        )
        original = _state(noc, [
            (0, 0, 0, 10, True),
            (1, 1, 15, 23, True),
            (2, 2, 15, 21, True),
            (3, 3, 30, 42, True),
        ])
        replayed = replay_under_contention(dag, original, noc)
        for task_id in [0, 1, 2, 3]:
            orig_procs = {i.processor_id for i in original.task_instances[task_id]}
            rep_procs = {i.processor_id for i in replayed.get_task_instances(task_id)}
            assert rep_procs == orig_procs

    def test_total_task_instance_count_preserved(self):
        noc = make_noc()
        dag = _dag({0: 10.0, 1: 5.0}, [(0, 1, 2.0)])
        original = _state(noc, [
            (0, 0, 0, 10, True),
            (1, 1, 12, 17, True),
        ])
        replayed = replay_under_contention(dag, original, noc)
        orig_count = sum(len(v) for v in original.task_instances.values())
        rep_count = sum(len(v) for v in replayed.task_instances.values())
        assert rep_count == orig_count


# ---------------------------------------------------------------------------
# Group 7: Preserves duplicates
# ---------------------------------------------------------------------------

class TestPreservesDuplicates:
    """Replay preserves is_primary flag; duplicates remain duplicates.

    DAG: 0->1. Task 0 has a primary on P0 and a duplicate on P1.
    Task 1 primary on P2.
    """

    @pytest.fixture
    def replayed(self):
        noc = make_noc()
        dag = _dag({0: 10.0, 1: 5.0}, [(0, 1, 3.0)])
        original = _state(noc, [
            (0, 0, 0, 10, True),
            (0, 1, 0, 10, False),
            (1, 2, 15, 20, True),
        ])
        return replay_under_contention(dag, original, noc)

    def test_primary_instance_present(self, replayed):
        primaries = [i for i in replayed.get_task_instances(0) if i.is_primary]
        assert len(primaries) == 1

    def test_duplicate_instance_present(self, replayed):
        duplicates = [i for i in replayed.get_task_instances(0) if not i.is_primary]
        assert len(duplicates) == 1

    def test_duplicate_processor_id_preserved(self, replayed):
        dup = next(i for i in replayed.get_task_instances(0) if not i.is_primary)
        assert dup.processor_id == 1

    def test_total_instance_count(self, replayed):
        total = sum(len(v) for v in replayed.task_instances.values())
        assert total == 3


# ---------------------------------------------------------------------------
# Group 8: Validation — one primary per DAG task
# ---------------------------------------------------------------------------

class TestValidationOnePrimary:
    def test_dag_task_with_no_instance_raises(self):
        noc = make_noc()
        dag = _dag({0: 10.0, 1: 5.0}, [(0, 1, 2.0)])
        original = _state(noc, [(0, 0, 0, 10, True)])
        with pytest.raises(ValueError, match="no primary instance"):
            replay_under_contention(dag, original, noc)

    def test_two_primaries_for_same_task_raises(self):
        noc = make_noc()
        dag = _dag({0: 10.0}, [])
        original = ScheduleState(noc)
        original.reserve_task(0, 0, 0, 10, True)
        original.task_instances[0].append(
            TaskInstance(task_id=0, processor_id=1, start_time=0, finish_time=10, is_primary=True)
        )
        with pytest.raises(ValueError, match="primary instances"):
            replay_under_contention(dag, original, noc)

    def test_task_in_state_but_not_in_dag_raises(self):
        noc = make_noc()
        dag = _dag({0: 10.0}, [])
        original = ScheduleState(noc)
        original.reserve_task(0, 0, 0, 10, True)
        original.task_instances[99] = [
            TaskInstance(task_id=99, processor_id=0, start_time=0, finish_time=5, is_primary=True)
        ]
        with pytest.raises(ValueError, match="99"):
            replay_under_contention(dag, original, noc)


# ---------------------------------------------------------------------------
# Group 9: Original state isolation
# ---------------------------------------------------------------------------

class TestOriginalStateIsolation:
    """replay_under_contention must not mutate original_state."""

    @pytest.fixture
    def setup(self):
        noc = make_noc()
        dag = _dag({0: 10.0, 1: 5.0}, [(0, 1, 5.0)])
        original = _state(noc, [
            (0, 0, 0, 10, True),
            (1, 1, 15, 20, True),
        ])
        return dag, noc, original

    def test_original_communication_instances_unchanged(self, setup):
        dag, noc, original = setup
        before = len(original.communication_instances)
        replay_under_contention(dag, original, noc)
        assert len(original.communication_instances) == before

    def test_original_task_instances_unchanged(self, setup):
        dag, noc, original = setup
        before = {tid: len(insts) for tid, insts in original.task_instances.items()}
        replay_under_contention(dag, original, noc)
        for tid, cnt in before.items():
            assert len(original.task_instances[tid]) == cnt

    def test_original_link_intervals_unchanged(self, setup):
        dag, noc, original = setup
        before = {link: len(ivs) for link, ivs in original.link_intervals.items()}
        replay_under_contention(dag, original, noc)
        for link, cnt in before.items():
            assert len(original.link_intervals[link]) == cnt

    def test_original_processor_intervals_unchanged(self, setup):
        dag, noc, original = setup
        before = {pid: len(ivs) for pid, ivs in original.processor_intervals.items()}
        replay_under_contention(dag, original, noc)
        for pid, cnt in before.items():
            assert len(original.processor_intervals[pid]) == cnt


# ---------------------------------------------------------------------------
# Group 10: HEFT / CD-LS fair replay
# ---------------------------------------------------------------------------

class TestClassicModelReplay:
    """States from HEFT / CD-LS have no CommunicationInstance objects.
    Replay should materialize remote communications under the contention model.
    """

    @pytest.fixture
    def setup(self):
        noc = make_noc()
        dag = _dag({0: 10.0, 1: 5.0}, [(0, 1, 5.0)])
        # Simulate HEFT output: tasks on different procs, no CommunicationInstance
        original = _state(noc, [
            (0, 0, 0, 10, True),
            (1, 1, 10, 15, True),
        ])
        return dag, noc, original

    def test_original_state_has_no_comms(self, setup):
        _, _, original = setup
        assert len(original.communication_instances) == 0

    def test_replay_creates_communication_instance(self, setup):
        dag, noc, original = setup
        replayed = replay_under_contention(dag, original, noc)
        assert len(replayed.communication_instances) == 1

    def test_replayed_makespan_exceeds_heft_estimate(self, setup):
        """HEFT placed task 1 at [10,15) ignoring comm. Replay reveals actual delay."""
        dag, noc, original = setup
        replayed = replay_under_contention(dag, original, noc)
        assert replayed.max_processor_finish_time() == pytest.approx(20.0)

    def test_summarize_shows_comm_count_increase(self, setup):
        dag, noc, original = setup
        replayed = replay_under_contention(dag, original, noc)
        summary = summarize_replay(original, replayed)
        assert summary["original_comm_count"] == 0.0
        assert summary["replayed_comm_count"] > 0.0

    def test_summarize_task_instance_count(self, setup):
        dag, noc, original = setup
        replayed = replay_under_contention(dag, original, noc)
        summary = summarize_replay(original, replayed)
        assert summary["task_instance_count"] == 2.0


# ---------------------------------------------------------------------------
# Group 11: CA-LS / CA-D compatibility
# ---------------------------------------------------------------------------

class TestContentionAwareStateCompat:
    """States from CA-LS or CA-D already have CommunicationInstances.
    Replay should work without errors and produce consistent timing.
    """

    @pytest.fixture
    def setup(self):
        noc = make_noc()
        dag = _dag({0: 10.0, 1: 5.0}, [(0, 1, 5.0)])
        original = ScheduleState(noc)
        original.reserve_task(0, 0, 0, 10, True)
        original.reserve_communication(
            source_task=0,
            target_task=1,
            source_processor=0,
            destination_processor=1,
            ready_time=10.0,
            communication_volume=5.0,
        )
        original.reserve_task(1, 1, 15, 20, True)
        return dag, noc, original

    def test_original_has_one_comm(self, setup):
        _, _, original = setup
        assert len(original.communication_instances) == 1

    def test_replay_returns_schedule_state(self, setup):
        dag, noc, original = setup
        result = replay_under_contention(dag, original, noc)
        assert isinstance(result, ScheduleState)

    def test_replayed_task_count_matches_original(self, setup):
        dag, noc, original = setup
        replayed = replay_under_contention(dag, original, noc)
        orig_total = sum(len(v) for v in original.task_instances.values())
        rep_total = sum(len(v) for v in replayed.task_instances.values())
        assert rep_total == orig_total

    def test_replayed_timing_matches_expected(self, setup):
        """CA-LS state has correct timing; replay should reproduce it."""
        dag, noc, original = setup
        replayed = replay_under_contention(dag, original, noc)
        child = replayed.get_task_instances(1)[0]
        assert child.start_time == pytest.approx(15.0)
        assert child.finish_time == pytest.approx(20.0)

    def test_replayed_comm_count(self, setup):
        dag, noc, original = setup
        replayed = replay_under_contention(dag, original, noc)
        assert len(replayed.communication_instances) == 1


# ---------------------------------------------------------------------------
# Group 12: Validation edge cases
# ---------------------------------------------------------------------------

class TestValidationEdgeCases:
    def test_mismatched_noc_rows_cols_raises(self):
        noc2x2 = make_noc(2, 2)
        noc3x3 = make_noc(3, 3)
        dag = _dag({0: 10.0}, [])
        state = _state(noc2x2, [(0, 0, 0, 10, True)])
        with pytest.raises(ValueError, match="NoC size"):
            replay_under_contention(dag, state, noc3x3)

    def test_mismatched_noc_alpha_raises(self):
        noc_a0 = make_noc(2, 2, alpha=0.0, beta=1.0)
        noc_a1 = make_noc(2, 2, alpha=1.0, beta=1.0)
        dag = _dag({0: 10.0}, [])
        state = _state(noc_a0, [(0, 0, 0, 10, True)])
        with pytest.raises(ValueError, match="alpha"):
            replay_under_contention(dag, state, noc_a1)

    def test_mismatched_noc_beta_raises(self):
        noc_b1 = make_noc(2, 2, alpha=0.0, beta=1.0)
        noc_b2 = make_noc(2, 2, alpha=0.0, beta=2.0)
        dag = _dag({0: 10.0}, [])
        state = _state(noc_b1, [(0, 0, 0, 10, True)])
        with pytest.raises(ValueError, match="beta"):
            replay_under_contention(dag, state, noc_b2)

    def test_task_in_state_not_in_dag_raises(self):
        noc = make_noc()
        dag = _dag({0: 10.0}, [])
        state = ScheduleState(noc)
        state.reserve_task(0, 0, 0, 10, True)
        state.task_instances[99] = [
            TaskInstance(task_id=99, processor_id=0, start_time=0, finish_time=5, is_primary=True)
        ]
        with pytest.raises(ValueError, match="99"):
            replay_under_contention(dag, state, noc)

    def test_dag_task_absent_from_state_raises(self):
        noc = make_noc()
        dag = _dag({0: 10.0, 1: 5.0}, [(0, 1, 2.0)])
        state = _state(noc, [(0, 0, 0, 10, True)])
        with pytest.raises(ValueError, match="no primary instance"):
            replay_under_contention(dag, state, noc)

    def test_non_daggraph_raises_correct_message(self):
        noc = make_noc()
        dag = _dag({0: 10.0}, [])
        state = _state(noc, [(0, 0, 0, 10, True)])
        with pytest.raises(ValueError, match="DAGGraph"):
            replay_under_contention(nx.DiGraph(), state, noc)

    def test_int_as_dag_raises(self):
        noc = make_noc()
        dag = _dag({0: 10.0}, [])
        state = _state(noc, [(0, 0, 0, 10, True)])
        with pytest.raises(ValueError, match="DAGGraph"):
            replay_under_contention(42, state, noc)
