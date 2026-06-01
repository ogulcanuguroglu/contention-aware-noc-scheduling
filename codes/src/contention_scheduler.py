"""
Contention-aware list scheduler without task duplication (CA-LS).

Uses the full NoC link-level contention model but does not duplicate tasks.
Corresponds to the CA-LS baseline from Sinnen et al. (2011).
Implemented in Phase 6.

Key difference from HEFT (Phase 5):
    HEFT estimates communication analytically and does not reserve links.
    CA-LS calls ScheduleState.reserve_communication() for every remote edge,
    so link intervals are blocked and subsequent communications experience
    realistic contention-induced delays.

Candidate evaluation via cloning:
    Each processor candidate is evaluated on a clone of the current state.
    Remote predecessor communications are reserved in the clone.
    Only the winning candidate's clone (plus the task reservation) is kept;
    rejected clones are discarded so no communication artifacts from losing
    candidates pollute the committed schedule.

Ranking:
    Upward-rank priority computation delegates to HEFTScheduler so the two
    schedulers use exactly the same formula and are directly comparable.
"""

import math

from src.heft_scheduler import HEFTScheduler
from src.models import DAGGraph
from src.noc import MeshNoC
from src.schedule_state import ScheduleState


class ContentionAwareScheduler:
    """
    Contention-Aware List Scheduler (CA-LS) for a homogeneous 2D mesh NoC.

    Args:
        noc: MeshNoC instance describing the target hardware.
    """

    def __init__(self, noc: MeshNoC) -> None:
        if not isinstance(noc, MeshNoC):
            raise ValueError(
                f"noc must be a MeshNoC instance, got {type(noc).__name__}"
            )
        self.noc = noc
        self._heft = HEFTScheduler(noc)

    # ------------------------------------------------------------------
    # Ranking (delegates to HEFTScheduler for identical formula)
    # ------------------------------------------------------------------

    def compute_upward_ranks(self, dag: DAGGraph) -> dict[int, float]:
        """
        Compute upward rank for every task in dag.

        Delegates to HEFTScheduler so rank values are identical to those used
        by the HEFT baseline on the same DAG and NoC.
        """
        self._validate_dag(dag)
        return self._heft.compute_upward_ranks(dag)

    def task_priority_order(self, dag: DAGGraph) -> list[int]:
        """
        Return task IDs sorted by descending upward rank, ascending task_id tie-break.

        Delegates to HEFTScheduler.task_priority_order().
        """
        self._validate_dag(dag)
        return self._heft.task_priority_order(dag)

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def schedule(self, dag: DAGGraph) -> ScheduleState:
        """
        Schedule all tasks with contention-aware communication reservation.

        For each task the highest-priority ready task is selected, then every
        processor candidate is evaluated on a clone of the current state.
        Remote predecessor communications are tentatively reserved in the clone.
        Only the winning candidate's state is promoted; rejected clones are
        discarded.

        Returns a ScheduleState with all task and link intervals committed.
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

            best_proc: int = 0
            best_start: float = 0.0
            best_finish: float = math.inf
            best_candidate: ScheduleState = state.clone()

            for proc in self.noc.processor_ids():
                start, finish, candidate = self.evaluate_task_on_processor(
                    dag, state, task_id, proc
                )
                if finish < best_finish or (finish == best_finish and proc < best_proc):
                    best_finish = finish
                    best_start = start
                    best_proc = proc
                    best_candidate = candidate

            best_candidate.reserve_task(
                task_id=task_id,
                processor_id=best_proc,
                start_time=best_start,
                finish_time=best_finish,
                is_primary=True,
            )
            state = best_candidate
            scheduled.add(task_id)

        return state

    def evaluate_task_on_processor(
        self,
        dag: DAGGraph,
        state: ScheduleState,
        task_id: int,
        processor_id: int,
    ) -> tuple[float, float, ScheduleState]:
        """
        Evaluate placing task_id on processor_id without committing.

        Clones state, reserves remote predecessor communications into the clone,
        computes DRT, finds the earliest feasible task start on processor_id,
        and returns (start_time, finish_time, candidate_state).

        The task itself is NOT reserved in candidate_state; the caller decides
        whether to commit.  The original state is never mutated.

        Raises ValueError if any input is invalid or any predecessor is not yet
        assigned a primary instance in state.
        """
        self._validate_dag(dag)
        self._validate_state(state)
        self._validate_task_id_in_dag(task_id, dag)
        self._validate_processor_id(processor_id)

        candidate = state.clone()
        comp_cost = dag.computation_cost(task_id)
        drt = self._reserve_predecessor_comms(dag, candidate, task_id, processor_id)
        start = candidate.earliest_slot(processor_id, comp_cost, not_before=drt)
        finish = start + comp_cost
        return start, finish, candidate

    # ------------------------------------------------------------------
    # Makespan
    # ------------------------------------------------------------------

    def compute_makespan(self, state: ScheduleState) -> float:
        """Return the makespan (maximum finish time across all processors)."""
        self._validate_state(state)
        return state.max_processor_finish_time()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _reserve_predecessor_comms(
        self,
        dag: DAGGraph,
        candidate: ScheduleState,
        task_id: int,
        processor_id: int,
    ) -> float:
        """
        Reserve all remote predecessor communications for task_id onto processor_id
        into candidate state.  Returns DRT (max arrival time over predecessors).

        Local communications (pred on same processor) contribute pred_finish_time
        directly without any link reservation.
        """
        drt = 0.0
        for pred in dag.predecessors(task_id):
            pred_instance = candidate.get_primary_instance(pred)
            pred_finish = pred_instance.finish_time
            pred_proc = pred_instance.processor_id
            vol = dag.communication_volume(pred, task_id)
            if pred_proc == processor_id:
                arrival = pred_finish
            else:
                comm = candidate.reserve_communication(
                    source_task=pred,
                    target_task=task_id,
                    source_processor=pred_proc,
                    destination_processor=processor_id,
                    ready_time=pred_finish,
                    communication_volume=vol,
                )
                arrival = comm.finish_time
            drt = max(drt, arrival)
        return drt

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
        # ScheduleState stores its NoC as _noc (private).  Compare all four
        # configuration parameters so a same-topology but different-alpha/beta
        # instance is rejected before any communication duration is computed.
        sn = state._noc
        if (
            sn.rows != self.noc.rows
            or sn.cols != self.noc.cols
            or sn.alpha != self.noc.alpha
            or sn.beta != self.noc.beta
        ):
            raise ValueError(
                "state NoC configuration does not match scheduler NoC "
                f"(state: rows={sn.rows}, cols={sn.cols}, "
                f"alpha={sn.alpha}, beta={sn.beta}; "
                f"scheduler: rows={self.noc.rows}, cols={self.noc.cols}, "
                f"alpha={self.noc.alpha}, beta={self.noc.beta})"
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
                f"processor_id must be int, "
                f"got {type(processor_id).__name__}: {processor_id!r}"
            )
        if not self.noc.is_valid_processor(processor_id):
            raise ValueError(
                f"processor_id {processor_id!r} is not a valid processor"
            )
