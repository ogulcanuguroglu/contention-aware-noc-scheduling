"""
Mutable scheduling state.

Tracks processor and link reservations during schedule construction.
Supports cloning for tentative (speculative) scheduling evaluation.
Implemented in Phase 4.

Interval overlap rule:
    [a_start, a_finish) and [b_start, b_finish) overlap iff
    a_start != a_finish AND b_start != b_finish AND
    a_start < b_finish AND b_start < a_finish.
    A zero-duration interval [t, t) is empty and never overlaps anything.
    Back-to-back intervals [0, 10) and [10, 20) are NOT overlapping.

Route-wide reservation model:
    Remote communication is reserved as a single atomic interval
    [start_time, start_time + duration) on every link along the XY route.
    This is a simplified model; per-flit pipeline timing is not implemented.

get_finish_time with processor_id:
    Raises ValueError if multiple instances of the same task exist on the
    same processor, as this should not occur in correct scheduling.
"""

import math

from src.models import CommunicationInstance, Interval, Link, TaskInstance
from src.noc import MeshNoC


class ScheduleState:
    """
    Mutable schedule state for processor and link reservations.

    Args:
        noc: The MeshNoC instance describing the target hardware.
    """

    def __init__(self, noc: MeshNoC) -> None:
        if not isinstance(noc, MeshNoC):
            raise ValueError(
                f"noc must be a MeshNoC instance, got {type(noc).__name__}"
            )
        self._noc = noc
        self.processor_intervals: dict[int, list[Interval]] = {
            pid: [] for pid in noc.processor_ids()
        }
        self.link_intervals: dict[Link, list[Interval]] = {
            link: [] for link in noc.all_directed_links()
        }
        self.task_instances: dict[int, list[TaskInstance]] = {}
        self.communication_instances: list[CommunicationInstance] = []

    # ------------------------------------------------------------------
    # Slot finding
    # ------------------------------------------------------------------

    def earliest_slot(
        self,
        processor_id: int,
        duration: float,
        not_before: float = 0.0,
    ) -> float:
        """
        Find the earliest start time >= not_before on processor_id such that
        [start_time, start_time + duration) does not overlap any reserved interval.
        """
        self._validate_processor_id(processor_id)
        self._validate_time_value(duration, "duration")
        self._validate_time_value(not_before, "not_before")

        if duration == 0.0:
            return not_before

        candidate = not_before
        for iv in self.processor_intervals[processor_id]:
            if candidate + duration <= iv.start_time:
                break
            if candidate < iv.finish_time:
                candidate = iv.finish_time
        return candidate

    def earliest_route_slot(
        self,
        route: list[Link],
        duration: float,
        not_before: float = 0.0,
    ) -> float:
        """
        Find the earliest start time >= not_before such that every link in route
        is free for the full interval [start_time, start_time + duration).
        """
        self._validate_time_value(duration, "duration")
        self._validate_time_value(not_before, "not_before")
        for link in route:
            self._validate_link(link)

        if not route or duration == 0.0:
            return not_before

        candidate = not_before
        while True:
            candidate_finish = candidate + duration
            max_conflict_end: float | None = None
            for link in route:
                for iv in self.link_intervals[link]:
                    if iv.start_time < candidate_finish and candidate < iv.finish_time:
                        if max_conflict_end is None or iv.finish_time > max_conflict_end:
                            max_conflict_end = iv.finish_time
            if max_conflict_end is None:
                return candidate
            candidate = max_conflict_end

    # ------------------------------------------------------------------
    # Reservations
    # ------------------------------------------------------------------

    def reserve_task(
        self,
        task_id: int,
        processor_id: int,
        start_time: float,
        finish_time: float,
        is_primary: bool = True,
    ) -> TaskInstance:
        """
        Reserve a task interval on processor_id.

        Raises ValueError if the interval overlaps an existing reservation.
        Returns the created TaskInstance.
        """
        self._validate_non_negative_int(task_id, "task_id")
        self._validate_processor_id(processor_id)
        self._validate_time_value(start_time, "start_time")
        self._validate_time_value(finish_time, "finish_time")
        if finish_time < start_time:
            raise ValueError(
                f"finish_time must be >= start_time, "
                f"got finish={finish_time}, start={start_time}"
            )

        for iv in self.processor_intervals[processor_id]:
            if self._intervals_overlap(start_time, finish_time, iv.start_time, iv.finish_time):
                raise ValueError(
                    f"Interval [{start_time}, {finish_time}) overlaps existing "
                    f"[{iv.start_time}, {iv.finish_time}) on processor {processor_id}"
                )

        ti = TaskInstance(
            task_id=task_id,
            processor_id=processor_id,
            start_time=start_time,
            finish_time=finish_time,
            is_primary=is_primary,
        )

        proc_iv = Interval(
            start_time=start_time,
            finish_time=finish_time,
            resource_id=processor_id,
            metadata={"type": "task", "task_id": task_id, "is_primary": is_primary},
        )
        self._insert_sorted_interval(self.processor_intervals[processor_id], proc_iv)

        if task_id not in self.task_instances:
            self.task_instances[task_id] = []
        self.task_instances[task_id].append(ti)

        return ti

    def reserve_route(
        self,
        route: list[Link],
        start_time: float,
        finish_time: float,
        metadata: dict | None = None,
    ) -> None:
        """
        Reserve [start_time, finish_time) on every link in route atomically.

        Raises ValueError if any link has a conflicting interval.
        All links are checked before any reservation is made.
        """
        self._validate_time_value(start_time, "start_time")
        self._validate_time_value(finish_time, "finish_time")
        if finish_time < start_time:
            raise ValueError(
                f"finish_time must be >= start_time, "
                f"got finish={finish_time}, start={start_time}"
            )
        for link in route:
            self._validate_link(link)

        for link in route:
            for iv in self.link_intervals[link]:
                if self._intervals_overlap(start_time, finish_time, iv.start_time, iv.finish_time):
                    raise ValueError(
                        f"Interval [{start_time}, {finish_time}) overlaps existing "
                        f"[{iv.start_time}, {iv.finish_time}) on link {link}"
                    )

        for link in route:
            link_iv = Interval(
                start_time=start_time,
                finish_time=finish_time,
                resource_id=link,
                metadata=metadata,
            )
            self._insert_sorted_interval(self.link_intervals[link], link_iv)

    def reserve_communication(
        self,
        source_task: int,
        target_task: int,
        source_processor: int,
        destination_processor: int,
        ready_time: float,
        communication_volume: float,
    ) -> CommunicationInstance:
        """
        Schedule a communication from source_processor to destination_processor.

        Local (same-processor) communication is free and reserves no links.
        Remote communication uses noc.get_route and reserves the route atomically.
        The start_time is the earliest feasible time >= ready_time with no link conflicts.
        Returns the created CommunicationInstance.
        """
        self._validate_non_negative_int(source_task, "source_task")
        self._validate_non_negative_int(target_task, "target_task")
        if source_task == target_task:
            raise ValueError(
                f"source_task and target_task must differ, got {source_task}"
            )
        self._validate_processor_id(source_processor, "source_processor")
        self._validate_processor_id(destination_processor, "destination_processor")
        self._validate_time_value(ready_time, "ready_time")
        self._validate_time_value(communication_volume, "communication_volume")

        if source_processor == destination_processor:
            ci = CommunicationInstance(
                source_task=source_task,
                target_task=target_task,
                source_processor=source_processor,
                destination_processor=destination_processor,
                route=[],
                start_time=ready_time,
                finish_time=ready_time,
                communication_volume=communication_volume,
            )
            self.communication_instances.append(ci)
            return ci

        route = self._noc.get_route(source_processor, destination_processor)
        duration = self._noc.communication_duration(
            source_processor, destination_processor, communication_volume
        )
        start_time = self.earliest_route_slot(route, duration, not_before=ready_time)
        finish_time = start_time + duration

        self.reserve_route(
            route,
            start_time,
            finish_time,
            metadata={
                "type": "communication",
                "source_task": source_task,
                "target_task": target_task,
            },
        )

        ci = CommunicationInstance(
            source_task=source_task,
            target_task=target_task,
            source_processor=source_processor,
            destination_processor=destination_processor,
            route=route,
            start_time=start_time,
            finish_time=finish_time,
            communication_volume=communication_volume,
        )
        self.communication_instances.append(ci)
        return ci

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def has_task_instance(
        self,
        task_id: int,
        processor_id: int | None = None,
    ) -> bool:
        """Return True if task has at least one instance (optionally on a specific processor)."""
        instances = self.task_instances.get(task_id, [])
        if not instances:
            return False
        if processor_id is None:
            return True
        return any(ti.processor_id == processor_id for ti in instances)

    def get_task_instances(self, task_id: int) -> list[TaskInstance]:
        """Return a shallow copy of all TaskInstances for task_id."""
        return list(self.task_instances.get(task_id, []))

    def get_primary_instance(self, task_id: int) -> TaskInstance:
        """
        Return the unique primary TaskInstance for task_id.

        Raises ValueError if no primary instance exists or if more than one does.
        """
        instances = self.task_instances.get(task_id, [])
        primaries = [ti for ti in instances if ti.is_primary]
        if not primaries:
            raise ValueError(f"No primary instance found for task {task_id}")
        if len(primaries) > 1:
            raise ValueError(
                f"Multiple primary instances found for task {task_id}: {len(primaries)}"
            )
        return primaries[0]

    def get_finish_time(
        self,
        task_id: int,
        processor_id: int | None = None,
    ) -> float:
        """
        Return finish time of a task instance.

        If processor_id is None, returns the primary instance finish time.
        If processor_id is given, returns the finish time of that task on that processor.
        Raises ValueError if not found or if multiple instances exist on the same processor.
        """
        if processor_id is None:
            return self.get_primary_instance(task_id).finish_time

        instances = [
            ti for ti in self.task_instances.get(task_id, [])
            if ti.processor_id == processor_id
        ]
        if not instances:
            raise ValueError(
                f"No instance of task {task_id} on processor {processor_id}"
            )
        if len(instances) > 1:
            raise ValueError(
                f"Multiple instances of task {task_id} on processor {processor_id}"
            )
        return instances[0].finish_time

    # ------------------------------------------------------------------
    # Availability and makespan helpers
    # ------------------------------------------------------------------

    def processor_available_time(self, processor_id: int) -> float:
        """Return finish_time of the last interval on processor_id, or 0.0 if empty."""
        intervals = self.processor_intervals[processor_id]
        return intervals[-1].finish_time if intervals else 0.0

    def link_available_time(self, link: Link) -> float:
        """Return finish_time of the last interval on link, or 0.0 if empty."""
        intervals = self.link_intervals[link]
        return intervals[-1].finish_time if intervals else 0.0

    def max_processor_finish_time(self) -> float:
        """Return the maximum finish time across all processor intervals, or 0.0."""
        max_t = 0.0
        for intervals in self.processor_intervals.values():
            if intervals:
                max_t = max(max_t, intervals[-1].finish_time)
        return max_t

    def max_link_finish_time(self) -> float:
        """Return the maximum finish time across all link intervals, or 0.0."""
        max_t = 0.0
        for intervals in self.link_intervals.values():
            if intervals:
                max_t = max(max_t, intervals[-1].finish_time)
        return max_t

    def probe_communication_arrival(
        self,
        source_processor: int,
        destination_processor: int,
        ready_time: float,
        communication_volume: float,
    ) -> float:
        """
        Compute when a communication would finish without reserving any links.

        Equivalent to reserve_communication() but read-only: finds the
        earliest feasible start time using the current link intervals and
        returns start_time + duration, without modifying any state.

        Used by ProposedScheduler to compare candidate source instances
        without creating sub-clones just for probing.

        Local (same-processor) communication returns ready_time immediately.
        """
        self._validate_processor_id(source_processor, "source_processor")
        self._validate_processor_id(destination_processor, "destination_processor")
        self._validate_time_value(ready_time, "ready_time")
        self._validate_time_value(communication_volume, "communication_volume")

        if source_processor == destination_processor:
            return ready_time

        route = self._noc.get_route(source_processor, destination_processor)
        duration = self._noc.communication_duration(
            source_processor, destination_processor, communication_volume
        )
        start = self.earliest_route_slot(route, duration, not_before=ready_time)
        return start + duration

    # ------------------------------------------------------------------
    # Clone
    # ------------------------------------------------------------------

    def clone(self) -> "ScheduleState":
        """
        Return a structurally independent copy of this ScheduleState.

        Interval, TaskInstance, CommunicationInstance, and Link objects are
        never mutated after creation, so they can be shared between the
        original and the clone.  Only the container lists and dicts are
        copied, making this substantially faster than deepcopy on large states.
        """
        new_state = object.__new__(ScheduleState)
        new_state._noc = self._noc
        new_state.processor_intervals = {
            pid: list(iv_list)
            for pid, iv_list in self.processor_intervals.items()
        }
        new_state.link_intervals = {
            link: list(iv_list)
            for link, iv_list in self.link_intervals.items()
        }
        new_state.task_instances = {
            tid: list(inst_list)
            for tid, inst_list in self.task_instances.items()
        }
        new_state.communication_instances = list(self.communication_instances)
        return new_state

    # ------------------------------------------------------------------
    # Integrity check
    # ------------------------------------------------------------------

    def validate_no_overlaps(self) -> None:
        """
        Validate that no processor or link has overlapping intervals.
        Raises ValueError if an overlap is detected.
        """
        for proc_id, intervals in self.processor_intervals.items():
            self._assert_no_overlap(intervals, f"processor {proc_id}")
        for link, intervals in self.link_intervals.items():
            self._assert_no_overlap(intervals, f"link {link}")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _intervals_overlap(
        a_start: float,
        a_finish: float,
        b_start: float,
        b_finish: float,
    ) -> bool:
        if a_start == a_finish or b_start == b_finish:
            return False
        return a_start < b_finish and b_start < a_finish

    def _insert_sorted_interval(
        self,
        interval_list: list[Interval],
        new_iv: Interval,
    ) -> None:
        interval_list.append(new_iv)
        interval_list.sort(key=lambda iv: iv.start_time)

    def _assert_no_overlap(
        self,
        intervals: list[Interval],
        label: str,
    ) -> None:
        sorted_ivs = sorted(intervals, key=lambda iv: iv.start_time)
        for i in range(len(sorted_ivs) - 1):
            a, b = sorted_ivs[i], sorted_ivs[i + 1]
            if self._intervals_overlap(a.start_time, a.finish_time, b.start_time, b.finish_time):
                raise ValueError(
                    f"Overlap on {label}: [{a.start_time}, {a.finish_time}) "
                    f"and [{b.start_time}, {b.finish_time})"
                )

    def _validate_time_value(self, val: float, name: str) -> None:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError(
                f"{name} must be numeric, got {type(val).__name__}: {val!r}"
            )
        if not math.isfinite(val):
            raise ValueError(f"{name} must be finite, got {val}")
        if val < 0:
            raise ValueError(f"{name} must be non-negative, got {val}")

    def _validate_non_negative_int(self, val: int, name: str) -> None:
        if isinstance(val, bool) or not isinstance(val, int):
            raise ValueError(
                f"{name} must be int, got {type(val).__name__}: {val!r}"
            )
        if val < 0:
            raise ValueError(f"{name} must be non-negative, got {val}")

    def _validate_processor_id(
        self,
        processor_id: int,
        name: str = "processor_id",
    ) -> None:
        if not self._noc.is_valid_processor(processor_id):
            raise ValueError(
                f"{name} is not a valid processor: {processor_id!r}"
            )

    def _validate_link(self, link: Link, name: str = "link") -> None:
        if link not in self.link_intervals:
            raise ValueError(f"{name} is not a valid link: {link!r}")
