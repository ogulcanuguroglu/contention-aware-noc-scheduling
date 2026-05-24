"""
Tests for src/noc.py.

Covers: construction, processor ID mapping, processors(), neighbors(),
all_directed_links(), XY routing, route_processor_sequence(),
hop_count and Manhattan distance, communication_duration, and 8x8 sanity.
Implemented in Phase 3.
"""

import pytest

from src.models import Link
from src.noc import MeshNoC


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_4x4() -> MeshNoC:
    return MeshNoC(rows=4, cols=4)


def make_2x3() -> MeshNoC:
    return MeshNoC(rows=2, cols=3)


# ---------------------------------------------------------------------------
# 1. Construction and basic properties
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_default_alpha_beta(self):
        noc = MeshNoC(rows=4, cols=4)
        assert noc.alpha == pytest.approx(1.0)
        assert noc.beta == pytest.approx(1.0)

    def test_custom_alpha_beta(self):
        noc = MeshNoC(rows=2, cols=3, alpha=0.5, beta=2.0)
        assert noc.alpha == pytest.approx(0.5)
        assert noc.beta == pytest.approx(2.0)

    def test_rows_cols_properties(self):
        noc = MeshNoC(rows=3, cols=5)
        assert noc.rows == 3
        assert noc.cols == 5

    def test_processor_count_4x4(self):
        assert make_4x4().processor_count() == 16

    def test_processor_count_2x3(self):
        assert make_2x3().processor_count() == 6

    def test_processor_ids(self):
        noc = make_4x4()
        assert noc.processor_ids() == list(range(16))

    def test_rejects_zero_rows(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=0, cols=4)

    def test_rejects_zero_cols(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols=0)

    def test_rejects_negative_rows(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=-1, cols=4)

    def test_rejects_negative_alpha(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols=4, alpha=-0.5)

    def test_rejects_negative_beta(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols=4, beta=-1.0)

    def test_zero_alpha_beta_allowed(self):
        noc = MeshNoC(rows=2, cols=2, alpha=0.0, beta=0.0)
        assert noc.alpha == 0.0
        assert noc.beta == 0.0

    def test_1x1_mesh(self):
        noc = MeshNoC(rows=1, cols=1)
        assert noc.processor_count() == 1

    def test_rejects_bool_rows(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=True, cols=4)  # type: ignore[arg-type]

    def test_rejects_bool_cols(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols=True)  # type: ignore[arg-type]

    def test_rejects_float_rows(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4.0, cols=4)  # type: ignore[arg-type]

    def test_rejects_float_cols(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols=4.0)  # type: ignore[arg-type]

    def test_rejects_string_rows(self):
        with pytest.raises(ValueError):
            MeshNoC(rows="4", cols=4)  # type: ignore[arg-type]

    def test_rejects_string_cols(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols="4")  # type: ignore[arg-type]

    def test_rejects_nan_alpha(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols=4, alpha=float("nan"))

    def test_rejects_infinity_alpha(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols=4, alpha=float("inf"))

    def test_rejects_nan_beta(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols=4, beta=float("nan"))

    def test_rejects_infinity_beta(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols=4, beta=float("inf"))

    def test_rejects_bool_alpha(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols=4, alpha=True)  # type: ignore[arg-type]

    def test_rejects_bool_beta(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols=4, beta=False)  # type: ignore[arg-type]

    def test_rejects_string_alpha(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols=4, alpha="1.0")  # type: ignore[arg-type]

    def test_rejects_string_beta(self):
        with pytest.raises(ValueError):
            MeshNoC(rows=4, cols=4, beta="0.5")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Processor ID mapping
# ---------------------------------------------------------------------------

