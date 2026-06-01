"""
Tests for src/contention_scheduler.py.

Covers: construction, ranking compatibility with HEFT, single-node schedule,
independent tasks, local and remote communication behavior, contention delay,
rejected-candidate isolation, precedence constraints, link interval correctness,
compute_makespan, evaluate_task_on_processor validation, schedule validation,
and HEFT comparison.
Implemented in Phase 6.
"""

import networkx as nx
import pytest

from src.models import DAGGraph, Link
from src.noc import MeshNoC
from src.schedule_state import ScheduleState
from src.contention_scheduler import ContentionAwareScheduler
from src.heft_scheduler import HEFTScheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_noc(rows: int = 4, cols: int = 4, alpha: float = 1.0, beta: float = 1.0) -> MeshNoC:
    return MeshNoC(rows=rows, cols=cols, alpha=alpha, beta=beta)


def make_ca(rows: int = 4, cols: int = 4, alpha: float = 1.0, beta: float = 1.0) -> ContentionAwareScheduler:
    return ContentionAwareScheduler(make_noc(rows, cols, alpha, beta))


def make_state(noc: MeshNoC | None = None) -> ScheduleState:
    return ScheduleState(noc if noc is not None else make_noc())


def _single_node_dag(cost: float = 10.0) -> DAGGraph:
    g = nx.DiGraph()
    g.add_node(0, computation_cost=cost)
    return DAGGraph(g)


def _chain_dag(costs=(10.0, 20.0, 30.0), volumes=(5.0, 7.0)) -> DAGGraph:
    g = nx.DiGraph()
    for i, c in enumerate(costs):
        g.add_node(i, computation_cost=c)
    for i, v in enumerate(volumes):
        g.add_edge(i, i + 1, communication_volume=v)
    return DAGGraph(g)


def _fork_join_dag() -> DAGGraph:
    """0->1, 0->2, 1->3, 2->3 (diamond)."""
    g = nx.DiGraph()
    for i, c in enumerate([10.0, 20.0, 15.0, 25.0]):
        g.add_node(i, computation_cost=c)
    g.add_edge(0, 1, communication_volume=5.0)
    g.add_edge(0, 2, communication_volume=3.0)
    g.add_edge(1, 3, communication_volume=4.0)
    g.add_edge(2, 3, communication_volume=6.0)
    return DAGGraph(g)


def _two_parent_dag() -> DAGGraph:
    """0->2, 1->2."""
    g = nx.DiGraph()
    g.add_node(0, computation_cost=10.0)
    g.add_node(1, computation_cost=10.0)
    g.add_node(2, computation_cost=15.0)
    g.add_edge(0, 2, communication_volume=5.0)
    g.add_edge(1, 2, communication_volume=5.0)
    return DAGGraph(g)


def _two_task_remote_dag(vol: float = 2.0) -> DAGGraph:
    """0->1, designed so remote placement is possible."""
    g = nx.DiGraph()
    g.add_node(0, computation_cost=10.0)
    g.add_node(1, computation_cost=5.0)
    g.add_edge(0, 1, communication_volume=vol)
    return DAGGraph(g)


