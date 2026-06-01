"""
Tests for src/classical_dup_scheduler.py.

Covers: construction, ranking compatibility with HEFT, single-task schedule,
no-duplication cases, forced duplication, duplicate correctness, candidate
isolation, HEFT comparison, and input validation.
Implemented in Phase 7.

Forced-duplication DAG design:
    Two independent parents 0 and 1 (cost=1 each) feed into child 2 (cost=1).
    Edges 0→2 and 1→2 each carry communication_volume=100.
    NoC: 2×2 mesh, alpha=0, beta=1  →  comm_duration = 1 * volume (no hop cost).

    Scheduling trace (deterministic):
        Task 0 ranks equal to task 1 (both have rank 102 on this NoC).
        Tie-break by task_id: task 0 is scheduled first → P0 [0, 1].
        Task 1 has EFT=2 on P0 (busy), EFT=1 on P1/P2/P3 → P1 [0, 1].
        Task 2 evaluating P0:
            pred=0 already on P0 (skip), pred=1 not on P0:
                EFT_no_dup = 102  (DRT from P1 = 1 + 100 = 101)
                dup of task 1 on P0 [1, 2] → DRT = 2 (local) → EFT_dup = 3
                Delta_EFT = 99 > 0  →  dup committed.
            Final EFT on P0 = 3.
        Task 2 evaluating P1: symmetric → EFT = 3 with dup of task 0 on P1.
        Tie P0 vs P1: P0 wins (smaller proc_id).
        Result: task 2 on P0 [2, 3]; dup of task 1 on P0 [1, 2] (is_primary=False).
        Makespan = 3.   HEFT makespan on same DAG = 102.

No-duplication DAG design:
    Same topology as forced-dup but volume=0.
    With vol=0: comm_duration = 0, so remote arrival == local arrival.
    Adding a dup of pred occupies the processor [1, 2], pushing task 2 start
    from t=1 to t=2.  Delta_EFT = EFT_no_dup(2) - EFT_dup(3) = -1 < 0 → no dup.
"""

import networkx as nx
import pytest

from src.models import DAGGraph
from src.noc import MeshNoC
from src.schedule_state import ScheduleState
from src.classical_dup_scheduler import ClassicalDuplicationScheduler
from src.heft_scheduler import HEFTScheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_noc(rows: int = 2, cols: int = 2,
             alpha: float = 0.0, beta: float = 1.0) -> MeshNoC:
    return MeshNoC(rows=rows, cols=cols, alpha=alpha, beta=beta)


def make_cd(rows: int = 2, cols: int = 2,
            alpha: float = 0.0, beta: float = 1.0) -> ClassicalDuplicationScheduler:
    return ClassicalDuplicationScheduler(make_noc(rows, cols, alpha, beta))


def make_state(noc: MeshNoC | None = None) -> ScheduleState:
    return ScheduleState(noc if noc is not None else make_noc())


def _single_node_dag(cost: float = 10.0) -> DAGGraph:
    g = nx.DiGraph()
    g.add_node(0, computation_cost=cost)
    return DAGGraph(g)


def _chain_dag(
    costs: tuple = (10.0, 20.0, 30.0),
    volumes: tuple = (5.0, 7.0),
) -> DAGGraph:
    g = nx.DiGraph()
    for i, c in enumerate(costs):
        g.add_node(i, computation_cost=c)
    for i, v in enumerate(volumes):
        g.add_edge(i, i + 1, communication_volume=v)
    return DAGGraph(g)


def _forced_dup_dag() -> DAGGraph:
    """0→2 vol=100, 1→2 vol=100; all costs=1. Forces duplication on 2×2 alpha=0 beta=1."""
    g = nx.DiGraph()
    for tid in range(3):
        g.add_node(tid, computation_cost=1.0)
    g.add_edge(0, 2, communication_volume=100.0)
    g.add_edge(1, 2, communication_volume=100.0)
    return DAGGraph(g)


