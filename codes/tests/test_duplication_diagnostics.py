"""
Phase 19 Part B — Counter validity tests for InstrumentedCDLS and InstrumentedCAD.

Tests:
  1. Counters exist and are non-negative after schedule().
  2. accepted + rejected == attempts.
  3. accepted <= attempts.
  4. total_new_placements >= direct_dup_accepted.
  5. recursive_ancestor_placements == total_new_placements - direct_dup_accepted.
  6. prune_removed <= prune_candidates.
  7. Scheduling results (makespan, task instance count) are unchanged vs base schedulers.
  8. Counters reset between consecutive schedule() calls on same instance.
"""

import pytest
import networkx as nx

from src.models import DAGGraph
from src.noc import MeshNoC
from src.classical_dup_scheduler import ClassicalDuplicationScheduler
from src.proposed_scheduler import ProposedScheduler
from src.graph_families import (
    generate_chain_dag,
    generate_fork_dag,
    generate_out_tree_dag,
    generate_fork_join_dag,
)
from scripts.instrumented_schedulers import InstrumentedCDLS, InstrumentedCAD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def noc():
    return MeshNoC(rows=4, cols=4, alpha=0.0, beta=1.0)


@pytest.fixture
def fork_dag():
    g = generate_fork_dag(n_branches=8, ccr=5.0, seed=0)
    return DAGGraph(g)


@pytest.fixture
def out_tree_dag():
    g = generate_out_tree_dag(depth=2, branching_factor=2, ccr=5.0, seed=0)
    return DAGGraph(g)


@pytest.fixture
def fork_join_dag():
    g = generate_fork_join_dag(n_branches=4, branch_length=3, ccr=5.0, seed=0)
    return DAGGraph(g)


@pytest.fixture
def chain_dag():
    g = generate_chain_dag(n_tasks=10, ccr=1.0, seed=0)
    return DAGGraph(g)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_cdls(noc, dag):
    sched = InstrumentedCDLS(noc)
    state = sched.schedule(dag)
    return sched, state


def run_cad(noc, dag):
    sched = InstrumentedCAD(noc)
    state = sched.schedule(dag)
    return sched, state


def count_instances(state, is_primary):
    return sum(
        1
        for insts in state.task_instances.values()
        for inst in insts
        if inst.is_primary == is_primary
    )


# ---------------------------------------------------------------------------
# Test 1: Counters exist and are non-negative — CD-LS
# ---------------------------------------------------------------------------

class TestCounterValidityCDLS:

    def test_attributes_exist(self, noc, fork_dag):
        sched, _ = run_cdls(noc, fork_dag)
        assert hasattr(sched, "diag")
        diag = sched.diag
        for attr in [
            "direct_dup_attempts", "direct_dup_accepted", "direct_dup_rejected",
            "total_new_placements", "recursive_ancestor_placements",
            "prune_candidates", "prune_removed",
        ]:
            assert hasattr(diag, attr), f"missing attribute: {attr}"

    def test_non_negative(self, noc, fork_dag):
        sched, _ = run_cdls(noc, fork_dag)
        d = sched.diag
        assert d.direct_dup_attempts >= 0
        assert d.direct_dup_accepted >= 0
        assert d.direct_dup_rejected >= 0
        assert d.total_new_placements >= 0
        assert d.recursive_ancestor_placements >= 0
        assert d.prune_candidates >= 0
        assert d.prune_removed >= 0

    def test_accepted_plus_rejected_equals_attempts(self, noc, fork_dag):
        sched, _ = run_cdls(noc, fork_dag)
        d = sched.diag
        assert d.direct_dup_accepted + d.direct_dup_rejected == d.direct_dup_attempts

    def test_accepted_leq_attempts(self, noc, fork_dag):
        sched, _ = run_cdls(noc, fork_dag)
        d = sched.diag
        assert d.direct_dup_accepted <= d.direct_dup_attempts

    def test_total_placements_geq_accepted(self, noc, fork_dag):
        sched, _ = run_cdls(noc, fork_dag)
        d = sched.diag
        assert d.total_new_placements >= d.direct_dup_accepted

    def test_recursive_equals_total_minus_accepted(self, noc, fork_dag):
        sched, _ = run_cdls(noc, fork_dag)
        d = sched.diag
        assert d.recursive_ancestor_placements == max(0, d.total_new_placements - d.direct_dup_accepted)

    def test_cdls_has_zero_recursive(self, noc, fork_dag):
        """CD-LS does not perform recursive ancestor placement."""
        sched, _ = run_cdls(noc, fork_dag)
        assert sched.diag.recursive_ancestor_placements == 0

    def test_cdls_has_zero_prune(self, noc, fork_dag):
        """CD-LS has no pruning pass."""
        sched, _ = run_cdls(noc, fork_dag)
        assert sched.diag.prune_candidates == 0
        assert sched.diag.prune_removed == 0

    @pytest.mark.parametrize("dag_fixture", ["fork_dag", "out_tree_dag", "fork_join_dag", "chain_dag"])
    def test_non_negative_multiple_dags(self, request, noc, dag_fixture):
        dag = request.getfixturevalue(dag_fixture)
        sched, _ = run_cdls(noc, dag)
        d = sched.diag
        assert d.direct_dup_attempts >= 0
        assert d.direct_dup_accepted >= 0
        assert d.direct_dup_rejected >= 0
        assert d.total_new_placements >= 0
        assert d.direct_dup_accepted + d.direct_dup_rejected == d.direct_dup_attempts


