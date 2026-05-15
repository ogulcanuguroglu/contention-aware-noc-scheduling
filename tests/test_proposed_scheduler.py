"""
Tests for src/proposed_scheduler.py.

Covers: construction, ranking compatibility with HEFT, single-task schedule,
no-edge DAG, remote communication reservation, contention delay, forced
duplication under contention, Delta_EFT tie, existing duplicate instance
selection, grandparent communication for dup placement, candidate isolation,
link interval integrity, no-recursive-duplication guard, baseline comparison,
makespan, input validation, and synthetic DAG sanity.
Implemented in Phase 8.

Coordinate system (2×2 mesh, row-major: pid = y*cols + x):
    P0=(x=0,y=0)  P1=(x=1,y=0)
    P2=(x=0,y=1)  P3=(x=1,y=1)

XY routing (X first, then Y):
    P0→P1 : [Link(0,1)]
    P1→P0 : [Link(1,0)]
    P0→P2 : [Link(0,2)]
    P2→P0 : [Link(2,0)]
    P1→P2 : [Link(1,0), Link(0,2)]   (X: col1→col0, Y: row0→row1)
    P0→P3 : [Link(0,1), Link(1,3)]
    ...

With alpha=0, beta=1: comm_duration = 1 * vol (hop count has no cost).

Forced-duplication DAG trace (same as CD-LS, alpha=0, beta=1, 2×2 mesh):
    Task 0 → P0 [0,1]   (primary)
    Task 1 → P1 [0,1]   (primary)
    Task 2 evaluating P0:
        pred=0 local → skip
        pred=1 not local:
            EFT_no_dup: comm P1→P0 vol=100, duration=100, arrival=101 → EFT=102
            EFT_dup:    dup task1 on P0[1,2]; both preds local → DRT=2 → EFT=3
            Delta=99>0 → commit dup
        final DRT=2, slot=[2,3], EFT=3
    Task 2 evaluating P1: symmetric EFT=3
    Tie → P0 wins.
    Result: task2→P0[2,3], dup of task1→P0[1,2].  Makespan=3.

    In the final committed state: both preds of task2 are local → no comms.
"""

import networkx as nx
import pytest

from src.models import DAGGraph, Link
from src.noc import MeshNoC
from src.schedule_state import ScheduleState
from src.proposed_scheduler import ProposedScheduler
from src.heft_scheduler import HEFTScheduler
from src.contention_scheduler import ContentionAwareScheduler
from src.classical_dup_scheduler import ClassicalDuplicationScheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_noc(rows: int = 2, cols: int = 2,
             alpha: float = 0.0, beta: float = 1.0) -> MeshNoC:
    return MeshNoC(rows=rows, cols=cols, alpha=alpha, beta=beta)


def make_ps(rows: int = 2, cols: int = 2,
            alpha: float = 0.0, beta: float = 1.0) -> ProposedScheduler:
    return ProposedScheduler(make_noc(rows, cols, alpha, beta))


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


def _fork_join_dag() -> DAGGraph:
    """0→1, 0→2, 1→3, 2→3 (diamond). costs=[10,20,15,25], vols=[5,3,4,6]."""
    g = nx.DiGraph()
    for i, c in enumerate([10.0, 20.0, 15.0, 25.0]):
        g.add_node(i, computation_cost=c)
    g.add_edge(0, 1, communication_volume=5.0)
    g.add_edge(0, 2, communication_volume=3.0)
    g.add_edge(1, 3, communication_volume=4.0)
    g.add_edge(2, 3, communication_volume=6.0)
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


def _two_task_dag(vol: float = 0.0) -> DAGGraph:
    """Simple two-task chain 0→1. costs=(5,3)."""
    g = nx.DiGraph()
    g.add_node(0, computation_cost=5.0)
    g.add_node(1, computation_cost=3.0)
    g.add_edge(0, 1, communication_volume=vol)
    return DAGGraph(g)


def _chain3_dag() -> DAGGraph:
    """0→1→2. costs=(1,1,1), vols=(50,50)."""
    g = nx.DiGraph()
    for i in range(3):
        g.add_node(i, computation_cost=1.0)
    g.add_edge(0, 1, communication_volume=50.0)
    g.add_edge(1, 2, communication_volume=50.0)
    return DAGGraph(g)