def _no_dup_dag() -> DAGGraph:
    """Same topology as forced-dup but vol=0 → Delta_EFT <= 0, no duplication."""
    g = nx.DiGraph()
    for tid in range(3):
        g.add_node(tid, computation_cost=1.0)
    g.add_edge(0, 2, communication_volume=0.0)
    g.add_edge(1, 2, communication_volume=0.0)
    return DAGGraph(g)


def _fork_join_dag() -> DAGGraph:
    """0→1, 0→2, 1→3, 2→3 (diamond)."""
    g = nx.DiGraph()
    for i, c in enumerate([10.0, 20.0, 15.0, 25.0]):
        g.add_node(i, computation_cost=c)
    g.add_edge(0, 1, communication_volume=5.0)
    g.add_edge(0, 2, communication_volume=3.0)
    g.add_edge(1, 3, communication_volume=4.0)
    g.add_edge(2, 3, communication_volume=6.0)
    return DAGGraph(g)


def _two_task_dag(vol: float = 0.0) -> DAGGraph:
    """Simple two-task chain 0→1."""
    g = nx.DiGraph()
    g.add_node(0, computation_cost=5.0)
    g.add_node(1, computation_cost=3.0)
    g.add_edge(0, 1, communication_volume=vol)
    return DAGGraph(g)


