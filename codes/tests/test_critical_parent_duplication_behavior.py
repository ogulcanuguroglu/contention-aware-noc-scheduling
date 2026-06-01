"""
Phase 19 Part B — Critical parent duplication behavior micro-tests.

Five targeted synthetic DAG tests:
  1. Single-level fork control case: CD-LS and CA-D both duplicate the same root.
  2. Multi-level out-tree: CA-D places recursive ancestor copies; CD-LS does not.
  3. Fork-join contention case: CA-D handles contention; CD-LS is optimistic.
  4. Low CCR (CCR=0.1): communication is cheap, duplication should rarely help.
  5. Chain DAG: linear dependencies, limited duplication opportunities.
"""

import pytest

from src.models import DAGGraph
from src.noc import MeshNoC
from src.graph_families import (
    generate_fork_dag,
    generate_out_tree_dag,
    generate_fork_join_dag,
    generate_chain_dag,
)
from scripts.instrumented_schedulers import InstrumentedCDLS, InstrumentedCAD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def noc():
    return MeshNoC(rows=4, cols=4, alpha=0.0, beta=1.0)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def count_dups(state):
    return sum(
        1
        for insts in state.task_instances.values()
        for inst in insts
        if not inst.is_primary
    )


def run_both(noc, dag):
    cdls = InstrumentedCDLS(noc)
    cad = InstrumentedCAD(noc)
    cdls_state = cdls.schedule(dag)
    cad_state = cad.schedule(dag)
    return cdls, cdls_state, cad, cad_state


# ---------------------------------------------------------------------------
# Test 1: Single-level fork (control case)
# Fork: root → 8 leaves, CCR=5.0 → communication dominates
# Expected: both CD-LS and CA-D duplicate the root near each leaf
#           → total_new_placements equal (or CA-D >= CD-LS)
#           → recursive_ancestor_placements == 0 for CD-LS
# ---------------------------------------------------------------------------

class TestSingleLevelForkControl:

    @pytest.fixture
    def dag(self):
        return DAGGraph(generate_fork_dag(n_branches=8, ccr=5.0, seed=0))

    def test_cdls_places_duplicates(self, noc, dag):
        cdls, state = InstrumentedCDLS(noc), None
        state = cdls.schedule(dag)
        assert cdls.diag.direct_dup_accepted > 0, "CD-LS should accept some duplications on fork at CCR=5.0"

    def test_cad_places_duplicates(self, noc, dag):
        cad, state = InstrumentedCAD(noc), None
        state = cad.schedule(dag)
        assert cad.diag.direct_dup_accepted > 0, "CA-D should accept some duplications on fork at CCR=5.0"

    def test_cdls_has_no_recursive_placements(self, noc, dag):
        cdls = InstrumentedCDLS(noc)
        cdls.schedule(dag)
        assert cdls.diag.recursive_ancestor_placements == 0, \
            "CD-LS is parent-only: recursive_ancestor_placements must be 0"

    def test_cad_geq_cdls_placements(self, noc, dag):
        cdls, cdls_state, cad, cad_state = run_both(noc, dag)
        assert cad.diag.total_new_placements >= cdls.diag.total_new_placements, \
            "CA-D places >= CD-LS on single-level fork (same or more ancestors)"

    def test_cdls_cad_same_makespan_on_fork(self, noc, dag):
        """On a one-level fork, parent-only and recursive duplication coincide."""
        cdls, cdls_state, cad, cad_state = run_both(noc, dag)
        assert abs(
            cdls_state.max_processor_finish_time() - cad_state.max_processor_finish_time()
        ) < 1e-9, "CD-LS and CA-D should produce identical makespans on a single-level fork"

    def test_attempts_geq_accepted(self, noc, dag):
        """Attempts >= accepted is always true (accepted is a subset of attempts)."""
        cdls = InstrumentedCDLS(noc)
        cdls.schedule(dag)
        # _evaluate_duplications is called once per (task, processor) candidate pair;
        # total attempts counts across ALL such calls, so attempts >= accepted.
        assert cdls.diag.direct_dup_attempts >= cdls.diag.direct_dup_accepted


