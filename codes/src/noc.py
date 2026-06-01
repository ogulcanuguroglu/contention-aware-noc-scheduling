"""
2D Mesh Network-on-Chip (NoC) model.

Implements processor-coordinate mapping, 4-neighbor topology, deterministic
XY routing, hop counting, and communication duration estimation.

Scope (Phase 3):
    Topology and routing only. Link interval reservation and contention
    detection are implemented in Phase 4 (schedule_state.py).

Processor ID mapping (row-major):
    processor_id = y * cols + x

    where x is the column index (0 <= x < cols) and y is the row index
    (0 <= y < rows). Row y=0 is the top row.

XY routing rule:
    First move in the X direction until the column matches the destination,
    then move in the Y direction. This is deterministic and loop-free on a
    mesh.

Communication duration:
    duration = alpha * hop_count + beta * communication_volume

    Local communication (src == dst) always has zero duration.
"""

import math

from src.models import Link, NoCConfig, Processor


class MeshNoC:
    """
    2D mesh Network-on-Chip with deterministic XY routing.

    Args:
        rows: Number of rows. Must be positive.
        cols: Number of columns. Must be positive.
        alpha: Per-hop latency coefficient. Must be non-negative.
        beta:  Bandwidth coefficient (volume penalty). Must be non-negative.
    """

    def __init__(
        self,
        rows: int,
        cols: int,
        alpha: float = 1.0,
        beta: float = 1.0,
    ) -> None:
        for name, val in (("rows", rows), ("cols", cols)):
            if isinstance(val, bool) or not isinstance(val, int):
                raise ValueError(
                    f"{name} must be int, got {type(val).__name__}: {val!r}"
                )
            if val <= 0:
                raise ValueError(f"{name} must be positive, got {val}")
        for name, val in (("alpha", alpha), ("beta", beta)):
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ValueError(
                    f"{name} must be numeric, got {type(val).__name__}: {val!r}"
                )
            if not math.isfinite(val):
                raise ValueError(f"{name} must be finite, got {val}")
            if val < 0:
                raise ValueError(f"{name} must be non-negative, got {val}")
        self._config = NoCConfig(rows=rows, cols=cols, alpha=alpha, beta=beta)

    # ------------------------------------------------------------------
    # Basic properties
    # ------------------------------------------------------------------

    @property
    def rows(self) -> int:
        return self._config.rows

    @property
    def cols(self) -> int:
        return self._config.cols

    @property
    def alpha(self) -> float:
        return self._config.alpha

    @property
    def beta(self) -> float:
        return self._config.beta

    def processor_count(self) -> int:
        """Return total number of processor tiles (rows * cols)."""
        return self._config.processor_count

    def processor_ids(self) -> list[int]:
        """Return all processor IDs in ascending order."""
        return list(range(self.processor_count()))

    # ------------------------------------------------------------------
    # Coordinate mapping
    # ------------------------------------------------------------------

    def to_coordinates(self, processor_id: int) -> tuple[int, int]:
        """
        Return (x, y) for a processor ID using row-major mapping.

        x = processor_id % cols  (column index)
        y = processor_id // cols (row index)
        """
        self._require_processor_id(processor_id)
        return (processor_id % self.cols, processor_id // self.cols)

    def to_processor_id(self, x: int, y: int) -> int:
        """Return the processor ID at column x, row y."""
        self._require_coordinates(x, y)
        return y * self.cols + x

    def processors(self) -> list[Processor]:
        """Return all Processor instances in row-major order."""
        result = []
        for pid in self.processor_ids():
            x, y = self.to_coordinates(pid)
            result.append(Processor(processor_id=pid, x=x, y=y))
        return result

    # ------------------------------------------------------------------
    # Topology
    # ------------------------------------------------------------------

    def is_valid_processor(self, processor_id: int) -> bool:
        """Return True if processor_id is a valid non-bool int in range."""
        if isinstance(processor_id, bool) or not isinstance(processor_id, int):
            return False
        return 0 <= processor_id < self.processor_count()

    def neighbors(self, processor_id: int) -> list[int]:
        """
        Return immediate 4-neighbors in deterministic order:
        left, right, up, down — only valid neighbors included.

        'Up' decreases y; 'down' increases y (y=0 is the top row).
        """
        self._require_processor_id(processor_id)
        x, y = self.to_coordinates(processor_id)
        result = []
        if x > 0:
            result.append(self.to_processor_id(x - 1, y))   # left
        if x < self.cols - 1:
            result.append(self.to_processor_id(x + 1, y))   # right
        if y > 0:
            result.append(self.to_processor_id(x, y - 1))   # up
        if y < self.rows - 1:
            result.append(self.to_processor_id(x, y + 1))   # down
        return result

    def all_directed_links(self) -> list[Link]:
        """
        Return every directed link in the mesh.

        For each adjacent pair (a, b) both Link(a, b) and Link(b, a) are
        included. Links are enumerated by iterating processors in ascending
        ID order and then neighbors() order, so the result is deterministic
        and contains no duplicates.

        Expected count: 2 * (rows*(cols-1) + cols*(rows-1))
        """
        links: list[Link] = []
        for pid in self.processor_ids():
            for neighbor in self.neighbors(pid):
                links.append(Link(source_processor=pid, destination_processor=neighbor))
        return links

    def manhattan_distance(self, src_proc: int, dst_proc: int) -> int:
        """Return Manhattan distance between two processors."""
        self._require_processor_id(src_proc, "src_proc")
        self._require_processor_id(dst_proc, "dst_proc")
        sx, sy = self.to_coordinates(src_proc)
        dx, dy = self.to_coordinates(dst_proc)
        return abs(dx - sx) + abs(dy - sy)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def get_route(self, src_proc: int, dst_proc: int) -> list[Link]:
        """
        Return the XY route from src_proc to dst_proc as a list of Links.

        Phase 1 — X: move column-by-column toward the destination column.
        Phase 2 — Y: move row-by-row toward the destination row.

        Returns [] for local communication (src_proc == dst_proc).
        """
        self._require_processor_id(src_proc, "src_proc")
        self._require_processor_id(dst_proc, "dst_proc")

        if src_proc == dst_proc:
            return []

        links: list[Link] = []
        cx, cy = self.to_coordinates(src_proc)
        dx, dy = self.to_coordinates(dst_proc)

        step_x = 1 if dx > cx else -1
        while cx != dx:
            nx = cx + step_x
            links.append(Link(
                source_processor=self.to_processor_id(cx, cy),
                destination_processor=self.to_processor_id(nx, cy),
            ))
            cx = nx

        step_y = 1 if dy > cy else -1
        while cy != dy:
            ny = cy + step_y
            links.append(Link(
                source_processor=self.to_processor_id(cx, cy),
                destination_processor=self.to_processor_id(cx, ny),
            ))
            cy = ny

        return links

    def route_processor_sequence(self, src_proc: int, dst_proc: int) -> list[int]:
        """
        Return processor IDs visited along the XY route, including both endpoints.

        Examples (4x4 mesh):
            route_processor_sequence(0, 0)  -> [0]
            route_processor_sequence(0, 5)  -> [0, 1, 5]
            route_processor_sequence(0, 15) -> [0, 1, 2, 3, 7, 11, 15]
            route_processor_sequence(15, 0) -> [15, 14, 13, 12, 8, 4, 0]
        """
        self._require_processor_id(src_proc, "src_proc")
        self._require_processor_id(dst_proc, "dst_proc")

        sequence = [src_proc]
        for link in self.get_route(src_proc, dst_proc):
            sequence.append(link.destination_processor)
        return sequence

    def hop_count(self, src_proc: int, dst_proc: int) -> int:
        """Return number of hops from src to dst. Equals manhattan_distance."""
        return len(self.get_route(src_proc, dst_proc))

    def communication_duration(
        self,
        src_proc: int,
        dst_proc: int,
        communication_volume: float,
    ) -> float:
        """
        Compute base communication duration:
            duration = alpha * hop_count + beta * communication_volume

        Returns 0.0 for local communication (src_proc == dst_proc),
        regardless of communication_volume.
        """
        self._require_processor_id(src_proc, "src_proc")
        self._require_processor_id(dst_proc, "dst_proc")
        self._require_volume(communication_volume)

        if src_proc == dst_proc:
            return 0.0

        return self.alpha * self.hop_count(src_proc, dst_proc) + self.beta * communication_volume

    # ------------------------------------------------------------------
    # Internal validators
    # ------------------------------------------------------------------

    def _require_processor_id(self, processor_id: int, name: str = "processor_id") -> None:
        if isinstance(processor_id, bool) or not isinstance(processor_id, int):
            raise ValueError(
                f"{name} must be int, got {type(processor_id).__name__}: {processor_id!r}"
            )
        n = self.processor_count()
        if not (0 <= processor_id < n):
            raise ValueError(f"{name} out of range [0, {n - 1}], got {processor_id}")

    def _require_coordinates(self, x: int, y: int) -> None:
        for name, val, limit in (("x", x, self.cols), ("y", y, self.rows)):
            if isinstance(val, bool) or not isinstance(val, int):
                raise ValueError(
                    f"{name} must be int, got {type(val).__name__}: {val!r}"
                )
            if not (0 <= val < limit):
                raise ValueError(f"{name} out of range [0, {limit - 1}], got {val}")

    def _require_volume(self, volume: float) -> None:
        if isinstance(volume, bool) or not isinstance(volume, (int, float)):
            raise ValueError(
                f"communication_volume must be numeric, "
                f"got {type(volume).__name__}: {volume!r}"
            )
        if not math.isfinite(volume):
            raise ValueError(f"communication_volume must be finite, got {volume}")
        if volume < 0:
            raise ValueError(f"communication_volume must be non-negative, got {volume}")
