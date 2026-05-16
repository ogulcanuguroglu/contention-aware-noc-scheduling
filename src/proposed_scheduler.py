"""
Proposed contention-aware task duplication scheduler (CA-D).

Main contribution of the project. Combines HEFT-style upward-rank list
scheduling, contention-aware link-level communication reservation via
ScheduleState.reserve_communication(), and selective parent-only task
duplication evaluated under the contention-aware model.

Applies duplication only when Delta_EFT = EFT_no_dup - EFT_dup > 0.
Implemented in Phase 8.

Key differences from CA-LS (Phase 6):
    CA-LS reserves communications contention-awarely but does not duplicate.
    ProposedScheduler evaluates duplicating each direct predecessor onto the
    candidate processor and applies the duplication when Delta_EFT > 0.

Key differences from CD-LS (Phase 7):
    CD-LS uses the classic (analytical) communication model with no link
    reservations.  ProposedScheduler evaluates Delta_EFT using the
    contention-aware model, so duplications are committed only when they
    actually reduce EFT under realistic link contention.

Communication model (contention-aware):
    Remote communication is scheduled via ScheduleState.reserve_communication().
    Arrival time = earliest feasible comm finish time accounting for link
    contention with previously reserved communications on the same route.
    Local communication (same processor) has zero cost; no link intervals or
    CommunicationInstance objects are created for local communication.

Ranking:
    Upward-rank priority delegates to HEFTScheduler for identical values.

Duplication rule (per predecessor, evaluated sequentially):
    For each direct predecessor pred of task T on candidate processor P:
        EFT_no_dup = EFT of T on P without duplicating pred (contention-aware)
        EFT_dup    = EFT of T on P with pred duplicated locally on P
        Delta_EFT  = EFT_no_dup - EFT_dup
    pred is duplicated on P only when Delta_EFT > 0.
    Predecessors are evaluated in ascending task_id order for determinism.
    Later predecessors see the effect of earlier committed dups.

Best-instance selection:
    When a predecessor has multiple instances (primary + earlier dups), all
    instances are evaluated.  For local instances, arrival = finish_time.
    For remote instances, arrival is determined by probing via a sub-clone.
    The winning instance is chosen by three-way priority (_is_better_instance):
      1. Smallest arrival time.
      2. Local over remote when arrivals are equal (avoids unnecessary comm
         reservation on NoC links).
      3. Smallest source processor_id as the final deterministic tie-break.
    Only the winning instance's communication (if remote) is committed.

Communication reservation order:
    Within both _contention_drt and _dup_drt_contention, predecessor (or
    grandparent) task IDs are iterated in ascending sorted order so that
    link-interval reservation sequences are independent of NetworkX edge
    insertion order.

Limitations (Phase 8 scope):
    - Parent-only: only direct predecessors are considered for duplication.
    - No recursive critical-ancestor duplication.
    - No redundant duplicate removal.
"""

import math

from src.heft_scheduler import HEFTScheduler
from src.models import DAGGraph
from src.noc import MeshNoC
from src.schedule_state import ScheduleState