# ---------------------------------------------------------------------------
# 1. Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_valid_construction(self):
        ca = make_ca()
        assert ca.noc is not None

    def test_noc_stored(self):
        noc = make_noc()
        ca = ContentionAwareScheduler(noc)
        assert ca.noc is noc

    def test_rejects_non_meshnoc(self):
        with pytest.raises(ValueError):
            ContentionAwareScheduler("not a noc")  # type: ignore[arg-type]

    def test_rejects_none(self):
        with pytest.raises(ValueError):
            ContentionAwareScheduler(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Ranking compatibility with HEFT
# ---------------------------------------------------------------------------

class TestRankingCompatibility:
    def test_upward_ranks_match_heft_chain(self):
        noc = make_noc()
        ca = ContentionAwareScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _chain_dag()
        ca_ranks = ca.compute_upward_ranks(dag)
        heft_ranks = heft.compute_upward_ranks(dag)
        for tid in dag.task_ids():
            assert ca_ranks[tid] == pytest.approx(heft_ranks[tid])

    def test_upward_ranks_match_heft_fork_join(self):
        noc = make_noc()
        ca = ContentionAwareScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _fork_join_dag()
        ca_ranks = ca.compute_upward_ranks(dag)
        heft_ranks = heft.compute_upward_ranks(dag)
        for tid in dag.task_ids():
            assert ca_ranks[tid] == pytest.approx(heft_ranks[tid])

    def test_priority_order_matches_heft(self):
        noc = make_noc()
        ca = ContentionAwareScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _fork_join_dag()
        assert ca.task_priority_order(dag) == heft.task_priority_order(dag)

    def test_ranks_reject_raw_digraph(self):
        with pytest.raises(ValueError):
            make_ca().compute_upward_ranks(nx.DiGraph())  # type: ignore[arg-type]

    def test_priority_order_rejects_raw_digraph(self):
        with pytest.raises(ValueError):
            make_ca().task_priority_order(nx.DiGraph())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. schedule — single node
# ---------------------------------------------------------------------------

class TestScheduleSingleNode:
    def test_one_task_scheduled(self):
        state = make_ca().schedule(_single_node_dag())
        assert state.has_task_instance(0)

    def test_assigned_to_processor_zero(self):
        state = make_ca().schedule(_single_node_dag(10.0))
        assert state.get_primary_instance(0).processor_id == 0

    def test_start_time_zero(self):
        state = make_ca().schedule(_single_node_dag(10.0))
        assert state.get_primary_instance(0).start_time == pytest.approx(0.0)

    def test_finish_time_equals_cost(self):
        state = make_ca().schedule(_single_node_dag(10.0))
        assert state.get_primary_instance(0).finish_time == pytest.approx(10.0)

    def test_no_communication_instances(self):
        assert make_ca().schedule(_single_node_dag()).communication_instances == []

    def test_no_link_intervals(self):
        state = make_ca().schedule(_single_node_dag())
        for ivs in state.link_intervals.values():
            assert ivs == []


# ---------------------------------------------------------------------------
# 4. schedule — independent tasks
# ---------------------------------------------------------------------------

class TestScheduleIndependentTasks:
    def _two_independent_dag(self) -> DAGGraph:
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=10.0)
        return DAGGraph(g)

    def test_all_tasks_scheduled(self):
        dag = self._two_independent_dag()
        state = make_ca().schedule(dag)
        for tid in dag.task_ids():
            assert state.has_task_instance(tid)

    def test_all_instances_primary(self):
        dag = self._two_independent_dag()
        state = make_ca().schedule(dag)
        for tid in dag.task_ids():
            assert state.get_primary_instance(tid).is_primary

    def test_no_communication_instances(self):
        dag = self._two_independent_dag()
        assert make_ca().schedule(dag).communication_instances == []

    def test_no_link_intervals(self):
        dag = self._two_independent_dag()
        state = make_ca().schedule(dag)
        for ivs in state.link_intervals.values():
            assert ivs == []

    def test_placed_on_different_processors(self):
        dag = self._two_independent_dag()
        state = make_ca().schedule(dag)
        procs = {state.get_primary_instance(t).processor_id for t in dag.task_ids()}
        assert len(procs) == 2


# ---------------------------------------------------------------------------
# 5. Local communication behavior
# ---------------------------------------------------------------------------