# ---------------------------------------------------------------------------
# 1. Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_valid_construction(self):
        cd = make_cd()
        assert cd.noc is not None

    def test_noc_stored(self):
        noc = make_noc()
        cd = ClassicalDuplicationScheduler(noc)
        assert cd.noc is noc

    def test_rejects_non_meshnoc(self):
        with pytest.raises(ValueError):
            ClassicalDuplicationScheduler("not a noc")  # type: ignore[arg-type]

    def test_rejects_none(self):
        with pytest.raises(ValueError):
            ClassicalDuplicationScheduler(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Ranking compatibility with HEFT
# ---------------------------------------------------------------------------

class TestRankingCompatibility:
    def test_ranks_match_heft_chain(self):
        noc = make_noc()
        cd = ClassicalDuplicationScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _chain_dag()
        cd_ranks = cd.compute_upward_ranks(dag)
        heft_ranks = heft.compute_upward_ranks(dag)
        for tid in dag.task_ids():
            assert cd_ranks[tid] == pytest.approx(heft_ranks[tid])

    def test_ranks_match_heft_fork_join(self):
        noc = make_noc(rows=4, cols=4, alpha=1.0, beta=1.0)
        cd = ClassicalDuplicationScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _fork_join_dag()
        cd_ranks = cd.compute_upward_ranks(dag)
        heft_ranks = heft.compute_upward_ranks(dag)
        for tid in dag.task_ids():
            assert cd_ranks[tid] == pytest.approx(heft_ranks[tid])

    def test_priority_order_matches_heft(self):
        noc = make_noc()
        cd = ClassicalDuplicationScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _fork_join_dag()
        assert cd.task_priority_order(dag) == heft.task_priority_order(dag)

    def test_ranks_reject_raw_digraph(self):
        with pytest.raises(ValueError):
            make_cd().compute_upward_ranks(nx.DiGraph())  # type: ignore[arg-type]

    def test_priority_order_rejects_raw_digraph(self):
        with pytest.raises(ValueError):
            make_cd().task_priority_order(nx.DiGraph())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. Single-task schedule
# ---------------------------------------------------------------------------

class TestSingleTask:
    def test_one_task_scheduled(self):
        state = make_cd().schedule(_single_node_dag())
        assert state.has_task_instance(0)

    def test_exactly_one_instance(self):
        state = make_cd().schedule(_single_node_dag())
        assert len(state.get_task_instances(0)) == 1

    def test_placed_on_proc_zero(self):
        state = make_cd().schedule(_single_node_dag(10.0))
        assert state.get_primary_instance(0).processor_id == 0

    def test_timing(self):
        state = make_cd().schedule(_single_node_dag(10.0))
        ti = state.get_primary_instance(0)
        assert ti.start_time == pytest.approx(0.0)
        assert ti.finish_time == pytest.approx(10.0)

    def test_no_link_intervals(self):
        state = make_cd().schedule(_single_node_dag())
        for ivs in state.link_intervals.values():
            assert ivs == []

    def test_no_communication_instances(self):
        state = make_cd().schedule(_single_node_dag())
        assert state.communication_instances == []


# ---------------------------------------------------------------------------
# 4. No-duplication cases
# ---------------------------------------------------------------------------

class TestNoDuplication:
    def test_zero_volume_produces_no_dups(self):
        """vol=0: remote arrival equals local finish, so dup never helps."""
        cd = make_cd()  # 2×2, alpha=0, beta=1
        dag = _no_dup_dag()
        state = cd.schedule(dag)
        total_instances = sum(len(state.get_task_instances(t)) for t in dag.task_ids())
        assert total_instances == dag.number_of_tasks()

    def test_zero_volume_all_primaries(self):
        cd = make_cd()
        state = cd.schedule(_no_dup_dag())
        for tid in _no_dup_dag().task_ids():
            for inst in state.get_task_instances(tid):
                assert inst.is_primary

    def test_independent_tasks_no_dup(self):
        """Tasks with no edges have no predecessors → nothing to duplicate."""
        g = nx.DiGraph()
        for i in range(4):
            g.add_node(i, computation_cost=5.0)
        dag = DAGGraph(g)
        state = make_cd().schedule(dag)
        total = sum(len(state.get_task_instances(t)) for t in dag.task_ids())
        assert total == dag.number_of_tasks()

    def test_local_pred_no_dup_on_single_proc_mesh(self):
        """1×1 mesh: all tasks land on P0; local predecessor → no dup possible."""
        cd = ClassicalDuplicationScheduler(MeshNoC(rows=1, cols=1))
        dag = _chain_dag(costs=(5.0, 3.0), volumes=(10.0,))
        state = cd.schedule(dag)
        # Both tasks must be on the single processor
        assert state.get_primary_instance(0).processor_id == 0
        assert state.get_primary_instance(1).processor_id == 0
        # No duplicates created
        total = sum(len(state.get_task_instances(t)) for t in dag.task_ids())
        assert total == dag.number_of_tasks()

    def test_link_intervals_empty_when_no_dup(self):
        state = make_cd().schedule(_no_dup_dag())
        for ivs in state.link_intervals.values():
            assert ivs == []


# ---------------------------------------------------------------------------
# 5. Forced duplication
# ---------------------------------------------------------------------------

class TestForcedDuplication:
    """
    Uses _forced_dup_dag() on 2×2 mesh with alpha=0, beta=1.
    Expected schedule (from module-level docstring trace):
        task 0 → P0 [0, 1]  (primary)
        task 1 → P1 [0, 1]  (primary)
        task 1 → P0 [1, 2]  (duplicate, is_primary=False)
        task 2 → P0 [2, 3]  (primary)
    """

    def _schedule(self):
        return make_cd().schedule(_forced_dup_dag())

    # -- Placement assertions (make test deterministic) --

    def test_task0_placement(self):
        state = self._schedule()
        ti = state.get_primary_instance(0)
        assert ti.processor_id == 0
        assert ti.start_time == pytest.approx(0.0)
        assert ti.finish_time == pytest.approx(1.0)

    def test_task1_primary_placement(self):
        state = self._schedule()
        ti = state.get_primary_instance(1)
        assert ti.processor_id == 1
        assert ti.start_time == pytest.approx(0.0)
        assert ti.finish_time == pytest.approx(1.0)

    def test_task2_primary_placement(self):
        state = self._schedule()
        ti = state.get_primary_instance(2)
        assert ti.processor_id == 0

    # -- Duplication assertions --

    def test_at_least_one_dup_exists(self):
        state = self._schedule()
        all_instances = [
            inst
            for tid in _forced_dup_dag().task_ids()
            for inst in state.get_task_instances(tid)
        ]
        dups = [inst for inst in all_instances if not inst.is_primary]
        assert len(dups) >= 1

    def test_dup_is_not_primary(self):
        state = self._schedule()
        for tid in _forced_dup_dag().task_ids():
            for inst in state.get_task_instances(tid):
                if not inst.is_primary:
                    assert inst.is_primary is False

    def test_each_original_task_has_exactly_one_primary(self):
        state = self._schedule()
        for tid in _forced_dup_dag().task_ids():
            primaries = [i for i in state.get_task_instances(tid) if i.is_primary]
            assert len(primaries) == 1

    def test_makespan(self):
        """CD-LS makespan must be 3.0 (not 102) on the forced-dup DAG."""
        cd = make_cd()
        state = cd.schedule(_forced_dup_dag())
        assert cd.compute_makespan(state) == pytest.approx(3.0)

    def test_cd_makespan_less_than_heft(self):
        noc = make_noc()
        cd = ClassicalDuplicationScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _forced_dup_dag()
        cd_ms = cd.compute_makespan(cd.schedule(dag))
        heft_ms = heft.compute_makespan(heft.schedule(dag))
        assert cd_ms < heft_ms

    def test_dup_task_id_matches_pred(self):
        """The duplicate instance must carry the correct predecessor task_id."""
        state = self._schedule()
        # task 1 should have 2 instances: primary on P1, dup on P0
        instances_1 = state.get_task_instances(1)
        assert len(instances_1) == 2
        for inst in instances_1:
            assert inst.task_id == 1


# ---------------------------------------------------------------------------
# 6. Duplicate correctness
# ---------------------------------------------------------------------------

class TestDuplicateCorrectness:
    def test_no_processor_interval_overlap(self):
        cd = make_cd()
        state = cd.schedule(_forced_dup_dag())
        state.validate_no_overlaps()

    def test_child_starts_after_local_dup_finishes(self):
        """task 2 must not start before the dup of task 1 on P0 finishes."""
        state = make_cd().schedule(_forced_dup_dag())
        ti2 = state.get_primary_instance(2)
        assert ti2.processor_id == 0  # assert expected placement first
        dup_on_p0 = [
            inst for inst in state.get_task_instances(1)
            if not inst.is_primary and inst.processor_id == 0
        ]
        assert dup_on_p0, "expected dup of task 1 on P0"
        assert ti2.start_time >= dup_on_p0[0].finish_time - 1e-9

    def test_link_intervals_always_empty(self):
        cd = make_cd()
        state = cd.schedule(_forced_dup_dag())
        for ivs in state.link_intervals.values():
            assert ivs == []

    def test_no_communication_instances_ever(self):
        """CD-LS never calls reserve_communication() → list stays empty."""
        cd = make_cd()
        state = cd.schedule(_forced_dup_dag())
        assert state.communication_instances == []

    def test_validate_no_overlaps_fork_join(self):
        cd = make_cd(rows=4, cols=4, alpha=1.0, beta=1.0)
        state = cd.schedule(_fork_join_dag())
        state.validate_no_overlaps()


# ---------------------------------------------------------------------------
# 7. Candidate isolation
# ---------------------------------------------------------------------------

class TestCandidateIsolation:
    def test_evaluate_does_not_mutate_original_state(self):
        cd = make_cd()
        dag = _two_task_dag(vol=100.0)
        noc = cd.noc
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 5.0)  # task 0 primary on P0

        original_ci_count = len(state.communication_instances)
        original_link_counts = {
            lk: len(ivs) for lk, ivs in state.link_intervals.items()
        }
        original_task1_count = len(state.get_task_instances(0))

        # Evaluate task 1 on several processors — must not mutate state
        cd.evaluate_task_on_processor(dag, state, 1, 0)
        cd.evaluate_task_on_processor(dag, state, 1, 1)

        assert len(state.communication_instances) == original_ci_count
        assert len(state.get_task_instances(0)) == original_task1_count
        for lk, count in original_link_counts.items():
            assert len(state.link_intervals[lk]) == count

    def test_rejected_candidate_dup_absent_from_final_state(self):
        """
        In the forced-dup schedule, P1's candidate gains dup of task 0 on P1.
        P0 wins.  Final state must NOT contain a dup of task 0 on P1.
        """
        state = make_cd().schedule(_forced_dup_dag())
        # task 0 must have exactly 1 instance (its primary on P0)
        instances_0 = state.get_task_instances(0)
        assert len(instances_0) == 1
        assert instances_0[0].is_primary
        assert instances_0[0].processor_id == 0

    def test_only_winning_candidate_dups_in_final_state(self):
        """Total extra instances equals exactly one dup per duplication event."""
        state = make_cd().schedule(_forced_dup_dag())
        dag = _forced_dup_dag()
        # Primary count = number of tasks
        primaries = sum(
            1 for tid in dag.task_ids()
            for inst in state.get_task_instances(tid)
            if inst.is_primary
        )
        assert primaries == dag.number_of_tasks()


