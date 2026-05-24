# Project Alignment Audit

**Project:** A Contention-Aware Duplication Heuristic for DAG Scheduling on NoC Systems  
**Course:** CMP720 – Embedded System Design, Hacettepe University M.S.  
**Authors:** Barış Büyükyılmaz, Ogulcan Uğuroğlu  
**Primary Reference:** Sinnen et al. (2011), *Contention-aware scheduling with task duplication*, JPDC 71:77–86  
**Audit Date:** 2026-05-16

---

## 1. Project Architecture Overview

The project implements a **static, offline DAG scheduling simulator** for 2D mesh Network-on-Chip (NoC) architectures. It is not a cycle-accurate hardware simulator; it does not simulate router microarchitecture, flit-level pipelining, virtual channels, or cache effects. Instead, it is a **reservation-based scheduling framework** in which all decisions are made before execution begins and their timing consequences are computed analytically.

The end-to-end pipeline is:

```
DAG generation
  └─ generate_dag() → nx.DiGraph
       ↓
  DAGGraph wrapper + validation
       ↓
  MeshNoC (topology + routing)
       ↓
  Scheduler.schedule(dag)
       ├─ reads DAGGraph, reads/writes ScheduleState
       └─ produces ScheduleState
            ↓
  schedule_summary(state) → metrics dict
       ↓
  experiment_runner.run_single_experiment() → row dict
       ↓
  run_experiment_grid(config) → pd.DataFrame
       ↓
  save_results() → CSV
       ↓
  plots.generate_all_plots() → PNG files
```

**What each stage produces and consumes:**

| Stage | Consumes | Produces |
|---|---|---|
| DAG generation | parameters (n, p_edge, CCR, seed) | `nx.DiGraph` with `computation_cost` nodes and `communication_volume` edges |
| DAGGraph | `nx.DiGraph` | validated wrapper exposing typed accessors |
| MeshNoC | rows, cols, alpha, beta | processor-ID/coordinate mapping, XY routes, link enumeration, duration formula |
| ScheduleState | MeshNoC | per-processor `Interval` lists, per-link `Interval` lists, `TaskInstance` registry, `CommunicationInstance` list |
| Scheduler | DAGGraph + MeshNoC | committed ScheduleState with all task and (if applicable) communication reservations |
| Metrics | ScheduleState | flat dict of scalar metrics |
| Experiment runner | YAML config | pandas DataFrame; CSV on disk |
| Plots | CSV or DataFrame | PNG files in results/plots/ |

The scheduler is the only stage that reads the DAG and writes the ScheduleState. All other stages are either purely generative (DAG, NoC) or purely analytical (metrics, runner, plots).

---

## 2. Module-by-Module Explanation

### `src/models.py` — Core data structures (Phase 1)

**Category:** Workload and architecture modeling

**Purpose:** Defines all shared dataclasses used by every other module.

**Main classes:**

| Class | Purpose |
|---|---|
| `Task` | Task node with `task_id` and `computation_cost` |
| `Edge` | Directed dependency with `source`, `target`, `communication_volume` |
| `Processor` | Mesh tile at coordinates `(x, y)` with `processor_id` |
| `Link` | Frozen (hashable) directed NoC link between two adjacent processors |
| `Interval` | Time interval `[start_time, finish_time)` on a processor or link; exposes `duration` property |
| `TaskInstance` | One execution of a task on a specific processor; has `is_primary` flag |
| `CommunicationInstance` | One scheduled transfer of a DAG edge; records route, timing, and volume |
| `NoCConfig` | Validated configuration for mesh size and alpha/beta parameters |
| `DAGGraph` | Thin validated wrapper around `nx.DiGraph`; enforces `computation_cost` and `communication_volume` attributes; exposes typed accessors |

**Input/Output:** Consumed by all other modules. Produces nothing beyond validated objects.

**Note:** The `DAGGraph` wrapper enforces structural invariants (acyclicity, non-negative node IDs, positive costs, non-negative volumes) at construction time. This is an important correctness contribution not present in the paper.

---

### `src/dag_generator.py` — Synthetic DAG generation (Phase 2)

**Category:** Workload modeling

**Purpose:** Generates reproducible synthetic random DAGs with exact CCR control.

**Main functions:**

- `generate_dag(n_tasks, edge_prob, ccr, comp_range, seed, ensure_weakly_connected)` — random DAG generator; returns `nx.DiGraph`
- `compute_ccr(g)` — computes actual CCR of a graph
- `_scale_for_ccr(g, ccr)` — scales all edge volumes in-place to achieve the target CCR exactly

**Algorithm:** Edges are added from node `i` to node `j` only when `i < j`, guaranteeing acyclicity. Computation costs are drawn from `Uniform(comp_min, comp_max)`. Edge volumes are drawn from `Uniform(1.0, 2.0)`, then globally scaled so that `total_comm / total_comp = CCR`. The connectivity policy adds chain edges `i → i+1` when the random process leaves isolated subgraphs.

**Input/Output:** Takes scalar parameters, returns an `nx.DiGraph` suitable for wrapping with `DAGGraph`.

---

### `src/noc.py` — 2D mesh NoC model (Phase 3)

**Category:** Architecture modeling

**Purpose:** Encapsulates the 2D mesh topology, processor-coordinate mapping, XY routing, and communication duration formula. Does not perform link interval reservation.

**Main class:** `MeshNoC(rows, cols, alpha, beta)`

**Key methods:**

