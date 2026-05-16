# Methodology

This document describes the scheduling problem formulation, communication model, scheduler algorithms, and fair replay evaluation used in the project.

---

## DAG Model

An application is represented as a Directed Acyclic Graph (DAG):

```
G = (V, E)
```

- **V** — set of tasks (nodes). Each task `v ∈ V` has a `computation_cost(v) > 0`.
- **E** — set of directed dependency edges. Each edge `(u, v) ∈ E` has a `communication_volume(u, v) ≥ 0`.
- A child task `v` cannot start until all of its predecessors `u` have finished and their data has arrived at `v`'s processor.
- Local communication (source and destination on the same processor) has zero cost.

**Communication-to-Computation Ratio (CCR):**

```
CCR = total_communication_volume / total_computation_cost
     = Σ communication_volume(u,v) / Σ computation_cost(v)
```

High CCR workloads are communication-dominated; low CCR workloads are computation-dominated. Schedulers that reduce or eliminate inter-processor communication (via task duplication) benefit most at high CCR.

**Node attribute:** `computation_cost` (float, > 0)  
**Edge attribute:** `communication_volume` (float, ≥ 0)

---

## NoC Model

### Processor grid

Processors are arranged in a 2D mesh of `rows × cols` tiles. Each processor has an integer ID with row-major coordinate mapping:

```
pid = y * cols + x    where (x, y) ∈ [0, cols) × [0, rows)
```

### XY routing

Communication from processor `src` to processor `dst` follows deterministic XY routing: first move in the x direction (horizontal), then in the y direction (vertical). The route is a sequence of directed links:

```
route(src, dst) = [Link(a, b), Link(b, c), ..., Link(prev, dst)]
```

Route length equals the Manhattan distance: `|x_src - x_dst| + |y_src - y_dst|`.

### Communication duration

```
duration(src, dst, vol) = alpha * hop_count(src, dst) + beta * vol
```

- `alpha` — per-hop latency coefficient
- `beta` — per-unit-volume bandwidth coefficient
- `hop_count(src, dst) = len(route(src, dst))`
- Local communication (src == dst): `duration = 0`, no link intervals reserved

### Link interval reservation

Remote communication is reserved as a single atomic interval on every directed link along the XY route simultaneously (whole-route reservation, not per-flit pipeline propagation). If any required link is already occupied during a candidate time window, the communication waits until all route links are simultaneously free.

Two communications contend when they need the same directed link `Link(a, b)` during overlapping time intervals.

### Link utilization

```
link_utilization(link) = total_busy_time(link) / makespan
```

Link utilization metrics are ratios in [0, 1]. A value of 0.5 means the link was occupied for 50% of the schedule duration.

---

## Scheduler Models

All four schedulers use the same upward-rank (HEFT-style) priority ordering, computed once before scheduling.

**Upward rank:**

```
rank_u(v) = computation_cost(v) + max_{s ∈ succ(v)} { avg_comm(v,s) + rank_u(s) }
```

Tasks are scheduled in descending rank order (ascending `task_id` as tie-break).

---

### HEFT-like Baseline (HEFTScheduler)

1. Compute upward ranks for all tasks.
2. Sort tasks by descending rank.
3. For each task in priority order:
   - For each processor, compute EFT analytically:
     - `DRT = max over parents { parent.finish_time + comm_duration(parent_proc, cand_proc, vol) }`
     - `EST = max(processor_available_time, DRT)`
     - `EFT = EST + computation_cost(task)`
   - Assign task to the processor with minimum EFT.
4. No link intervals reserved. `link_intervals` is empty after scheduling.

**Native makespan:** May underestimate real execution time; contention is not modeled.

---

### Contention-Aware List Scheduler (CA-LS / ContentionAwareScheduler)

Same priority as HEFT. Differs by evaluating each processor candidate on a cloned `ScheduleState` with full link-interval reservation:

1. Compute upward ranks. Sort tasks by descending rank.
2. For each task:
   - For each processor, clone the current committed state.
   - In the clone, call `reserve_communication()` for all remote predecessors.
   - `DRT = max over parents { comm.finish_time }` (actual contention-delayed arrival)
   - `EFT = earliest_slot(proc, cost, DRT) + cost`
   - Commit the clone with minimum EFT; discard rejected clones.
3. No task duplication.

**Native makespan:** Reflects realistic link-contention delays. `replay_overhead_ratio ≈ 1.0`.

---

### Classical Duplication Scheduler (CD-LS / ClassicalDuplicationScheduler)

Adds parent-only task duplication to the HEFT-like approach but reverts to the analytic communication model:

1. Compute upward ranks. Sort tasks by descending rank.
2. For each task and each processor candidate (cloned state):
   - For each remote predecessor `pred`, evaluate duplication:
     - `EFT_no_dup` = EFT without duplicating `pred` (analytic comm cost)
     - `EFT_dup` = EFT with `pred` duplicated onto candidate processor
     - `Delta_EFT = EFT_no_dup - EFT_dup`
   - Duplicate `pred` onto candidate if `Delta_EFT > 0`.
3. No link intervals reserved.
4. Exactly one primary instance per original task.

**Native makespan:** Analytic and potentially optimistic; contention is not modeled. CD-LS native wins may be artefacts of the optimistic model.

---

### Proposed Contention-Aware Duplication Scheduler (CA-D / ProposedScheduler)

Main contribution. Combines contention-aware link reservation with greedy recursive ancestor duplication and conservative redundant duplicate pruning:

**Per-task scheduling:**

1. Compute upward ranks. Sort tasks by descending rank.
2. For each task and each processor candidate (cloned state):
   - For each direct predecessor `pred` not already local:
     - Sub-clone without duplication → compute `EFT_no_dup` (contention-aware)
     - Sub-clone with `pred` placed via `_place_recursive_duplicate` → compute `EFT_dup`
     - `Delta_EFT = EFT_no_dup - EFT_dup`
     - If `Delta_EFT > _EPS`: commit duplication into candidate clone
   - Sub-clones used for probing are discarded; only the accepted candidate is committed.
3. After all duplication decisions for the candidate, reserve final predecessor communications.
4. Commit the processor candidate with minimum EFT.
5. Exactly one primary instance per original task.

**Greedy recursive ancestor duplication (`_place_recursive_duplicate`):**

When placing a duplicate of `pred` on candidate processor `P`, each predecessor `gp` of `pred` that is not already on `P` is independently evaluated: if placing `gp` recursively reduces `pred`'s EFT by more than `_EPS`, the `gp` placement is committed. This is a greedy per-predecessor decision evaluated in ascending `task_id` order. It is inspired by the recursive critical-parent duplication concept from contention-aware scheduling literature but does not reproduce that algorithm exactly.

**Key invariants:**
- Processor candidates are evaluated with cloned `ScheduleState` objects; rejected clones are discarded without modifying committed state.
- Duplication is committed only if `Delta_EFT > _EPS` (a small epsilon threshold).
- Visiting set prevents revisiting tasks already in the current recursion chain.

**Conservative redundant duplicate pruning (`_prune_redundant_duplicates`):**

After the full schedule is constructed, a single post-schedule pass removes duplicate instances that are provably unnecessary. A duplicate is removed only when all four conditions hold simultaneously:

- A. `is_primary == False`
- B. At least one other instance of the same task remains
- C. No `CommunicationInstance` uses it as a source
- D. No remaining successor instance on the same processor would lose required data

The pass is conservative: if there is any doubt, the duplicate is kept. It does not reschedule tasks, reroute communications, shift intervals, create new intervals, or remove link intervals. It does not implement full Sinnen-style redundant task and in-edge removal.

**This scheduler is not an exact reproduction of Sinnen et al. Algorithm 3.** See [docs/known_limitations.md](known_limitations.md) for specific differences.

---

## Fair Replay

### Motivation

HEFT and CD-LS use the analytic (contention-free) communication model and produce empty `link_intervals`. CA-LS and CA-D use explicit link-interval reservation. Comparing native makespans directly mixes two different communication models and is not fair.

### Method

`replay_under_contention(dag, original_state, noc)` is a placement-preserving post-hoc contention evaluation:

1. Extract all `TaskInstance` objects from `original_state`.
2. Preserve `task_id`, `processor_id`, and `is_primary` for each instance.
3. Recompute task start/finish times in a deterministic order (sorted by original start time, then finish time, then task_id, then processor_id, with primary before duplicate on ties).
4. An instance is ready when every DAG predecessor has at least one already-replayed instance in the new state.
5. For each remote predecessor communication, reserve the XY route links and create a `CommunicationInstance`.
6. Source-instance selection among duplicated predecessors: earliest arrival wins; ties broken by local-over-remote preference, then smaller processor_id.

**Preserved:** task placement and primary/duplicate status.  
**Not preserved:** original task start/finish times.  
**Recomputed:** all timing under the common contention-aware NoC model.

### Key metrics

```
replay_overhead_ratio     = replayed_makespan / native_makespan
replayed_speedup_vs_heft  = heft_replayed_makespan / scheduler_replayed_makespan
```

`replayed_speedup_vs_heft > 1.0` means the scheduler's placement achieves a shorter replayed makespan than HEFT's placement under the same contention model. This is the recommended primary comparison metric.

### Report wording

> In addition to each scheduler's native makespan, we perform a fair contention replay. This replay preserves the task-to-processor placement and duplicate instances produced by each scheduler, but recomputes task start times and remote communication reservations under a common 2D mesh NoC contention model. This allows contention-blind and contention-aware schedulers to be compared under the same communication model.
