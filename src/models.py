"""
Core data model definitions for the scheduling simulation.

Defines dataclasses for tasks, edges, processors, links, intervals,
and schedule instances used throughout the framework.
Implemented in Phase 1.

NetworkX DiGraph attribute convention used by DAGGraph:
  node attribute: 'computation_cost'   (float, > 0)
  edge attribute: 'communication_volume' (float, >= 0)
"""

import dataclasses

import networkx as nx


@dataclasses.dataclass
class Task:
    """A DAG task node with a computation cost."""

    task_id: int
    computation_cost: float

    def __post_init__(self) -> None:
        if self.task_id < 0:
            raise ValueError(f"task_id must be non-negative, got {self.task_id}")
        if self.computation_cost <= 0:
            raise ValueError(f"computation_cost must be positive, got {self.computation_cost}")


@dataclasses.dataclass
class Edge:
    """A directed dependency edge between two DAG tasks."""

    source: int
    target: int
    communication_volume: float

    def __post_init__(self) -> None:
        if self.source < 0 or self.target < 0:
            raise ValueError(
                f"source and target must be non-negative, got {self.source}, {self.target}"
            )
        if self.source == self.target:
            raise ValueError(f"source and target must differ, got {self.source}")
        if self.communication_volume < 0:
            raise ValueError(
                f"communication_volume must be non-negative, got {self.communication_volume}"
            )


@dataclasses.dataclass
class Processor:
    """A processor tile placed at coordinates (x, y) in the 2D mesh NoC."""

    processor_id: int
    x: int
    y: int

    def __post_init__(self) -> None:
        if self.processor_id < 0:
            raise ValueError(f"processor_id must be non-negative, got {self.processor_id}")
        if self.x < 0 or self.y < 0:
            raise ValueError(f"x and y must be non-negative, got ({self.x}, {self.y})")


@dataclasses.dataclass(frozen=True)
class Link:
    """
    A directed NoC link between two neighbouring processor tiles.

    frozen=True makes Link hashable so instances can be used as dict keys
    in ScheduleState link-interval tables.
    """

    source_processor: int
    destination_processor: int

    def __post_init__(self) -> None:
        if self.source_processor < 0 or self.destination_processor < 0:
            raise ValueError(
                f"source_processor and destination_processor must be non-negative, "
                f"got {self.source_processor}, {self.destination_processor}"
            )
        if self.source_processor == self.destination_processor:
            raise ValueError(
                f"source_processor and destination_processor must differ, "
                f"got {self.source_processor}"
            )


@dataclasses.dataclass
class Interval:
    """A reserved time interval on a processor or NoC link."""

    start_time: float
    finish_time: float
    resource_id: str | int | None = None
    metadata: dict | None = None

    def __post_init__(self) -> None:
        if self.start_time < 0:
            raise ValueError(f"start_time must be non-negative, got {self.start_time}")
        if self.finish_time < self.start_time:
            raise ValueError(
                f"finish_time must be >= start_time, "
                f"got finish={self.finish_time}, start={self.start_time}"
            )

    @property
    def duration(self) -> float:
        return self.finish_time - self.start_time


@dataclasses.dataclass
class TaskInstance:
    """One scheduled execution of a task on a specific processor."""

    task_id: int
    processor_id: int
    start_time: float
    finish_time: float
    is_primary: bool = True

    def __post_init__(self) -> None:
        if self.task_id < 0:
            raise ValueError(f"task_id must be non-negative, got {self.task_id}")
        if self.processor_id < 0:
            raise ValueError(f"processor_id must be non-negative, got {self.processor_id}")
        if self.start_time < 0:
            raise ValueError(f"start_time must be non-negative, got {self.start_time}")
        if self.finish_time < self.start_time:
            raise ValueError(
                f"finish_time must be >= start_time, "
                f"got finish={self.finish_time}, start={self.start_time}"
            )

    @property
    def duration(self) -> float:
        return self.finish_time - self.start_time