- `to_coordinates(pid)` / `to_processor_id(x, y)` — row-major bidirectional mapping: `pid = y * cols + x`
- `get_route(src, dst)` — returns XY route as `list[Link]` (first horizontal, then vertical)
- `hop_count(src, dst)` — equals Manhattan distance; equals `len(get_route(...))`
- `communication_duration(src, dst, vol)` — `alpha * hop_count + beta * vol`; returns `0.0` for local communication

**Input/Output:** Takes mesh dimensions and parameters; provides all topology and routing queries needed by schedulers.

---

### `src/schedule_state.py` — Mutable schedule state (Phase 4)

**Category:** Scheduling infrastructure

**Purpose:** The central data structure that accumulates all scheduling decisions. Tracks processor and link reservations, task instances, and communication instances.

**Main class:** `ScheduleState(noc: MeshNoC)`

**Key methods:**

| Method | Purpose |
|---|---|
| `earliest_slot(proc, dur, not_before)` | Finds first gap on a processor's interval list |
| `earliest_route_slot(route, dur, not_before)` | Finds first gap across all links in a route simultaneously |
| `reserve_task(task_id, proc, start, finish, is_primary)` | Commits a task interval; rejects overlap |
| `reserve_route(route, start, finish, metadata)` | Atomically reserves all route links; rejects overlap |
| `reserve_communication(src_task, dst_task, src_proc, dst_proc, ready_time, vol)` | End-to-end: computes duration, finds earliest non-conflicting slot, reserves route, creates `CommunicationInstance` |
| `clone()` | Deep copy for tentative scheduling without polluting committed state |
| `validate_no_overlaps()` | Post-scheduling integrity check |

**Route reservation model:** Remote communication is reserved as a single atomic interval on every link along the XY route simultaneously. This is a simplified whole-route reservation, not pipeline-style flit propagation.

**Input/Output:** Created by schedulers; read by metrics functions.

---

### `src/heft_scheduler.py` — HEFT-like baseline (Phase 5)

**Category:** Scheduling

**Purpose:** Classic list scheduling without duplication and without link-level contention. Serves as the baseline against which all other schedulers are measured.

**Main class:** `HEFTScheduler(noc: MeshNoC)`

**Algorithm:**
1. Compute upward ranks: `rank_u(n) = w(n) + max_s(avg_comm_cost(n,s) + rank_u(s))`
2. Sort tasks by descending rank (ascending task_id tie-break)
3. For each task in priority order, try all processors; commit the one with minimum EFT
4. DRT uses `task_finish + comm_duration` analytically — no link intervals reserved

**Communication model:** Analytic only. Communication cost uses `average_hop_count` (mean Manhattan distance over all processor pairs) in rank computation, and exact hop count in DRT computation. No `reserve_communication()` calls; `link_intervals` remains empty.

---

### `src/contention_scheduler.py` — CA-LS (Phase 6)

**Category:** Scheduling

**Purpose:** Contention-aware list scheduler without duplication. Identical priority to HEFT but uses explicit link interval reservation.

**Main class:** `ContentionAwareScheduler(noc: MeshNoC)`

**Algorithm:**
1. Priority order delegates to `HEFTScheduler.task_priority_order()` for identical ranking
2. For each ready task, evaluate every processor on a `clone()` of current state
3. In each clone, call `reserve_communication()` for all remote predecessors to account for contention-induced delays
4. Commit the clone with minimum EFT; discard rejected clones
5. No duplication

**Communication model:** Full link-interval reservation. DRT = max arrival time from predecessor communication finish times, which include contention-induced waiting.

---

### `src/classical_dup_scheduler.py` — CD-LS (Phase 7)

**Category:** Scheduling

**Purpose:** Duplication-based list scheduler using the classic (contention-free) communication model. Assesses whether duplicating a parent task eliminates remote communication cost.

**Main class:** `ClassicalDuplicationScheduler(noc: MeshNoC)`

**Algorithm:**
1. Priority order delegates to HEFTScheduler
2. For each task, try each processor on a clone
3. In each clone, for each predecessor not already local, evaluate: `Delta_EFT = EFT_no_dup - EFT_dup`; apply duplication if `Delta_EFT > 0`
4. Predecessors evaluated in ascending task_id order for determinism
5. No `reserve_communication()` calls; `link_intervals` remains empty
6. Exactly one primary instance per original task

**Communication model:** Classic analytic model (`alpha * hop_count + beta * vol`). No contention.

---

### `src/proposed_scheduler.py` — CA-D (Phase 8)

**Category:** Scheduling

**Purpose:** Main contribution. Combines contention-aware link reservation with selective parent-only task duplication. Evaluates duplication decisions under the contention model so that only genuinely beneficial duplications are applied.

**Main class:** `ProposedScheduler(noc: MeshNoC)`

**Algorithm:**
1. Priority order delegates to HEFTScheduler
2. For each ready task, evaluate each processor on a clone
3. For each predecessor not already local:
   - Compute `EFT_no_dup` on a sub-clone with contention-aware communications reserved
   - Compute `EFT_dup` on another sub-clone where the predecessor is duplicated locally
   - Commit duplication to the candidate only if `Delta_EFT > 0`
4. After all duplication decisions, reserve final predecessor communications into the candidate
5. Commit the processor candidate with minimum EFT
6. Best-instance selection: when multiple instances of a predecessor exist, select the one minimising arrival time (with local-over-remote tie-breaking and processor_id secondary tie-break)

**Communication model:** Full link-interval reservation via `reserve_communication()` for all contention evaluations and final committed communications. Sub-clones used for probing are discarded.

---

### `src/metrics.py` — Schedule metrics (Phase 9)

**Category:** Metrics

**Purpose:** Pure functions that extract scalar performance metrics from a committed `ScheduleState`.