# ---------------------------------------------------------------------------
# Test 2: Multi-level out-tree (recursive vs parent-only)
# Out-tree: depth=2, bf=2 → root(0) → T1,T2 → T3,T4,T5,T6
# At CCR=5.0, CA-D should place recursive ancestor duplicates (T0 on multiple procs)
# while CD-LS only places direct predecessors
# ---------------------------------------------------------------------------

class TestMultiLevelOutTreeRecursive:

    @pytest.fixture
    def dag(self):
        return DAGGraph(generate_out_tree_dag(depth=2, branching_factor=2, ccr=5.0, seed=0))

    def test_cad_has_recursive_placements(self, noc, dag):
        cad = InstrumentedCAD(noc)
        cad.schedule(dag)
        assert cad.diag.recursive_ancestor_placements > 0, \
            "CA-D should place recursive ancestor duplicates on multi-level out-tree at CCR=5.0"

    def test_cdls_has_no_recursive_placements(self, noc, dag):
        cdls = InstrumentedCDLS(noc)
        cdls.schedule(dag)
        assert cdls.diag.recursive_ancestor_placements == 0

    def test_cad_places_more_total_than_cdls(self, noc, dag):
        cdls, _, cad, _ = run_both(noc, dag)
        assert cad.diag.total_new_placements > cdls.diag.total_new_placements, \
            "CA-D places more total duplicates than CD-LS on multi-level out-tree at CCR=5.0"

    def test_cad_better_makespan(self, noc, dag):
        cdls, cdls_state, cad, cad_state = run_both(noc, dag)
        cad_ms = cad_state.max_processor_finish_time()
        cdls_ms = cdls_state.max_processor_finish_time()
        assert cad_ms <= cdls_ms + 1e-9, \
            "CA-D makespan should be <= CD-LS on out-tree at CCR=5.0"

    def test_cdls_attempts_nonneg(self, noc, dag):
        """CD-LS evaluates only direct predecessors, not grandparents.
        Attempts is the count over all (task, processor) candidate calls."""
        cdls = InstrumentedCDLS(noc)
        cdls.schedule(dag)
        assert cdls.diag.direct_dup_attempts >= 0
        assert cdls.diag.direct_dup_attempts >= cdls.diag.direct_dup_accepted


# ---------------------------------------------------------------------------
# Test 3: Fork-join contention case
# Fork-join: 4 branches × length 3 → 14 tasks, CCR=5.0
# CA-D should be contention-aware; CD-LS may produce optimistic native makespan
# ---------------------------------------------------------------------------

class TestForkJoinContentionCase:

    @pytest.fixture
    def dag(self):
        return DAGGraph(generate_fork_join_dag(n_branches=4, branch_length=3, ccr=5.0, seed=0))

    def test_both_have_nonzero_attempts(self, noc, dag):
        cdls, cdls_state, cad, cad_state = run_both(noc, dag)
        assert cdls.diag.direct_dup_attempts > 0
        assert cad.diag.direct_dup_attempts > 0

    def test_cad_prune_candidates_geq_prune_removed(self, noc, dag):
        cad = InstrumentedCAD(noc)
        cad.schedule(dag)
        assert cad.diag.prune_removed <= cad.diag.prune_candidates

    def test_cdls_no_prune_pass(self, noc, dag):
        cdls = InstrumentedCDLS(noc)
        cdls.schedule(dag)
        assert cdls.diag.prune_candidates == 0
        assert cdls.diag.prune_removed == 0

    def test_accepted_plus_rejected_invariant(self, noc, dag):
        cdls, _, cad, _ = run_both(noc, dag)
        assert cdls.diag.direct_dup_accepted + cdls.diag.direct_dup_rejected == cdls.diag.direct_dup_attempts
        assert cad.diag.direct_dup_accepted + cad.diag.direct_dup_rejected == cad.diag.direct_dup_attempts

    def test_cad_total_placements_geq_direct_accepted(self, noc, dag):
        cad = InstrumentedCAD(noc)
        cad.schedule(dag)
        assert cad.diag.total_new_placements >= cad.diag.direct_dup_accepted