# ---------------------------------------------------------------------------
# Test 2: Counters exist and are non-negative — CA-D
# ---------------------------------------------------------------------------

class TestCounterValidityCAD:

    def test_attributes_exist(self, noc, fork_dag):
        sched, _ = run_cad(noc, fork_dag)
        assert hasattr(sched, "diag")
        diag = sched.diag
        for attr in [
            "direct_dup_attempts", "direct_dup_accepted", "direct_dup_rejected",
            "total_new_placements", "recursive_ancestor_placements",
            "prune_candidates", "prune_removed",
        ]:
            assert hasattr(diag, attr), f"missing attribute: {attr}"

    def test_non_negative(self, noc, fork_dag):
        sched, _ = run_cad(noc, fork_dag)
        d = sched.diag
        assert d.direct_dup_attempts >= 0
        assert d.direct_dup_accepted >= 0
        assert d.direct_dup_rejected >= 0
        assert d.total_new_placements >= 0
        assert d.recursive_ancestor_placements >= 0
        assert d.prune_candidates >= 0
        assert d.prune_removed >= 0

    def test_accepted_plus_rejected_equals_attempts(self, noc, fork_dag):
        sched, _ = run_cad(noc, fork_dag)
        d = sched.diag
        assert d.direct_dup_accepted + d.direct_dup_rejected == d.direct_dup_attempts

    def test_accepted_leq_attempts(self, noc, fork_dag):
        sched, _ = run_cad(noc, fork_dag)
        d = sched.diag
        assert d.direct_dup_accepted <= d.direct_dup_attempts

    def test_total_placements_geq_accepted(self, noc, fork_dag):
        sched, _ = run_cad(noc, fork_dag)
        d = sched.diag
        assert d.total_new_placements >= d.direct_dup_accepted

    def test_recursive_equals_total_minus_accepted(self, noc, fork_dag):
        sched, _ = run_cad(noc, fork_dag)
        d = sched.diag
        assert d.recursive_ancestor_placements == max(0, d.total_new_placements - d.direct_dup_accepted)

    def test_prune_removed_leq_candidates(self, noc, fork_dag):
        sched, _ = run_cad(noc, fork_dag)
        d = sched.diag
        assert d.prune_removed <= d.prune_candidates

    @pytest.mark.parametrize("dag_fixture", ["fork_dag", "out_tree_dag", "fork_join_dag", "chain_dag"])
    def test_non_negative_multiple_dags(self, request, noc, dag_fixture):
        dag = request.getfixturevalue(dag_fixture)
        sched, _ = run_cad(noc, dag)
        d = sched.diag
        assert d.direct_dup_attempts >= 0
        assert d.direct_dup_accepted >= 0
        assert d.direct_dup_rejected >= 0
        assert d.total_new_placements >= 0
        assert d.direct_dup_accepted + d.direct_dup_rejected == d.direct_dup_attempts
        assert d.prune_removed <= d.prune_candidates


# ---------------------------------------------------------------------------
# Test 3: Scheduling results unchanged (vs. base schedulers)
# ---------------------------------------------------------------------------