**Functions:**

| Function | Metric |
|---|---|
| `compute_makespan` | max processor finish time |
| `count_primary_tasks` | number of `is_primary=True` instances |
| `count_duplicate_tasks` | number of `is_primary=False` instances |
| `duplication_ratio` | duplicate_count / primary_count |
| `count_total_task_instances` | primary + duplicate |
| `task_instance_ratio` | total_instances / primary_count (instances per original task) |
| `count_communication_instances` | number of `CommunicationInstance` objects |
| `average_communication_latency` | mean `ci.duration` |
| `total_communication_time` | sum of `ci.duration` |
| `link_busy_time` | per-link total interval duration |
| `average_link_utilization` | mean(link_busy / makespan) over all links |
| `max_link_utilization` | max(link_busy / makespan) |
| `processor_busy_time` | per-processor total interval duration |
| `average_processor_utilization` | mean(proc_busy / makespan) |
| `max_processor_utilization` | max(proc_busy / makespan) |
| `schedule_summary` | flat dict of all key metrics |
| `speedup` | baseline_makespan / scheduler_makespan |

**Note:** Link utilization is computed from `link_intervals` busy time, not from `CommunicationInstance` durations, because one communication may simultaneously occupy multiple route links.

---

### `src/experiment_runner.py` — Batch experiment engine (Phase 9)

**Category:** Experiments

**Purpose:** Orchestrates the full Cartesian product of schedulers × DAG configurations × NoC configurations × seeds. Produces a pandas DataFrame per run, computes HEFT-relative metrics, and saves CSV.

**Main functions:**

- `build_scheduler(name, noc)` — factory returning the correct scheduler class
- `run_single_experiment(...)` — generates DAG, times scheduler, validates state, returns flat dict
- `run_experiment_grid(config)` — Cartesian product via `itertools.product`; calls `add_relative_metrics()`
- `add_relative_metrics(df)` — attaches `baseline_makespan_heft`, `speedup_vs_heft`, `normalized_makespan_vs_heft` per workload group
- `save_results(df, path)` — writes CSV with parent directory creation
- `load_config(path)` — YAML loader
- `run_from_config(path)` — end-to-end: load, run, save, return

**Groupby key for HEFT-relative metrics:** 12 workload-defining columns (`n_tasks`, `edge_prob`, `ccr`, `comp_min`, `comp_max`, `noc_rows`, `noc_cols`, `processor_count`, `alpha`, `beta`, `seed`, `achieved_ccr`).

---

### `src/plots.py` — Visualization (Phase 10)

**Category:** Visualization

**Purpose:** Generates publication-ready comparison plots from experiment CSV files.

**Main functions:**

| Function | Plot |
|---|---|
| `load_results(path)` | Load and validate experiment CSV |
| `aggregate_results(df, metric, group_by)` | Mean/std/count aggregation |
| `plot_metric_vs_ccr(...)` | Core line plot with optional error bars, log-x CCR axis |
| `plot_makespan_vs_ccr` | Wrapper |
| `plot_speedup_vs_ccr` | Wrapper; adds `y=1.0` reference line |
| `plot_task_instance_ratio_vs_ccr` | Wrapper |
| `plot_communication_count_vs_ccr` | Wrapper |
| `plot_link_utilization_vs_ccr` | Wrapper |
| `plot_runtime_vs_task_count` | Log-y runtime scaling |
| `generate_all_plots(csv, output_dir)` | Batch: all six standard plots |
| `print_summary_table(df, group_by)` | Mean summary per scheduler |

**Robustness features:** Falls back from log to linear x-axis when CCR includes zero; falls back from log to linear y-axis when runtime means include zero; validates group-by columns before aggregation.

---

## 3. Paper Variable Mapping

The primary paper (Sinnen et al. 2011) uses the following notation for the scheduling problem:

| Paper notation | Paper meaning | Implementation name | Location | Status |
|---|---|---|---|---|
| G = (V, E, w, c) | Task graph | `DAGGraph` wrapping `nx.DiGraph` | `models.py`, `dag_generator.py` | Direct equivalent |
| V | Set of tasks (nodes) | `dag.task_ids()` / `g.nodes` | `models.py` | Direct equivalent |
| E | Set of edges (dependencies) | `dag.edge_ids()` / `g.edges` | `models.py` | Direct equivalent |
| w(n) | Computation cost of task n | `computation_cost` node attribute; `dag.computation_cost(n)` | `models.py`, `dag_generator.py` | Direct equivalent |
| c(e_ij) | Communication cost of edge (i,j) | `communication_volume` edge attribute; `dag.communication_volume(i,j)` | `models.py`, `dag_generator.py` | Renamed but equivalent (volume, not cost directly) |
| P | Set of processors | `noc.processor_ids()` | `noc.py` | Direct equivalent |
| proc(n) | Processor assigned to task n | `TaskInstance.processor_id` (primary instance) | `models.py` | Direct equivalent |
| ts(n, P) | Start time of task n on processor P | `TaskInstance.start_time` | `models.py` | Direct equivalent |
| tf(n, P) | Finish time of task n on processor P | `TaskInstance.finish_time` | `models.py` | Direct equivalent |
| tdr(n, P) | Data Ready Time for task n on P | computed by `_classic_drt()` / `_contention_drt()` | scheduler files | Direct equivalent |
| sl(S) | Schedule length (makespan) | `compute_makespan(state)` / `state.max_processor_finish_time()` | `metrics.py`, `schedule_state.py` | Direct equivalent |
| Duplicated task instances | Multiple executions of one task | `TaskInstance` with `is_primary=False` | `models.py`, `schedule_state.py` | Direct equivalent |
| Communication edge finish time | Time data from parent arrives | `CommunicationInstance.finish_time` | `models.py` | Direct equivalent |
| Communication route R | Path from source to destination processor | `list[Link]` returned by `noc.get_route(src, dst)` | `noc.py`, `models.py` | Direct equivalent (XY-specific) |
| Communication link | One directed hop in the route | `Link(source_processor, destination_processor)` | `models.py` | Direct equivalent |
| Contention | Two communications using the same link concurrently | Overlapping `Interval` objects in `state.link_intervals[link]` | `schedule_state.py` | Direct equivalent (reservation-based) |
| Bottom-level / upward rank | Task priority metric | `compute_upward_ranks()` in `HEFTScheduler` | `heft_scheduler.py` | Approximated (uses average hop count for rank; paper uses exact communication cost) |
| Source instance selection | Choosing which duplicate sends the data | `_is_better_instance()` in `ProposedScheduler` | `proposed_scheduler.py` | Fully implemented |
| Tentative scheduling | Evaluating a candidate without committing | `state.clone()` → evaluate → discard or keep | `schedule_state.py`, all schedulers | Fully implemented |
| Redundant duplicate removal | Post-hoc removal of unnecessary copies | Not implemented | — | Not implemented |
| Recursive critical-parent duplication | Duplicating ancestors, not just direct parents | Not implemented (parent-only) | — | Not implemented |
| Ideal-switch / one-port model | Paper's reference network model | Not modeled; 2D mesh NoC used instead | — | Replaced by NoC model |
| Half-duplex links | Bidirectional but not simultaneous | Not implemented | — | Not implemented |