@dataclasses.dataclass
class CommunicationInstance:
    """One scheduled communication of a DAG edge transferred across the NoC."""

    source_task: int
    target_task: int
    source_processor: int
    destination_processor: int
    route: list[Link]
    start_time: float
    finish_time: float
    communication_volume: float

    def __post_init__(self) -> None:
        for name, val in (
            ("source_task", self.source_task),
            ("target_task", self.target_task),
            ("source_processor", self.source_processor),
            ("destination_processor", self.destination_processor),
        ):
            if val < 0:
                raise ValueError(f"{name} must be non-negative, got {val}")
        if self.source_task == self.target_task:
            raise ValueError(
                f"source_task and target_task must differ, got {self.source_task}"
            )
        if self.start_time < 0:
            raise ValueError(f"start_time must be non-negative, got {self.start_time}")
        if self.finish_time < self.start_time:
            raise ValueError(
                f"finish_time must be >= start_time, "
                f"got finish={self.finish_time}, start={self.start_time}"
            )
        if self.communication_volume < 0:
            raise ValueError(
                f"communication_volume must be non-negative, got {self.communication_volume}"
            )
        if self.source_processor != self.destination_processor and not self.route:
            raise ValueError("route must not be empty for remote communication")

    @property
    def duration(self) -> float:
        return self.finish_time - self.start_time


@dataclasses.dataclass
class NoCConfig:
    """Configuration parameters for the 2D mesh NoC."""

    rows: int
    cols: int
    alpha: float = 1.0
    beta: float = 1.0
    routing: str = "xy"

    def __post_init__(self) -> None:
        if self.rows <= 0 or self.cols <= 0:
            raise ValueError(
                f"rows and cols must be positive, got rows={self.rows}, cols={self.cols}"
            )
        if self.alpha < 0 or self.beta < 0:
            raise ValueError(
                f"alpha and beta must be non-negative, got alpha={self.alpha}, beta={self.beta}"
            )
        if self.routing != "xy":
            raise ValueError(f"Only 'xy' routing is supported, got '{self.routing}'")

    @property
    def processor_count(self) -> int:
        """Total number of processor tiles in the mesh."""
        return self.rows * self.cols


@dataclasses.dataclass
class DAGGraph:
    """
    Thin wrapper around a NetworkX DiGraph representing the application task graph.

    The underlying graph must be directed and acyclic. Every node must carry a
    'computation_cost' attribute (float > 0) and every edge must carry a
    'communication_volume' attribute (float >= 0).
    """

    graph: nx.DiGraph

    def __post_init__(self) -> None:
        if not self.graph.is_directed():
            raise ValueError("graph must be directed")
        if not nx.is_directed_acyclic_graph(self.graph):
            raise ValueError("graph must be acyclic")
        for node in self.graph.nodes:
            if not isinstance(node, int):
                raise ValueError(
                    f"node ID must be int, got {type(node).__name__}: {node!r}"
                )
            if node < 0:
                raise ValueError(f"node ID must be non-negative, got {node}")
            node_attrs = self.graph.nodes[node]
            if "computation_cost" not in node_attrs:
                raise ValueError(f"node {node} is missing 'computation_cost' attribute")
            cost = node_attrs["computation_cost"]
            if cost <= 0:
                raise ValueError(
                    f"node {node} computation_cost must be positive, got {cost}"
                )
        for u, v in self.graph.edges:
            edge_attrs = self.graph.edges[u, v]
            if "communication_volume" not in edge_attrs:
                raise ValueError(f"edge ({u}, {v}) is missing 'communication_volume' attribute")
            vol = edge_attrs["communication_volume"]
            if vol < 0:
                raise ValueError(
                    f"edge ({u}, {v}) communication_volume must be non-negative, got {vol}"
                )

    def task_ids(self) -> list[int]:
        """Return all task IDs in the DAG."""
        return list(self.graph.nodes)

    def edge_ids(self) -> list[tuple[int, int]]:
        """Return all (source, target) edge pairs."""
        return list(self.graph.edges)

    def computation_cost(self, task_id: int) -> float:
        """Return the computation cost of a task."""
        return float(self.graph.nodes[task_id]["computation_cost"])

    def communication_volume(self, source: int, target: int) -> float:
        """Return the communication volume of an edge."""
        return float(self.graph.edges[source, target]["communication_volume"])

    def predecessors(self, task_id: int) -> list[int]:
        """Return immediate predecessor task IDs."""
        return list(self.graph.predecessors(task_id))

    def successors(self, task_id: int) -> list[int]:
        """Return immediate successor task IDs."""
        return list(self.graph.successors(task_id))

    def number_of_tasks(self) -> int:
        return self.graph.number_of_nodes()

    def number_of_edges(self) -> int:
        return self.graph.number_of_edges()