class ProposedScheduler:
    """
    Proposed Contention-Aware Duplication Scheduler (CA-D) for a
    homogeneous 2D mesh NoC.

    Combines contention-aware link-level communication reservation with
    selective parent-only task duplication evaluated under the contention
    model.  Uses HEFT-compatible upward-rank priority.

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
        Schedule all tasks with parent-only contention-aware task duplication.

        For each ready task (highest-priority first), every processor is
        evaluated on a clone of the current state.  Parent duplications are
        tentatively applied per the Delta_EFT > 0 rule under the contention
        model.  Only the winning processor candidate is promoted; rejected
        clones are discarded so their dup instances and communication
        reservations never pollute the committed final state.

        Returns a ScheduleState with all task intervals committed and all
        selected remote communications represented by CommunicationInstance
        objects with reserved link intervals.
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
        under the contention-aware model, reserves selected predecessor
        communications for task_id, and returns
        (start_time, finish_time, candidate_state).

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

    def contention_data_ready_time(
        self,
        dag: DAGGraph,
        state: ScheduleState,
        task_id: int,
        processor_id: int,
    ) -> float:
        """
        Compute Data Ready Time for task_id on processor_id and reserve
        the selected communications into state (contention-aware model).

        For each predecessor, all available instances are evaluated:
          - Local instance (same processor): arrival = instance.finish_time,
            no CommunicationInstance or link interval is created.
          - Remote instance: probed via a sub-clone of state; the selected
            (earliest-arriving) remote instance's comm is committed to state.

        When both local and remote instances exist for a predecessor, the
        one giving the earliest arrival is selected.

        Returns 0.0 for entry tasks (no predecessors).
        Raises ValueError if any input is invalid or any predecessor has no
        scheduled instance in state.
        """
        self._validate_dag(dag)
        self._validate_state(state)
        self._validate_task_id_in_dag(task_id, dag)
        self._validate_processor_id(processor_id)
        return self._contention_drt(dag, state, task_id, processor_id)

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
        Apply beneficial parent duplications for task_id on processor_id
        under the contention-aware model.

        Predecessors are evaluated in ascending task_id order for determinism.
        For each predecessor pred not already on processor_id:
            1. sub_no_dup = candidate.clone(); compute EFT_no_dup (reserves
               all predecessor comms in the sub-clone, then discards it).
            2. sub_dup = candidate.clone(); place dup of pred; compute
               EFT_dup from that sub-clone (then discard it).
            3. If Delta_EFT > 0: commit dup and its grandparent comms to
               candidate.  Later predecessors see this effect.

        After all preds, reserve the selected predecessor comms for task_id
        into candidate (final _contention_drt call) and return
        (start_time, finish_time).  The task itself is NOT reserved.
        """
        comp_cost = dag.computation_cost(task_id)

        for pred in sorted(dag.predecessors(task_id)):
            if candidate.has_task_instance(pred, processor_id):
                continue  # pred already local — no dup needed

            # -- EFT_no_dup: from sub-clone, no dup of pred --
            sub_no_dup = candidate.clone()
            drt_no_dup = self._contention_drt(dag, sub_no_dup, task_id, processor_id)
            start_no_dup = sub_no_dup.earliest_slot(
                processor_id, comp_cost, not_before=drt_no_dup
            )
            eft_no_dup = start_no_dup + comp_cost

            # -- EFT_dup: sub-clone with pred duplicated on processor_id --
            sub_dup = candidate.clone()
            dup_cost = dag.computation_cost(pred)
            dup_drt = self._dup_drt_contention(dag, sub_dup, pred, processor_id)
            dup_start = sub_dup.earliest_slot(
                processor_id, dup_cost, not_before=dup_drt
            )
            dup_finish = dup_start + dup_cost
            sub_dup.reserve_task(
                task_id=pred,
                processor_id=processor_id,
                start_time=dup_start,
                finish_time=dup_finish,
                is_primary=False,
            )
            drt_dup = self._contention_drt(dag, sub_dup, task_id, processor_id)
            start_dup = sub_dup.earliest_slot(
                processor_id, comp_cost, not_before=drt_dup
            )
            eft_dup = start_dup + comp_cost

            # -- Commit dup only when strictly beneficial --
            if eft_no_dup - eft_dup > 0:
                # Recompute dup placement on the live candidate (not sub_dup),
                # since candidate may have accumulated earlier committed dups.
                dup_drt_c = self._dup_drt_contention(dag, candidate, pred, processor_id)
                dup_start_c = candidate.earliest_slot(
                    processor_id, dup_cost, not_before=dup_drt_c
                )
                dup_finish_c = dup_start_c + dup_cost
                candidate.reserve_task(
                    task_id=pred,
                    processor_id=processor_id,
                    start_time=dup_start_c,
                    finish_time=dup_finish_c,
                    is_primary=False,
                )

        # Reserve final predecessor comms for task_id and compute its slot.
        drt_final = self._contention_drt(dag, candidate, task_id, processor_id)
        start_final = candidate.earliest_slot(
            processor_id, comp_cost, not_before=drt_final
        )
        return start_final, start_final + comp_cost

    def _contention_drt(
        self,
        dag: DAGGraph,
        candidate: ScheduleState,
        task_id: int,
        processor_id: int,
    ) -> float:
        """
        Compute Data Ready Time for task_id on processor_id (contention model).

        Predecessors are iterated in ascending task_id order for determinism.
        For each predecessor, evaluates ALL available instances and selects
        the winner via _is_better_instance (arrival → local preference →
        smaller processor_id):
          - Local instance: arrival = finish_time (no comm created).
          - Remote instance: probed via a sub-clone of candidate; arrival =
            comm.finish_time from the probe.

        The selected instance's communication (if remote) is committed to
        candidate.  Local arrivals commit nothing.

        Returns 0.0 for entry tasks.
        Raises ValueError if any predecessor has no instances in candidate.
        """
        drt = 0.0
        for pred in sorted(dag.predecessors(task_id)):
            vol = dag.communication_volume(pred, task_id)
            instances = candidate.get_task_instances(pred)
            if not instances:
                raise ValueError(
                    f"Predecessor {pred} of task {task_id} has no scheduled instance"
                )

            best_arrival = math.inf
            best_inst = None
            best_is_local = False

            for inst in instances:
                if inst.processor_id == processor_id:
                    arrival = inst.finish_time
                    is_local = True
                else:
                    arrival = candidate.probe_communication_arrival(
                        source_processor=inst.processor_id,
                        destination_processor=processor_id,
                        ready_time=inst.finish_time,
                        communication_volume=vol,
                    )
                    is_local = False

                if self._is_better_instance(
                    arrival, is_local, inst.processor_id,
                    best_arrival, best_is_local,
                    best_inst.processor_id if best_inst is not None else None,
                ):
                    best_arrival = arrival
                    best_inst = inst
                    best_is_local = is_local

            if not best_is_local:
                candidate.reserve_communication(
                    source_task=pred,
                    target_task=task_id,
                    source_processor=best_inst.processor_id,
                    destination_processor=processor_id,
                    ready_time=best_inst.finish_time,
                    communication_volume=vol,
                )

            drt = max(drt, best_arrival)

        return drt

    def _dup_drt_contention(
        self,
        dag: DAGGraph,
        candidate: ScheduleState,
        pred_id: int,
        processor_id: int,
    ) -> float:
        """
        Compute the Data Ready Time for a duplicate of pred_id on processor_id
        using the contention-aware model.

        Grandparent task IDs are iterated in ascending sorted order for
        determinism.  Uses committed instances of pred_id's own predecessors
        (grandparents of the original task).  Reserves selected grandparent
        communications into candidate via _is_better_instance (arrival →
        local preference → smaller processor_id).  No recursive ancestor
        duplication is attempted (Phase 8 scope).

        Returns 0.0 if pred_id has no predecessors (entry task).
        Raises ValueError if any grandparent has no instances in candidate.
        """
        drt = 0.0
        for gp in sorted(dag.predecessors(pred_id)):
            vol = dag.communication_volume(gp, pred_id)
            instances = candidate.get_task_instances(gp)
            if not instances:
                raise ValueError(
                    f"Grandparent {gp} of pred {pred_id} has no scheduled instance"
                )

            best_arrival = math.inf
            best_inst = None
            best_is_local = False

            for inst in instances:
                if inst.processor_id == processor_id:
                    arrival = inst.finish_time
                    is_local = True
                else:
                    arrival = candidate.probe_communication_arrival(
                        source_processor=inst.processor_id,
                        destination_processor=processor_id,
                        ready_time=inst.finish_time,
                        communication_volume=vol,
                    )
                    is_local = False

                if self._is_better_instance(
                    arrival, is_local, inst.processor_id,
                    best_arrival, best_is_local,
                    best_inst.processor_id if best_inst is not None else None,
                ):
                    best_arrival = arrival
                    best_inst = inst
                    best_is_local = is_local

            if not best_is_local:
                candidate.reserve_communication(
                    source_task=gp,
                    target_task=pred_id,
                    source_processor=best_inst.processor_id,
                    destination_processor=processor_id,
                    ready_time=best_inst.finish_time,
                    communication_volume=vol,
                )

            drt = max(drt, best_arrival)

        return drt

    @staticmethod
    def _is_better_instance(
        arrival: float,
        is_local: bool,
        inst_processor: int,
        best_arrival: float,
        best_is_local: bool,
        best_processor: int | None,
    ) -> bool:
        """
        Return True when the candidate instance beats the current best.

        Priority order:
          1. Smaller arrival time (strict).
          2. Local over remote when arrivals are equal (avoids comm reservation).
          3. Smaller source processor_id as final deterministic tie-break.
        """
        if arrival < best_arrival:
            return True
        if arrival > best_arrival:
            return False
        if is_local and not best_is_local:
            return True
        if is_local == best_is_local and best_processor is not None:
            return inst_processor < best_processor
        return False

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
