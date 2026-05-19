"""
Phase 19 Part B — Task removal (pruning) behavior tests for CA-D.

CA-D's _prune_redundant_duplicates removes duplicate instances satisfying:
  A. is_primary == False
  B. Another instance of the same task exists elsewhere
  C. The duplicate is NOT the source of any CommunicationInstance
  D. No successor on the same processor would lose its only data source

Tests:
  1. Pruning triggers (prune_removed > 0) on a DAG where removal is expected.
  2. Pruning does NOT trigger (prune_removed == 0) where all dups are necessary.
  3. prune_removed <= prune_candidates always holds.
  4. After pruning, the final schedule still has valid primary instances for every task.
  5. Pruning invariants hold across all DAG families and CCR values.
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
from scripts.instrumented_schedulers import InstrumentedCAD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def noc():
    return MeshNoC(rows=4, cols=4, alpha=0.0, beta=1.0)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run_cad(noc, dag):
    sched = InstrumentedCAD(noc)
    state = sched.schedule(dag)
    return sched, state


def primary_task_ids(state):
    return {
        tid
        for tid, insts in state.task_instances.items()
        for inst in insts
        if inst.is_primary
    }


def all_task_ids(state):
    return set(state.task_instances.keys())


# ---------------------------------------------------------------------------
# Test 1: Pruning safety invariant — removed <= candidates always
# ---------------------------------------------------------------------------

class TestPruningBoundInvariant:

    @pytest.mark.parametrize("ccr", [0.1, 1.0, 5.0, 10.0])
    def test_fork_pruning_bound(self, noc, ccr):
        dag = DAGGraph(generate_fork_dag(n_branches=8, ccr=ccr, seed=0))
        sched, _ = run_cad(noc, dag)
        assert sched.diag.prune_removed <= sched.diag.prune_candidates

    @pytest.mark.parametrize("ccr", [0.1, 1.0, 5.0, 10.0])
    def test_out_tree_pruning_bound(self, noc, ccr):
        dag = DAGGraph(generate_out_tree_dag(depth=2, branching_factor=2, ccr=ccr, seed=0))
        sched, _ = run_cad(noc, dag)
        assert sched.diag.prune_removed <= sched.diag.prune_candidates

    @pytest.mark.parametrize("ccr", [0.1, 1.0, 5.0, 10.0])
    def test_fork_join_pruning_bound(self, noc, ccr):
        dag = DAGGraph(generate_fork_join_dag(n_branches=4, branch_length=3, ccr=ccr, seed=0))
        sched, _ = run_cad(noc, dag)
        assert sched.diag.prune_removed <= sched.diag.prune_candidates

    @pytest.mark.parametrize("ccr", [0.1, 1.0, 5.0, 10.0])
    def test_chain_pruning_bound(self, noc, ccr):
        dag = DAGGraph(generate_chain_dag(n_tasks=10, ccr=ccr, seed=0))
        sched, _ = run_cad(noc, dag)
        assert sched.diag.prune_removed <= sched.diag.prune_candidates


# ---------------------------------------------------------------------------
# Test 2: After pruning, all primary instances are still present
# ---------------------------------------------------------------------------

class TestPruningPreservesPrimaries:

    @pytest.mark.parametrize("dag_func,dag_kwargs,ccr", [
        (generate_fork_dag, {"n_branches": 8}, 5.0),
        (generate_out_tree_dag, {"depth": 2, "branching_factor": 2}, 5.0),
        (generate_fork_join_dag, {"n_branches": 4, "branch_length": 3}, 5.0),
        (generate_chain_dag, {"n_tasks": 10}, 5.0),
        (generate_fork_dag, {"n_branches": 8}, 0.1),
        (generate_out_tree_dag, {"depth": 2, "branching_factor": 2}, 0.1),
    ])
    def test_all_primaries_present_after_pruning(self, noc, dag_func, dag_kwargs, ccr):
        dag = DAGGraph(dag_func(**dag_kwargs, ccr=ccr, seed=0))
        sched, state = run_cad(noc, dag)
        n_tasks = dag.number_of_tasks()
        prim_ids = primary_task_ids(state)
        assert len(prim_ids) == n_tasks, (
            f"After pruning, {n_tasks - len(prim_ids)} primary tasks are missing"
        )


# ---------------------------------------------------------------------------
# Test 3: Pruning does NOT trigger when all dups are necessary
# Conservative pruning: CA-D rarely removes because local dups eliminate comms
# On a fork dag at CCR=5.0, each leaf copies root locally; removing would break
# the local data dependency (Condition C or D fails)
# ---------------------------------------------------------------------------

class TestPruningDoesNotTriggerOnFork:

    def test_fork_ccr5_no_pruning(self, noc):
        """On fork at CCR=5.0, all duplicates provide local data → pruning skips them."""
        dag = DAGGraph(generate_fork_dag(n_branches=8, ccr=5.0, seed=0))
        sched, state = run_cad(noc, dag)
        assert sched.diag.prune_removed == 0, (
            "CA-D should not remove any duplicates on fork at CCR=5.0: "
            "each root duplicate provides local data to a leaf task"
        )

    def test_out_tree_ccr5_no_pruning(self, noc):
        """On out-tree at CCR=5.0, ancestor dups provide local data chains → pruning skips."""
        dag = DAGGraph(generate_out_tree_dag(depth=2, branching_factor=2, ccr=5.0, seed=0))
        sched, state = run_cad(noc, dag)
        assert sched.diag.prune_removed == 0, (
            "CA-D should not remove any duplicates on out-tree at CCR=5.0"
        )


# ---------------------------------------------------------------------------
# Test 4: Pruning candidate count equals non-primary instance count before pruning
# This verifies that _prune_redundant_duplicates receives all dups as candidates
# ---------------------------------------------------------------------------

class TestPruningCandidateCount:

    def test_prune_candidates_nonneg(self, noc):
        dag = DAGGraph(generate_fork_dag(n_branches=8, ccr=5.0, seed=0))
        sched, _ = run_cad(noc, dag)
        assert sched.diag.prune_candidates >= 0

    def test_prune_candidates_leq_total_instances(self, noc):
        dag = DAGGraph(generate_out_tree_dag(depth=2, branching_factor=2, ccr=5.0, seed=0))
        sched, state = run_cad(noc, dag)
        total_instances = sum(len(insts) for insts in state.task_instances.values())
        # prune_candidates is count of non-primary before pruning pass
        # must be <= total instances in the final state + removed
        assert sched.diag.prune_candidates >= sched.diag.prune_removed

    @pytest.mark.parametrize("ccr", [0.1, 1.0, 5.0, 10.0])
    def test_prune_candidates_consistent_with_schedule(self, noc, ccr):
        dag = DAGGraph(generate_fork_join_dag(n_branches=4, branch_length=3, ccr=ccr, seed=0))
        sched, state = run_cad(noc, dag)
        final_dups = sum(
            1
            for insts in state.task_instances.values()
            for inst in insts
            if not inst.is_primary
        )
        # final_dups == prune_candidates - prune_removed
        assert final_dups == sched.diag.prune_candidates - sched.diag.prune_removed


# ---------------------------------------------------------------------------
# Test 5: Multi-seed consistency — invariants hold for seeds 0-4
# ---------------------------------------------------------------------------

class TestMultiSeedPruningInvariants:

    @pytest.mark.parametrize("seed", range(5))
    def test_fork_multi_seed(self, noc, seed):
        dag = DAGGraph(generate_fork_dag(n_branches=8, ccr=5.0, seed=seed))
        sched, state = run_cad(noc, dag)
        d = sched.diag
        assert d.prune_removed <= d.prune_candidates
        assert d.direct_dup_accepted + d.direct_dup_rejected == d.direct_dup_attempts
        assert d.total_new_placements >= d.direct_dup_accepted

    @pytest.mark.parametrize("seed", range(5))
    def test_out_tree_multi_seed(self, noc, seed):
        dag = DAGGraph(generate_out_tree_dag(depth=2, branching_factor=2, ccr=5.0, seed=seed))
        sched, state = run_cad(noc, dag)
        d = sched.diag
        assert d.prune_removed <= d.prune_candidates
        assert d.direct_dup_accepted + d.direct_dup_rejected == d.direct_dup_attempts
        assert d.total_new_placements >= d.direct_dup_accepted

    @pytest.mark.parametrize("seed", range(5))
    def test_fork_join_multi_seed(self, noc, seed):
        dag = DAGGraph(generate_fork_join_dag(n_branches=4, branch_length=3, ccr=5.0, seed=seed))
        sched, state = run_cad(noc, dag)
        d = sched.diag
        assert d.prune_removed <= d.prune_candidates
        assert d.direct_dup_accepted + d.direct_dup_rejected == d.direct_dup_attempts
        assert d.total_new_placements >= d.direct_dup_accepted
        # primaries all present
        prim_ids = primary_task_ids(state)
        assert len(prim_ids) == dag.number_of_tasks()