class TestResultsUnchanged:

    def test_cdls_makespan_unchanged(self, noc, out_tree_dag):
        base_state = ClassicalDuplicationScheduler(noc).schedule(out_tree_dag)
        instr_sched, instr_state = run_cdls(noc, out_tree_dag)
        assert abs(
            instr_state.max_processor_finish_time() - base_state.max_processor_finish_time()
        ) < 1e-9

    def test_cad_makespan_unchanged(self, noc, out_tree_dag):
        base_state = ProposedScheduler(noc).schedule(out_tree_dag)
        instr_sched, instr_state = run_cad(noc, out_tree_dag)
        assert abs(
            instr_state.max_processor_finish_time() - base_state.max_processor_finish_time()
        ) < 1e-9

    def test_cdls_instance_count_unchanged(self, noc, fork_dag):
        base_state = ClassicalDuplicationScheduler(noc).schedule(fork_dag)
        _, instr_state = run_cdls(noc, fork_dag)
        base_dups = count_instances(base_state, is_primary=False)
        instr_dups = count_instances(instr_state, is_primary=False)
        assert base_dups == instr_dups

    def test_cad_instance_count_unchanged(self, noc, fork_dag):
        base_state = ProposedScheduler(noc).schedule(fork_dag)
        _, instr_state = run_cad(noc, fork_dag)
        base_dups = count_instances(base_state, is_primary=False)
        instr_dups = count_instances(instr_state, is_primary=False)
        assert base_dups == instr_dups

    @pytest.mark.parametrize("dag_fixture", ["fork_dag", "out_tree_dag", "fork_join_dag", "chain_dag"])
    def test_cdls_unchanged_multiple_dags(self, request, noc, dag_fixture):
        dag = request.getfixturevalue(dag_fixture)
        base_state = ClassicalDuplicationScheduler(noc).schedule(dag)
        _, instr_state = run_cdls(noc, dag)
        assert abs(
            instr_state.max_processor_finish_time() - base_state.max_processor_finish_time()
        ) < 1e-9

    @pytest.mark.parametrize("dag_fixture", ["fork_dag", "out_tree_dag", "fork_join_dag", "chain_dag"])
    def test_cad_unchanged_multiple_dags(self, request, noc, dag_fixture):
        dag = request.getfixturevalue(dag_fixture)
        base_state = ProposedScheduler(noc).schedule(dag)
        _, instr_state = run_cad(noc, dag)
        assert abs(
            instr_state.max_processor_finish_time() - base_state.max_processor_finish_time()
        ) < 1e-9


# ---------------------------------------------------------------------------
# Test 4: Counters reset between consecutive schedule() calls
# ---------------------------------------------------------------------------

class TestCounterReset:

    def test_cdls_resets_on_second_call(self, noc, fork_dag, chain_dag):
        sched = InstrumentedCDLS(noc)
        sched.schedule(fork_dag)
        first_attempts = sched.diag.direct_dup_attempts

        sched.schedule(chain_dag)
        second_attempts = sched.diag.direct_dup_attempts

        # chain_dag CCR=1.0 may have different attempt count than fork_dag CCR=5.0
        # The point is that diag was fully reset (not accumulated)
        base_chain = ClassicalDuplicationScheduler(noc)
        base_chain_sched = InstrumentedCDLS(noc)
        base_chain_sched.schedule(chain_dag)
        assert second_attempts == base_chain_sched.diag.direct_dup_attempts

    def test_cad_resets_on_second_call(self, noc, fork_dag, chain_dag):
        sched = InstrumentedCAD(noc)
        sched.schedule(fork_dag)

        sched.schedule(chain_dag)
        second_attempts = sched.diag.direct_dup_attempts

        fresh_sched = InstrumentedCAD(noc)
        fresh_sched.schedule(chain_dag)
        assert second_attempts == fresh_sched.diag.direct_dup_attempts

    def test_cdls_accepted_not_accumulated(self, noc, fork_dag):
        sched = InstrumentedCDLS(noc)
        sched.schedule(fork_dag)
        first_accepted = sched.diag.direct_dup_accepted

        sched.schedule(fork_dag)
        second_accepted = sched.diag.direct_dup_accepted

        assert second_accepted == first_accepted  # same DAG → same deterministic result

    def test_cad_accepted_not_accumulated(self, noc, out_tree_dag):
        sched = InstrumentedCAD(noc)
        sched.schedule(out_tree_dag)
        first_accepted = sched.diag.direct_dup_accepted

        sched.schedule(out_tree_dag)
        second_accepted = sched.diag.direct_dup_accepted

        assert second_accepted == first_accepted