---

## 4. Algorithm Mapping to Sinnen et al. 2011

| Algorithm component | Paper | Implementation | Status | Notes |
|---|---|---|---|---|
| List scheduling framework | Yes | Yes | Fully implemented | Ready-task list with EFT-based placement |
| Bottom-level / upward-rank priority | Yes | Yes | Fully implemented | Computed once before scheduling; identical formula in all four schedulers |
| Task insertion technique | Yes | Yes | Fully implemented | `earliest_slot()` finds gaps in processor intervals |
| Earliest start time (EST) | Yes | Yes | Fully implemented | `state.earliest_slot(proc, cost, not_before=DRT)` |
| Earliest finish time (EFT) | Yes | Yes | Fully implemented | `EFT = start + computation_cost` |
| Data Ready Time (DRT) | Yes | Yes | Fully implemented | Both classic (HEFT, CD-LS) and contention-aware (CA-LS, CA-D) variants |
| Edge scheduling on communication links | Yes | Yes | Fully implemented | `reserve_communication()` reserves link intervals; `earliest_route_slot()` handles contention |
| Source instance selection among duplicates | Yes | Yes | Fully implemented | `_is_better_instance()`: arrival → local-over-remote → smaller proc_id |
| Tentative scheduling | Yes | Yes | Fully implemented | `state.clone()` used in all schedulers; rejected clones discarded |
| Duplication decision rule (`Delta_EFT > 0`) | Yes | Yes | Fully implemented | Applied in both CD-LS and CA-D |
| Recursive critical-parent duplication | Yes | No | Not implemented | Only direct parents evaluated; no ancestor traversal |
| Redundant duplicate removal | Yes | No | Not implemented | Post-scheduling pruning of unnecessary copies omitted |
| Contention-aware evaluation of duplicated schedules | Yes | Yes | Fully implemented | CA-D evaluates Delta_EFT under the contention model using sub-clones |
| Final makespan calculation | Yes | Yes | Fully implemented | `max_processor_finish_time()` |
| Re-simulation of classical schedules under contention | Paper evaluates old schedules under new model | No | Not implemented | This project runs each scheduler independently; no re-simulation step |
| Non-increasing bottom-level ordering | Yes | Yes | Fully implemented | Descending rank, ascending task_id tie-break |
| Average vs. exact communication cost in rank | Paper uses a specific model | Approximated | Approximated | `HEFTScheduler.average_hop_count()` averages over all pairs; exact hop used only in DRT |

---

## 5. Baseline Scheduler Comparison

### Individual descriptions

**1. HEFT-like Baseline (HEFTScheduler)**  
Standard list scheduling derived from HEFT (Topcuoglu et al., 2002) adapted to a homogeneous NoC. Uses average-hop-count upward rank for priority. Assigns each task to the processor with the minimum EFT. DRT computed analytically; no link intervals reserved.

**2. CA-LS (ContentionAwareScheduler)**  
Same upward-rank priority as HEFT. Differs by using full link-interval reservation via `reserve_communication()`. DRT reflects actual contention-delayed arrival times. No task duplication. Evaluates each processor candidate on a state clone.

**3. CD-LS (ClassicalDuplicationScheduler)**  
Adds parent-only task duplication to the HEFT-like approach but reverts to the classic (contention-free) communication model. Evaluates `Delta_EFT` analytically. No link intervals reserved. May be overly optimistic because it ignores communication contention.

**4. CA-D / Proposed (ProposedScheduler)**  
Combines full link-interval contention reservation (from CA-LS) with parent-only task duplication (from CD-LS). Evaluates `Delta_EFT` under contention, so duplication decisions are realistic. Uses sub-clones for all tentative evaluations.

### Comparison table

