"""
Metrics calculation for completed schedules.

Computes makespan, task counts, duplication statistics, communication
latency, link utilization, processor utilization, and speedup.
All functions are pure: they read ScheduleState without mutation.
Implemented in Phase 9.

Duplication ratio note:
    duplication_ratio  = duplicate_count / primary_count  (excess instances)
    task_instance_ratio = total_instances / primary_count  (instances per task,
        matches the project definition: duplication ratio = instances / |V|)

Link utilization note:
    Utilization is computed from link_intervals busy time, not from
    CommunicationInstance duration, because one communication may occupy
    multiple route links simultaneously.

Processor utilization note:
    processor_intervals contains intervals for both primary and duplicate
    task executions.  Utilization is relative to makespan across all
    processors in the NoC, including idle ones.
"""

import math

from src.models import Link
from src.schedule_state import ScheduleState


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_state(state: ScheduleState) -> None:
    if not isinstance(state, ScheduleState):
        raise ValueError(
            f"state must be a ScheduleState instance, got {type(state).__name__}"
        )


# ---------------------------------------------------------------------------
# Makespan
# ---------------------------------------------------------------------------

def compute_makespan(state: ScheduleState) -> float:
    """Return the schedule makespan (maximum processor finish time)."""
    _validate_state(state)
    return state.max_processor_finish_time()


# ---------------------------------------------------------------------------
# Task-instance counts
# ---------------------------------------------------------------------------

def count_primary_tasks(state: ScheduleState) -> int:
    """Return the number of TaskInstance objects with is_primary=True."""
    _validate_state(state)
    return sum(
        1
        for instances in state.task_instances.values()
        for inst in instances
        if inst.is_primary
    )


def count_duplicate_tasks(state: ScheduleState) -> int:
    """Return the number of TaskInstance objects with is_primary=False."""
    _validate_state(state)
    return sum(
        1
        for instances in state.task_instances.values()
        for inst in instances
        if not inst.is_primary
    )


def duplication_ratio(state: ScheduleState) -> float:
    """
    Return duplicate_count / primary_count.

    Returns 0.0 when primary_count is zero.
    """
    _validate_state(state)
    primary = count_primary_tasks(state)
    if primary == 0:
        return 0.0
    return count_duplicate_tasks(state) / primary


def count_total_task_instances(state: ScheduleState) -> int:
    """Return the total number of task instances (primary + duplicate)."""
    _validate_state(state)
    return count_primary_tasks(state) + count_duplicate_tasks(state)


def task_instance_ratio(state: ScheduleState) -> float:
    """
    Return total_task_instances / primary_count.

    Returns 0.0 when primary_count is zero.
    Matches the project definition: duplication ratio = instances / |V|,
    where |V| is the number of original DAG tasks (primary instances).
    """
    _validate_state(state)
    primary = count_primary_tasks(state)
    if primary == 0:
        return 0.0
    return count_total_task_instances(state) / primary


# ---------------------------------------------------------------------------
# Communication metrics
# ---------------------------------------------------------------------------

def count_communication_instances(state: ScheduleState) -> int:
    """Return the number of CommunicationInstance objects in the schedule."""
    _validate_state(state)
    return len(state.communication_instances)


def average_communication_latency(state: ScheduleState) -> float:
    """
    Return the average duration of all CommunicationInstance objects.

    Returns 0.0 when there are no communication instances.
    """
    _validate_state(state)
    cis = state.communication_instances
    if not cis:
        return 0.0
    return sum(ci.duration for ci in cis) / len(cis)


def total_communication_time(state: ScheduleState) -> float:
    """
    Return the sum of durations of all CommunicationInstance objects.

    Returns 0.0 when there are no communication instances.
    """
    _validate_state(state)
    return sum(ci.duration for ci in state.communication_instances)


# ---------------------------------------------------------------------------
# Link utilization
# ---------------------------------------------------------------------------

def link_busy_time(state: ScheduleState) -> dict[Link, float]:
    """
    Return a dict mapping each Link to its total busy time.

    Busy time is the sum of interval durations on that link across
    all reserved communication intervals.  Links with no reservations
    appear with a value of 0.0.
    """
    _validate_state(state)
    return {
        link: sum(iv.duration for iv in intervals)
        for link, intervals in state.link_intervals.items()
    }


def average_link_utilization(
    state: ScheduleState,
    makespan: float | None = None,
) -> float:
    """
    Return average link utilization across all links in the NoC.

    utilization_per_link = busy_time / makespan
    average = mean over all links (idle links contribute 0).

    If makespan is None, compute_makespan(state) is used.
    Returns 0.0 when makespan is 0 or there are no links.
    """
    _validate_state(state)
    if makespan is None:
        makespan = compute_makespan(state)
    if makespan == 0.0:
        return 0.0
    busy = link_busy_time(state)
    if not busy:
        return 0.0
    return sum(busy.values()) / (len(busy) * makespan)