class TestProcessorIDMapping:
    def test_to_coordinates_top_left(self):
        assert make_4x4().to_coordinates(0) == (0, 0)

    def test_to_coordinates_top_right(self):
        assert make_4x4().to_coordinates(3) == (3, 0)

    def test_to_coordinates_bottom_left(self):
        assert make_4x4().to_coordinates(12) == (0, 3)

    def test_to_coordinates_bottom_right(self):
        assert make_4x4().to_coordinates(15) == (3, 3)

    def test_to_coordinates_middle(self):
        # pid=5 in 4x4: x=5%4=1, y=5//4=1
        assert make_4x4().to_coordinates(5) == (1, 1)

    def test_to_processor_id_origin(self):
        assert make_4x4().to_processor_id(0, 0) == 0

    def test_to_processor_id_top_right(self):
        assert make_4x4().to_processor_id(3, 0) == 3

    def test_to_processor_id_bottom_left(self):
        assert make_4x4().to_processor_id(0, 3) == 12

    def test_to_processor_id_bottom_right(self):
        assert make_4x4().to_processor_id(3, 3) == 15

    def test_roundtrip_all_processors(self):
        noc = make_4x4()
        for pid in noc.processor_ids():
            x, y = noc.to_coordinates(pid)
            assert noc.to_processor_id(x, y) == pid

    def test_rejects_out_of_range_processor_id(self):
        with pytest.raises(ValueError):
            make_4x4().to_coordinates(16)

    def test_rejects_negative_processor_id(self):
        with pytest.raises(ValueError):
            make_4x4().to_coordinates(-1)

    def test_rejects_bool_processor_id(self):
        with pytest.raises(ValueError):
            make_4x4().to_coordinates(True)

    def test_rejects_out_of_range_x(self):
        with pytest.raises(ValueError):
            make_4x4().to_processor_id(4, 0)

    def test_rejects_out_of_range_y(self):
        with pytest.raises(ValueError):
            make_4x4().to_processor_id(0, 4)

    def test_2x3_mapping(self):
        noc = make_2x3()
        # 2 rows, 3 cols: pid = y*3 + x
        assert noc.to_coordinates(0) == (0, 0)
        assert noc.to_coordinates(2) == (2, 0)
        assert noc.to_coordinates(3) == (0, 1)
        assert noc.to_coordinates(5) == (2, 1)


# ---------------------------------------------------------------------------
# 3. processors()
# ---------------------------------------------------------------------------

class TestProcessors:
    def test_returns_all_processors(self):
        noc = make_4x4()
        procs = noc.processors()
        assert len(procs) == 16

    def test_processor_ids_match(self):
        noc = make_4x4()
        procs = noc.processors()
        ids = [p.processor_id for p in procs]
        assert ids == list(range(16))

    def test_coordinates_correct(self):
        noc = make_4x4()
        procs = noc.processors()
        for p in procs:
            x, y = noc.to_coordinates(p.processor_id)
            assert p.x == x
            assert p.y == y

    def test_1x1_processor(self):
        noc = MeshNoC(rows=1, cols=1)
        procs = noc.processors()
        assert len(procs) == 1
        assert procs[0].processor_id == 0
        assert procs[0].x == 0
        assert procs[0].y == 0


# ---------------------------------------------------------------------------
# 4. is_valid_processor and neighbors()
# ---------------------------------------------------------------------------

class TestNeighbors:
    def test_is_valid_processor_valid(self):
        noc = make_4x4()
        assert noc.is_valid_processor(0) is True
        assert noc.is_valid_processor(15) is True

    def test_is_valid_processor_out_of_range(self):
        assert make_4x4().is_valid_processor(16) is False

    def test_is_valid_processor_negative(self):
        assert make_4x4().is_valid_processor(-1) is False

    def test_is_valid_processor_bool_false(self):
        assert make_4x4().is_valid_processor(True) is False
        assert make_4x4().is_valid_processor(False) is False

    def test_is_valid_processor_float(self):
        assert make_4x4().is_valid_processor(1.0) is False  # type: ignore[arg-type]

    def test_corner_top_left_neighbors(self):
        # pid=0 (x=0,y=0): right=1, down=4
        assert make_4x4().neighbors(0) == [1, 4]

    def test_corner_top_right_neighbors(self):
        # pid=3 (x=3,y=0): left=2, down=7
        assert make_4x4().neighbors(3) == [2, 7]

    def test_corner_bottom_left_neighbors(self):
        # pid=12 (x=0,y=3): right=13, up=8
        assert make_4x4().neighbors(12) == [13, 8]

    def test_corner_bottom_right_neighbors(self):
        # pid=15 (x=3,y=3): left=14, up=11
        assert make_4x4().neighbors(15) == [14, 11]

    def test_edge_top_middle_neighbors(self):
        # pid=1 (x=1,y=0): left=0, right=2, down=5
        assert make_4x4().neighbors(1) == [0, 2, 5]

    def test_edge_left_middle_neighbors(self):
        # pid=4 (x=0,y=1): right=5, up=0, down=8
        assert make_4x4().neighbors(4) == [5, 0, 8]

    def test_interior_neighbors(self):
        # pid=5 (x=1,y=1): left=4, right=6, up=1, down=9
        assert make_4x4().neighbors(5) == [4, 6, 1, 9]

    def test_interior_neighbors_pid10(self):
        # pid=10 (x=2,y=2): left=9, right=11, up=6, down=14
        assert make_4x4().neighbors(10) == [9, 11, 6, 14]

    def test_neighbors_count_corner(self):
        assert len(make_4x4().neighbors(0)) == 2

    def test_neighbors_count_edge(self):
        assert len(make_4x4().neighbors(1)) == 3

    def test_neighbors_count_interior(self):
        assert len(make_4x4().neighbors(5)) == 4

    def test_1x1_has_no_neighbors(self):
        noc = MeshNoC(rows=1, cols=1)
        assert noc.neighbors(0) == []

    def test_rejects_invalid_processor_id(self):
        with pytest.raises(ValueError):
            make_4x4().neighbors(16)