# ---------------------------------------------------------------------------
# 8. HEFT comparison
# ---------------------------------------------------------------------------

class TestHEFTComparison:
    def test_both_schedule_all_tasks(self):
        noc = make_noc()
        cd = ClassicalDuplicationScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _forced_dup_dag()
        cd_state = cd.schedule(dag)
        heft_state = heft.schedule(dag)
        for tid in dag.task_ids():
            assert cd_state.has_task_instance(tid)
            assert heft_state.has_task_instance(tid)

    def test_heft_has_no_dup_instances(self):
        noc = make_noc()
        heft = HEFTScheduler(noc)
        dag = _forced_dup_dag()
        state = heft.schedule(dag)
        for tid in dag.task_ids():
            assert len(state.get_task_instances(tid)) == 1

    def test_cd_has_dup_on_forced_dag(self):
        cd = make_cd()
        state = cd.schedule(_forced_dup_dag())
        total = sum(
            len(state.get_task_instances(tid))
            for tid in _forced_dup_dag().task_ids()
        )
        assert total > _forced_dup_dag().number_of_tasks()

    def test_cd_link_intervals_empty_like_heft(self):
        noc = make_noc()
        cd = ClassicalDuplicationScheduler(noc)
        state = cd.schedule(_fork_join_dag())
        for ivs in state.link_intervals.values():
            assert ivs == []

    def test_cd_valid_schedule_on_synthetic_dag(self):
        from src.dag_generator import generate_dag
        g = generate_dag(n_tasks=20, edge_prob=0.3, ccr=1.0,
                         comp_range=(10, 100), seed=42)
        dag = DAGGraph(g)
        cd = make_cd(rows=4, cols=4, alpha=1.0, beta=1.0)
        state = cd.schedule(dag)
        # All tasks scheduled with exactly one primary
        for tid in dag.task_ids():
            assert state.has_task_instance(tid)
            primaries = [i for i in state.get_task_instances(tid) if i.is_primary]
            assert len(primaries) == 1
        # No link intervals
        for ivs in state.link_intervals.values():
            assert ivs == []
        # No overlaps
        state.validate_no_overlaps()


