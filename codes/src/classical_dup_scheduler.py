"""
Classical Duplication Scheduler without contention awareness (CD-LS).

Applies parent-only task duplication using the classic communication model
(no link-level reservations). Uses Delta_EFT > 0 decision rule.
Implemented in Phase 7.

Key differences from HEFT (Phase 5):
    HEFT uses only analytical communication cost with no duplication.
    CD-LS evaluates duplicating each direct predecessor onto the candidate
    processor and applies the duplication when Delta_EFT > 0.

Key differences from CA-LS (Phase 6):
    CA-LS reserves NoC link intervals via reserve_communication().
    CD-LS uses only classic analytical communication cost; no links are
    reserved and link_intervals remains empty for all CD-LS schedules.

Key differences from ProposedScheduler (Phase 8):
    Phase 8 evaluates duplication under the contention-aware communication
    model. CD-LS uses only classic (contention-free) communication cost.

Communication model (classic, no contention):
    duration(src_proc, dst_proc, vol) = alpha * hop_count(src, dst) + beta * vol
    Local communication (src == dst) has zero cost.

Ranking:
    Upward-rank priority delegates to HEFTScheduler for identical values.

Duplication rule (per predecessor, evaluated sequentially):
    For each direct predecessor pred of task T on candidate processor P:
        EFT_no_dup = EFT of T on P without duplicating pred (current candidate)
        EFT_dup    = EFT of T on P with pred duplicated locally on P
        Delta_EFT  = EFT_no_dup - EFT_dup
    pred is duplicated on P only when Delta_EFT > 0.
    Predecessors are evaluated in ascending task_id order for determinism.
    Later predecessors see the effect of earlier committed dups.

Best-instance selection:
    When a predecessor has multiple instances (primary + earlier dups from
    prior scheduling iterations), the instance giving the earliest data
    arrival under the classic comm model is chosen. This applies both to
    DRT computation for the task and to DRT computation for dup placement.

Limitations (Phase 7 scope):
    - Parent-only: only direct predecessors are considered for duplication.
      Recursive critical-ancestor duplication is deferred to Phase 8.
    - No redundant duplicate removal.
    - No contention awareness in duplication decisions.
    - communication_instances list remains empty (no CommunicationInstance
      objects created, since the classic model is purely analytical).
"""

import math

from src.heft_scheduler import HEFTScheduler
from src.models import DAGGraph
from src.noc import MeshNoC
from src.schedule_state import ScheduleState


