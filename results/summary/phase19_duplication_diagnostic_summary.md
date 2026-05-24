# Phase 19 — Duplication Diagnostic Summary

**Dataset:** 4 DAG families × 4 CCR values × 20 seeds = 320 cases per scheduler.
**Instrumentation:** InstrumentedCDLS and InstrumentedCAD (scripts/instrumented_schedulers.py).
Scheduling behavior is NOT changed by instrumentation; counters use before/after
frozenset snapshots of (task_id, processor_id) duplicate pairs.

## Counter Definitions

| Counter | Definition |
|---------|-----------|
| `direct_dup_attempts` | Total calls to evaluate a direct predecessor not already local, summed over all `_evaluate_duplications` invocations |
| `direct_dup_accepted` | Predecessor placements where delta-EFT > threshold (pred placed on target processor) |
| `direct_dup_rejected` | Predecessor evaluations where delta-EFT ≤ threshold (pred NOT placed) |
| `total_new_placements` | All new (task_id, proc_id) duplicate pairs added across the schedule, including recursive ancestors |
| `recursive_ancestor_placements` | `total_new_placements − direct_dup_accepted` (CA-D only; extra ancestors placed beyond direct predecessors) |
| `prune_candidates` | Non-primary instances considered by `_prune_redundant_duplicates` (CA-D only) |
| `prune_removed` | Instances actually removed by the pruning pass (CA-D only) |

## Mean Counters Per Case (over 20 seeds, all CCR combined)

| DAG family | Scheduler | Attempts | Accepted | Rejected | Total placements | Recursive | Prune candidates | Prune removed |
|------------|-----------|:--------:|:--------:|:--------:|:----------------:|:---------:|:----------------:|:-------------:|
| Chain | CD-LS | 135.0 | 78.8 | 56.3 | 78.8 | 0 | 0 | 0 |
| Chain | CA-D | 135.0 | 135.0 | 0.0 | 675.0 | 540.0 | 0 | 0 |
| Fork | CD-LS | 99.0 | 99.0 | 0.0 | 99.0 | 0 | 0 | 0 |
| Fork | CA-D | 99.0 | 99.0 | 0.0 | 99.0 | 0 | 7.0 | 0 |
| Out-tree | CD-LS | 90.0 | 59.8 | 30.3 | 59.8 | 0 | 0 | 0 |
| Out-tree | CA-D | 90.0 | 87.5 | 2.5 | 142.2 | 54.7 | 5.0 | 0 |
| Fork-join | CD-LS | 237.0 | 124.8 | 112.3 | 124.8 | 0 | 0 | 0 |
| Fork-join | CA-D | 237.0 | 198.1 | 38.9 | 405.7 | 207.6 | 5.5 | 0 |

**Note:** "attempts" counts over all `_evaluate_duplications` calls (once per (task, processor) candidate pair during scheduling), not once per task.

## Key Findings

### Critical parent duplication status

CA-D does NOT implement Sinnen-style critical-parent selection (choosing the single
predecessor with maximum communication cost and duplicating only that one).

Instead, CA-D evaluates ALL direct predecessors and recursively duplicates beneficial
ancestors via `_place_recursive_duplicate`. This is a greedy ALL-predecessor strategy,
not a critical-parent strategy. The docstring of `proposed_scheduler.py` explicitly
states this distinction.

Evidence: `recursive_ancestor_placements > 0` on out-tree (54.7 mean) and fork-join
(207.6 mean) confirms that CA-D places grandparent duplicates, which no critical-parent
implementation would do for non-critical predecessors.

### Recursive placement is structure-dependent

- **Chain**: CA-D places 540 recursive ancestors per case on average. The high count
  reflects that the chain's long path causes each task's ancestors to be recursively
  duplicated onto many processors during candidate evaluation. TIR = 1.0 (no net duplicates
  after the schedule completes), indicating that recursive evaluations do not result in
  kept duplicates when the chain structure provides no speedup from parallelism.
- **Fork**: No recursive placements (root is a direct predecessor of every leaf; no
  grandparents exist). CD-LS and CA-D place identical duplicates on this topology.
- **Out-tree**: 54.7 recursive placements per case (CA-D). These are root (T0) duplicates
  triggered by leaf evaluations that need both T1/T2 (direct pred) and T0 (grandparent)
  to be local. CD-LS places 0 recursive ancestors.
- **Fork-join**: 207.6 recursive placements per case (CA-D). Complex branch structure
  requires extensive ancestor duplication to achieve local data delivery at each branch node.

### Task removal (pruning) status

**Pruning never triggered in any tested case.**

`prune_removed = 0` across all 320 cases (4 DAG × 4 CCR × 20 seeds) for CA-D.

This is expected behavior, not a bug. CA-D's `_prune_redundant_duplicates` uses four
conditions (A–D) that are all jointly required for removal:

- **Condition C** (not source of any CommunicationInstance): When CA-D places a duplicate
  locally, it does NOT create a CommunicationInstance (local deps are free). The duplicate
  is therefore a data source for its successors on that processor via direct local access,
  but this is tracked internally (not as a CommunicationInstance).
- **Condition D** (no successor on same processor loses data): Even if Condition C passes
  (no comm instance was created for that duplicate), Condition D fails because successors
  on the same processor rely on the local duplicate for data. Removing the duplicate would
  leave those successors without a local data source.

The result: once CA-D places an ancestor duplicate to support a successor, removing it
would violate data availability for that successor. Conservative pruning correctly
identifies this and retains all placed duplicates.

### Invariant verification

All counter invariants verified across 320 cases × 2 schedulers:
- `direct_dup_accepted + direct_dup_rejected == direct_dup_attempts` ✓
- `direct_dup_accepted ≤ direct_dup_attempts` ✓
- `total_new_placements ≥ direct_dup_accepted` ✓
- `recursive_ancestor_placements ≥ 0` ✓
- `prune_removed ≤ prune_candidates` ✓
- Scheduling results (makespan, instance count) unchanged by instrumentation ✓

See `tests/test_duplication_diagnostics.py` (40 tests) for formal verification.