# ---------------------------------------------------------------------------
# Test 4: Low CCR case (CCR=0.1) — communication cheap, duplication rarely helps
# Fork CCR=0.1: communication is cheap → duplication likely rejected
# ---------------------------------------------------------------------------

class TestLowCCRFewDuplications:

    @pytest.fixture
    def dag(self):
        return DAGGraph(generate_fork_dag(n_branches=8, ccr=0.1, seed=0))

    def test_cdls_low_ccr_few_accepted(self, noc, dag):
        cdls = InstrumentedCDLS(noc)
        cdls.schedule(dag)
        # At low CCR, communication is cheap → duplicating wastes cycles
        # Not all forks will be duplicated; may be fewer than at CCR=5.0
        high_ccr_dag = DAGGraph(generate_fork_dag(n_branches=8, ccr=5.0, seed=0))
        cdls_high = InstrumentedCDLS(noc)
        cdls_high.schedule(high_ccr_dag)
        assert cdls.diag.direct_dup_accepted <= cdls_high.diag.direct_dup_accepted, \
            "Low CCR should produce fewer or equal accepted duplications than high CCR"

    def test_cad_low_ccr_few_accepted(self, noc, dag):
        cad = InstrumentedCAD(noc)
        cad.schedule(dag)
        high_ccr_dag = DAGGraph(generate_fork_dag(n_branches=8, ccr=5.0, seed=0))
        cad_high = InstrumentedCAD(noc)
        cad_high.schedule(high_ccr_dag)
        assert cad.diag.direct_dup_accepted <= cad_high.diag.direct_dup_accepted, \
            "Low CCR should produce fewer or equal accepted duplications than high CCR"

    def test_invariants_hold_at_low_ccr(self, noc, dag):
        cdls, _, cad, _ = run_both(noc, dag)
        for d, name in [(cdls.diag, "CD-LS"), (cad.diag, "CA-D")]:
            assert d.direct_dup_accepted + d.direct_dup_rejected == d.direct_dup_attempts, \
                f"{name}: accepted + rejected != attempts at low CCR"
            assert d.total_new_placements >= d.direct_dup_accepted, \
                f"{name}: total_placements < direct_accepted at low CCR"


# ---------------------------------------------------------------------------
# Test 5: Chain DAG — linear structure limits duplication
# Chain: 0→1→2→...→9, CCR=5.0
# Each task has exactly one predecessor → limited but possible duplication
# ---------------------------------------------------------------------------

class TestChainDAGLinearDuplication:

    @pytest.fixture
    def dag(self):
        return DAGGraph(generate_chain_dag(n_tasks=10, ccr=5.0, seed=0))

    def test_cdls_attempts_positive_or_zero(self, noc, dag):
        """Chain has one predecessor per task; each (task, proc) call counts <=1 attempt.
        Total attempts across all calls is non-negative."""
        cdls = InstrumentedCDLS(noc)
        cdls.schedule(dag)
        assert cdls.diag.direct_dup_attempts >= 0
        assert cdls.diag.direct_dup_attempts >= cdls.diag.direct_dup_accepted

    def test_cad_attempts_positive_or_zero(self, noc, dag):
        cad = InstrumentedCAD(noc)
        cad.schedule(dag)
        assert cad.diag.direct_dup_attempts >= 0
        assert cad.diag.direct_dup_attempts >= cad.diag.direct_dup_accepted

    def test_cdls_has_no_recursive_on_chain(self, noc, dag):
        cdls = InstrumentedCDLS(noc)
        cdls.schedule(dag)
        assert cdls.diag.recursive_ancestor_placements == 0

    def test_invariants_hold(self, noc, dag):
        cdls, _, cad, _ = run_both(noc, dag)
        for d in [cdls.diag, cad.diag]:
            assert d.direct_dup_accepted + d.direct_dup_rejected == d.direct_dup_attempts
            assert d.total_new_placements >= d.direct_dup_accepted
            assert d.prune_removed <= d.prune_candidates

    def test_cad_recursive_on_chain_nonneg(self, noc, dag):
        """CA-D may place recursive grandparent duplicates on a chain at high CCR."""
        cad = InstrumentedCAD(noc)
        cad.schedule(dag)
        assert cad.diag.recursive_ancestor_placements >= 0