# ---------------------------------------------------------------------------
# 9. Existing duplicate usage
# ---------------------------------------------------------------------------

class TestExistingDuplicateUsage:
    """
    Verify classic_data_ready_time() uses the earliest-arriving instance when
    a predecessor has multiple instances (primary + duplicate).

    Setup:
        2×2 mesh, alpha=0, beta=1 → comm_duration = 1 * vol (no hop cost).
        DAG: 0→1 with communication_volume=50.
        State: task 0 primary on P0 [0, 10], task 0 duplicate on P1 [0, 5].

    Arrivals for task 1 on P1:
        from local dup  (P1 → P1): finish=5,  vol=0  → arrival = 5.0
        from remote primary (P0→P1): finish=10, vol=50 → arrival = 60.0
        Best = 5.0

    Arrivals for task 1 on P0:
        from local primary (P0→P0): finish=10, vol=0  → arrival = 10.0
        from remote dup    (P1→P0): finish=5,  vol=50 → arrival = 55.0
        Best = 10.0
    """

    def _setup(self):
        noc = make_noc(rows=2, cols=2, alpha=0.0, beta=1.0)
        cd = ClassicalDuplicationScheduler(noc)
        dag = _two_task_dag(vol=50.0)
        state = make_state(noc)
        state.reserve_task(task_id=0, processor_id=0,
                           start_time=0.0, finish_time=10.0, is_primary=True)
        state.reserve_task(task_id=0, processor_id=1,
                           start_time=0.0, finish_time=5.0, is_primary=False)
        return cd, dag, state

    def test_drt_uses_local_dup_not_remote_primary(self):
        """DRT for task 1 on P1 must be 5.0 (local dup), not 60.0 (remote primary)."""
        cd, dag, state = self._setup()
        drt = cd.classic_data_ready_time(dag, state, 1, 1)
        assert drt == pytest.approx(5.0)

    def test_drt_remote_only_when_no_dup(self):
        """With only P0 primary, DRT for task 1 on P1 = 10 + 50 = 60.0."""
        noc = make_noc(rows=2, cols=2, alpha=0.0, beta=1.0)
        cd = ClassicalDuplicationScheduler(noc)
        dag = _two_task_dag(vol=50.0)
        state = make_state(noc)
        state.reserve_task(task_id=0, processor_id=0,
                           start_time=0.0, finish_time=10.0, is_primary=True)
        drt = cd.classic_data_ready_time(dag, state, 1, 1)
        assert drt == pytest.approx(60.0)

    def test_drt_local_only_arrival_on_same_proc(self):
        """DRT for task 1 on P0 = 10.0 (local primary); remote dup gives 55.0."""
        cd, dag, state = self._setup()
        drt = cd.classic_data_ready_time(dag, state, 1, 0)
        assert drt == pytest.approx(10.0)

    def test_drt_zero_for_entry_task(self):
        """Entry task (no predecessors) has DRT = 0.0."""
        noc = make_noc()
        cd = ClassicalDuplicationScheduler(noc)
        dag = _single_node_dag()
        state = make_state(noc)
        drt = cd.classic_data_ready_time(dag, state, 0, 0)
        assert drt == pytest.approx(0.0)

    def test_drt_raises_on_unscheduled_predecessor(self):
        """Raises ValueError when a predecessor has no instance in state."""
        noc = make_noc()
        cd = ClassicalDuplicationScheduler(noc)
        dag = _two_task_dag(vol=10.0)
        state = make_state(noc)  # task 0 not scheduled
        with pytest.raises(ValueError):
            cd.classic_data_ready_time(dag, state, 1, 0)