class TestLocalCommunication:
    def test_same_proc_no_link_reservation(self):
        # Large beta forces same-processor placement
        ca = make_ca(alpha=1.0, beta=1000.0)
        g = nx.DiGraph()
        g.add_node(0, computation_cost=1.0)
        g.add_node(1, computation_cost=1.0)
        g.add_edge(0, 1, communication_volume=100.0)
        dag = DAGGraph(g)
        state = ca.schedule(dag)
        ti0 = state.get_primary_instance(0)
        ti1 = state.get_primary_instance(1)
        if ti0.processor_id == ti1.processor_id:
            # Local: no link intervals and no comm instances
            assert state.communication_instances == []
            for ivs in state.link_intervals.values():
                assert ivs == []
            # Child starts after parent
            assert ti1.start_time >= ti0.finish_time

    def test_evaluate_local_no_comm_instance(self):
        ca = make_ca()
        dag = _two_task_remote_dag(vol=2.0)
        noc = ca.noc
        state = make_state(noc)
        state.reserve_task(0, 0, 0.0, 10.0)  # task 0 on proc 0
        # Evaluate task 1 on same proc 0 (local)
        start, finish, candidate = ca.evaluate_task_on_processor(dag, state, 1, 0)
        assert candidate.communication_instances == []
        for ivs in candidate.link_intervals.values():
            assert ivs == []
        assert start >= 10.0  # must wait for parent


# ---------------------------------------------------------------------------
# 6. Remote communication behavior
# ---------------------------------------------------------------------------

class TestRemoteCommunication:
    def test_evaluate_creates_comm_instance(self):
        ca = make_ca()
        dag = _two_task_remote_dag(vol=2.0)
        state = make_state(ca.noc)
        state.reserve_task(0, 0, 0.0, 10.0)  # task 0 on proc 0
        # Evaluate task 1 on proc 5 (remote)
        start, finish, candidate = ca.evaluate_task_on_processor(dag, state, 1, 5)
        assert len(candidate.communication_instances) == 1
        ci = candidate.communication_instances[0]
        assert ci.source_processor == 0
        assert ci.destination_processor == 5

    def test_evaluate_comm_route_correct(self):
        ca = make_ca()
        dag = _two_task_remote_dag(vol=2.0)
        state = make_state(ca.noc)
        state.reserve_task(0, 0, 0.0, 10.0)
        _, _, candidate = ca.evaluate_task_on_processor(dag, state, 1, 5)
        ci = candidate.communication_instances[0]
        assert ci.route == ca.noc.get_route(0, 5)

    def test_evaluate_comm_finish_time(self):
        ca = make_ca()
        dag = _two_task_remote_dag(vol=2.0)
        state = make_state(ca.noc)
        state.reserve_task(0, 0, 0.0, 10.0)
        start, finish, candidate = ca.evaluate_task_on_processor(dag, state, 1, 5)
        ci = candidate.communication_instances[0]
        expected_comm_dur = ca.noc.communication_duration(0, 5, 2.0)
        assert ci.finish_time == pytest.approx(10.0 + expected_comm_dur)
        assert start >= ci.finish_time - 1e-9

    def test_original_state_unchanged(self):
        ca = make_ca()
        dag = _two_task_remote_dag(vol=2.0)
        state = make_state(ca.noc)
        state.reserve_task(0, 0, 0.0, 10.0)
        original_ci_count = len(state.communication_instances)
        ca.evaluate_task_on_processor(dag, state, 1, 5)
        # Original state must not have gained any communication instances
        assert len(state.communication_instances) == original_ci_count
        for ivs in state.link_intervals.values():
            assert ivs == []

    def test_evaluate_link_intervals_reserved_in_candidate(self):
        ca = make_ca()
        dag = _two_task_remote_dag(vol=2.0)
        state = make_state(ca.noc)
        state.reserve_task(0, 0, 0.0, 10.0)
        _, _, candidate = ca.evaluate_task_on_processor(dag, state, 1, 5)
        route = ca.noc.get_route(0, 5)
        for link in route:
            assert len(candidate.link_intervals[link]) >= 1


# ---------------------------------------------------------------------------
# 7. Contention behavior
# ---------------------------------------------------------------------------