# ---------------------------------------------------------------------------
# 5. all_directed_links()
# ---------------------------------------------------------------------------

class TestAllDirectedLinks:
    def test_count_4x4(self):
        noc = make_4x4()
        # 2 * (rows*(cols-1) + cols*(rows-1)) = 2*(4*3 + 4*3) = 48
        links = noc.all_directed_links()
        assert len(links) == 48

    def test_count_2x3(self):
        noc = make_2x3()
        # 2*(2*(3-1) + 3*(2-1)) = 2*(4+3) = 14
        links = noc.all_directed_links()
        assert len(links) == 14

    def test_count_1x1(self):
        noc = MeshNoC(rows=1, cols=1)
        assert noc.all_directed_links() == []

    def test_all_are_link_instances(self):
        for link in make_4x4().all_directed_links():
            assert isinstance(link, Link)

    def test_no_self_links(self):
        for link in make_4x4().all_directed_links():
            assert link.source_processor != link.destination_processor

    def test_all_processors_valid(self):
        noc = make_4x4()
        for link in noc.all_directed_links():
            assert noc.is_valid_processor(link.source_processor)
            assert noc.is_valid_processor(link.destination_processor)

    def test_both_directions_present(self):
        noc = make_4x4()
        link_set = set(noc.all_directed_links())
        # For every link (a,b), (b,a) must also exist
        for link in list(link_set):
            reverse = Link(link.destination_processor, link.source_processor)
            assert reverse in link_set

    def test_no_duplicate_links(self):
        links = make_4x4().all_directed_links()
        assert len(links) == len(set(links))


# ---------------------------------------------------------------------------
# 6. XY routing: get_route()
# ---------------------------------------------------------------------------

class TestGetRoute:
    def test_self_route_empty(self):
        assert make_4x4().get_route(0, 0) == []

    def test_single_hop_right(self):
        # 0 -> 1 (x: 0->1, y unchanged)
        route = make_4x4().get_route(0, 1)
        assert route == [Link(0, 1)]

    def test_single_hop_down(self):
        # 0 -> 4 (y: 0->1)
        route = make_4x4().get_route(0, 4)
        assert route == [Link(0, 4)]

    def test_single_hop_left(self):
        # 1 -> 0
        route = make_4x4().get_route(1, 0)
        assert route == [Link(1, 0)]

    def test_single_hop_up(self):
        # 4 -> 0
        route = make_4x4().get_route(4, 0)
        assert route == [Link(4, 0)]

    def test_two_hop_x_then_y(self):
        # 0 (0,0) -> 5 (1,1): right then down
        route = make_4x4().get_route(0, 5)
        assert route == [Link(0, 1), Link(1, 5)]

    def test_diagonal_0_to_15(self):
        # (0,0) -> (3,3): 3 right + 3 down = 6 hops
        route = make_4x4().get_route(0, 15)
        assert len(route) == 6
        expected = [
            Link(0, 1), Link(1, 2), Link(2, 3),   # X phase
            Link(3, 7), Link(7, 11), Link(11, 15), # Y phase
        ]
        assert route == expected

    def test_diagonal_15_to_0(self):
        # (3,3) -> (0,0): 3 left + 3 up = 6 hops
        route = make_4x4().get_route(15, 0)
        assert len(route) == 6
        expected = [
            Link(15, 14), Link(14, 13), Link(13, 12), # X phase
            Link(12, 8), Link(8, 4), Link(4, 0),       # Y phase
        ]
        assert route == expected

    def test_pure_x_route(self):
        # 0 -> 3: move only in X
        route = make_4x4().get_route(0, 3)
        assert route == [Link(0, 1), Link(1, 2), Link(2, 3)]

    def test_pure_y_route(self):
        # 0 -> 12: move only in Y
        route = make_4x4().get_route(0, 12)
        assert route == [Link(0, 4), Link(4, 8), Link(8, 12)]

    def test_route_is_contiguous(self):
        noc = make_4x4()
        route = noc.get_route(0, 15)
        for i in range(len(route) - 1):
            assert route[i].destination_processor == route[i + 1].source_processor

    def test_route_starts_at_src(self):
        noc = make_4x4()
        route = noc.get_route(2, 13)
        assert route[0].source_processor == 2

    def test_route_ends_at_dst(self):
        noc = make_4x4()
        route = noc.get_route(2, 13)
        assert route[-1].destination_processor == 13

    def test_all_links_are_neighbors(self):
        noc = make_4x4()
        route = noc.get_route(0, 15)
        for link in route:
            assert link.destination_processor in noc.neighbors(link.source_processor)

    def test_rejects_invalid_src(self):
        with pytest.raises(ValueError):
            make_4x4().get_route(16, 0)

    def test_rejects_invalid_dst(self):
        with pytest.raises(ValueError):
            make_4x4().get_route(0, 16)


