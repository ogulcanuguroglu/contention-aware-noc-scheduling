"""
Contention replay evaluator for fair multi-scheduler comparison.

Given a ScheduleState produced by any scheduler (HEFT, CA-LS, CD-LS, or CA-D),
replay_under_contention() produces a fresh ScheduleState that:

  - preserves the scheduler's task placement decisions (task → processor),
  - preserves primary vs duplicate instance flags,
  - does NOT preserve original start/finish times,
  - recomputes all timing under the common contention-aware communication model,
  - materializes every remote communication as a CommunicationInstance with
    reserved NoC link intervals.

This allows fair makespan comparison across all four schedulers, which otherwise
produce ScheduleStates under two different communication models:

  Classic model (HEFT, CD-LS):
      Communication cost computed analytically; no link reservations created.
  Contention model (CA-LS, CA-D):
      Communications scheduled as link-interval reservations.

The replayed makespan is a common physical evaluation metric, not the
scheduler's own internal predicted makespan.

Phase 12.

Replay ordering:
    All TaskInstance objects from original_state are replayed in a
    deterministic order.  An instance is ready when every DAG predecessor of
    its task_id has at least one already-replayed instance in the new state.
    Among ready instances the one with the smallest

        (original_start_time, original_finish_time, task_id,
         processor_id, not is_primary)

    key is selected next, so primary instances sort before duplicates on
    equal timestamps.

Communication model:
    Identical to the CA-LS/CA-D model:
        duration = alpha * hop_count(src, dst) + beta * volume
    Remote communications use ScheduleState.reserve_communication() for
    link-interval reservation.  Local communications (same processor) are
    free and do not create CommunicationInstance objects or link intervals.

Duplicate semantics:
    A duplicate of task T has the same DAG predecessors as the primary of T.
    Duplicates are independent executions on a different processor; they are
    NOT sequenced after the primary and do NOT depend on the primary instance
    of the same task.  Each instance (primary or duplicate) computes its own
    DRT from T's DAG predecessors using whichever instances of those
    predecessors are already replayed at that point.
"""

import math

from src.models import DAGGraph, TaskInstance
from src.noc import MeshNoC
from src.schedule_state import ScheduleState


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def replay_under_contention(
    dag: DAGGraph,
    original_state: ScheduleState,
    noc: MeshNoC,
) -> ScheduleState:
    """
    Replay a scheduler's placement decisions under the contention-aware model.

    Accepts a ScheduleState produced by any scheduler and returns a fresh
    ScheduleState where:
      - every TaskInstance has the same task_id, processor_id, and is_primary
        flag as in original_state,
      - start/finish times are recomputed under contention-aware DRT,
      - all remote communications are materialized with reserved link intervals.

    Does not mutate original_state.

    Args:
        dag:            Application DAG.  Provides computation costs, edge
                        volumes, and predecessor relationships.
        original_state: Committed ScheduleState from any scheduler.  Determines
                        which task goes on which processor and which instances
                        (primary or duplicate) exist.
        noc:            MeshNoC to use for routing and link reservation.  Must
                        match original_state's NoC (rows, cols, alpha, beta).

    Returns:
        A fresh ScheduleState with recomputed contention-aware timing.

    Raises:
        ValueError: if any input fails validation (see _validate_inputs).
    """
    _validate_inputs(dag, original_state, noc)

    # Collect all instances sorted by original timing priority.
    # not is_primary: False (primary=0) sorts before True (duplicate=1).
    pending: list[TaskInstance] = sorted(
        (
            inst
            for inst_list in original_state.task_instances.values()
            for inst in inst_list
        ),
        key=lambda i: (
            i.start_time,
            i.finish_time,
            i.task_id,
            i.processor_id,
            not i.is_primary,
        ),
    )

    replay_state = ScheduleState(noc)
    replayed_task_ids: set[int] = set()

    while pending:
        ready: list[TaskInstance] = [
            inst for inst in pending
            if all(p in replayed_task_ids for p in dag.predecessors(inst.task_id))
        ]
        if not ready:
            details = [(i.task_id, i.processor_id) for i in pending[:5]]
            raise ValueError(
                f"Replay stalled: no ready instance. "
                f"First pending (task_id, proc_id): {details}"
            )

        inst = ready[0]
        pending = [i for i in pending if i is not inst]

        drt = _compute_replay_drt(dag, replay_state, inst.task_id, inst.processor_id)
        cost = dag.computation_cost(inst.task_id)
        start = replay_state.earliest_slot(inst.processor_id, cost, not_before=drt)
        finish = start + cost
        replay_state.reserve_task(
            task_id=inst.task_id,
            processor_id=inst.processor_id,
            start_time=start,
            finish_time=finish,
            is_primary=inst.is_primary,
        )
        replayed_task_ids.add(inst.task_id)

    return replay_state


def contention_replayed_makespan(
    dag: DAGGraph,
    original_state: ScheduleState,
    noc: MeshNoC,
) -> float:
    """Return the replayed contention-aware makespan."""
    return replay_under_contention(dag, original_state, noc).max_processor_finish_time()