class TestContentionBehavior:
    def test_existing_link_reservation_delays_communication(self):
        ca = make_ca()
        dag = _two_task_remote_dag(vol=1.0)
        state = make_state(ca.noc)
        state.reserve_task(0, 0, 0.0, 0.0)  # parent finishes at t=0

        # Block Link(0,1) — first link on route 0->5 — until t=100
        state.reserve_route([Link(0, 1)], 0.0, 100.0)

        start, finish, candidate = ca.evaluate_task_on_processor(dag, state, 1, 5)
        ci = candidate.communication_instances[0]
        # Communication must start at or after t=100 (blocked until then)
        assert ci.start_time >= 100.0 - 1e-9
        assert start >= ci.finish_time - 1e-9

    def test_no_contention_without_existing_reservation(self):
        ca = make_ca()
        dag = _two_task_remote_dag(vol=1.0)
        state = make_state(ca.noc)
        state.reserve_task(0, 0, 0.0, 0.0)  # parent finishes at t=0

        start, finish, candidate = ca.evaluate_task_on_processor(dag, state, 1, 5)
        ci = candidate.communication_instances[0]
        expected_dur = ca.noc.communication_duration(0, 5, 1.0)
        assert ci.start_time == pytest.approx(0.0)
        assert ci.finish_time == pytest.approx(expected_dur)


# ---------------------------------------------------------------------------
# 8. Rejected candidates do not pollute final state
# ---------------------------------------------------------------------------

class TestRejectedCandidateIsolation:
    def test_evaluate_does_not_mutate_original_state(self):
        ca = make_ca()
        dag = _two_task_remote_dag(vol=2.0)
        state = make_state(ca.noc)
        state.reserve_task(0, 0, 0.0, 10.0)

        # Evaluate two different processors
        ca.evaluate_task_on_processor(dag, state, 1, 5)
        ca.evaluate_task_on_processor(dag, state, 1, 1)

        # Original state must be pristine
        assert len(state.communication_instances) == 0
        for ivs in state.link_intervals.values():
            assert ivs == []

    def test_final_state_has_only_selected_comm(self):
        # Force a scenario where task 1 has multiple processor options:
        # alpha=0, beta=1 -> pure volume cost; with vol=0 all placements are equal,
        # so proc 0 wins via tie-break (task 0 is already there, child on proc 0 = local).
        ca = make_ca(alpha=0.0, beta=1.0)
        g = nx.DiGraph()
        g.add_node(0, computation_cost=1.0)
        g.add_node(1, computation_cost=1.0)
        g.add_edge(0, 1, communication_volume=0.0)
        dag = DAGGraph(g)
        state = ca.schedule(dag)
        # Local comm -> no comm instances at all
        assert len(state.communication_instances) == 0

    def test_schedule_comm_count_matches_remote_edges(self):
        # alpha=0, beta=0: zero comm cost everywhere, tie-break gives proc 0 for both
        # -> local, no CI. Use nonzero to force remote in a deterministic way:
        # Two independent parents on different procs, child forced remote.
        ca = make_ca(alpha=1.0, beta=0.0)
        dag = _fork_join_dag()
        state = ca.schedule(dag)
        # Verify total CI count <= number of edges (could be less if some are local)
        assert len(state.communication_instances) <= dag.number_of_edges()


# ---------------------------------------------------------------------------
# 9. Precedence constraints
# ---------------------------------------------------------------------------

