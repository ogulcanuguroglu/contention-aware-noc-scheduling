"""
Tests for src/heft_scheduler.py.

Covers: construction, average_hop_count, average_communication_cost,
compute_upward_ranks, task_priority_order, schedule (single node, independent
tasks, chain, fork-join), precedence constraints, estimate_data_ready_time,
processor tie-breaking, ready-task robustness, ScheduleState integration,
and input validation.
Implemented in Phase 5.
"""

import math

import networkx as nx
import pytest

from src.models import DAGGraph
from src.noc import MeshNoC
from src.heft_scheduler import HEFTScheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_noc(rows: int = 4, cols: int = 4, alpha: float = 1.0, beta: float = 1.0) -> MeshNoC:
    return MeshNoC(rows=rows, cols=cols, alpha=alpha, beta=beta)


def make_scheduler(rows: int = 4, cols: int = 4, alpha: float = 1.0, beta: float = 1.0) -> HEFTScheduler:
    return HEFTScheduler(make_noc(rows, cols, alpha, beta))


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


def _fork_dag() -> DAGGraph:
    """DAG: 0 -> 1, 0 -> 2 (fork)."""
    g = nx.DiGraph()
    g.add_node(0, computation_cost=10.0)
    g.add_node(1, computation_cost=20.0)
    g.add_node(2, computation_cost=15.0)
    g.add_edge(0, 1, communication_volume=5.0)
    g.add_edge(0, 2, communication_volume=3.0)
    return DAGGraph(g)


def _fork_join_dag() -> DAGGraph:
    """DAG: 0 -> 1, 0 -> 2, 1 -> 3, 2 -> 3 (diamond)."""
    g = nx.DiGraph()
    for i, c in enumerate([10.0, 20.0, 15.0, 25.0]):
        g.add_node(i, computation_cost=c)
    g.add_edge(0, 1, communication_volume=5.0)
    g.add_edge(0, 2, communication_volume=3.0)
    g.add_edge(1, 3, communication_volume=4.0)
    g.add_edge(2, 3, communication_volume=6.0)
    return DAGGraph(g)


def _two_parent_dag() -> DAGGraph:
    """DAG: 0 -> 2, 1 -> 2."""
    g = nx.DiGraph()
    g.add_node(0, computation_cost=10.0)
    g.add_node(1, computation_cost=10.0)
    g.add_node(2, computation_cost=15.0)
    g.add_edge(0, 2, communication_volume=5.0)
    g.add_edge(1, 2, communication_volume=5.0)
    return DAGGraph(g)