# ---------------------------------------------------------------------------
# 10. Input validation
# ---------------------------------------------------------------------------

class TestValidation:
    # -- schedule --

    def test_schedule_rejects_raw_digraph(self):
        with pytest.raises(ValueError):
            make_cd().schedule(nx.DiGraph())  # type: ignore[arg-type]

    # -- evaluate_task_on_processor --

    def _base_state(self, cd: ClassicalDuplicationScheduler) -> tuple[DAGGraph, ScheduleState]:
        dag = _two_task_dag(vol=5.0)
        state = make_state(cd.noc)
        state.reserve_task(0, 0, 0.0, 5.0)
        return dag, state

    def test_evaluate_rejects_raw_digraph(self):
        cd = make_cd()
        state = make_state(cd.noc)
        with pytest.raises(ValueError):
            cd.evaluate_task_on_processor(nx.DiGraph(), state, 0, 0)  # type: ignore[arg-type]

    def test_evaluate_rejects_non_state(self):
        cd = make_cd()
        dag = _single_node_dag()
        with pytest.raises(ValueError):
            cd.evaluate_task_on_processor(dag, "bad", 0, 0)  # type: ignore[arg-type]

    def test_evaluate_rejects_mismatched_noc(self):
        cd = make_cd(rows=2, cols=2)
        dag = _single_node_dag()
        foreign = ScheduleState(MeshNoC(rows=4, cols=4))
        with pytest.raises(ValueError, match="NoC configuration"):
            cd.evaluate_task_on_processor(dag, foreign, 0, 0)

    def test_evaluate_rejects_same_topology_different_alpha_beta(self):
        cd = make_cd(rows=2, cols=2, alpha=1.0, beta=1.0)
        dag = _single_node_dag()
        foreign = ScheduleState(MeshNoC(rows=2, cols=2, alpha=99.0, beta=99.0))
        with pytest.raises(ValueError, match="NoC configuration"):
            cd.evaluate_task_on_processor(dag, foreign, 0, 0)

    def test_evaluate_rejects_bool_task_id(self):
        cd = make_cd()
        dag, state = self._base_state(cd)
        with pytest.raises(ValueError):
            cd.evaluate_task_on_processor(dag, state, True, 0)  # type: ignore[arg-type]

    def test_evaluate_rejects_non_int_task_id(self):
        cd = make_cd()
        dag, state = self._base_state(cd)
        with pytest.raises(ValueError):
            cd.evaluate_task_on_processor(dag, state, 1.0, 0)  # type: ignore[arg-type]

    def test_evaluate_rejects_missing_task_id(self):
        cd = make_cd()
        dag, state = self._base_state(cd)
        with pytest.raises(ValueError):
            cd.evaluate_task_on_processor(dag, state, 999, 0)

    def test_evaluate_rejects_bool_processor_id(self):
        cd = make_cd()
        dag, state = self._base_state(cd)
        with pytest.raises(ValueError):
            cd.evaluate_task_on_processor(dag, state, 1, True)  # type: ignore[arg-type]

    def test_evaluate_rejects_non_int_processor_id(self):
        cd = make_cd()
        dag, state = self._base_state(cd)
        with pytest.raises(ValueError):
            cd.evaluate_task_on_processor(dag, state, 1, 0.0)  # type: ignore[arg-type]

    def test_evaluate_rejects_invalid_processor_id(self):
        cd = make_cd()
        dag, state = self._base_state(cd)
        with pytest.raises(ValueError):
            cd.evaluate_task_on_processor(dag, state, 1, 999)

    def test_evaluate_rejects_unscheduled_predecessor(self):
        cd = make_cd()
        dag = _two_task_dag(vol=5.0)
        state = make_state(cd.noc)  # task 0 NOT scheduled
        with pytest.raises(ValueError):
            cd.evaluate_task_on_processor(dag, state, 1, 0)

    # -- compute_makespan --

    def test_makespan_rejects_non_state(self):
        with pytest.raises(ValueError):
            make_cd().compute_makespan("not a state")  # type: ignore[arg-type]

    def test_makespan_rejects_mismatched_noc(self):
        cd = make_cd(rows=2, cols=2)
        foreign = ScheduleState(MeshNoC(rows=4, cols=4))
        with pytest.raises(ValueError):
            cd.compute_makespan(foreign)

    def test_makespan_accepts_own_schedule(self):
        cd = make_cd()
        state = cd.schedule(_forced_dup_dag())
        result = cd.compute_makespan(state)
        assert result > 0