| Property | HEFT | CA-LS | CD-LS | CA-D (Proposed) |
|---|---|---|---|---|
| Task duplication | No | No | Yes (parent-only) | Yes (parent-only) |
| Link contention model | No | Yes | No | Yes |
| Link interval reservation | No | Yes | No | Yes |
| `CommunicationInstance` objects | No | Yes | No | Yes |
| Communication cost | Analytic only | Reservation-based | Analytic only | Reservation-based |
| `link_intervals` after scheduling | Empty | Populated | Empty | Populated |
| Multiple `TaskInstance` per task possible | No | No | Yes | Yes |
| Expected advantage | Fast; simple baseline | Realistic comm delays; no duplication overhead | Lower makespan via task copies; ignores contention | Most realistic; benefits of duplication under contention |
| Potential disadvantage | Ignores contention; may underestimate makespan | No duplication; may miss makespan improvement | Contention-blind: may overestimate improvement | High runtime due to exhaustive sub-clone evaluation |
| When it performs well | Low-CCR, sparse DAGs | Moderate-CCR; balanced task placement | High-CCR; little contention | High-CCR; high contention; when duplication genuinely helps |
| When it performs poorly | High-CCR, congested NoC | No duplication opportunity | High-contention scenarios | Small DAGs with many processors: overhead dominates benefit |

---

## 6. Proposal vs Implementation Mismatches

### 6.1 Communication Penalty Model

The project proposal introduced the following communication penalty (CP) formula:

```
CP = lambda1 * U(route) + lambda2 * B(route) + lambda3 * L(route)
```

where `U(route)` represents link utilization, `B(route)` bandwidth, and `L(route)` latency along the route, with `lambda1`, `lambda2`, `lambda3` as weighting coefficients.

**This formula is not implemented.** The implemented communication model is:

```
duration(i→j, src→dst) = alpha * hop_count(src, dst) + beta * communication_volume(i, j)
```

with contention handled by explicit link-interval reservation:
- `ScheduleState.reserve_communication()` calls `earliest_route_slot()` to find the first time slot at which all links along the XY route are simultaneously free.
- The communication is then reserved as a single atomic interval on every link in the route.
- The data arrives at the destination at `start_time + duration`, which already accounts for contention-induced waiting.

**Assessment:** The implemented model is not a deviation from the primary paper but rather a more concrete and directly executable realization of the link-scheduling model described by Sinnen et al. (2011). The paper schedules communication edges onto links and represents contention through link occupancy; the implementation does exactly this through interval reservation. The CP formula in the proposal was a preliminary design sketch that was superseded by the cleaner reservation-based approach during implementation. The proposal must be updated to describe the implemented model.

### 6.2 Other Proposal-to-Code Mismatches

| Proposal element | Implementation | Status |
|---|---|---|
| CP = lambda1*U + lambda2*B + lambda3*L | `duration = alpha*hop_count + beta*vol` + reservation | Replaced by cleaner model |
| Recursive ancestor duplication mentioned as a goal | Parent-only duplication only | Deferred; scope reduced |
| Redundant duplicate removal mentioned | Not implemented | Deferred |
| 4×4 and 8×8 mesh sizes | Configurable; default.yaml uses sizes [4, 8] | Implemented as intended |
| CCR values [0.1, 1.0, 5.0] | Identical | Implemented as intended |
| Seeds for reproducibility | Fully seeded numpy `default_rng` | Implemented as intended |

---

## 7. NoC Model Alignment

### Why 2D mesh

The 2D mesh is the canonical topology for on-chip multiprocessor networks due to its regularity, scalability, and practical deployability. Tang et al. (2017) use a 2D mesh NoC as the architecture model for duplication-based schedule optimization on MPSoC platforms, confirming that this topology is appropriate for DAG scheduling research targeting embedded multicore systems.

### XY routing

Deterministic XY routing (first move in x, then in y) is the standard routing protocol for mesh NoCs. It is deadlock-free, simple to implement, and produces minimal-length routes equal to the Manhattan distance. The implementation uses `noc.get_route(src, dst)` returning a `list[Link]`, precisely modeling each directed hop.

### Directed links

Each directed hop from processor `a` to processor `b` is modeled as a `Link(source_processor=a, destination_processor=b)`. The `ScheduleState` maintains a separate `list[Interval]` for each directed `Link`. Two communications share a link only if they traverse the same directed hop; communications on reverse links (b→a) do not conflict with those on (a→b).

### Link contention

Contention is modeled through time-interval reservation: if a link already has a reserved interval `[t1, t2)` and a new communication needs the same link during `[t1', t2')`, the new communication must wait until `t2` before it can start. This is implemented in `earliest_route_slot()`. This matches the spirit of the Sinnen et al. model, which explicitly schedules communication edges onto links and detects overlap.

### How this differs from ILP-based approaches

Tang et al. (2017) use Integer Linear Programming (CF-ILP and CA-ILP) to optimize mapping and duplication decisions when the schedule structure is already known. The present project uses greedy list scheduling heuristics, which are polynomial-time and do not require an ILP solver. The ILP approach from Tang et al. is explicitly not implemented, as stated in the literature map.

### Not modeled NoC aspects

The following aspects of real NoC behavior are deliberately excluded as they are outside the scope of a scheduler-level simulator:

- Router buffer occupancy and buffer blocking
- Packet or flit-level simulation
- Wormhole routing (only the entire message is modeled)
- Multicast or broadcast communication
- Adaptive or oblivious non-XY routing
- Energy consumption and dynamic voltage scaling
- Memory hierarchy pressure
- Half-duplex link variants
- Cycle-accurate propagation timing
- Virtual channels and flow control

---

## 8. Extra Contributions Beyond the Primary Paper and Proposal

The implementation includes the following features that go beyond the primary paper's algorithmic description:

| Contribution | Value |
|---|---|
| Deterministic synthetic DAG generation with exact CCR scaling | Enables reproducible experiments at controlled communication intensity |
| `ensure_weakly_connected` policy with chain-edge fallback | Prevents degenerate disconnected graphs that would trivialize scheduling |
| Validated dataclasses (`DAGGraph`, `Task`, `Interval`, etc.) | Catches modeling errors at construction time; prevents silent corruption |
| 2D mesh NoC model with explicit directed-link topology | Concretizes the abstract "network" of the paper to an embedded-system-relevant architecture |
| Deterministic XY routing with Manhattan-distance-optimal paths | Reproducible, minimal-hop routes free from tie-breaking ambiguity |
| Atomic route-wide interval reservation (`reserve_route`) | Correctly models the whole-message contention constraint |
| `earliest_route_slot()` for simultaneous multi-link availability | Handles contention on routes spanning multiple hops |
| Deep-clone-based tentative scheduling | Ensures failed candidates do not pollute committed state; satisfies a critical correctness invariant |
| Three-way instance selection rule (`_is_better_instance`) | Deterministic tie-breaking: arrival → local preference → smaller processor_id |
| Four-scheduler comparative framework (HEFT / CA-LS / CD-LS / CA-D) | Isolates the individual contributions of contention awareness and task duplication |
| `ScheduleState.validate_no_overlaps()` post-scheduling check | Detects scheduling bugs that would otherwise silently produce invalid schedules |
| Comprehensive pytest suite (813 tests, 11 test modules) | Provides regression safety for every module and algorithmic phase |
| Experiment runner with Cartesian product grid and YAML config | Enables systematic comparative experiments without manual scripting |
| CSV output with 30+ columns per experiment row | Enables offline analysis and reuse without re-running experiments |
| HEFT-relative speedup and normalized makespan | Standard comparison metric used in DAG scheduling literature |
| Serial speedup (`total_work / makespan`) | Quantifies parallel efficiency independent of baseline choice |
| Task instance ratio (`total_instances / |V|`) | Project-defined metric matching the proposal's "duplication ratio" definition |
| Link utilization metrics (average and maximum) | Diagnoses NoC bottlenecks independently of makespan |
| Scheduler runtime measurement (ms) | Reveals practical scalability constraints |
| `src/plots.py` with 12 public functions and CLI | Enables direct report-quality figure generation from any results CSV |
| `show_error` control and `reference_line_y` on speedup plot | Presentation-quality plot control for varying data densities |

---

## 9. Missing Features and Limitations

| Feature | Status | Category |
|---|---|---|
| Recursive critical-ancestor duplication | Not implemented | Report limitation; future work (Phase 12) |
| Redundant duplicate removal (post-hoc pruning) | Not implemented | Report limitation; future work |
| Full Sinnen et al. algorithm reproduction | Not achieved | Acceptable simplification (different network model) |
| Half-duplex network variant | Not implemented | Acceptable simplification (not needed for 2D mesh) |
| Ideal-switch / one-port model from paper | Not modeled | Acceptable simplification (2D mesh is more relevant) |
| Re-simulation of classical schedules under contention model | Not implemented | Report limitation |
| Graph-family benchmark generator (trees, SP-graphs, fork-join) | Not implemented | Report limitation; Benchmark Plan Stage 1 |
| Real application DAG benchmarks (STG, Pegasus, etc.) | Not used | Report limitation; Benchmark Plan Stage 2 |
| Homogeneous processors only | Implemented | Acceptable simplification; stated scope |
| Heterogeneous computation matrix | Not implemented | Acceptable simplification; future work |
| Memory model | Not implemented | Future work |
| Energy model | Not implemented | Future work |
| Reliability or security model | Not implemented | Out of scope |
| Packet/flit-level NoC simulation | Not implemented | Acceptable simplification (scheduler-level only) |
| Adaptive routing | Not implemented | Acceptable simplification |
| High runtime of Proposed scheduler | Observed | Report limitation; due to exhaustive sub-clone evaluation for every (task, processor, predecessor) triple |
| Synthetic random DAGs only | Current state | Report limitation; see Benchmark Plan |
| NoC sizes limited to 4×4 and 8×8 | Current default | Acceptable for proof-of-concept; easily extended |

**Note on CA-D runtime:** For a DAG with `n` tasks and `p` processors, the proposed scheduler creates `O(n × p × parents(t))` state clones per scheduling step, each of which may involve further clones for sub-candidate probing. At 100 tasks on a 64-processor mesh, observed runtimes exceed 10 seconds per experiment. This is a known and significant limitation that must be disclosed in the paper.

---

## 10. Related Work Positioning

### Contention-aware scheduling

**Sinnen et al. (2011)** — Primary reference. Introduces contention-aware DAG scheduling by scheduling communication edges onto shared links, using tentative scheduling and task duplication. This project is directly inspired by this work and implements its core ideas on a 2D mesh NoC. The four-scheduler comparison structure mirrors the paper's evaluation.

### NoC-based scheduling

**Tang et al. (2017)** — Focuses on optimizing duplication-based schedules on NoC-based MPSoCs using ILP. Justifies the NoC+MPSoC context for this project. The concept of explicit link contention in an on-chip network directly motivates the 2D mesh model. The ILP approach is not implemented; only heuristic scheduling is used.

### List scheduling with duplication

**Tang et al. (2010) — HEFD** — List scheduling with task duplication for heterogeneous systems. Related to CD-LS and CA-D through the shared idea of EFT-based processor selection with parent duplication. This project uses a homogeneous setting; the HEFD priority model is not adopted. Used as related work to show list scheduling with duplication has precedent.