# ---------------------------------------------------------------------------
# 1. Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_valid_construction(self):
        s = make_scheduler()
        assert s.noc is not None

    def test_noc_stored(self):
        noc = make_noc()
        s = HEFTScheduler(noc)
        assert s.noc is noc

    def test_rejects_non_meshnoc(self):
        with pytest.raises(ValueError):
            HEFTScheduler("not a noc")  # type: ignore[arg-type]

    def test_rejects_none(self):
        with pytest.raises(ValueError):
            HEFTScheduler(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. average_hop_count
# ---------------------------------------------------------------------------

class TestAverageHopCount:
    def test_1x1_returns_zero(self):
        s = make_scheduler(rows=1, cols=1)
        assert s.average_hop_count() == pytest.approx(0.0)

    def test_2x2_returns_4_over_3(self):
        # 4 procs, 12 ordered pairs; distances sum:
        # (0,1)=1,(0,2)=1,(0,3)=2,(1,0)=1,(1,2)=2,(1,3)=1,
        # (2,0)=1,(2,1)=2,(2,3)=1,(3,0)=2,(3,1)=1,(3,2)=1 => total=16
        s = make_scheduler(rows=2, cols=2)
        assert s.average_hop_count() == pytest.approx(16 / 12)

    def test_4x4_returns_positive_finite(self):
        s = make_scheduler(rows=4, cols=4)
        avg = s.average_hop_count()
        assert avg > 0
        assert math.isfinite(avg)

    def test_deterministic(self):
        s = make_scheduler(rows=4, cols=4)
        assert s.average_hop_count() == s.average_hop_count()

    def test_1x4_returns_expected(self):
        # 4 procs in a line: 0-1-2-3
        # distances: (0,1)=1,(0,2)=2,(0,3)=3,(1,0)=1,(1,2)=1,(1,3)=2,
        #            (2,0)=2,(2,1)=1,(2,3)=1,(3,0)=3,(3,1)=2,(3,2)=1 => total=20
        s = make_scheduler(rows=1, cols=4)
        assert s.average_hop_count() == pytest.approx(20 / 12)


# ---------------------------------------------------------------------------
# 3. average_communication_cost
# ---------------------------------------------------------------------------

class TestAverageCommunicationCost:
    def test_uses_alpha_and_beta(self):
        s = make_scheduler(rows=2, cols=2, alpha=2.0, beta=3.0)
        avg_hops = s.average_hop_count()
        expected = 2.0 * avg_hops + 3.0 * 5.0
        assert s.average_communication_cost(5.0) == pytest.approx(expected)

    def test_zero_volume_includes_hop_cost(self):
        # alpha=1, beta=1; volume=0 still yields alpha * avg_hops
        s = make_scheduler(rows=2, cols=2)
        avg_hops = s.average_hop_count()
        assert s.average_communication_cost(0.0) == pytest.approx(avg_hops)

    def test_zero_alpha_zero_hops(self):
        s = make_scheduler(rows=4, cols=4, alpha=0.0, beta=1.0)
        assert s.average_communication_cost(5.0) == pytest.approx(5.0)

    def test_rejects_negative_volume(self):
        with pytest.raises(ValueError):
            make_scheduler().average_communication_cost(-1.0)

    def test_rejects_nan_volume(self):
        with pytest.raises(ValueError):
            make_scheduler().average_communication_cost(float("nan"))

    def test_rejects_infinity_volume(self):
        with pytest.raises(ValueError):
            make_scheduler().average_communication_cost(float("inf"))

    def test_rejects_bool_volume(self):
        with pytest.raises(ValueError):
            make_scheduler().average_communication_cost(True)  # type: ignore[arg-type]

    def test_rejects_string_volume(self):
        with pytest.raises(ValueError):
            make_scheduler().average_communication_cost("5")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 4. compute_upward_ranks
# ---------------------------------------------------------------------------

class TestComputeUpwardRanks:
    def test_single_node(self):
        s = make_scheduler()
        dag = _single_node_dag(cost=10.0)
        ranks = s.compute_upward_ranks(dag)
        assert ranks[0] == pytest.approx(10.0)

    def test_chain_exit_node(self):
        s = make_scheduler()
        dag = _chain_dag(costs=(10.0, 20.0, 30.0), volumes=(5.0, 7.0))
        ranks = s.compute_upward_ranks(dag)
        # task 2 has no successors
        assert ranks[2] == pytest.approx(30.0)

    def test_chain_rank_1(self):
        s = make_scheduler()
        dag = _chain_dag(costs=(10.0, 20.0, 30.0), volumes=(5.0, 7.0))
        ranks = s.compute_upward_ranks(dag)
        expected = 20.0 + s.average_communication_cost(7.0) + ranks[2]
        assert ranks[1] == pytest.approx(expected)

    def test_chain_rank_0(self):
        s = make_scheduler()
        dag = _chain_dag(costs=(10.0, 20.0, 30.0), volumes=(5.0, 7.0))
        ranks = s.compute_upward_ranks(dag)
        expected = 10.0 + s.average_communication_cost(5.0) + ranks[1]
        assert ranks[0] == pytest.approx(expected)

    def test_chain_rank_ordering(self):
        s = make_scheduler()
        dag = _chain_dag()
        ranks = s.compute_upward_ranks(dag)
        # entry task has highest rank in a chain
        assert ranks[0] > ranks[1] > ranks[2]

    def test_fork_uses_max_successor_path(self):
        s = make_scheduler()
        dag = _fork_dag()
        ranks = s.compute_upward_ranks(dag)
        # rank[0] must use the max of the two successor paths
        path1 = s.average_communication_cost(5.0) + ranks[1]
        path2 = s.average_communication_cost(3.0) + ranks[2]
        expected = 10.0 + max(path1, path2)
        assert ranks[0] == pytest.approx(expected)

    def test_all_tasks_have_rank(self):
        s = make_scheduler()
        dag = _fork_join_dag()
        ranks = s.compute_upward_ranks(dag)
        assert set(ranks.keys()) == set(dag.task_ids())

    def test_ranks_are_positive(self):
        s = make_scheduler()
        dag = _fork_join_dag()
        for r in s.compute_upward_ranks(dag).values():
            assert r > 0

    def test_rejects_invalid_dag(self):
        with pytest.raises(ValueError):
            make_scheduler().compute_upward_ranks(nx.DiGraph())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 5. task_priority_order
# ---------------------------------------------------------------------------

class TestTaskPriorityOrder:
    def test_descending_rank_order(self):
        s = make_scheduler()
        dag = _chain_dag()
        order = s.task_priority_order(dag)
        ranks = s.compute_upward_ranks(dag)
        for i in range(len(order) - 1):
            assert ranks[order[i]] >= ranks[order[i + 1]]

    def test_ascending_task_id_tie_break(self):
        # Single node: only one task, trivially correct
        s = make_scheduler()
        dag = _single_node_dag()
        assert s.task_priority_order(dag) == [0]

    def test_all_tasks_present(self):
        s = make_scheduler()
        dag = _fork_join_dag()
        order = s.task_priority_order(dag)
        assert set(order) == set(dag.task_ids())
        assert len(order) == dag.number_of_tasks()

    def test_tie_break_by_task_id(self):
        # Create two independent tasks with same cost -> same rank
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=10.0)
        dag = DAGGraph(g)
        s = make_scheduler()
        order = s.task_priority_order(dag)
        ranks = s.compute_upward_ranks(dag)
        if ranks[0] == ranks[1]:
            assert order[0] == 0  # smaller task_id first


