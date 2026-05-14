"""
Heterogeneous Earliest Finish Time (HEFT)-like list scheduler.

Baseline scheduler without task duplication and without link-level contention.
Uses upward rank priority and classic communication model.
Implemented in Phase 5.

Communication cost model:
    average_communication_cost(volume) = alpha * average_hop_count + beta * volume

    where average_hop_count is the mean Manhattan distance over all ordered
    processor pairs (src, dst) with src != dst. For a 1x1 mesh, average_hop_count
    is 0.0 and remote communication is impossible.

    This estimate is used in upward rank computation only. Actual arrival times
    in schedule() use noc.communication_duration() with real processor assignments.

No link reservation:
    This phase uses only reserve_task(). Communication durations are computed
    analytically but no link interval is blocked for other communications.
    Arrival time = predecessor_finish + communication_duration (analytic only).

Scheduling loop:
    Uses a ready-task list: a task is ready when all its predecessors have been
    assigned primary instances. The priority list (descending upward rank,
    ascending task_id tie-break) orders which ready task is picked first.
"""

import math

from src.models import DAGGraph
from src.noc import MeshNoC
from src.schedule_state import ScheduleState


class HEFTScheduler:
    """
    HEFT-like list scheduler for a homogeneous 2D mesh NoC.

    Args:
        noc: MeshNoC instance describing the target hardware.
    """

    def __init__(self, noc: MeshNoC) -> None:
        if not isinstance(noc, MeshNoC):
            raise ValueError(
                f"noc must be a MeshNoC instance, got {type(noc).__name__}"
            )
        self.noc = noc

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def average_hop_count(self) -> float:
        """
        Return mean Manhattan distance over all ordered processor pairs src != dst.

        Returns 0.0 for a 1x1 mesh (no remote communication possible).
        """
        procs = self.noc.processor_ids()
        n = len(procs)
        if n <= 1:
            return 0.0
        total = sum(
            self.noc.manhattan_distance(src, dst)
            for src in procs
            for dst in procs
            if src != dst
        )
        return total / (n * (n - 1))

    def average_communication_cost(self, communication_volume: float) -> float:
        """
        Estimate communication cost using average hop count.

        Returns: alpha * average_hop_count + beta * communication_volume
        """
        self._validate_volume(communication_volume)
        return self.noc.alpha * self.average_hop_count() + self.noc.beta * communication_volume

    def compute_upward_ranks(self, dag: DAGGraph) -> dict[int, float]:
        """
        Compute upward rank for every task in dag.

        rank_u(n) = computation_cost(n) + max over successors s of
                    (average_communication_cost(volume(n,s)) + rank_u(s))

        Exit tasks (no successors) have rank_u = computation_cost.
        Computed bottom-up via memoised recursion.
        Returns dict mapping task_id -> rank value.
        """
        self._validate_dag(dag)
        rank: dict[int, float] = {}

        def _compute(task_id: int) -> float:
            if task_id in rank:
                return rank[task_id]
            cost = dag.computation_cost(task_id)
            successors = dag.successors(task_id)
            if not successors:
                rank[task_id] = cost
            else:
                best = max(
                    self.average_communication_cost(dag.communication_volume(task_id, s))
                    + _compute(s)
                    for s in successors
                )
                rank[task_id] = cost + best
            return rank[task_id]

        for tid in dag.task_ids():
            _compute(tid)
        return rank

    def task_priority_order(self, dag: DAGGraph) -> list[int]:
        """
        Return task IDs sorted by descending upward rank, then ascending task_id.
        """
        self._validate_dag(dag)
        ranks = self.compute_upward_ranks(dag)
        return sorted(dag.task_ids(), key=lambda t: (-ranks[t], t))

    def estimate_data_ready_time(
        self,
        dag: DAGGraph,
        state: ScheduleState,
        task_id: int,
        processor_id: int,
    ) -> float:
        """
        Compute Data Ready Time for task_id placed on processor_id.

        DRT = max over predecessors pred of:
            pred_finish_time                                (local, same processor)
            pred_finish_time + communication_duration(...)  (remote, different processor)

        Returns 0.0 if task has no predecessors.
        Raises ValueError if dag is not a DAGGraph, state is not a ScheduleState,
        task_id is invalid, processor_id is invalid, or any predecessor lacks a
        primary instance.
        """
        self._validate_dag(dag)
        self._validate_state(state)
        self._validate_task_id_in_dag(task_id, dag)
        self._validate_processor_id(processor_id)

        predecessors = dag.predecessors(task_id)
        if not predecessors:
            return 0.0

        drt = 0.0
        for pred in predecessors:
            pred_instance = state.get_primary_instance(pred)
            pred_finish = pred_instance.finish_time
            pred_proc = pred_instance.processor_id
            if pred_proc == processor_id:
                arrival = pred_finish
            else:
                comm_dur = self.noc.communication_duration(
                    pred_proc,
                    processor_id,
                    dag.communication_volume(pred, task_id),
                )
                arrival = pred_finish + comm_dur
            drt = max(drt, arrival)
        return drt

    def schedule(self, dag: DAGGraph) -> ScheduleState:
        """
        Schedule all tasks in dag using HEFT-like list scheduling.

        Returns a ScheduleState with every task reserved as a primary instance.
        No link intervals are reserved.
        """
        self._validate_dag(dag)
        state = ScheduleState(self.noc)
        priority_order = self.task_priority_order(dag)
        priority_pos: dict[int, int] = {tid: i for i, tid in enumerate(priority_order)}

        scheduled: set[int] = set()
        all_tasks = set(dag.task_ids())

        while len(scheduled) < len(all_tasks):
            ready = [
                t for t in all_tasks - scheduled
                if all(p in scheduled for p in dag.predecessors(t))
            ]
            if not ready:
                raise ValueError(
                    "Scheduling stalled: no ready tasks. The DAG may contain a cycle."
                )

            task_id = min(ready, key=lambda t: priority_pos[t])
            comp_cost = dag.computation_cost(task_id)

            best_proc: int = 0
            best_start: float = 0.0
            best_finish: float = math.inf

            for proc in self.noc.processor_ids():
                drt = self.estimate_data_ready_time(dag, state, task_id, proc)
                start = state.earliest_slot(proc, comp_cost, not_before=drt)
                finish = start + comp_cost
                if finish < best_finish or (finish == best_finish and proc < best_proc):
                    best_finish = finish
                    best_start = start
                    best_proc = proc

            state.reserve_task(
                task_id=task_id,
                processor_id=best_proc,
                start_time=best_start,
                finish_time=best_finish,
                is_primary=True,
            )
            scheduled.add(task_id)

        return state

    def compute_makespan(self, state: ScheduleState) -> float:
        """Return the makespan (maximum finish time across all processors)."""
        self._validate_state(state)
        return state.max_processor_finish_time()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_dag(dag: DAGGraph) -> None:
        if not isinstance(dag, DAGGraph):
            raise ValueError(
                f"dag must be a DAGGraph instance, got {type(dag).__name__}"
            )

    def _validate_state(self, state: ScheduleState) -> None:
        if not isinstance(state, ScheduleState):
            raise ValueError(
                f"state must be a ScheduleState instance, got {type(state).__name__}"
            )
        if set(state.processor_intervals.keys()) != set(self.noc.processor_ids()):
            raise ValueError(
                "state processor topology does not match scheduler NoC"
            )
        if set(state.link_intervals.keys()) != set(self.noc.all_directed_links()):
            raise ValueError(
                "state link topology does not match scheduler NoC"
            )

    @staticmethod
    def _validate_task_id_in_dag(task_id: int, dag: DAGGraph) -> None:
        if isinstance(task_id, bool) or not isinstance(task_id, int):
            raise ValueError(
                f"task_id must be int, got {type(task_id).__name__}: {task_id!r}"
            )
        if task_id not in dag.task_ids():
            raise ValueError(f"task_id {task_id} not in dag")

    def _validate_processor_id(self, processor_id: int) -> None:
        if isinstance(processor_id, bool) or not isinstance(processor_id, int):
            raise ValueError(
                f"processor_id must be int, got {type(processor_id).__name__}: {processor_id!r}"
            )
        if not self.noc.is_valid_processor(processor_id):
            raise ValueError(f"processor_id {processor_id!r} is not a valid processor")

    def _validate_volume(self, volume: float) -> None:
        if isinstance(volume, bool) or not isinstance(volume, (int, float)):
            raise ValueError(
                f"communication_volume must be numeric, "
                f"got {type(volume).__name__}: {volume!r}"
            )
        if not math.isfinite(volume):
            raise ValueError(f"communication_volume must be finite, got {volume}")
        if volume < 0:
            raise ValueError(
                f"communication_volume must be non-negative, got {volume}"
            )