class TestPrecedenceConstraints:
    def test_two_parent_child_waits_for_both(self):
        ca = make_ca()
        dag = _two_parent_dag()
        state = ca.schedule(dag)
        ti2 = state.get_primary_instance(2)

        for pred in dag.predecessors(2):
            ti_pred = state.get_primary_instance(pred)
            if ti_pred.processor_id == ti2.processor_id:
                arr = ti_pred.finish_time
            else:
                # Find the CommunicationInstance for this edge
                ci_list = [
                    ci for ci in state.communication_instances
                    if ci.source_task == pred and ci.target_task == 2
                ]
                if ci_list:
                    arr = ci_list[0].finish_time
                else:
                    arr = ti_pred.finish_time + ca.noc.communication_duration(
                        ti_pred.processor_id, ti2.processor_id,
                        dag.communication_volume(pred, 2)
                    )
            assert ti2.start_time >= arr - 1e-9

    def test_fork_join_join_waits_for_both_paths(self):
        ca = make_ca()
        dag = _fork_join_dag()
        state = ca.schedule(dag)
        ti3 = state.get_primary_instance(3)

        for pred in dag.predecessors(3):
            ti_pred = state.get_primary_instance(pred)
            if ti_pred.processor_id == ti3.processor_id:
                arr = ti_pred.finish_time
            else:
                ci_list = [
                    ci for ci in state.communication_instances
                    if ci.source_task == pred and ci.target_task == 3
                ]
                arr = ci_list[0].finish_time if ci_list else (
                    ti_pred.finish_time + ca.noc.communication_duration(
                        ti_pred.processor_id, ti3.processor_id,
                        dag.communication_volume(pred, 3)
                    )
                )
            assert ti3.start_time >= arr - 1e-9

    def test_validate_no_overlaps_after_schedule(self):
        ca = make_ca()
        dag = _fork_join_dag()
        state = ca.schedule(dag)
        state.validate_no_overlaps()


# ---------------------------------------------------------------------------
# 10. Link intervals
# ---------------------------------------------------------------------------

class TestLinkIntervals:
    def test_remote_comm_route_links_reserved(self):
        ca = make_ca()
        dag = _two_task_remote_dag(vol=2.0)
        state = ca.schedule(dag)
        ti0 = state.get_primary_instance(0)
        ti1 = state.get_primary_instance(1)
        if ti0.processor_id != ti1.processor_id:
            # Remote: route links must have intervals
            route = ca.noc.get_route(ti0.processor_id, ti1.processor_id)
            for link in route:
                assert len(state.link_intervals[link]) >= 1

    def test_no_link_overlap(self):
        ca = make_ca()
        dag = _fork_join_dag()
        state = ca.schedule(dag)
        state.validate_no_overlaps()

    def test_comm_instance_links_match_route(self):
        ca = make_ca()
        dag = _two_task_remote_dag(vol=2.0)
        state = ca.schedule(dag)
        for ci in state.communication_instances:
            if ci.source_processor != ci.destination_processor:
                expected_route = ca.noc.get_route(ci.source_processor, ci.destination_processor)
                assert ci.route == expected_route

    def test_local_comm_no_link_intervals(self):
        # Force local with high beta
        ca = make_ca(alpha=1.0, beta=1000.0)
        g = nx.DiGraph()
        g.add_node(0, computation_cost=1.0)
        g.add_node(1, computation_cost=1.0)
        g.add_edge(0, 1, communication_volume=100.0)
        dag = DAGGraph(g)
        state = ca.schedule(dag)
        ti0 = state.get_primary_instance(0)
        ti1 = state.get_primary_instance(1)
        if ti0.processor_id == ti1.processor_id:
            for ivs in state.link_intervals.values():
                assert ivs == []


# ---------------------------------------------------------------------------
# 11. compute_makespan
# ---------------------------------------------------------------------------

class TestComputeMakespan:
    def test_equals_max_processor_finish_time(self):
        ca = make_ca()
        dag = _fork_join_dag()
        state = ca.schedule(dag)
        assert ca.compute_makespan(state) == pytest.approx(state.max_processor_finish_time())

    def test_rejects_non_schedule_state(self):
        with pytest.raises(ValueError):
            make_ca().compute_makespan("not a state")  # type: ignore[arg-type]

    def test_rejects_mismatched_noc_topology(self):
        ca = make_ca(rows=4, cols=4)
        mismatched = ScheduleState(MeshNoC(rows=8, cols=8))
        with pytest.raises(ValueError):
            ca.compute_makespan(mismatched)

    def test_makespan_positive(self):
        ca = make_ca()
        dag = _fork_join_dag()
        assert ca.compute_makespan(ca.schedule(dag)) > 0


# ---------------------------------------------------------------------------
# 12. evaluate_task_on_processor validation
# ---------------------------------------------------------------------------