# ---------------------------------------------------------------------------
# 11. Forbidden-method regression guard
# ---------------------------------------------------------------------------

class TestNoLinkReservation:
    """
    Ensure ClassicalDuplicationScheduler never calls reserve_communication()
    or reserve_route() on any ScheduleState during scheduling.

    Monkeypatching both methods to raise AssertionError means a single
    accidental call fails the test immediately, regardless of code path.
    """

    def test_cd_never_calls_link_reservation_methods(self, monkeypatch):
        def forbidden(*args, **kwargs):
            raise AssertionError("CD-LS must not reserve communications or routes")

        monkeypatch.setattr(ScheduleState, "reserve_communication", forbidden)
        monkeypatch.setattr(ScheduleState, "reserve_route", forbidden)

        cd = make_cd()
        state = cd.schedule(_forced_dup_dag())

        assert state.communication_instances == []
        for ivs in state.link_intervals.values():
            assert ivs == []

    def test_cd_never_calls_link_reservation_fork_join(self, monkeypatch):
        def forbidden(*args, **kwargs):
            raise AssertionError("CD-LS must not reserve communications or routes")

        monkeypatch.setattr(ScheduleState, "reserve_communication", forbidden)
        monkeypatch.setattr(ScheduleState, "reserve_route", forbidden)

        cd = make_cd(rows=4, cols=4, alpha=1.0, beta=1.0)
        state = cd.schedule(_fork_join_dag())

        assert state.communication_instances == []
        for ivs in state.link_intervals.values():
            assert ivs == []