def max_link_utilization(
    state: ScheduleState,
    makespan: float | None = None,
) -> float:
    """
    Return maximum link utilization across all links in the NoC.

    Returns 0.0 when makespan is 0 or there are no links.
    """
    _validate_state(state)
    if makespan is None:
        makespan = compute_makespan(state)
    if makespan == 0.0:
        return 0.0
    busy = link_busy_time(state)
    if not busy:
        return 0.0
    return max(busy.values()) / makespan


# ---------------------------------------------------------------------------
# Processor utilization
# ---------------------------------------------------------------------------

def processor_busy_time(state: ScheduleState) -> dict[int, float]:
    """
    Return a dict mapping each processor ID to its total busy time.

    Busy time is the sum of all task-execution interval durations on
    that processor (both primary and duplicate executions).
    """
    _validate_state(state)
    return {
        pid: sum(iv.duration for iv in intervals)
        for pid, intervals in state.processor_intervals.items()
    }


def average_processor_utilization(
    state: ScheduleState,
    makespan: float | None = None,
) -> float:
    """
    Return average processor utilization across all processors in the NoC.

    Idle processors (no tasks assigned) contribute 0 to the average.
    Returns 0.0 when makespan is 0 or there are no processors.
    """
    _validate_state(state)
    if makespan is None:
        makespan = compute_makespan(state)
    if makespan == 0.0:
        return 0.0
    busy = processor_busy_time(state)
    if not busy:
        return 0.0
    return sum(busy.values()) / (len(busy) * makespan)


def max_processor_utilization(
    state: ScheduleState,
    makespan: float | None = None,
) -> float:
    """
    Return maximum processor utilization across all processors in the NoC.

    Returns 0.0 when makespan is 0 or there are no processors.
    """
    _validate_state(state)
    if makespan is None:
        makespan = compute_makespan(state)
    if makespan == 0.0:
        return 0.0
    busy = processor_busy_time(state)
    if not busy:
        return 0.0
    return max(busy.values()) / makespan


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------

def schedule_summary(state: ScheduleState) -> dict[str, float | int]:
    """
    Return a flat dict of all key metrics for a completed schedule.

    Computes makespan once and passes it to utilization functions to avoid
    redundant traversal.

    Keys returned:
        makespan, primary_task_count, duplicate_task_count, duplication_ratio,
        total_task_instance_count, task_instance_ratio,
        communication_count, average_communication_latency,
        total_communication_time, average_link_utilization,
        max_link_utilization, average_processor_utilization,
        max_processor_utilization.
    """
    _validate_state(state)
    ms = compute_makespan(state)
    return {
        "makespan": ms,
        "primary_task_count": count_primary_tasks(state),
        "duplicate_task_count": count_duplicate_tasks(state),
        "duplication_ratio": duplication_ratio(state),
        "total_task_instance_count": count_total_task_instances(state),
        "task_instance_ratio": task_instance_ratio(state),
        "communication_count": count_communication_instances(state),
        "average_communication_latency": average_communication_latency(state),
        "total_communication_time": total_communication_time(state),
        "average_link_utilization": average_link_utilization(state, ms),
        "max_link_utilization": max_link_utilization(state, ms),
        "average_processor_utilization": average_processor_utilization(state, ms),
        "max_processor_utilization": max_processor_utilization(state, ms),
    }


# ---------------------------------------------------------------------------
# Speedup
# ---------------------------------------------------------------------------

def speedup(baseline_makespan: float, scheduler_makespan: float) -> float:
    """
    Return baseline_makespan / scheduler_makespan.

    Special case: both zero → return 1.0.
    Raises ValueError for negative, infinite, or NaN inputs, and when
    scheduler_makespan is 0 while baseline_makespan is not.
    """
    _validate_speedup_input(baseline_makespan, "baseline_makespan")
    _validate_speedup_input(scheduler_makespan, "scheduler_makespan")
    if scheduler_makespan == 0.0:
        if baseline_makespan == 0.0:
            return 1.0
        raise ValueError(
            f"scheduler_makespan is 0 with non-zero baseline_makespan "
            f"({baseline_makespan}): speedup is undefined"
        )
    return baseline_makespan / scheduler_makespan


def _validate_speedup_input(val: float, name: str) -> None:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValueError(
            f"{name} must be numeric, got {type(val).__name__}: {val!r}"
        )
    if not math.isfinite(val):
        raise ValueError(f"{name} must be finite, got {val}")
    if val < 0:
        raise ValueError(f"{name} must be non-negative, got {val}")