# ---------------------------------------------------------------------------
# 1. Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_valid_construction(self):
        ps = make_ps()
        assert ps.noc is not None

    def test_noc_stored(self):
        noc = make_noc()
        ps = ProposedScheduler(noc)
        assert ps.noc is noc

    def test_rejects_non_meshnoc(self):
        with pytest.raises(ValueError):
            ProposedScheduler("not a noc")  # type: ignore[arg-type]

    def test_rejects_none(self):
        with pytest.raises(ValueError):
            ProposedScheduler(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Ranking compatibility with HEFT
# ---------------------------------------------------------------------------

class TestRankingCompatibility:
    def test_ranks_match_heft_chain(self):
        noc = make_noc()
        ps = ProposedScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _chain_dag()
        for tid in dag.task_ids():
            assert ps.compute_upward_ranks(dag)[tid] == pytest.approx(
                heft.compute_upward_ranks(dag)[tid]
            )

    def test_ranks_match_heft_fork_join(self):
        noc = make_noc(rows=4, cols=4, alpha=1.0, beta=1.0)
        ps = ProposedScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _fork_join_dag()
        for tid in dag.task_ids():
            assert ps.compute_upward_ranks(dag)[tid] == pytest.approx(
                heft.compute_upward_ranks(dag)[tid]
            )

    def test_priority_order_matches_heft(self):
        noc = make_noc()
        ps = ProposedScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _fork_join_dag()
        assert ps.task_priority_order(dag) == heft.task_priority_order(dag)

    def test_ranks_reject_raw_digraph(self):
        with pytest.raises(ValueError):
            make_ps().compute_upward_ranks(nx.DiGraph())  # type: ignore[arg-type]

    def test_priority_order_rejects_raw_digraph(self):
        with pytest.raises(ValueError):
            make_ps().task_priority_order(nx.DiGraph())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. Single-task schedule
# ---------------------------------------------------------------------------

class TestSingleTask:
    def test_one_primary_instance(self):
        state = make_ps().schedule(_single_node_dag())
        assert state.has_task_instance(0)
        assert len(state.get_task_instances(0)) == 1

    def test_placed_on_proc_zero(self):
        state = make_ps().schedule(_single_node_dag(10.0))
        assert state.get_primary_instance(0).processor_id == 0

    def test_timing(self):
        state = make_ps().schedule(_single_node_dag(10.0))
        ti = state.get_primary_instance(0)
        assert ti.start_time == pytest.approx(0.0)
        assert ti.finish_time == pytest.approx(10.0)

    def test_no_duplicates(self):
        state = make_ps().schedule(_single_node_dag())
        assert len(state.get_task_instances(0)) == 1
        assert state.get_primary_instance(0).is_primary

    def test_no_communication_instances(self):
        state = make_ps().schedule(_single_node_dag())
        assert state.communication_instances == []

    def test_no_link_intervals(self):
        state = make_ps().schedule(_single_node_dag())
        for ivs in state.link_intervals.values():
            assert ivs == []


# ---------------------------------------------------------------------------
# 4. No-edge DAG
# ---------------------------------------------------------------------------

class TestNoEdgeDag:
    def test_all_tasks_scheduled(self):
        g = nx.DiGraph()
        for i in range(4):
            g.add_node(i, computation_cost=5.0)
        dag = DAGGraph(g)
        state = make_ps().schedule(dag)
        for tid in dag.task_ids():
            assert state.has_task_instance(tid)

    def test_no_duplicates(self):
        g = nx.DiGraph()
        for i in range(4):
            g.add_node(i, computation_cost=5.0)
        dag = DAGGraph(g)
        state = make_ps().schedule(dag)
        total = sum(len(state.get_task_instances(t)) for t in dag.task_ids())
        assert total == dag.number_of_tasks()

    def test_no_communication_instances(self):
        g = nx.DiGraph()
        for i in range(3):
            g.add_node(i, computation_cost=5.0)
        dag = DAGGraph(g)
        state = make_ps().schedule(dag)
        assert state.communication_instances == []


# ---------------------------------------------------------------------------
# 5. Remote communication behavior
# ---------------------------------------------------------------------------

class TestRemoteCommunication:
    """
    4×4 NoC, alpha=0, beta=1.
    P0=(x=0,y=0)=0, P5=(x=1,y=1)=5.
    XY route P0→P5: Link(0,1) then Link(1,5).
    comm_duration = 1*vol (alpha=0).
    Task 0 primary on P0 [0,10].  Evaluate task 1 (cost=3, vol=10) on P5.

    P5 is pre-occupied [0,1000) so a dup of task0 there would start at t=1000
    (EFT_dup=1008) while EFT_no_dup=1003.  Delta<0 → no dup → remote comm IS
    committed.  Expected comm: start=10, finish=20.  Task1 start=1000, finish=1003.
    """

    def _setup(self):
        noc = make_noc(rows=4, cols=4, alpha=0.0, beta=1.0)
        ps = ProposedScheduler(noc)
        dag = _two_task_dag(vol=10.0)
        state = make_state(noc)
        state.reserve_task(task_id=0, processor_id=0,
                           start_time=0.0, finish_time=10.0, is_primary=True)
        # Block P5 so that duplicating task0 there is more costly than remote comm.
        # dup_start=1000 → EFT_dup=1008 > EFT_no_dup=1003 → Delta<0 → no dup.
        state.reserve_task(task_id=99, processor_id=5,
                           start_time=0.0, finish_time=1000.0)
        return ps, dag, state, noc

    def test_candidate_has_communication_instance(self):
        ps, dag, state, noc = self._setup()
        _start, _finish, candidate = ps.evaluate_task_on_processor(dag, state, 1, 5)
        assert len(candidate.communication_instances) == 1
        ci = candidate.communication_instances[0]
        assert ci.source_task == 0
        assert ci.target_task == 1
        assert ci.source_processor == 0
        assert ci.destination_processor == 5

    def test_communication_route_is_correct(self):
        ps, dag, state, noc = self._setup()
        _start, _finish, candidate = ps.evaluate_task_on_processor(dag, state, 1, 5)
        ci = candidate.communication_instances[0]
        expected_route = noc.get_route(0, 5)
        assert ci.route == expected_route

    def test_route_links_have_intervals(self):
        ps, dag, state, noc = self._setup()
        _start, _finish, candidate = ps.evaluate_task_on_processor(dag, state, 1, 5)
        ci = candidate.communication_instances[0]
        for link in ci.route:
            ivs = candidate.link_intervals[link]
            matching = [
                iv for iv in ivs
                if iv.start_time == pytest.approx(ci.start_time)
                and iv.finish_time == pytest.approx(ci.finish_time)
            ]
            assert len(matching) >= 1

    def test_task_start_after_comm_finish(self):
        ps, dag, state, noc = self._setup()
        start, finish, _candidate = ps.evaluate_task_on_processor(dag, state, 1, 5)
        # comm: start=10, duration=10, finish=20; P5 blocked until 1000, task starts at 1000
        assert start >= 20.0 - 1e-9
        assert finish == pytest.approx(start + 3.0)

    def test_original_state_not_mutated(self):
        ps, dag, state, noc = self._setup()
        original_ci_count = len(state.communication_instances)
        original_link_totals = {lk: len(ivs) for lk, ivs in state.link_intervals.items()}
        ps.evaluate_task_on_processor(dag, state, 1, 5)
        assert len(state.communication_instances) == original_ci_count
        for lk, count in original_link_totals.items():
            assert len(state.link_intervals[lk]) == count


# ---------------------------------------------------------------------------
# 6. Contention delay
# ---------------------------------------------------------------------------

class TestContentionDelay:
    """
    4×4 NoC, alpha=0, beta=1.
    Route P0→P5: [Link(0,1), Link(1,5)].
    Pre-reserve Link(0,1) for [0, 100).
    Comm for edge 0→1 (vol=10, duration=10) cannot start until t=100.
    Expected: comm [100, 110), task1 start=110, finish=113.
    """

    def _setup_with_blocked_link(self):
        noc = make_noc(rows=4, cols=4, alpha=0.0, beta=1.0)
        ps = ProposedScheduler(noc)
        dag = _two_task_dag(vol=10.0)
        state = make_state(noc)
        state.reserve_task(task_id=0, processor_id=0,
                           start_time=0.0, finish_time=10.0, is_primary=True)
        # Block first link on P0→P5 route
        route = noc.get_route(0, 5)
        first_link = route[0]
        state.reserve_route([first_link], start_time=0.0, finish_time=100.0)
        return ps, dag, state

    def test_comm_delayed_by_blocked_link(self):
        """Use contention_data_ready_time to confirm comm is pushed past t=100."""
        ps, dag, state = self._setup_with_blocked_link()
        ps.contention_data_ready_time(dag, state, 1, 5)
        ci = state.communication_instances[0]
        assert ci.start_time == pytest.approx(100.0)

    def test_task_start_after_delayed_comm(self):
        """DRT for task1 on P5 equals comm finish time (100+10=110)."""
        ps, dag, state = self._setup_with_blocked_link()
        drt = ps.contention_data_ready_time(dag, state, 1, 5)
        assert drt == pytest.approx(110.0)
        ci = state.communication_instances[0]
        assert ci.finish_time == pytest.approx(110.0)


# ---------------------------------------------------------------------------
# 7. Forced duplication under contention
# ---------------------------------------------------------------------------

class TestForcedDuplication:
    """
    Uses _forced_dup_dag() on 2×2 mesh with alpha=0, beta=1.
    Expected schedule (same as CD-LS; no link contention for these routes):
        task 0 → P0 [0,1]  (primary)
        task 1 → P1 [0,1]  (primary)
        task 1 → P0 [1,2]  (duplicate, is_primary=False)
        task 2 → P0 [2,3]  (primary)
    Both preds of task 2 are local on P0 → no communication instances.
    Makespan = 3.
    """

    def _schedule(self):
        return make_ps().schedule(_forced_dup_dag())

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
        assert state.get_primary_instance(2).processor_id == 0

    def test_at_least_one_dup_exists(self):
        state = self._schedule()
        dups = [
            inst
            for tid in _forced_dup_dag().task_ids()
            for inst in state.get_task_instances(tid)
            if not inst.is_primary
        ]
        assert len(dups) >= 1

    def test_dup_is_not_primary(self):
        state = self._schedule()
        for tid in _forced_dup_dag().task_ids():
            for inst in state.get_task_instances(tid):
                if not inst.is_primary:
                    assert inst.is_primary is False

    def test_each_task_has_exactly_one_primary(self):
        state = self._schedule()
        for tid in _forced_dup_dag().task_ids():
            primaries = [i for i in state.get_task_instances(tid) if i.is_primary]
            assert len(primaries) == 1

    def test_makespan(self):
        ps = make_ps()
        state = ps.schedule(_forced_dup_dag())
        assert ps.compute_makespan(state) == pytest.approx(3.0)

    def test_child_starts_after_dup_finishes(self):
        state = self._schedule()
        ti2 = state.get_primary_instance(2)
        assert ti2.processor_id == 0
        dup_on_p0 = [
            inst for inst in state.get_task_instances(1)
            if not inst.is_primary and inst.processor_id == 0
        ]
        assert dup_on_p0, "expected dup of task 1 on P0"
        assert ti2.start_time >= dup_on_p0[0].finish_time - 1e-9

    def test_validate_no_overlaps(self):
        state = self._schedule()
        state.validate_no_overlaps()

    def test_no_comms_when_all_local(self):
        """Both preds of task2 are local → no communication instances needed."""
        state = self._schedule()
        assert state.communication_instances == []


# ---------------------------------------------------------------------------
# 8. Delta_EFT tie / no improvement
# ---------------------------------------------------------------------------

class TestDeltaEFTTie:
    def test_zero_volume_no_dups(self):
        """vol=0: remote arrival == local finish; dup occupies a slot → Delta<=0."""
        ps = make_ps()
        dag = _no_dup_dag()
        state = ps.schedule(dag)
        total = sum(len(state.get_task_instances(t)) for t in dag.task_ids())
        assert total == dag.number_of_tasks()

    def test_all_instances_primary_when_no_dup(self):
        ps = make_ps()
        state = ps.schedule(_no_dup_dag())
        for tid in _no_dup_dag().task_ids():
            for inst in state.get_task_instances(tid):
                assert inst.is_primary


# ---------------------------------------------------------------------------
# 9. Existing duplicate / best-instance selection
# ---------------------------------------------------------------------------

class TestExistingDuplicateUsage:
    """
    State: task 0 primary on P0 [0,10], dup on P1 [0,5].
    Edge 0→1, vol=50.  2×2 mesh, alpha=0, beta=1.

    Arrivals for task 1 on P1:
        local dup (P1→P1):      arrival = 5.0            (no comm)
        remote primary (P0→P1): arrival = 10 + 50 = 60   (remote)
        Best = 5.0 → no communication reserved.

    Arrivals for task 1 on P0:
        local primary (P0→P0):  arrival = 10.0           (no comm)
        remote dup    (P1→P0):  arrival = 5 + 50 = 55    (remote)
        Best = 10.0 → no communication reserved.

    Arrivals for task 1 on P2 (neither P0 nor P1):
        remote primary (P0→P2): arrival = 10 + 50 = 60
        remote dup    (P1→P2):  arrival = 5 + 50 = 55
        Best = P1 dup, arrival = 55.0 → comm from P1 to P2 committed.
    """

    def _setup(self):
        noc = make_noc(rows=2, cols=2, alpha=0.0, beta=1.0)
        ps = ProposedScheduler(noc)
        dag = _two_task_dag(vol=50.0)
        state = make_state(noc)
        state.reserve_task(task_id=0, processor_id=0,
                           start_time=0.0, finish_time=10.0, is_primary=True)
        state.reserve_task(task_id=0, processor_id=1,
                           start_time=0.0, finish_time=5.0, is_primary=False)
        return ps, dag, state

    def test_local_dup_selected_on_p1(self):
        """DRT for task 1 on P1 = 5.0 (local dup wins); no comm reserved."""
        ps, dag, state = self._setup()
        drt = ps.contention_data_ready_time(dag, state, 1, 1)
        assert drt == pytest.approx(5.0)
        assert state.communication_instances == []

    def test_local_primary_selected_on_p0(self):
        """DRT for task 1 on P0 = 10.0 (local primary wins); no comm reserved."""
        ps, dag, state = self._setup()
        drt = ps.contention_data_ready_time(dag, state, 1, 0)
        assert drt == pytest.approx(10.0)
        assert state.communication_instances == []

    def test_best_remote_instance_selected_on_p2(self):
        """DRT for task 1 on P2 = 55.0 (P1 dup wins over P0 primary)."""
        ps, dag, state = self._setup()
        drt = ps.contention_data_ready_time(dag, state, 1, 2)
        assert drt == pytest.approx(55.0)

    def test_comm_from_dup_not_primary_on_p2(self):
        """Comm committed for task 1 on P2 must originate from P1 (dup), not P0 (primary)."""
        ps, dag, state = self._setup()
        ps.contention_data_ready_time(dag, state, 1, 2)
        assert len(state.communication_instances) == 1
        ci = state.communication_instances[0]
        assert ci.source_processor == 1  # P1 (dup), not P0 (primary)
        assert ci.destination_processor == 2

    def test_drt_zero_for_entry_task(self):
        noc = make_noc()
        ps = ProposedScheduler(noc)
        dag = _single_node_dag()
        state = make_state(noc)
        assert ps.contention_data_ready_time(dag, state, 0, 0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 10. Grandparent communication for dup placement
# ---------------------------------------------------------------------------

class TestGrandparentCommunication:
    """
    DAG: 0→1→2, vols=50, costs=1.  2×2 mesh, alpha=0, beta=1.
    Task 0 scheduled on P0 [0,1].
    Task 1 scheduled on P2 [51,52]  (after comm from P0, duration=50).
    When evaluating task 2 and considering dup of task1 on P1:
        grandparent comm: task0 (P0) → dup_task1 (P1), vol=50, arrival=51
        dup_task1 slot: [51,52] on P1 (if P1 is free)
    """

    def _setup(self):
        noc = make_noc(rows=2, cols=2, alpha=0.0, beta=1.0)
        ps = ProposedScheduler(noc)
        dag = _chain3_dag()
        state = make_state(noc)
        # Task 0 primary on P0 [0,1]
        state.reserve_task(task_id=0, processor_id=0,
                           start_time=0.0, finish_time=1.0, is_primary=True)
        # Task 1 primary on P2 [51,52]  (1 + 50 comm = 51 ready; slot=[51,52])
        state.reserve_task(task_id=1, processor_id=2,
                           start_time=51.0, finish_time=52.0, is_primary=True)
        return ps, dag, state

    def test_dup_of_task1_on_p1_waits_for_grandparent(self):
        """
        Dup of task1 on P1 must be committed (Delta_EFT=50>0) and must not
        start before task0's data arrives from P0.

        Setup guarantee: P1 is free; dup of task1 on P1 gives EFT=53 vs
        EFT_no_dup=103, so Delta=50>0 and the dup is always triggered.
        Grandparent comm P0→P1 vol=50, dur=50, arrival=51: dup starts at 51.
        """
        ps, dag, state = self._setup()
        _start, _finish, candidate = ps.evaluate_task_on_processor(dag, state, 2, 1)
        dup_instances = [
            inst for inst in candidate.get_task_instances(1)
            if not inst.is_primary and inst.processor_id == 1
        ]
        assert len(dup_instances) == 1, "dup of task1 on P1 must be committed (Delta_EFT=50>0)"
        assert dup_instances[0].start_time >= 51.0 - 1e-9

    def test_grandparent_comm_reserved_for_dup(self):
        """
        Grandparent comm task0 (P0) → dup_task1 (P1) must be committed.
        Dup is guaranteed (Delta_EFT=50>0) so this assertion is unconditional.
        """
        ps, dag, state = self._setup()
        _start, _finish, candidate = ps.evaluate_task_on_processor(dag, state, 2, 1)
        gp_comms = [
            ci for ci in candidate.communication_instances
            if ci.source_task == 0 and ci.target_task == 1
            and ci.destination_processor == 1
        ]
        assert len(gp_comms) == 1
        assert gp_comms[0].source_processor == 0

    def test_no_recursive_dup_of_grandparent(self):
        """Task 0 must not be duplicated (it is only a grandparent, not a direct pred of task 2)."""
        ps, dag, state = self._setup()
        _start, _finish, candidate = ps.evaluate_task_on_processor(dag, state, 2, 1)
        task0_instances = candidate.get_task_instances(0)
        assert all(inst.is_primary for inst in task0_instances)
        assert len([i for i in task0_instances if i.is_primary]) == 1


# ---------------------------------------------------------------------------
# 11. Candidate isolation
# ---------------------------------------------------------------------------

class TestCandidateIsolation:
    def test_evaluate_does_not_mutate_original_state(self):
        ps = make_ps()
        dag = _two_task_dag(vol=100.0)
        state = make_state(ps.noc)
        state.reserve_task(task_id=0, processor_id=0,
                           start_time=0.0, finish_time=5.0, is_primary=True)
        original_ci = len(state.communication_instances)
        original_link_totals = {lk: len(ivs) for lk, ivs in state.link_intervals.items()}
        original_t0_count = len(state.get_task_instances(0))

        ps.evaluate_task_on_processor(dag, state, 1, 0)
        ps.evaluate_task_on_processor(dag, state, 1, 1)

        assert len(state.communication_instances) == original_ci
        assert len(state.get_task_instances(0)) == original_t0_count
        for lk, count in original_link_totals.items():
            assert len(state.link_intervals[lk]) == count

    def test_rejected_dup_absent_from_final_state(self):
        """P1 candidate gains dup of task0 on P1; P0 wins. Final state must not have dup of task0."""
        state = make_ps().schedule(_forced_dup_dag())
        instances_0 = state.get_task_instances(0)
        assert len(instances_0) == 1
        assert instances_0[0].is_primary
        assert instances_0[0].processor_id == 0

    def test_only_winner_dups_in_final_state(self):
        state = make_ps().schedule(_forced_dup_dag())
        dag = _forced_dup_dag()
        primaries = sum(
            1 for tid in dag.task_ids()
            for inst in state.get_task_instances(tid)
            if inst.is_primary
        )
        assert primaries == dag.number_of_tasks()


# ---------------------------------------------------------------------------
# 12. Link interval integrity
# ---------------------------------------------------------------------------

class TestLinkIntervals:
    def test_validate_no_overlaps_forced_dup(self):
        state = make_ps().schedule(_forced_dup_dag())
        state.validate_no_overlaps()

    def test_validate_no_overlaps_fork_join(self):
        ps = make_ps(rows=4, cols=4, alpha=1.0, beta=1.0)
        state = ps.schedule(_fork_join_dag())
        state.validate_no_overlaps()

    def test_each_remote_comm_has_link_intervals(self):
        """
        For every CommunicationInstance with a non-empty route, every link in
        the route must have at least one interval covering [ci.start, ci.finish).
        """
        ps = make_ps(rows=4, cols=4, alpha=1.0, beta=1.0)
        state = ps.schedule(_fork_join_dag())
        for ci in state.communication_instances:
            if not ci.route:
                continue
            for link in ci.route:
                ivs = state.link_intervals[link]
                matching = [
                    iv for iv in ivs
                    if iv.start_time == pytest.approx(ci.start_time)
                    and iv.finish_time == pytest.approx(ci.finish_time)
                ]
                assert len(matching) >= 1, (
                    f"No matching interval on {link} for comm {ci}"
                )


# ---------------------------------------------------------------------------
# 13. No recursive duplication
# ---------------------------------------------------------------------------

class TestNoRecursiveDuplication:
    def test_only_direct_predecessors_duplicated(self):
        """
        Chain 0→1→2→3. Evaluate task3 on P1 with tasks 0,1,2 scheduled.
        Only task2 (direct pred) can be duped; tasks 0 and 1 must not be duped.
        """
        noc = make_noc(rows=2, cols=2, alpha=0.0, beta=1.0)
        ps = ProposedScheduler(noc)
        g = nx.DiGraph()
        for i in range(4):
            g.add_node(i, computation_cost=1.0)
        for i in range(3):
            g.add_edge(i, i + 1, communication_volume=50.0)
        dag = DAGGraph(g)
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 1.0, is_primary=True)
        state.reserve_task(1, 1, 51.0, 52.0, is_primary=True)
        state.reserve_task(2, 0, 52.0, 53.0, is_primary=True)

        _s, _f, candidate = ps.evaluate_task_on_processor(dag, state, 3, 1)

        # task0 and task1 must have no extra instances
        assert len([i for i in candidate.get_task_instances(0) if not i.is_primary]) == 0
        assert len([i for i in candidate.get_task_instances(1) if not i.is_primary]) == 0

    def test_grandparent_not_duplicated_for_dup_placement(self):
        """
        Scheduling _chain3_dag: placing a dup of task1 should NOT create a dup of task0.
        Task0's data arrives at the dup location via communication, not via duplication.
        """
        ps = make_ps(rows=2, cols=2, alpha=0.0, beta=1.0)
        state = ps.schedule(_chain3_dag())
        # task0 must have exactly one primary, no dups
        t0_instances = state.get_task_instances(0)
        assert len(t0_instances) == 1
        assert t0_instances[0].is_primary


# ---------------------------------------------------------------------------
# 14. Comparison with baselines
# ---------------------------------------------------------------------------

class TestBaselineComparison:
    def test_all_schedulers_schedule_all_tasks(self):
        noc = make_noc()
        dag = _forced_dup_dag()
        for sched in [
            HEFTScheduler(noc),
            ContentionAwareScheduler(noc),
            ClassicalDuplicationScheduler(noc),
            ProposedScheduler(noc),
        ]:
            state = sched.schedule(dag)
            for tid in dag.task_ids():
                assert state.has_task_instance(tid)

    def test_heft_has_no_dups(self):
        noc = make_noc()
        state = HEFTScheduler(noc).schedule(_forced_dup_dag())
        for tid in _forced_dup_dag().task_ids():
            assert len(state.get_task_instances(tid)) == 1

    def test_proposed_has_dup_on_forced_dag(self):
        ps = make_ps()
        state = ps.schedule(_forced_dup_dag())
        total = sum(
            len(state.get_task_instances(tid))
            for tid in _forced_dup_dag().task_ids()
        )
        assert total > _forced_dup_dag().number_of_tasks()

    def test_proposed_makespan_better_than_heft_on_forced_dag(self):
        noc = make_noc()
        ps = ProposedScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _forced_dup_dag()
        assert ps.compute_makespan(ps.schedule(dag)) < heft.compute_makespan(heft.schedule(dag))


# ---------------------------------------------------------------------------
# 15. compute_makespan
# ---------------------------------------------------------------------------

class TestMakespan:
    def test_equals_max_processor_finish_time(self):
        ps = make_ps()
        state = ps.schedule(_forced_dup_dag())
        assert ps.compute_makespan(state) == pytest.approx(
            state.max_processor_finish_time()
        )

    def test_rejects_non_state(self):
        with pytest.raises(ValueError):
            make_ps().compute_makespan("not a state")  # type: ignore[arg-type]

    def test_rejects_mismatched_noc(self):
        ps = make_ps(rows=2, cols=2)
        foreign = ScheduleState(MeshNoC(rows=4, cols=4))
        with pytest.raises(ValueError):
            ps.compute_makespan(foreign)

    def test_rejects_same_topology_different_alpha_beta(self):
        ps = make_ps(rows=2, cols=2, alpha=1.0, beta=1.0)
        foreign = ScheduleState(MeshNoC(rows=2, cols=2, alpha=99.0, beta=99.0))
        with pytest.raises(ValueError):
            ps.compute_makespan(foreign)


# ---------------------------------------------------------------------------
# 16. Input validation
# ---------------------------------------------------------------------------

class TestValidation:
    # -- schedule --

    def test_schedule_rejects_raw_digraph(self):
        with pytest.raises(ValueError):
            make_ps().schedule(nx.DiGraph())  # type: ignore[arg-type]

    # -- evaluate_task_on_processor --

    def _base_state(self, ps: ProposedScheduler) -> tuple[DAGGraph, ScheduleState]:
        dag = _two_task_dag(vol=5.0)
        state = make_state(ps.noc)
        state.reserve_task(0, 0, 0.0, 5.0)
        return dag, state

    def test_evaluate_rejects_raw_digraph(self):
        ps = make_ps()
        state = make_state(ps.noc)
        with pytest.raises(ValueError):
            ps.evaluate_task_on_processor(nx.DiGraph(), state, 0, 0)  # type: ignore[arg-type]

    def test_evaluate_rejects_non_state(self):
        ps = make_ps()
        dag = _single_node_dag()
        with pytest.raises(ValueError):
            ps.evaluate_task_on_processor(dag, "bad", 0, 0)  # type: ignore[arg-type]

    def test_evaluate_rejects_mismatched_noc(self):
        ps = make_ps(rows=2, cols=2)
        dag = _single_node_dag()
        foreign = ScheduleState(MeshNoC(rows=4, cols=4))
        with pytest.raises(ValueError, match="NoC configuration"):
            ps.evaluate_task_on_processor(dag, foreign, 0, 0)

    def test_evaluate_rejects_same_topology_different_alpha_beta(self):
        ps = make_ps(rows=2, cols=2, alpha=1.0, beta=1.0)
        dag = _single_node_dag()
        foreign = ScheduleState(MeshNoC(rows=2, cols=2, alpha=99.0, beta=99.0))
        with pytest.raises(ValueError, match="NoC configuration"):
            ps.evaluate_task_on_processor(dag, foreign, 0, 0)

    def test_evaluate_rejects_bool_task_id(self):
        ps = make_ps()
        dag, state = self._base_state(ps)
        with pytest.raises(ValueError):
            ps.evaluate_task_on_processor(dag, state, True, 0)  # type: ignore[arg-type]

    def test_evaluate_rejects_non_int_task_id(self):
        ps = make_ps()
        dag, state = self._base_state(ps)
        with pytest.raises(ValueError):
            ps.evaluate_task_on_processor(dag, state, 1.0, 0)  # type: ignore[arg-type]

    def test_evaluate_rejects_missing_task_id(self):
        ps = make_ps()
        dag, state = self._base_state(ps)
        with pytest.raises(ValueError):
            ps.evaluate_task_on_processor(dag, state, 999, 0)

    def test_evaluate_rejects_bool_processor_id(self):
        ps = make_ps()
        dag, state = self._base_state(ps)
        with pytest.raises(ValueError):
            ps.evaluate_task_on_processor(dag, state, 1, True)  # type: ignore[arg-type]

    def test_evaluate_rejects_non_int_processor_id(self):
        ps = make_ps()
        dag, state = self._base_state(ps)
        with pytest.raises(ValueError):
            ps.evaluate_task_on_processor(dag, state, 1, 0.0)  # type: ignore[arg-type]

    def test_evaluate_rejects_invalid_processor_id(self):
        ps = make_ps()
        dag, state = self._base_state(ps)
        with pytest.raises(ValueError):
            ps.evaluate_task_on_processor(dag, state, 1, 999)

    def test_evaluate_rejects_unscheduled_predecessor(self):
        ps = make_ps()
        dag = _two_task_dag(vol=5.0)
        state = make_state(ps.noc)  # task 0 NOT scheduled
        with pytest.raises(ValueError):
            ps.evaluate_task_on_processor(dag, state, 1, 0)

    # -- contention_data_ready_time --

    def test_drt_rejects_unscheduled_predecessor(self):
        ps = make_ps()
        dag = _two_task_dag(vol=10.0)
        state = make_state(ps.noc)
        with pytest.raises(ValueError):
            ps.contention_data_ready_time(dag, state, 1, 0)

    def test_drt_rejects_bool_task_id(self):
        ps = make_ps()
        state = make_state(ps.noc)
        with pytest.raises(ValueError):
            ps.contention_data_ready_time(_single_node_dag(), state, True, 0)  # type: ignore[arg-type]

    def test_drt_rejects_invalid_processor_id(self):
        ps = make_ps()
        state = make_state(ps.noc)
        with pytest.raises(ValueError):
            ps.contention_data_ready_time(_single_node_dag(), state, 0, 999)


# ---------------------------------------------------------------------------
# 17. Synthetic DAG sanity
# ---------------------------------------------------------------------------

class TestSyntheticDag:
    def test_20_task_dag_schedules_correctly(self):
        from src.dag_generator import generate_dag
        g = generate_dag(n_tasks=20, edge_prob=0.3, ccr=1.0,
                         comp_range=(10, 100), seed=42)
        dag = DAGGraph(g)
        ps = make_ps(rows=4, cols=4, alpha=1.0, beta=1.0)
        state = ps.schedule(dag)
        for tid in dag.task_ids():
            assert state.has_task_instance(tid)
            primaries = [i for i in state.get_task_instances(tid) if i.is_primary]
            assert len(primaries) == 1
        state.validate_no_overlaps()

    def test_comm_instances_have_non_empty_routes(self):
        from src.dag_generator import generate_dag
        g = generate_dag(n_tasks=20, edge_prob=0.3, ccr=5.0,
                         comp_range=(10, 100), seed=7)
        dag = DAGGraph(g)
        ps = make_ps(rows=4, cols=4, alpha=1.0, beta=1.0)
        state = ps.schedule(dag)
        # All remote CommunicationInstances must have a non-empty route
        for ci in state.communication_instances:
            if ci.source_processor != ci.destination_processor:
                assert len(ci.route) > 0
        state.validate_no_overlaps()


# ---------------------------------------------------------------------------
# 18. Local-instance tie preference
# ---------------------------------------------------------------------------

class TestLocalTiePreference:
    """
    When a remote primary instance and a local duplicate instance both deliver
    data at arrival time X, the local instance must win.

    Setup: task0 primary on P0 [0,10], dup on P1 [0,10].
    Edge 0→1, vol=0.  alpha=0, beta=1 → remote duration = 0 → remote arrival = 10.
    Local dup arrival on P1 = 10.  Tie → local must win → no CommunicationInstance.
    """

    def _setup(self):
        noc = make_noc(rows=2, cols=2, alpha=0.0, beta=1.0)
        ps = ProposedScheduler(noc)
        dag = _two_task_dag(vol=0.0)
        state = make_state(noc)
        state.reserve_task(task_id=0, processor_id=0,
                           start_time=0.0, finish_time=10.0, is_primary=True)
        state.reserve_task(task_id=0, processor_id=1,
                           start_time=0.0, finish_time=10.0, is_primary=False)
        return ps, dag, state

    def test_drt_equals_local_finish_time(self):
        """DRT for task1 on P1 is 10.0 (the local dup finish time)."""
        ps, dag, state = self._setup()
        drt = ps.contention_data_ready_time(dag, state, 1, 1)
        assert drt == pytest.approx(10.0)

    def test_no_communication_instance_created(self):
        """Local wins the tie: no CommunicationInstance must be committed."""
        ps, dag, state = self._setup()
        ps.contention_data_ready_time(dag, state, 1, 1)
        assert state.communication_instances == []

    def test_no_link_interval_reserved(self):
        """Local wins the tie: no link interval must be reserved."""
        ps, dag, state = self._setup()
        ps.contention_data_ready_time(dag, state, 1, 1)
        for ivs in state.link_intervals.values():
            assert ivs == []


# ---------------------------------------------------------------------------
# 19. Insertion-order determinism
# ---------------------------------------------------------------------------

class TestInsertionOrderDeterminism:
    """
    Regression: schedule output must be identical for two semantically
    identical DAGs that differ only in edge insertion order.

    _contention_drt and _dup_drt_contention iterate predecessors via
    sorted(), so communication reservations follow task_id order regardless
    of the NetworkX DiGraph construction sequence.

    DAG shape: entry tasks 0 (cost=5) and 1 (cost=1); exit task 2 (cost=1).
    Edges: 0→2 (vol=1) and 1→2 (vol=10).
    On a 4×4 mesh (alpha=0, beta=1):
      - Route P0→P5 and route P1→P5 share Link(1,5).
      - Different insertion orders give different networkx predecessor iteration
        sequences, which without sorting produce different link reservations and
        potentially different DRTs.  With sorted(), both DAGs produce identical
        schedules.
    """

    @staticmethod
    def _make_dag(reversed_edges: bool) -> DAGGraph:
        g = nx.DiGraph()
        g.add_node(0, computation_cost=5.0)
        g.add_node(1, computation_cost=1.0)
        g.add_node(2, computation_cost=1.0)
        if reversed_edges:
            g.add_edge(1, 2, communication_volume=10.0)
            g.add_edge(0, 2, communication_volume=1.0)
        else:
            g.add_edge(0, 2, communication_volume=1.0)
            g.add_edge(1, 2, communication_volume=10.0)
        return DAGGraph(g)

    @staticmethod
    def _primary_summary(state: ScheduleState, task_ids) -> dict:
        return {
            tid: (
                state.get_primary_instance(tid).processor_id,
                state.get_primary_instance(tid).start_time,
                state.get_primary_instance(tid).finish_time,
            )
            for tid in task_ids
        }

    @staticmethod
    def _dup_summary(state: ScheduleState, task_ids) -> list:
        return sorted(
            (inst.task_id, inst.processor_id, inst.start_time, inst.finish_time)
            for tid in task_ids
            for inst in state.get_task_instances(tid)
            if not inst.is_primary
        )

    @staticmethod
    def _comm_summary(state: ScheduleState) -> list:
        return sorted(
            (
                ci.source_task, ci.target_task,
                ci.source_processor, ci.destination_processor,
                ci.start_time, ci.finish_time,
                tuple(ci.route),
            )
            for ci in state.communication_instances
        )

    def test_primary_assignments_identical(self):
        noc = make_noc(rows=4, cols=4, alpha=0.0, beta=1.0)
        ps = ProposedScheduler(noc)
        state_fwd = ps.schedule(self._make_dag(reversed_edges=False))
        state_rev = ps.schedule(self._make_dag(reversed_edges=True))
        task_ids = [0, 1, 2]
        assert self._primary_summary(state_fwd, task_ids) == \
               self._primary_summary(state_rev, task_ids)

    def test_duplicate_instances_identical(self):
        noc = make_noc(rows=4, cols=4, alpha=0.0, beta=1.0)
        ps = ProposedScheduler(noc)
        state_fwd = ps.schedule(self._make_dag(reversed_edges=False))
        state_rev = ps.schedule(self._make_dag(reversed_edges=True))
        task_ids = [0, 1, 2]
        assert self._dup_summary(state_fwd, task_ids) == \
               self._dup_summary(state_rev, task_ids)

    def test_communication_instances_identical(self):
        noc = make_noc(rows=4, cols=4, alpha=0.0, beta=1.0)
        ps = ProposedScheduler(noc)
        state_fwd = ps.schedule(self._make_dag(reversed_edges=False))
        state_rev = ps.schedule(self._make_dag(reversed_edges=True))
        assert self._comm_summary(state_fwd) == self._comm_summary(state_rev)