class ClassicalDuplicationScheduler:
    """
    Classical Duplication List Scheduler (CD-LS) for a homogeneous 2D mesh NoC.

    Uses parent-only task duplication with the classic communication model.
    No NoC link intervals are reserved; link_intervals remains empty after
    any schedule produced by this scheduler.

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

        Delegates to HEFTScheduler so rank values are identical to those
        used by the HEFT baseline on the same DAG and NoC.
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
        Schedule all tasks with parent-only task duplication.

        For each ready task (highest-priority first), every processor is
        evaluated on a clone of the current state.  Parent duplications are
        tentatively applied per the Delta_EFT > 0 rule.  Only the winning
        processor candidate is promoted; rejected clones are discarded so
        their dup instances never pollute the committed final state.

        link_intervals remain empty: no reserve_communication() or
        reserve_route() is called at any point.

        Returns a ScheduleState with all task intervals committed.
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

        Clones state, applies beneficial parent duplications (Delta_EFT > 0)
        to the clone, computes DRT under the classic communication model, and
        returns (start_time, finish_time, candidate_state).

        The task itself is NOT reserved in candidate_state; the caller decides
        whether to commit.  The original state is never mutated.

        Raises ValueError if any input is invalid or any predecessor has no
        scheduled instance in state.
        """
        self._validate_dag(dag)
        self._validate_state(state)
        self._validate_task_id_in_dag(task_id, dag)
        self._validate_processor_id(processor_id)

        candidate = state.clone()
        start, finish = self._evaluate_duplications(dag, candidate, task_id, processor_id)
        return start, finish, candidate

    # ------------------------------------------------------------------
    # Public DRT helper
    # ------------------------------------------------------------------

    def classic_data_ready_time(
        self,
        dag: DAGGraph,
        state: ScheduleState,
        task_id: int,
        processor_id: int,
    ) -> float:
        """
        Compute Data Ready Time for task_id on processor_id (classic model).

        Validates all inputs, then delegates to _classic_drt().  When a
        predecessor has multiple instances (primary + duplicates from earlier
        scheduling iterations), the instance giving the earliest data arrival
        is chosen.

        Returns 0.0 for entry tasks (no predecessors).
        Raises ValueError if any input is invalid or any predecessor has no
        scheduled instance in state.
        """
        self._validate_dag(dag)
        self._validate_state(state)
        self._validate_task_id_in_dag(task_id, dag)
        self._validate_processor_id(processor_id)
        return self._classic_drt(dag, state, task_id, processor_id)

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

    def _evaluate_duplications(
        self,
        dag: DAGGraph,
        candidate: ScheduleState,
        task_id: int,
        processor_id: int,
    ) -> tuple[float, float]:
        """
        Apply beneficial parent duplications for task_id on processor_id.

        Predecessors are evaluated in ascending task_id order for determinism.
        For each predecessor pred not already on processor_id:
            1. Compute EFT_no_dup from the current candidate.
            2. Create sub-clone; place dup of pred on processor_id in it.
            3. Compute EFT_dup from the sub-clone.
            4. If Delta_EFT = EFT_no_dup - EFT_dup > 0: commit dup to candidate.
        Later predecessors see the effect of earlier committed dups.

        Returns (start_time, finish_time) for task_id after all beneficial
        dups have been applied.  The task itself is NOT reserved.
        """
        comp_cost = dag.computation_cost(task_id)

        for pred in sorted(dag.predecessors(task_id)):
            if candidate.has_task_instance(pred, processor_id):
                continue  # pred already local — no dup needed

            # -- EFT_no_dup: from current candidate (may have earlier dups) --
            drt_no_dup = self._classic_drt(dag, candidate, task_id, processor_id)
            start_no_dup = candidate.earliest_slot(
                processor_id, comp_cost, not_before=drt_no_dup
            )
            eft_no_dup = start_no_dup + comp_cost

            # -- Tentative dup placement in a sub-clone --
            dup_cost = dag.computation_cost(pred)
            dup_drt = self._dup_drt(dag, candidate, pred, processor_id)
            sub_clone = candidate.clone()
            dup_start = sub_clone.earliest_slot(
                processor_id, dup_cost, not_before=dup_drt
            )
            dup_finish = dup_start + dup_cost
            sub_clone.reserve_task(
                task_id=pred,
                processor_id=processor_id,
                start_time=dup_start,
                finish_time=dup_finish,
                is_primary=False,
            )

            # -- EFT_dup: from sub-clone with pred now local --
            drt_dup = self._classic_drt(dag, sub_clone, task_id, processor_id)
            start_dup = sub_clone.earliest_slot(
                processor_id, comp_cost, not_before=drt_dup
            )
            eft_dup = start_dup + comp_cost

            # -- Commit dup only when beneficial --
            if eft_no_dup - eft_dup > 0:
                # dup_start was computed from candidate.clone() before candidate
                # was modified, so it remains valid for the unmodified candidate.
                candidate.reserve_task(
                    task_id=pred,
                    processor_id=processor_id,
                    start_time=dup_start,
                    finish_time=dup_finish,
                    is_primary=False,
                )

        drt_final = self._classic_drt(dag, candidate, task_id, processor_id)
        start_final = candidate.earliest_slot(
            processor_id, comp_cost, not_before=drt_final
        )
        return start_final, start_final + comp_cost

    def _classic_drt(
        self,
        dag: DAGGraph,
        candidate: ScheduleState,
        task_id: int,
        processor_id: int,
    ) -> float:
        """
        Compute Data Ready Time for task_id on processor_id (classic model).

        For each predecessor, picks the instance giving the earliest arrival:
            local (inst on processor_id):  arrival = inst.finish_time
            remote:                        arrival = inst.finish_time
                                                     + communication_duration(...)

        Uses the minimum arrival across all instances of each predecessor so
        that duplicates created in earlier iterations are exploited when they
        provide a shorter path.

        Returns 0.0 for entry tasks (no predecessors).
        Raises ValueError if any predecessor has no instances in candidate.
        """
        drt = 0.0
        for pred in dag.predecessors(task_id):
            vol = dag.communication_volume(pred, task_id)
            instances = candidate.get_task_instances(pred)
            if not instances:
                raise ValueError(
                    f"Predecessor {pred} of task {task_id} has no scheduled instance"
                )
            best_arrival = min(
                inst.finish_time
                if inst.processor_id == processor_id
                else inst.finish_time + self.noc.communication_duration(
                    inst.processor_id, processor_id, vol
                )
                for inst in instances
            )
            drt = max(drt, best_arrival)
        return drt

    def _dup_drt(
        self,
        dag: DAGGraph,
        candidate: ScheduleState,
        pred_id: int,
        processor_id: int,
    ) -> float:
        """
        Compute the Data Ready Time for a duplicate of pred_id on processor_id.

        Uses committed instances of pred_id's own predecessors (grandparents
        of the original task).  No recursive ancestor duplication is attempted
        (Phase 7 scope limitation).

        Returns 0.0 if pred_id has no predecessors (entry task).
        Raises ValueError if any grandparent has no instances in candidate.
        """
        drt = 0.0
        for gp in dag.predecessors(pred_id):
            vol = dag.communication_volume(gp, pred_id)
            instances = candidate.get_task_instances(gp)
            if not instances:
                raise ValueError(
                    f"Grandparent {gp} of pred {pred_id} has no scheduled instance"
                )
            best_arrival = min(
                inst.finish_time
                if inst.processor_id == processor_id
                else inst.finish_time + self.noc.communication_duration(
                    inst.processor_id, processor_id, vol
                )
                for inst in instances
            )
            drt = max(drt, best_arrival)
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