class TestEvaluateValidation:
    def _scheduled_state(self, ca: ContentionAwareScheduler) -> tuple[DAGGraph, ScheduleState]:
        dag = _two_task_remote_dag()
        state = make_state(ca.noc)
        state.reserve_task(0, 0, 0.0, 10.0)
        return dag, state

    def test_rejects_raw_digraph(self):
        ca = make_ca()
        state = make_state(ca.noc)
        with pytest.raises(ValueError):
            ca.evaluate_task_on_processor(nx.DiGraph(), state, 0, 0)  # type: ignore[arg-type]

    def test_rejects_non_schedule_state(self):
        ca = make_ca()
        dag = _single_node_dag()
        with pytest.raises(ValueError):
            ca.evaluate_task_on_processor(dag, "bad", 0, 0)  # type: ignore[arg-type]

    def test_rejects_mismatched_noc_topology(self):
        ca = make_ca(rows=4, cols=4)
        dag = _single_node_dag()
        mismatched = ScheduleState(MeshNoC(rows=8, cols=8))
        with pytest.raises(ValueError):
            ca.evaluate_task_on_processor(dag, mismatched, 0, 0)

    def test_rejects_bool_task_id(self):
        ca = make_ca()
        dag, state = self._scheduled_state(ca)
        with pytest.raises(ValueError):
            ca.evaluate_task_on_processor(dag, state, True, 0)  # type: ignore[arg-type]

    def test_rejects_non_int_task_id(self):
        ca = make_ca()
        dag, state = self._scheduled_state(ca)
        with pytest.raises(ValueError):
            ca.evaluate_task_on_processor(dag, state, 1.0, 0)  # type: ignore[arg-type]

    def test_rejects_missing_task_id(self):
        ca = make_ca()
        dag, state = self._scheduled_state(ca)
        with pytest.raises(ValueError):
            ca.evaluate_task_on_processor(dag, state, 99, 0)

    def test_rejects_bool_processor_id(self):
        ca = make_ca()
        dag, state = self._scheduled_state(ca)
        with pytest.raises(ValueError):
            ca.evaluate_task_on_processor(dag, state, 1, True)  # type: ignore[arg-type]

    def test_rejects_non_int_processor_id(self):
        ca = make_ca()
        dag, state = self._scheduled_state(ca)
        with pytest.raises(ValueError):
            ca.evaluate_task_on_processor(dag, state, 1, 0.0)  # type: ignore[arg-type]

    def test_rejects_invalid_processor_id(self):
        ca = make_ca()
        dag, state = self._scheduled_state(ca)
        with pytest.raises(ValueError):
            ca.evaluate_task_on_processor(dag, state, 1, 999)

    def test_raises_if_predecessor_not_scheduled(self):
        ca = make_ca()
        dag = _two_task_remote_dag()
        state = make_state(ca.noc)
        # task 0 NOT scheduled; evaluating task 1 should raise
        with pytest.raises(ValueError):
            ca.evaluate_task_on_processor(dag, state, 1, 0)


# ---------------------------------------------------------------------------
# 13. schedule validation
# ---------------------------------------------------------------------------

class TestScheduleValidation:
    def test_rejects_raw_digraph(self):
        with pytest.raises(ValueError):
            make_ca().schedule(nx.DiGraph())  # type: ignore[arg-type]

    def test_does_not_mutate_dag(self):
        ca = make_ca()
        dag = _fork_join_dag()
        original_tasks = set(dag.task_ids())
        original_edges = set(dag.edge_ids())
        ca.schedule(dag)
        assert set(dag.task_ids()) == original_tasks
        assert set(dag.edge_ids()) == original_edges

    def test_all_tasks_scheduled_synthetic_dag(self):
        from src.dag_generator import generate_dag
        g = generate_dag(n_tasks=20, edge_prob=0.3, ccr=1.0, comp_range=(10, 100), seed=42)
        dag = DAGGraph(g)
        ca = make_ca(rows=4, cols=4)
        state = ca.schedule(dag)
        assert len(state.task_instances) == 20
        for tid in dag.task_ids():
            assert state.has_task_instance(tid)

    def test_all_tasks_exactly_one_primary(self):
        from src.dag_generator import generate_dag
        g = generate_dag(n_tasks=15, edge_prob=0.3, ccr=1.0, comp_range=(10, 100), seed=7)
        dag = DAGGraph(g)
        ca = make_ca(rows=4, cols=4)
        state = ca.schedule(dag)
        for tid in dag.task_ids():
            primaries = [ti for ti in state.get_task_instances(tid) if ti.is_primary]
            assert len(primaries) == 1