def summarize_replay(
    original_state: ScheduleState,
    replayed_state: ScheduleState,
) -> dict[str, float]:
    """
    Return a flat dict comparing original and replayed schedule metrics.

    Keys:
        original_makespan     — max processor finish time in original_state
        replayed_makespan     — max processor finish time in replayed_state
        original_comm_count   — len(original_state.communication_instances)
        replayed_comm_count   — len(replayed_state.communication_instances)
        task_instance_count   — total TaskInstance objects in original_state
    """
    return {
        "original_makespan": original_state.max_processor_finish_time(),
        "replayed_makespan": replayed_state.max_processor_finish_time(),
        "original_comm_count": float(len(original_state.communication_instances)),
        "replayed_comm_count": float(len(replayed_state.communication_instances)),
        "task_instance_count": float(
            sum(len(v) for v in original_state.task_instances.values())
        ),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_replay_drt(
    dag: DAGGraph,
    replay_state: ScheduleState,
    task_id: int,
    processor_id: int,
) -> float:
    """
    Compute DRT for task_id on processor_id using the contention-aware model.

    Iterates DAG predecessors in ascending task_id order.  For each predecessor
    selects the already-replayed instance that gives the earliest arrival at
    processor_id using three-way priority (arrival → local preference →
    smaller processor_id).  The winning remote communication, if any, is
    committed to replay_state via reserve_communication().

    Returns 0.0 for entry tasks (no predecessors).
    Raises ValueError if a required predecessor has no replayed instance.
    """
    drt = 0.0
    for pred in sorted(dag.predecessors(task_id)):
        vol = dag.communication_volume(pred, task_id)
        instances = replay_state.get_task_instances(pred)
        if not instances:
            raise ValueError(
                f"Predecessor {pred} of task {task_id} has no replayed instance"
            )

        best_arrival: float = math.inf
        best_inst: TaskInstance | None = None
        best_is_local: bool = False

        for src in instances:
            if src.processor_id == processor_id:
                arrival = src.finish_time
                is_local = True
            else:
                arrival = replay_state.probe_communication_arrival(
                    source_processor=src.processor_id,
                    destination_processor=processor_id,
                    ready_time=src.finish_time,
                    communication_volume=vol,
                )
                is_local = False

            if _is_better_source(
                arrival, is_local, src.processor_id,
                best_arrival, best_is_local,
                best_inst.processor_id if best_inst is not None else None,
            ):
                best_arrival = arrival
                best_inst = src
                best_is_local = is_local

        if not best_is_local and best_inst is not None:
            replay_state.reserve_communication(
                source_task=pred,
                target_task=task_id,
                source_processor=best_inst.processor_id,
                destination_processor=processor_id,
                ready_time=best_inst.finish_time,
                communication_volume=vol,
            )

        drt = max(drt, best_arrival)

    return drt


def _is_better_source(
    arrival: float,
    is_local: bool,
    proc_id: int,
    best_arrival: float,
    best_is_local: bool,
    best_proc: int | None,
) -> bool:
    """Three-way priority: smallest arrival → local over remote → smaller proc_id."""
    if arrival < best_arrival:
        return True
    if arrival > best_arrival:
        return False
    if is_local and not best_is_local:
        return True
    if is_local == best_is_local and best_proc is not None:
        return proc_id < best_proc
    return False


def _validate_inputs(
    dag: DAGGraph,
    original_state: ScheduleState,
    noc: MeshNoC,
) -> None:
    """
    Raise ValueError if any input combination is invalid.

    Checks:
    1. Type checks for dag, original_state, noc.
    2. NoC configuration consistency: original_state._noc must match noc
       (rows, cols, alpha, beta).
    3. Every task_id in original_state must be in the DAG.
    4. Every DAG task must have exactly one primary instance in original_state.
    5. Every processor_id referenced in original_state must be valid for noc.
    """
    if not isinstance(dag, DAGGraph):
        raise ValueError(
            f"dag must be a DAGGraph instance, got {type(dag).__name__}"
        )
    if not isinstance(original_state, ScheduleState):
        raise ValueError(
            f"original_state must be a ScheduleState instance, "
            f"got {type(original_state).__name__}"
        )
    if not isinstance(noc, MeshNoC):
        raise ValueError(
            f"noc must be a MeshNoC instance, got {type(noc).__name__}"
        )

    sn = original_state._noc
    if sn.rows != noc.rows or sn.cols != noc.cols:
        raise ValueError(
            f"original_state NoC size ({sn.rows}x{sn.cols}) does not match "
            f"replay noc ({noc.rows}x{noc.cols})"
        )
    if sn.alpha != noc.alpha or sn.beta != noc.beta:
        raise ValueError(
            f"original_state NoC parameters (alpha={sn.alpha}, beta={sn.beta}) "
            f"do not match replay noc (alpha={noc.alpha}, beta={noc.beta})"
        )

    dag_task_ids: set[int] = set(dag.task_ids())

    for task_id in original_state.task_instances:
        if task_id not in dag_task_ids:
            raise ValueError(
                f"original_state contains task_id {task_id} "
                f"which is not in the DAG"
            )

    for task_id in dag_task_ids:
        instances = original_state.task_instances.get(task_id, [])
        primaries = [i for i in instances if i.is_primary]
        if len(primaries) == 0:
            raise ValueError(
                f"DAG task {task_id} has no primary instance in original_state"
            )
        if len(primaries) > 1:
            raise ValueError(
                f"DAG task {task_id} has {len(primaries)} primary instances in "
                f"original_state; expected exactly one"
            )

    for task_id, inst_list in original_state.task_instances.items():
        for inst in inst_list:
            if not noc.is_valid_processor(inst.processor_id):
                raise ValueError(
                    f"Task instance (task_id={task_id}, "
                    f"processor_id={inst.processor_id}) has a processor_id "
                    f"not valid for the replay noc "
                    f"({noc.rows}x{noc.cols} mesh)"
                )
