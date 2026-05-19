"""
Instrumented scheduler wrappers for Phase 19 duplication diagnostics.

These subclasses wrap ClassicalDuplicationScheduler (CD-LS) and ProposedScheduler
(CA-D) with lightweight diagnostic counters.  Scheduling behavior is NOT changed;
counters are added by overriding decision-point methods and using before/after
state snapshots.

Key design:
  - Each scheduler instance carries a DupDiagnostics object (self.diag).
  - self.diag is reset at the start of every schedule() call.
  - Counters are filled by overriding _evaluate_duplications (both schedulers)
    and _prune_redundant_duplicates (CA-D only).
  - No logic is duplicated from the parent classes; snapshot diffs are used.
  - The parent's _evaluate_duplications is called via super() so the actual
    scheduling result is always produced by the parent code.

Terminology used in counters:
  direct_dup_attempt : a direct predecessor of the current task was not already
      local to the candidate processor → a duplication evaluation was performed.
  direct_dup_accepted: the delta-EFT test accepted the duplication; a new
      duplicate instance appeared in the committed state for that predecessor.
  direct_dup_rejected: the delta-EFT test rejected the duplication; no new
      instance for that predecessor on that processor.
  total_new_placements: total NEW duplicate (task_id, processor_id) pairs added
      to the state by _evaluate_duplications (includes recursive ancestor
      placements triggered by CA-D's _place_recursive_duplicate).
  recursive_ancestor_placements: total_new_placements - direct_dup_accepted
      (proxy for how many extra ancestors CA-D placed beyond what a parent-only
      scheduler would have placed).
  prune_candidates: number of duplicate instances considered for removal.
  prune_removed: number actually removed.

Note on "critical parent" duplication:
  ProposedScheduler does NOT implement Sinnen-style critical-parent selection.
  It uses greedy recursive ancestor duplication of ALL beneficial predecessors.
  The docstring of proposed_scheduler.py explicitly states this.  The counters
  here reflect the greedy recursive implementation, not a critical-parent variant.
"""

from dataclasses import dataclass, field

from src.classical_dup_scheduler import ClassicalDuplicationScheduler
from src.proposed_scheduler import ProposedScheduler
from src.models import DAGGraph
from src.schedule_state import ScheduleState
from src.noc import MeshNoC


# ---------------------------------------------------------------------------
# Diagnostic dataclass
# ---------------------------------------------------------------------------

@dataclass
class DupDiagnostics:
    """Per-schedule accumulator of duplication diagnostic counters."""

    # Direct predecessor evaluations
    direct_dup_attempts: int = 0    # preds evaluated (not already local)
    direct_dup_accepted: int = 0    # pred placed → delta-EFT > threshold
    direct_dup_rejected: int = 0    # pred not placed → delta-EFT <= threshold

    # All placements (direct + recursive ancestors, CA-D only)
    total_new_placements: int = 0   # new (task_id, proc) dup pairs added per call
    recursive_ancestor_placements: int = 0  # computed post-schedule

    # Post-schedule pruning (CA-D only)
    prune_candidates: int = 0       # dup instances considered for removal
    prune_removed: int = 0          # dup instances actually removed

    def finalize(self) -> None:
        """Compute derived fields after schedule() completes."""
        self.recursive_ancestor_placements = max(
            0, self.total_new_placements - self.direct_dup_accepted
        )


# ---------------------------------------------------------------------------
# Shared snapshot helper
# ---------------------------------------------------------------------------

def _dup_key_set(state: ScheduleState) -> frozenset:
    """Return frozenset of (task_id, processor_id) for all non-primary instances."""
    return frozenset(
        (tid, inst.processor_id)
        for tid, insts in state.task_instances.items()
        for inst in insts
        if not inst.is_primary
    )


# ---------------------------------------------------------------------------
# Instrumented CD-LS
# ---------------------------------------------------------------------------

class InstrumentedCDLS(ClassicalDuplicationScheduler):
    """CD-LS with lightweight duplication-decision counters."""

    def __init__(self, noc: MeshNoC) -> None:
        super().__init__(noc)
        self.diag = DupDiagnostics()

    def schedule(self, dag: DAGGraph) -> ScheduleState:
        self.diag = DupDiagnostics()
        result = super().schedule(dag)
        self.diag.finalize()
        return result

    def _evaluate_duplications(
        self, dag: DAGGraph, candidate: ScheduleState,
        task_id: int, processor_id: int,
    ) -> tuple[float, float]:
        # Predecessors that are NOT already local → will be evaluated
        preds_to_eval = [
            p for p in sorted(dag.predecessors(task_id))
            if not candidate.has_task_instance(p, processor_id)
        ]
        self.diag.direct_dup_attempts += len(preds_to_eval)

        # State before parent call
        before_keys = _dup_key_set(candidate)

        # Delegate to parent (no logic duplication)
        result = super()._evaluate_duplications(dag, candidate, task_id, processor_id)

        # State after parent call
        after_keys = _dup_key_set(candidate)
        new_keys = after_keys - before_keys

        # Count per pred: was it placed on processor_id?
        for pred in preds_to_eval:
            if (pred, processor_id) in new_keys:
                self.diag.direct_dup_accepted += 1
            else:
                self.diag.direct_dup_rejected += 1

        self.diag.total_new_placements += len(new_keys)
        return result


# ---------------------------------------------------------------------------
# Instrumented CA-D
# ---------------------------------------------------------------------------

class InstrumentedCAD(ProposedScheduler):
    """CA-D with lightweight duplication-decision and pruning counters."""

    def __init__(self, noc: MeshNoC) -> None:
        super().__init__(noc)
        self.diag = DupDiagnostics()

    def schedule(self, dag: DAGGraph) -> ScheduleState:
        self.diag = DupDiagnostics()
        result = super().schedule(dag)
        self.diag.finalize()
        return result

    def _evaluate_duplications(
        self, dag: DAGGraph, candidate: ScheduleState,
        task_id: int, processor_id: int,
    ) -> tuple[float, float]:
        preds_to_eval = [
            p for p in sorted(dag.predecessors(task_id))
            if not candidate.has_task_instance(p, processor_id)
        ]
        self.diag.direct_dup_attempts += len(preds_to_eval)

        before_keys = _dup_key_set(candidate)

        result = super()._evaluate_duplications(dag, candidate, task_id, processor_id)

        after_keys = _dup_key_set(candidate)
        new_keys = after_keys - before_keys

        # A direct predecessor was "accepted" if it appears on processor_id.
        # Extra placements (new_keys - accepted) are recursive ancestors.
        for pred in preds_to_eval:
            if (pred, processor_id) in new_keys:
                self.diag.direct_dup_accepted += 1
            else:
                self.diag.direct_dup_rejected += 1

        self.diag.total_new_placements += len(new_keys)
        return result

    def _prune_redundant_duplicates(
        self, dag: DAGGraph, state: ScheduleState,
    ) -> ScheduleState:
        self.diag.prune_candidates = sum(
            1
            for insts in state.task_instances.values()
            for inst in insts
            if not inst.is_primary
        )

        result = super()._prune_redundant_duplicates(dag, state)

        after_count = sum(
            1
            for insts in result.task_instances.values()
            for inst in insts
            if not inst.is_primary
        )
        self.diag.prune_removed = self.diag.prune_candidates - after_count
        return result