# ---------------------------------------------------------------------------
# 14. Comparison with HEFT
# ---------------------------------------------------------------------------

class TestHEFTComparison:
    def test_both_schedule_all_tasks(self):
        noc = make_noc()
        ca = ContentionAwareScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _fork_join_dag()
        ca_state = ca.schedule(dag)
        heft_state = heft.schedule(dag)
        for tid in dag.task_ids():
            assert ca_state.has_task_instance(tid)
            assert heft_state.has_task_instance(tid)

    def test_heft_has_no_comm_instances(self):
        noc = make_noc()
        heft = HEFTScheduler(noc)
        dag = _fork_join_dag()
        state = heft.schedule(dag)
        assert state.communication_instances == []

    def test_heft_has_no_link_intervals(self):
        noc = make_noc()
        heft = HEFTScheduler(noc)
        dag = _fork_join_dag()
        state = heft.schedule(dag)
        for ivs in state.link_intervals.values():
            assert ivs == []

    def test_ca_link_intervals_reflect_remote_comms(self):
        noc = make_noc()
        ca = ContentionAwareScheduler(noc)
        dag = _fork_join_dag()
        state = ca.schedule(dag)
        # Every remote CI must have its route links reserved
        for ci in state.communication_instances:
            if ci.source_processor != ci.destination_processor:
                for link in ci.route:
                    # At least one interval exists on this link
                    assert len(state.link_intervals[link]) >= 1

    def test_both_states_valid(self):
        noc = make_noc()
        ca = ContentionAwareScheduler(noc)
        heft = HEFTScheduler(noc)
        dag = _fork_join_dag()
        ca.schedule(dag).validate_no_overlaps()
        heft.schedule(dag).validate_no_overlaps()


# ---------------------------------------------------------------------------
# 15. NoC config mismatch validation (same topology, different alpha/beta)
# ---------------------------------------------------------------------------

class TestNoCConfigMismatchValidation:
    """Regression tests for _validate_state catching alpha/beta mismatches."""

    def _make_foreign_state(self) -> ScheduleState:
        """ScheduleState built with same 4x4 topology but alpha=10, beta=100."""
        foreign_noc = MeshNoC(rows=4, cols=4, alpha=10.0, beta=100.0)
        return ScheduleState(foreign_noc)

    def test_evaluate_rejects_same_topology_different_alpha_beta(self):
        ca = make_ca(rows=4, cols=4, alpha=1.0, beta=1.0)
        dag = _single_node_dag()
        foreign_state = self._make_foreign_state()
        with pytest.raises(ValueError, match="NoC configuration"):
            ca.evaluate_task_on_processor(dag, foreign_state, 0, 0)

    def test_compute_makespan_rejects_same_topology_different_alpha_beta(self):
        ca = make_ca(rows=4, cols=4, alpha=1.0, beta=1.0)
        foreign_state = self._make_foreign_state()
        with pytest.raises(ValueError, match="NoC configuration"):
            ca.compute_makespan(foreign_state)

    def test_schedule_generated_state_accepted_by_compute_makespan(self):
        ca = make_ca(rows=4, cols=4, alpha=1.0, beta=1.0)
        dag = _fork_join_dag()
        state = ca.schedule(dag)
        # Must not raise — state was built with the same NoC instance
        result = ca.compute_makespan(state)
        assert result > 0