# ---------------------------------------------------------------------------
# 6. schedule — single node
# ---------------------------------------------------------------------------

class TestScheduleSingleNode:
    def test_one_task_scheduled(self):
        s = make_scheduler()
        dag = _single_node_dag(cost=10.0)
        state = s.schedule(dag)
        assert state.has_task_instance(0)

    def test_assigned_to_processor_zero(self):
        # Single task on empty processors: all have EFT = 10, tie broken by proc 0
        s = make_scheduler()
        dag = _single_node_dag(cost=10.0)
        state = s.schedule(dag)
        ti = state.get_primary_instance(0)
        assert ti.processor_id == 0

    def test_start_time_zero(self):
        s = make_scheduler()
        dag = _single_node_dag(cost=10.0)
        state = s.schedule(dag)
        assert state.get_primary_instance(0).start_time == pytest.approx(0.0)

    def test_finish_time_equals_cost(self):
        s = make_scheduler()
        dag = _single_node_dag(cost=10.0)
        state = s.schedule(dag)
        assert state.get_primary_instance(0).finish_time == pytest.approx(10.0)

    def test_makespan_equals_cost(self):
        s = make_scheduler()
        dag = _single_node_dag(cost=10.0)
        state = s.schedule(dag)
        assert s.compute_makespan(state) == pytest.approx(10.0)

    def test_no_link_intervals_reserved(self):
        s = make_scheduler()
        dag = _single_node_dag(cost=10.0)
        state = s.schedule(dag)
        for ivs in state.link_intervals.values():
            assert ivs == []

    def test_no_communication_instances(self):
        s = make_scheduler()
        dag = _single_node_dag(cost=10.0)
        state = s.schedule(dag)
        assert state.communication_instances == []


# ---------------------------------------------------------------------------
# 7. schedule — independent tasks
# ---------------------------------------------------------------------------