### Selective / reduced duplication

**Bansal et al. (2003)** — Improved duplication strategy for precedence-constrained graphs. Motivates the `Delta_EFT > 0` decision rule: only duplicate when it provably helps. The implementation adopts this selective approach. The exact Bansal algorithm is not reproduced.

**Mei et al. (2014)** — Resource-aware scheduling with reduced task duplication. Motivates future work on post-scheduling redundant duplicate removal. The current implementation counts duplicates and reports `task_instance_ratio` but does not prune redundant copies.

### Bottom-up / recursive duplication

**Bozdag et al. (2006) — DBUS** — Bottom-up scheduling with recursive ancestor duplication. Demonstrates that duplicating more than just direct parents can yield further improvements. This project implements parent-only duplication, making DBUS a direct motivation for the "recursive ancestor duplication" future work item.

### Clustering-based duplication

**He et al. (2019) — TDCA** — Task-duplication-based clustering for heterogeneous environments. Not implemented and not conceptually related to the current flat list-scheduling approach. Used only as related work in the heterogeneous-clustering category.

### Energy-aware duplication

**Liang and Pang (2017)** — Energy-aware duplication scheduling for parallel tasks on clusters. Task duplication increases energy consumption; energy-aware scheduling adds an energy objective. Not implemented; used only for future work discussion.

---

## 11. Report-Writing Recommendations

### Problem Definition

The problem must be clearly stated as: **static, offline scheduling of a DAG application onto a homogeneous 2D mesh NoC, minimizing schedule length (makespan), while accounting for communication contention on NoC links and optionally exploiting task duplication to reduce inter-processor communication overhead.**

Explicitly state:
- Static means all scheduling decisions precede execution
- Offline means the full application DAG is known before scheduling begins
- Homogeneous means all processors have identical computation speeds
- Communication contention means two transmissions cannot simultaneously occupy the same directed link

### Communication Model

The proposal's CP formula (`CP = lambda1*U + lambda2*B + lambda3*L`) must be **replaced or explicitly revised** in the final report. The implemented model is:

```
duration(i→j, src→dst) = alpha * hop_count(src, dst) + beta * vol(i, j)
```

Contention is handled through link-interval reservation: a communication must wait until all links on its XY route are simultaneously free. This should be presented as the communication model in the paper, as it is what was actually implemented and evaluated.

### Algorithm Section

Add a pseudo-code description of the CA-D scheduler covering:

1. Upward-rank computation (identical to HEFT)
2. Ready-task selection (descending rank)
3. Per-processor evaluation loop
4. Duplication evaluation sub-loop: `Delta_EFT > 0` under contention model
5. Source-instance selection rule
6. Commit winning candidate

Note explicitly that this is parent-only duplication and that recursive ancestor duplication is deferred to future work.

### Baselines

Describe all four baselines in the paper:

| Scheduler | Label | Description |
|---|---|---|
| HEFT-like | HEFT | Analytic communication, no duplication, no link reservation |
| CA-LS | CA-LS | Full link reservation, no duplication |
| CD-LS | CD-LS | Analytic communication, parent-only duplication |
| Proposed | CA-D | Full link reservation, parent-only duplication |

Explain that HEFT and CD-LS use the analytic model and therefore cannot observe communication contention. CA-LS and CA-D model contention explicitly through link-interval reservation.

### Experimental Methodology

State clearly:

- Synthetic random DAGs: `n ∈ {20, 50, 100}` tasks, edge probability `p ∈ {0.15, 0.30}`, CCR `∈ {0.1, 1.0, 5.0}`, computation costs uniform in `[10, 100]`, connected via chain fallback
- NoC sizes: 4×4 (16 processors) and 8×8 (64 processors)
- Communication parameters: `alpha = 1.0`, `beta = 0.1`
- Seeds: 5 random seeds per configuration for statistical variation
- Metrics: makespan, speedup vs HEFT, task instance ratio, communication count, max link utilization, scheduler runtime
- Schedule validation: `validate_no_overlaps()` called after every run

### Results Interpretation

Explain the following observed trend clearly in the paper:

**Why CD-LS can outperform CA-D:** CD-LS ignores link contention. It assumes communications are always instantaneous after the predecessor finishes. As a result, it may over-eagerly duplicate tasks (creating copies that appear beneficial under the optimistic model) and achieve lower reported makespans because contention costs are not accounted for. CA-D evaluates duplication under realistic contention, making more conservative decisions. In high-contention settings, CA-D's pessimistic evaluations may cause it to skip beneficial duplications that CD-LS would apply. This is not a failure of CA-D but a reflection that CD-LS operates on an overly optimistic model.

Additionally, when all tasks run on P0 (high-alpha, low-CCR), all schedulers produce identical makespans because remote communication is prohibitively expensive and the optimal strategy is to run serially. This is expected correct behavior.

### Limitations

State the following limitations explicitly in the paper:

1. No recursive ancestor duplication — the CA-D scheduler only considers direct parents, not grandparents or further ancestors
2. No redundant duplicate removal — unnecessary copies are not pruned after scheduling
3. Synthetic random DAGs only — no standard benchmark graph families (trees, SP-graphs, fork-join graphs) or real application DAGs
4. High scheduler runtime for CA-D — exhaustive sub-clone evaluation is polynomial in task and processor count but practically slow for large instances
5. Homogeneous processors only — no heterogeneous computation matrix
6. Whole-route atomic reservation — the implementation reserves a message's entire duration on all route links simultaneously, which overestimates contention compared to pipeline-style flit propagation

### Future Work

Recommend the following extensions:

1. Recursive critical-ancestor duplication to match the full Sinnen et al. algorithm
2. Redundant duplicate removal to reduce wasted computation
3. Graph-family benchmark generators (random, fork, fork-join, in-tree, out-tree, series-parallel)
4. Evaluation on standard public benchmarks (STG, Pegasus workflows, HPEC task graphs)
5. Extension to heterogeneous processor computation weights
6. Efficient sub-clone pruning or candidate filtering to reduce CA-D runtime
7. Pipelined (flit-level) communication model for more accurate contention representation
8. Energy-aware duplication objective (cf. Liang and Pang, 2017)
9. Exploration of alternative NoC topologies (torus, fat-tree) and routing policies

---

## 12. Benchmark and Dataset Plan

### Stage 1: Paper-like synthetic graph families

The current generator produces random DAGs. To enable trend comparison with Sinnen et al. (2011), implement the following graph families:

| Family | Structure | Why it matters |
|---|---|---|
| Random DAGs (current) | Random edges with i < j | General workload; CCR sensitivity |
| Fork graphs | One source → k parallel tasks → one sink | Exposes parallelism; communication from source |
| Fork-join graphs | Fork then join | Classic parallel pattern; sensitivity to duplication |
| In-trees | All paths converge to one sink | Data aggregation workloads; benefits duplication at sink |
| Out-trees | One source fans to all sinks | Broadcast workloads; duplication on source |
| Series-parallel graphs | Nested fork-join | Generalization of fork-join |

These families expose different scheduling sensitivities and allow comparison of scheduler behavior at controlled structural parameters. Sinnen et al. (2011) used random, SP (series-parallel), and tree-family graphs in their evaluation. Implementing these would allow claims of structural coverage similar to the primary paper.

Recommended approach: extend `dag_generator.py` with `generate_fork_dag()`, `generate_intree_dag()`, etc., following the same CCR-scaling convention.

### Stage 2: Public DAG benchmark search

Recommended search targets for publicly available DAG scheduling benchmarks:

- **Standard Task Graph Set (STG)** — classic DAG scheduling benchmarks used in HEFT and many follow-up papers; available from Kasahara Lab (Waseda University)
- **Pegasus workflow DAGs** — scientific workflow management system (astronomy, bioinformatics); represent real HPC applications
- **HPEC Graph Challenge** — task graph benchmarks for parallel/distributed computing challenges
- **ParaDaG / DAGGEN** — random DAG generation tools with configurable graph families
- **Task graph benchmarks from Topcuoglu et al. (2002)** — the original HEFT paper includes worked examples

Note: Most public benchmarks assume heterogeneous processors and do not include NoC routing topology. Adapting them requires either using only computation cost (ignoring heterogeneity) or adding a homogeneous wrapper.

### Stage 3: Trend-based comparison

Exact numerical reproduction of results from Sinnen et al. (2011) is likely **not achievable** because:

- The paper's exact DAG generator, random seed, graph family sizes, and machine model are not available
- The paper uses a general network model (ideal-switch / one-port) rather than 2D mesh XY routing
- The paper's communication cost representation may differ in detail from the reservation-based model

The appropriate comparison strategy is **trend-based**:

- **Low vs. high CCR:** Expect duplication to be beneficial at high CCR (high communication volume makes remote execution expensive) and neutral at low CCR
- **Effect of duplication:** CD-LS and CA-D should reduce makespan compared to HEFT on high-CCR workloads
- **Effect of contention:** CA-LS should show longer makespans than HEFT on congested NoC workloads; CA-D should demonstrate that duplication reduces contention by co-locating dependent tasks
- **Link utilization:** CA-LS and CA-D should show higher max link utilization than HEFT; CD-LS should show zero link utilization (no link reservations)
- **Runtime cost:** CA-D should have the highest scheduler runtime; HEFT the lowest
- **Speedup over HEFT:** CA-D is expected to show speedup at high CCR; degradation at low CCR due to scheduling overhead

These trends are verifiable with the current experiment framework and do not require exact graph-family reproduction.

---

## 13. Final Positioning Statement

This project is **a paper-inspired, NoC-focused implementation of contention-aware task duplication for DAG scheduling**, not a full reimplementation of Sinnen et al. (2011).

**Specifically:**

The project adopts the core algorithmic ideas from Sinnen et al. (2011) — list scheduling with upward-rank priority, contention-aware link-level communication reservation, selective task duplication via the `Delta_EFT > 0` rule, tentative scheduling through state cloning, and source-instance selection among duplicated predecessors — and realizes them concretely on a **2D mesh NoC with deterministic XY routing**.

The primary deviations from the paper are:

1. **Network model:** The paper uses an ideal-switch or half-duplex model. This project uses a 2D mesh with atomic whole-route XY reservation.
2. **Duplication depth:** The paper implements recursive critical-parent duplication. This project implements parent-only duplication.
3. **Post-processing:** The paper removes redundant duplicates. This project does not.
4. **Workloads:** The paper evaluates on random, series-parallel, and tree-family graphs. This project currently evaluates on random DAGs only.

These deviations are documented, justified, and consistent with the project's stated scope of delivering a NoC-specific contention-aware duplication heuristic for a graduate embedded system design course. The implementation is **paper-compatible** in concept and algorithmic structure, and **paper-inspired** in its extension to the NoC context. It is accurate to describe it as:

> A paper-inspired implementation of contention-aware task duplication for DAG scheduling on a 2D mesh NoC, using explicit link-interval reservation and selective parent-only duplication, validated against HEFT, CA-LS, and CD-LS baselines on synthetic random DAGs.

---

*End of audit.*