# ---------------------------------------------------------------------------
# 7. route_processor_sequence()
# ---------------------------------------------------------------------------

class TestRouteProcessorSequence:
    def test_self_sequence(self):
        assert make_4x4().route_processor_sequence(0, 0) == [0]

    def test_sequence_0_to_1(self):
        assert make_4x4().route_processor_sequence(0, 1) == [0, 1]

    def test_sequence_0_to_5(self):
        # (0,0) -> (1,1): [0, 1, 5]
        assert make_4x4().route_processor_sequence(0, 5) == [0, 1, 5]

    def test_sequence_0_to_15(self):
        assert make_4x4().route_processor_sequence(0, 15) == [0, 1, 2, 3, 7, 11, 15]

    def test_sequence_15_to_0(self):
        assert make_4x4().route_processor_sequence(15, 0) == [15, 14, 13, 12, 8, 4, 0]

    def test_sequence_starts_at_src(self):
        noc = make_4x4()
        seq = noc.route_processor_sequence(3, 12)
        assert seq[0] == 3

    def test_sequence_ends_at_dst(self):
        noc = make_4x4()
        seq = noc.route_processor_sequence(3, 12)
        assert seq[-1] == 12

    def test_sequence_length_equals_hops_plus_one(self):
        noc = make_4x4()
        for src, dst in [(0, 15), (3, 12), (5, 10), (0, 0)]:
            seq = noc.route_processor_sequence(src, dst)
            assert len(seq) == noc.hop_count(src, dst) + 1


# ---------------------------------------------------------------------------
# 8. hop_count() and manhattan_distance()
# ---------------------------------------------------------------------------

class TestHopCountAndDistance:
    def test_self_hop_count(self):
        assert make_4x4().hop_count(0, 0) == 0

    def test_adjacent_hop_count(self):
        assert make_4x4().hop_count(0, 1) == 1
        assert make_4x4().hop_count(0, 4) == 1

    def test_diagonal_hop_count(self):
        assert make_4x4().hop_count(0, 15) == 6

    def test_hop_count_equals_manhattan_distance(self):
        noc = make_4x4()
        for src in range(16):
            for dst in range(16):
                assert noc.hop_count(src, dst) == noc.manhattan_distance(src, dst)

    def test_manhattan_self(self):
        assert make_4x4().manhattan_distance(5, 5) == 0

    def test_manhattan_symmetric(self):
        noc = make_4x4()
        assert noc.manhattan_distance(0, 15) == noc.manhattan_distance(15, 0)

    def test_manhattan_0_to_15(self):
        assert make_4x4().manhattan_distance(0, 15) == 6

    def test_manhattan_adjacent_x(self):
        assert make_4x4().manhattan_distance(0, 1) == 1

    def test_manhattan_adjacent_y(self):
        assert make_4x4().manhattan_distance(0, 4) == 1

    def test_manhattan_5_to_10(self):
        # 5=(1,1), 10=(2,2): |2-1|+|2-1|=2
        assert make_4x4().manhattan_distance(5, 10) == 2

    def test_rejects_invalid_processor(self):
        with pytest.raises(ValueError):
            make_4x4().hop_count(0, 16)