class TestScheduleIndependentTasks:
    def test_all_tasks_scheduled(self):
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=10.0)
        dag = DAGGraph(g)
        s = make_scheduler()
        state = s.schedule(dag)
        assert state.has_task_instance(0)
        assert state.has_task_instance(1)

    def test_all_instances_primary(self):
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=10.0)
        dag = DAGGraph(g)
        s = make_scheduler()
        state = s.schedule(dag)
        for tid in dag.task_ids():
            assert state.get_primary_instance(tid).is_primary

    def test_no_link_intervals_reserved(self):
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=10.0)
        dag = DAGGraph(g)
        s = make_scheduler()
        state = s.schedule(dag)
        for ivs in state.link_intervals.values():
            assert ivs == []

    def test_independent_tasks_can_run_in_parallel(self):
        # Two independent tasks: EFT is minimised by placing on different processors
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=10.0)
        dag = DAGGraph(g)
        s = make_scheduler()
        state = s.schedule(dag)
        # Both should start at 0 if placed on different processors
        procs = {state.get_primary_instance(t).processor_id for t in [0, 1]}
        assert len(procs) == 2  # placed on different processors
        assert state.max_processor_finish_time() == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 8. schedule — chain
# ---------------------------------------------------------------------------

class TestScheduleChain:
    def test_chain_all_tasks_scheduled(self):
        s = make_scheduler()
        dag = _chain_dag()
        state = s.schedule(dag)
        for tid in dag.task_ids():
            assert state.has_task_instance(tid)

    def test_chain_task1_starts_after_task0_data_arrives(self):
        s = make_scheduler()
        dag = _chain_dag(costs=(10.0, 20.0, 30.0), volumes=(5.0, 7.0))
        state = s.schedule(dag)
        ti0 = state.get_primary_instance(0)
        ti1 = state.get_primary_instance(1)
        if ti0.processor_id == ti1.processor_id:
            assert ti1.start_time >= ti0.finish_time
        else:
            comm_dur = s.noc.communication_duration(
                ti0.processor_id, ti1.processor_id,
                dag.communication_volume(0, 1)
            )
            assert ti1.start_time >= ti0.finish_time + comm_dur - 1e-9

    def test_chain_task2_starts_after_task1_data_arrives(self):
        s = make_scheduler()
        dag = _chain_dag(costs=(10.0, 20.0, 30.0), volumes=(5.0, 7.0))
        state = s.schedule(dag)
        ti1 = state.get_primary_instance(1)
        ti2 = state.get_primary_instance(2)
        if ti1.processor_id == ti2.processor_id:
            assert ti2.start_time >= ti1.finish_time
        else:
            comm_dur = s.noc.communication_duration(
                ti1.processor_id, ti2.processor_id,
                dag.communication_volume(1, 2)
            )
            assert ti2.start_time >= ti1.finish_time + comm_dur - 1e-9

    def test_high_comm_volume_prefers_same_processor(self):
        # Large communication volume: placing on same proc avoids comm cost
        # alpha=1, beta=100; volume=1000 -> remote cost >= 100000
        s = make_scheduler(rows=2, cols=2, alpha=1.0, beta=100.0)
        g = nx.DiGraph()
        g.add_node(0, computation_cost=1.0)
        g.add_node(1, computation_cost=1.0)
        g.add_edge(0, 1, communication_volume=1000.0)
        dag = DAGGraph(g)
        state = s.schedule(dag)
        ti0 = state.get_primary_instance(0)
        ti1 = state.get_primary_instance(1)
        assert ti0.processor_id == ti1.processor_id

    def test_no_link_intervals_reserved(self):
        s = make_scheduler()
        dag = _chain_dag()
        state = s.schedule(dag)
        for ivs in state.link_intervals.values():
            assert ivs == []


# ---------------------------------------------------------------------------
# 9. Precedence constraints
# ---------------------------------------------------------------------------

class TestPrecedenceConstraints:
    def test_two_parent_task_waits_for_both(self):
        s = make_scheduler()
        dag = _two_parent_dag()
        state = s.schedule(dag)
        ti0 = state.get_primary_instance(0)
        ti1 = state.get_primary_instance(1)
        ti2 = state.get_primary_instance(2)

        def arrival(parent_ti, vol):
            if parent_ti.processor_id == ti2.processor_id:
                return parent_ti.finish_time
            return parent_ti.finish_time + s.noc.communication_duration(
                parent_ti.processor_id, ti2.processor_id, vol
            )

        arr0 = arrival(ti0, dag.communication_volume(0, 2))
        arr1 = arrival(ti1, dag.communication_volume(1, 2))
        drt = max(arr0, arr1)
        assert ti2.start_time >= drt - 1e-9

    def test_fork_join_join_waits_for_both_paths(self):
        s = make_scheduler()
        dag = _fork_join_dag()
        state = s.schedule(dag)
        ti3 = state.get_primary_instance(3)
        for pred in dag.predecessors(3):
            ti_pred = state.get_primary_instance(pred)
            if ti_pred.processor_id == ti3.processor_id:
                arr = ti_pred.finish_time
            else:
                arr = ti_pred.finish_time + s.noc.communication_duration(
                    ti_pred.processor_id, ti3.processor_id,
                    dag.communication_volume(pred, 3)
                )
            assert ti3.start_time >= arr - 1e-9

    def test_all_tasks_scheduled_in_dag(self):
        s = make_scheduler()
        dag = _fork_join_dag()
        state = s.schedule(dag)
        for tid in dag.task_ids():
            assert state.has_task_instance(tid)


# ---------------------------------------------------------------------------
# 10. estimate_data_ready_time
# ---------------------------------------------------------------------------