# ---------------------------------------------------------------------------
# 9. communication_duration()
# ---------------------------------------------------------------------------

class TestCommunicationDuration:
    def test_local_communication_zero(self):
        noc = make_4x4()
        assert noc.communication_duration(0, 0, 10.0) == pytest.approx(0.0)

    def test_local_ignores_volume(self):
        noc = make_4x4()
        assert noc.communication_duration(5, 5, 999.0) == pytest.approx(0.0)

    def test_one_hop_default_coefficients(self):
        # alpha=1, beta=1, hops=1, volume=5 -> 1*1 + 1*5 = 6
        noc = make_4x4()
        assert noc.communication_duration(0, 1, 5.0) == pytest.approx(6.0)

    def test_formula_alpha_hops_plus_beta_volume(self):
        noc = MeshNoC(rows=4, cols=4, alpha=2.0, beta=3.0)
        # 0->15: hops=6, volume=4 -> 2*6 + 3*4 = 12+12 = 24
        assert noc.communication_duration(0, 15, 4.0) == pytest.approx(24.0)

    def test_zero_volume(self):
        # alpha=1, beta=1, hops=1, volume=0 -> 1
        noc = make_4x4()
        assert noc.communication_duration(0, 1, 0.0) == pytest.approx(1.0)

    def test_zero_alpha(self):
        noc = MeshNoC(rows=4, cols=4, alpha=0.0, beta=1.0)
        assert noc.communication_duration(0, 15, 5.0) == pytest.approx(5.0)

    def test_zero_beta(self):
        noc = MeshNoC(rows=4, cols=4, alpha=1.0, beta=0.0)
        # hops=6, volume=100 -> 6+0=6
        assert noc.communication_duration(0, 15, 100.0) == pytest.approx(6.0)

    def test_zero_both_coefficients(self):
        noc = MeshNoC(rows=4, cols=4, alpha=0.0, beta=0.0)
        assert noc.communication_duration(0, 15, 100.0) == pytest.approx(0.0)

    def test_rejects_negative_volume(self):
        with pytest.raises(ValueError):
            make_4x4().communication_duration(0, 1, -1.0)

    def test_rejects_nan_volume(self):
        with pytest.raises(ValueError):
            make_4x4().communication_duration(0, 1, float("nan"))

    def test_rejects_inf_volume(self):
        with pytest.raises(ValueError):
            make_4x4().communication_duration(0, 1, float("inf"))

    def test_rejects_bool_volume(self):
        with pytest.raises(ValueError):
            make_4x4().communication_duration(0, 1, True)  # type: ignore[arg-type]

    def test_rejects_string_volume(self):
        with pytest.raises(ValueError):
            make_4x4().communication_duration(0, 1, "5")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 10. 8x8 sanity checks
# ---------------------------------------------------------------------------

class TestLargerMesh:
    def test_8x8_processor_count(self):
        noc = MeshNoC(rows=8, cols=8)
        assert noc.processor_count() == 64

    def test_8x8_link_count(self):
        noc = MeshNoC(rows=8, cols=8)
        # 2*(8*7 + 8*7) = 2*112 = 224
        assert len(noc.all_directed_links()) == 224

    def test_8x8_corner_to_corner_hops(self):
        noc = MeshNoC(rows=8, cols=8)
        # (0,0)=0 to (7,7)=63: 7+7=14 hops
        assert noc.hop_count(0, 63) == 14

    def test_8x8_route_length(self):
        noc = MeshNoC(rows=8, cols=8)
        assert len(noc.get_route(0, 63)) == 14

    def test_8x8_route_sequence_length(self):
        noc = MeshNoC(rows=8, cols=8)
        assert len(noc.route_processor_sequence(0, 63)) == 15

    def test_8x8_communication_duration(self):
        noc = MeshNoC(rows=8, cols=8, alpha=1.0, beta=0.5)
        # hops=14, volume=10: 1*14 + 0.5*10 = 19
        assert noc.communication_duration(0, 63, 10.0) == pytest.approx(19.0)

    def test_8x8_all_routes_acyclic(self):
        noc = MeshNoC(rows=8, cols=8)
        # spot-check several routes for no repeated processors
        for src, dst in [(0, 63), (63, 0), (7, 56), (56, 7), (27, 36)]:
            seq = noc.route_processor_sequence(src, dst)
            assert len(seq) == len(set(seq)), f"cycle in route {src}->{dst}"