class TestEstimateDataReadyTime:
    def test_no_predecessors_returns_zero(self):
        s = make_scheduler()
        dag = _chain_dag()
        state = s.schedule(dag)
        # task 0 has no predecessors, DRT = 0 for any proc
        assert s.estimate_data_ready_time(dag, state, 0, 0) == pytest.approx(0.0)

    def test_local_predecessor_returns_finish_time(self):
        s = make_scheduler()
        # Schedule task 0 on proc 0, then compute DRT for task 1 on proc 0
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=5.0)
        g.add_edge(0, 1, communication_volume=2.0)
        dag = DAGGraph(g)
        from src.schedule_state import ScheduleState
        state = ScheduleState(s.noc)
        state.reserve_task(0, 0, 0.0, 10.0)
        drt = s.estimate_data_ready_time(dag, state, 1, 0)
        assert drt == pytest.approx(10.0)  # same proc, no comm cost

    def test_remote_predecessor_adds_comm_duration(self):
        s = make_scheduler()
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=5.0)
        g.add_edge(0, 1, communication_volume=2.0)
        dag = DAGGraph(g)
        from src.schedule_state import ScheduleState
        state = ScheduleState(s.noc)
        state.reserve_task(0, 0, 0.0, 10.0)
        # task 1 on proc 5 (different from 0)
        comm_dur = s.noc.communication_duration(0, 5, 2.0)
        drt = s.estimate_data_ready_time(dag, state, 1, 5)
        assert drt == pytest.approx(10.0 + comm_dur)

    def test_multiple_predecessors_returns_max(self):
        s = make_scheduler()
        dag = _two_parent_dag()
        from src.schedule_state import ScheduleState
        state = ScheduleState(s.noc)
        # Place task 0 finishing at t=5 on proc 0, task 1 finishing at t=20 on proc 1
        state.reserve_task(0, 0, 0.0, 5.0)
        state.reserve_task(1, 1, 0.0, 20.0)
        arr0 = 5.0 + s.noc.communication_duration(0, 2, 5.0)
        arr1 = 20.0 + s.noc.communication_duration(1, 2, 5.0)
        drt = s.estimate_data_ready_time(dag, state, 2, 2)
        assert drt == pytest.approx(max(arr0, arr1))

    def test_missing_predecessor_raises(self):
        s = make_scheduler()
        dag = _chain_dag()
        from src.schedule_state import ScheduleState
        state = ScheduleState(s.noc)
        # task 1 has predecessor 0 but 0 is not scheduled
        with pytest.raises(ValueError):
            s.estimate_data_ready_time(dag, state, 1, 0)

    def test_invalid_processor_raises(self):
        s = make_scheduler()
        dag = _single_node_dag()
        from src.schedule_state import ScheduleState
        state = ScheduleState(s.noc)
        with pytest.raises(ValueError):
            s.estimate_data_ready_time(dag, state, 0, 999)

    def test_invalid_task_raises(self):
        s = make_scheduler()
        dag = _single_node_dag()
        from src.schedule_state import ScheduleState
        state = ScheduleState(s.noc)
        with pytest.raises(ValueError):
            s.estimate_data_ready_time(dag, state, 99, 0)

    def test_rejects_non_schedule_state(self):
        s = make_scheduler()
        dag = _single_node_dag()
        with pytest.raises(ValueError):
            s.estimate_data_ready_time(dag, "not a state", 0, 0)  # type: ignore[arg-type]

    def test_rejects_bool_task_id(self):
        s = make_scheduler()
        dag = _single_node_dag()
        from src.schedule_state import ScheduleState
        state = ScheduleState(s.noc)
        with pytest.raises(ValueError):
            s.estimate_data_ready_time(dag, state, True, 0)  # type: ignore[arg-type]

    def test_rejects_non_int_task_id(self):
        s = make_scheduler()
        dag = _single_node_dag()
        from src.schedule_state import ScheduleState
        state = ScheduleState(s.noc)
        with pytest.raises(ValueError):
            s.estimate_data_ready_time(dag, state, 0.0, 0)  # type: ignore[arg-type]

    def test_rejects_bool_processor_id(self):
        s = make_scheduler()
        dag = _single_node_dag()
        from src.schedule_state import ScheduleState
        state = ScheduleState(s.noc)
        with pytest.raises(ValueError):
            s.estimate_data_ready_time(dag, state, 0, True)  # type: ignore[arg-type]

    def test_rejects_non_int_processor_id(self):
        s = make_scheduler()
        dag = _single_node_dag()
        from src.schedule_state import ScheduleState
        state = ScheduleState(s.noc)
        with pytest.raises(ValueError):
            s.estimate_data_ready_time(dag, state, 0, 0.0)  # type: ignore[arg-type]

    def test_rejects_mismatched_noc_topology(self):
        s = make_scheduler(rows=4, cols=4)
        dag = _single_node_dag()
        from src.schedule_state import ScheduleState
        mismatched_state = ScheduleState(MeshNoC(rows=8, cols=8))
        with pytest.raises(ValueError):
            s.estimate_data_ready_time(dag, mismatched_state, 0, 0)

    def test_rejects_raw_digraph_as_dag(self):
        s = make_scheduler()
        from src.schedule_state import ScheduleState
        state = ScheduleState(s.noc)
        with pytest.raises(ValueError):
            s.estimate_data_ready_time(nx.DiGraph(), state, 0, 0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 11. Processor tie-breaking
# ---------------------------------------------------------------------------

class TestProcessorTieBreaking:
    def test_single_task_goes_to_proc_0(self):
        # All processors are empty, all have same EFT -> proc 0 chosen
        s = make_scheduler()
        dag = _single_node_dag(cost=10.0)
        state = s.schedule(dag)
        assert state.get_primary_instance(0).processor_id == 0

    def test_two_independent_tasks_sequential_tie_break(self):
        # First task: all procs equal -> proc 0
        # Second task: proc 0 busy [0,10), proc 1 free -> proc 1 (EFT=10 < proc 0 EFT=20)
        g = nx.DiGraph()
        g.add_node(0, computation_cost=10.0)
        g.add_node(1, computation_cost=10.0)
        dag = DAGGraph(g)
        s = make_scheduler()
        state = s.schedule(dag)
        procs = {state.get_primary_instance(t).processor_id for t in [0, 1]}
        # They must be on different processors
        assert len(procs) == 2


# ---------------------------------------------------------------------------
# 12. Ready-task robustness
# ---------------------------------------------------------------------------

class TestReadyTaskRobustness:
    def test_all_tasks_scheduled_chain(self):
        s = make_scheduler()
        dag = _chain_dag(costs=(5.0, 5.0, 5.0), volumes=(1.0, 1.0))
        state = s.schedule(dag)
        assert len(state.task_instances) == 3

    def test_all_tasks_scheduled_fork_join(self):
        s = make_scheduler()
        dag = _fork_join_dag()
        state = s.schedule(dag)
        assert len(state.task_instances) == 4

    def test_larger_generated_dag(self):
        from src.dag_generator import generate_dag
        g = generate_dag(n_tasks=20, edge_prob=0.3, ccr=1.0, comp_range=(10, 100), seed=42)
        dag = DAGGraph(g)
        s = make_scheduler(rows=4, cols=4)
        state = s.schedule(dag)
        assert len(state.task_instances) == 20
        for tid in dag.task_ids():
            assert state.has_task_instance(tid)


# ---------------------------------------------------------------------------
# 13. ScheduleState integration
# ---------------------------------------------------------------------------

class TestScheduleStateIntegration:
    def test_schedule_returns_schedule_state(self):
        from src.schedule_state import ScheduleState
        s = make_scheduler()
        dag = _fork_join_dag()
        state = s.schedule(dag)
        assert isinstance(state, ScheduleState)

    def test_validate_no_overlaps_passes(self):
        s = make_scheduler()
        dag = _fork_join_dag()
        state = s.schedule(dag)
        state.validate_no_overlaps()  # must not raise

    def test_makespan_equals_max_processor_finish_time(self):
        s = make_scheduler()
        dag = _fork_join_dag()
        state = s.schedule(dag)
        assert s.compute_makespan(state) == pytest.approx(state.max_processor_finish_time())

    def test_no_link_intervals_reserved(self):
        s = make_scheduler()
        dag = _fork_join_dag()
        state = s.schedule(dag)
        for ivs in state.link_intervals.values():
            assert ivs == []

    def test_every_task_has_exactly_one_primary(self):
        s = make_scheduler()
        dag = _fork_join_dag()
        state = s.schedule(dag)
        for tid in dag.task_ids():
            primaries = [ti for ti in state.get_task_instances(tid) if ti.is_primary]
            assert len(primaries) == 1

    def test_makespan_positive(self):
        s = make_scheduler()
        dag = _fork_join_dag()
        state = s.schedule(dag)
        assert s.compute_makespan(state) > 0

    def test_chain_makespan_at_least_sum_of_costs(self):
        s = make_scheduler(rows=1, cols=1)  # 1x1: no comm cost, all on same proc
        dag = _chain_dag(costs=(10.0, 20.0, 30.0), volumes=(0.0, 0.0))
        state = s.schedule(dag)
        assert s.compute_makespan(state) == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# 14. Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_schedule_rejects_raw_digraph(self):
        s = make_scheduler()
        with pytest.raises(ValueError):
            s.schedule(nx.DiGraph())  # type: ignore[arg-type]

    def test_compute_upward_ranks_rejects_raw_digraph(self):
        s = make_scheduler()
        with pytest.raises(ValueError):
            s.compute_upward_ranks(nx.DiGraph())  # type: ignore[arg-type]

    def test_task_priority_order_rejects_raw_digraph(self):
        s = make_scheduler()
        with pytest.raises(ValueError):
            s.task_priority_order(nx.DiGraph())  # type: ignore[arg-type]

    def test_estimate_drt_rejects_invalid_processor(self):
        s = make_scheduler()
        dag = _single_node_dag()
        from src.schedule_state import ScheduleState
        state = ScheduleState(s.noc)
        with pytest.raises(ValueError):
            s.estimate_data_ready_time(dag, state, 0, 999)

    def test_estimate_drt_rejects_invalid_task(self):
        s = make_scheduler()
        dag = _single_node_dag()
        from src.schedule_state import ScheduleState
        state = ScheduleState(s.noc)
        with pytest.raises(ValueError):
            s.estimate_data_ready_time(dag, state, 99, 0)

    def test_compute_makespan_rejects_non_schedule_state(self):
        s = make_scheduler()
        with pytest.raises(ValueError):
            s.compute_makespan("not a state")  # type: ignore[arg-type]

    def test_compute_makespan_rejects_mismatched_noc_topology(self):
        s = make_scheduler(rows=4, cols=4)
        from src.schedule_state import ScheduleState
        mismatched_state = ScheduleState(MeshNoC(rows=8, cols=8))
        with pytest.raises(ValueError):
            s.compute_makespan(mismatched_state)
