# PHASE PLAN

## Overview

The project is implemented in staged phases. Each phase must leave the codebase runnable and testable. No phase skips tests. No placeholder code should silently pass.

Validation should rely on small deterministic examples first, then random DAG experiments later.

---

## Phase 0 — Project Scaffold

**Goal:** Set up directory structure, dependencies, configuration, context documents, and empty module stubs. No algorithmic logic yet.

**Deliverables:**
- `PROJECT_CONTEXT.md`
- `PHASE_PLAN.md`
- `requirements.txt`
- `configs/default.yaml`
- `src/__init__.py` and all module stubs with module-level docstrings
- `tests/__init__.py` and empty test file stubs
- `results/raw/.gitkeep` and `results/plots/.gitkeep`
- Validate: `python -m pytest tests/ --collect-only` runs without import errors

**Required module stubs:**
- `src/main.py`
- `src/models.py`
- `src/dag_generator.py`
- `src/noc.py`
- `src/schedule_state.py`
- `src/heft_scheduler.py`
- `src/contention_scheduler.py`
- `src/classical_dup_scheduler.py`
- `src/proposed_scheduler.py`
- `src/metrics.py`
- `src/experiment_runner.py`
- `src/plots.py`

**What is NOT in this phase:**
- Dataclass/model definitions
- DAG generation
- NoC routing
- Scheduling logic

---

## Phase 1 — Core Models

**Goal:** Define all core data structures used throughout the project.

**Deliverables:**
- `src/models.py` with dataclasses and type hints:
  - `Task`
  - `Edge`
  - `Processor`
  - `LinkId` or `Link`
  - `Interval`
  - `TaskInstance`
  - `CommunicationInstance`
  - `NoCConfig`
  - `DAGGraph` wrapper or documented `networkx.DiGraph` convention
- `tests/test_models.py`: basic construction, equality/hashability where needed, and field validation tests

**Important design decision:**
Use `networkx.DiGraph` for the actual DAG representation, but document the expected node and edge attributes:
- node attribute: `weight`
- edge attribute: `volume`

**What is NOT in this phase:**
- Random DAG generation
- NoC routing
- Schedule reservation logic
- Scheduler logic

---

## Phase 2 — DAG Generator

**Goal:** Generate synthetic random DAGs with controllable Communication-to-Computation Ratio (CCR), task count, and graph density.

**Deliverables:**
- `src/dag_generator.py`:
  - `generate_dag(n_tasks, edge_prob, ccr, comp_range, seed) -> networkx.DiGraph`
  - Each node has `weight` computation cost
  - Each edge has `volume` communication volume
  - The graph is guaranteed acyclic
  - The graph avoids isolated nodes when possible
  - CCR is enforced by scaling edge volumes after graph generation
- `tests/test_dag_generator.py`:
  - acyclicity
  - no isolated nodes for normal parameter settings
  - CCR tolerance
  - reproducibility with fixed seeds
  - different seeds produce different graphs with high probability

**CCR definition:**

```text
CCR = total_communication_volume / total_computation_weight
```

**What is NOT in this phase:**
- NoC model
- Scheduling

---

## Phase 3 — NoC Topology and XY Routing

**Goal:** Implement the 2D mesh NoC topology and deterministic XY routing. Do not implement schedule-state reservation here.

**Deliverables:**
- `src/noc.py`:
  - `MeshNoC(rows, cols, alpha, beta)` class
  - processor id to `(x, y)` coordinate mapping
  - coordinate to processor id mapping
  - explicit directed links between neighboring processors
  - `get_route(src_proc, dst_proc) -> list[Link]`
  - `hop_count(src_proc, dst_proc) -> int`
  - `communication_duration(volume, hop_count) -> float`
- `tests/test_noc.py`:
  - processor-coordinate mapping correctness
  - XY route correctness
  - route length equals Manhattan distance
  - local route is empty and local hop count is zero
  - invalid processor ids raise clear errors

**What is NOT in this phase:**
- Link interval reservation
- Scheduler integration
- Schedule state

---

## Phase 4 — Schedule State and Interval Reservation

**Goal:** Implement the mutable scheduling state object that tracks processor and link reservations.

**Deliverables:**
- `src/schedule_state.py`: `ScheduleState` class
  - Processor interval list per processor, non-overlapping
  - Link interval list per directed link, non-overlapping
  - task instance registry
  - communication instance registry
  - `earliest_processor_slot(processor_id, duration, not_before) -> start_time`
  - `reserve_task(task_id, processor_id, start_time, finish_time, is_primary)`
  - `reserve_communication(edge, src_proc, dst_proc, route, volume, ready_time) -> finish_time`
  - `clone() -> ScheduleState` for tentative scheduling
- Tests:
  - task interval reservation
  - processor overlap rejection or automatic feasible placement
  - communication reservation on links
  - contention ordering on the same link
  - local communication does not reserve links
  - clone isolation

**DRT note:**
Do not overcommit to a generic `data_ready_time()` API until scheduler needs are clear. It may be implemented in schedulers using the committed task and communication instances.

**What is NOT in this phase:**
- Scheduler algorithms

---

## Phase 5 — HEFT-like Baseline Scheduler

**Goal:** Implement the classic list scheduling baseline without duplication and without link-level contention.

**Deliverables:**
- `src/heft_scheduler.py`: `HEFTScheduler`
  - Upward-rank or bottom-level priority computation
  - List scheduling with Earliest Finish Time (EFT)-based processor selection
  - Classic communication model: local cost zero, remote cost based on hop count and communication volume
  - No link reservations
  - Processor insertion technique for task placement
- `src/metrics.py` initial functions:
  - `compute_makespan`
  - `compute_speedup`
- `src/main.py`:
  - `--scheduler heft`
  - `--tasks`
  - `--ccr`
  - `--seed`
  - prints makespan
- Tests:
  - single-task DAG
  - simple chain DAG
  - fork-join DAG
  - precedence constraints are respected

**Validation command:**

```bash
python -m src.main --scheduler heft --tasks 20 --ccr 1.0 --seed 42
```

**What is NOT in this phase:**
- Contention model
- Duplication

---

## Phase 6 — Contention-Aware List Scheduler, No Duplication

**Goal:** Extend list scheduling to use the contention-aware NoC communication model.

**Deliverables:**
- `src/contention_scheduler.py`: `ContentionAwareScheduler`
  - Same priority strategy as HEFT unless explicitly configured otherwise
  - Uses `ScheduleState` with link-level reservations
  - Data Ready Time (DRT) uses actual communication finish times on links
  - No task duplication
- `src/main.py`:
  - `--scheduler ca_ls`
- Tests:
  - communication on same link causes delay
  - local communication does not reserve links
  - precedence constraints are respected using communication arrival times
  - deterministic small DAG schedule validity

**Validation:**
Compare HEFT and CA-LS on the same DAG, but do not assume CA-LS makespan must always be greater or lower. Different models and placement choices can produce different schedules. Validate correctness and report both makespans.

**What is NOT in this phase:**
- Task duplication

---

## Phase 7 — Classical Duplication Scheduler, No Contention

**Goal:** Implement duplication-based scheduling using the classic communication model.

**Deliverables:**
- `src/classical_dup_scheduler.py`: `ClassicalDuplicationScheduler`
  - Parent-only duplication
  - Uses classic communication model, no link reservations
  - Uses `Delta_EFT = EFT_no_dup - EFT_dup`
  - Applies duplication only when `Delta_EFT > 0`
- `src/main.py`:
  - `--scheduler classical_dup`
- Tests:
  - crafted DAG where duplication improves makespan
  - crafted DAG where duplication does not improve makespan and is rejected
  - exactly one primary instance per original task
  - duplication ratio calculation on deterministic schedule

**Validation:**
Use a crafted high-communication DAG to show duplication can improve makespan. Do not require improvement on every random high-CCR DAG.

**What is NOT in this phase:**
- Contention-aware duplication decisions

---

## Phase 8 — Proposed Contention-Aware Duplication Scheduler

**Goal:** Implement the main contribution: contention-aware task duplication heuristic.

**Deliverables:**
- `src/proposed_scheduler.py`: `ProposedScheduler`
  - List scheduling using bottom-level or upward-rank priority
  - For each task, evaluates parent-only duplication candidates using tentative scheduling
  - Uses `ScheduleState.clone()` for tentative evaluation
  - Computes `Delta_EFT` under contention-aware communication model
  - Applies duplication only when `Delta_EFT > 0`
  - Keeps exactly one primary instance for each original task
- `src/main.py`:
  - `--scheduler proposed`
- Tests:
  - crafted DAG where contention-aware duplication improves makespan versus CA-LS
  - crafted DAG where duplication is rejected because it does not improve EFT
  - tentative scheduling does not mutate committed state on rejected candidates
  - local communication after duplication avoids NoC link reservation

**Optional extensions, not required for minimum viable project:**
- Critical-parent-only candidate filtering
- Recursive critical ancestor duplication
- Redundant duplicate and in-edge removal

**Validation:**
For high-CCR random DAGs, proposed scheduling is expected to often improve over CA-LS, but this must not be a hard unit-test assumption. Use deterministic crafted tests for correctness.

---

## Phase 9 — Metrics and Experiment Runner

**Goal:** Implement full metrics calculation and batch experiment execution.

**Deliverables:**
- `src/metrics.py` complete functions:
  - `compute_makespan`
  - `compute_speedup`
  - `compute_avg_communication_latency`
  - `compute_avg_link_utilization`
  - `compute_max_link_utilization`
  - `compute_duplication_count`
  - `compute_duplication_ratio`
  - `compute_scheduler_runtime`
- `src/experiment_runner.py`:
  - `run_experiments(config) -> pandas.DataFrame`
  - Iterates over all scheduler × DAG configuration × seed combinations
  - Saves raw CSV to `results/raw/`
- `src/main.py`:
  - `--mode single`
  - `--mode experiment`
- Tests:
  - metric correctness on deterministic schedules
  - experiment runner produces expected columns
  - CSV file is written

**Validation:**
CSV file produced under `results/raw/`, with columns matching the expected metrics.

---

## Phase 10 — Plots and Visualization

**Goal:** Produce clear comparison plots from experiment CSV files.

**Deliverables:**
- `src/plots.py`:
  - Makespan vs CCR per scheduler
  - Speedup vs task count per scheduler
  - Link utilization vs CCR
  - Duplication ratio vs CCR
  - Scheduler runtime vs task count, optional
- Saved to `results/plots/`
- Tests or validation script:
  - plot functions can load a small CSV and produce PNG files

**Validation:**
PNG files are produced in `results/plots/`.

---

## Phase 11 — Final Experiments and Result Analysis

**Status:** Complete.

**Goal:** Run a computationally manageable diagnostic experiment grid, generate CSV results, generate plots, and write a concise result-analysis summary.  This grid (`final_grid_small`) is a Phase 11 validation grid, not the full final paper evaluation.

**Note:** During this phase, two performance issues discovered while running ProposedScheduler on large configurations were fixed in `src/schedule_state.py`:
- `clone()` replaced `copy.deepcopy` with a fast shallow structural copy (list/dict containers copied, immutable objects shared).
- `probe_communication_arrival()` added as a read-only DRT probe that avoids creating sub-clones when comparing remote communication candidates.

**Experiment grid (final_grid_small):**

| Parameter | Values |
|-----------|--------|
| Seeds | 0, 1, 2 |
| Task counts | 20, 40 |
| Edge probabilities | 0.25, 0.40 |
| CCR values | 0.1, 1.0, 5.0 |
| Computation range | [5, 20] |
| NoC sizes | 4×4 |
| alpha | 0.0 |
| beta | 1.0 |
| Schedulers | heft, contention_aware, classical_duplication, proposed |

Expected row count: 3 × 2 × 2 × 3 × 1 × 4 = 144 rows.

**Deliverables:**
- `results/raw/final_grid_small.csv` — 144-row experiment CSV
- `results/plots/final_grid_small/with_error/` — 6 standard plots with error bars
- `results/plots/final_grid_small/no_error/` — 6 standard plots without error bars
- `results/summary/final_grid_small_summary.md` — experiment configuration, mean tables, CCR trend table, best-scheduler counts, interpretation, and limitations
- `scripts/run_final_experiments.py` — driver script for reproducing the grid

**Validation:**
- CSV row count == 144
- All four schedulers appear exactly 36 times
- No NaN in makespan, speedup_vs_heft, task_instance_ratio, communication_count, max_link_utilization, runtime_ms
- HEFT rows: speedup_vs_heft == 1.0, duplicate_task_count == 0, communication_count == 0
- CD-LS rows: communication_count == 0
- CA-LS rows: duplicate_task_count == 0
- All schedules: primary_task_count == n_tasks
- Full test suite still passes

**Note on existing CSV artifact:** The `final_grid_small.csv` produced in Phase 11 does not contain fair replay metrics columns added in Phase 13.  Regenerate by re-running `scripts/run_final_experiments.py` to get all columns.

---

## Phase 12 — Fair Contention Replay Evaluation

**Status:** Complete.

**Goal:** Add a fair post-hoc contention replay evaluator so schedules from any scheduler (HEFT, CA-LS, CD-LS, CA-D) can be evaluated under the same physical link-contention model, enabling apples-to-apples makespan comparison across the two communication models used by different schedulers.

**Deliverables:**
- `src/contention_replay.py` — new module:
  - `replay_under_contention(dag, original_state, noc) -> ScheduleState`
  - `contention_replayed_makespan(dag, original_state, noc) -> float`
  - `summarize_replay(original_state, replayed_state) -> dict`
- `tests/test_contention_replay.py` — 60 tests across 12 groups

**Key semantics:**
- Preserves task placement decisions (task → processor, is_primary flag).
- Does not preserve original start/finish times.
- Recomputes all timing under the contention-aware communication model.
- Materializes every remote communication as a `CommunicationInstance` with reserved NoC link intervals.
- Uses `probe_communication_arrival()` for read-only DRT probing; no sub-clones created per candidate.
- Does not change any scheduler decision logic.

**Replay ordering:**
All `TaskInstance` objects from the original state are processed in a deterministic order: `(start_time, finish_time, task_id, processor_id, not is_primary)`.  An instance is ready when every DAG predecessor has at least one already-replayed instance.

**Validation:**
- 60 tests added; full suite passed after implementation.

**What is NOT in this phase:**
- Modifying scheduler algorithms.
- Integrating replay metrics into experiment CSV output (that is Phase 13).

---

## Phase 13 — Integrate Fair Replay Metrics into Experiment Runner

**Status:** Complete.

**Goal:** Add fair contention replay metrics to experiment CSV outputs so every scheduler can be compared under the same physical NoC model without re-running schedulers.

**Deliverables:**
- `src/experiment_runner.py` — updated:
  - `run_single_experiment()` calls `replay_under_contention()` after each scheduler run and stores 5 per-row replay columns.
  - `add_replay_relative_metrics()` new function: computes `replayed_speedup_vs_heft` using HEFT's `replayed_makespan` as the per-workload-group baseline.
  - `run_experiment_grid()` calls `add_replay_relative_metrics()` after `add_relative_metrics()`.
- `scripts/run_final_experiments.py` — validation updated to require replay columns; Phase 13 note added to summary text.
- `tests/test_experiment_replay_metrics.py` — 30 tests across 10 groups.

**New result columns (all future-generated CSVs):**

| Column | Formula |
|--------|---------|
| `replayed_makespan` | `replayed_state.max_processor_finish_time()` |
| `replayed_communication_count` | `len(replayed_state.communication_instances)` |
| `replayed_max_link_utilization` | `max_link_utilization(replayed_state, replayed_ms)` |
| `replay_overhead_ratio` | `replayed_ms / original_ms` (1.0 if original_ms == 0) |
| `replayed_vs_original_delta` | `replayed_ms − original_ms` |
| `replayed_speedup_vs_heft` | `heft_replayed_ms / row_replayed_ms` per workload group |

**Key semantics:**
- All existing metrics and columns remain unchanged.
- `replayed_speedup_vs_heft` uses the same `_GROUPBY_COLS` workload grouping as `speedup_vs_heft`.
- Scheduler behavior is unchanged.
- The `final_grid_small.csv` produced in Phase 11 is stale; it does not contain replay columns until regenerated.

**Validation:**
- 30 tests added; full suite passed with 917 tests total.

**What is NOT in this phase:**
- Modifying scheduler algorithms.
- Adding new plots for replay metrics (planned in Phase 16).
- Regenerating `final_grid_small.csv` (planned in Phase 16).

---

## Phase 14 — Graph Family Benchmark Generator

**Status:** Planned (not yet implemented).

**Goal:** Add deterministic paper-like graph families for stronger benchmark comparison beyond random Erdős–Rényi DAGs.

**New families to implement:**
- chain
- fork
- join
- fork-join
- in-tree
- out-tree
- diamond / series-parallel-like DAG if feasible

**Files to create or modify:**
- `src/graph_families.py` — new module; one generator function per family
- `tests/test_graph_families.py` — correctness tests for each family
- `src/experiment_runner.py` — optional integration for graph-family experiments

**What is NOT in this phase:**
- Modifying existing scheduler modules
- Modifying `dag_generator.py` beyond minor helpers
- Running new large-scale experiments (that belongs to a later analysis phase)

**Validation:**
- Each generator produces a valid `nx.DiGraph` accepted by `DAGGraph`
- Structural checks: chain has n-1 edges, fork has k outgoing edges from root, etc.
- CCR scaling still works on all families

---

## Phase 15 — Improve Existing ProposedScheduler

**Status:** Planned (not yet implemented).

**Goal:** Improve the current `ProposedScheduler` in-place with recursive critical-parent duplication and redundant duplicate removal.

**Important constraint:** Do not create a new scheduler class. Improve `ProposedScheduler` in-place.

**Planned improvements:**

1. **Recursive critical-parent duplication**
   - Currently: only direct predecessors are considered for duplication
   - Target: trace up the critical parent chain and duplicate ancestors that reduce EFT
   - Must preserve `Delta_EFT > 0` rule at each duplication step
   - Must preserve the contention-aware evaluation model

2. **Redundant duplicate removal**
   - After scheduling, identify task duplicates that no longer reduce any child's EFT
   - Remove redundant duplicates and their associated link reservations
   - Must preserve exactly one primary instance per original task
   - Must preserve all correctness invariants

**Files to modify:**
- `src/proposed_scheduler.py` — only
- `tests/test_proposed_scheduler.py` — add tests for recursive duplication and duplicate removal

**What is NOT in this phase:**
- Modifying other scheduler modules
- Modifying metrics, experiment runner, or plots
- Energy-aware objectives
- Heterogeneous processor model

**Validation:**
- All existing tests for `ProposedScheduler` still pass
- New deterministic tests verify recursive ancestor duplication
- New deterministic tests verify redundant duplicate removal
- Full test suite passes

---

## Phase 16 — Fair Replay Plots and Regenerated Final Diagnostic Results

**Status:** Planned (not yet implemented).

**Goal:** Regenerate the `final_grid_small` experiment CSV with the Phase 13 replay metric columns and update plots and summary tables to include fair replay metrics for scheduler comparison.

**Deliverables:**
- Regenerated `results/raw/final_grid_small.csv` — 144 rows, now including all 6 replay columns
- Updated `results/summary/final_grid_small_summary.md` — adds fair replay comparison tables and interpretation alongside original predicted-makespan metrics
- Optional new plots comparing `replayed_makespan` and `replayed_speedup_vs_heft` across schedulers and CCR values

**Key comparison enabled:**
This phase produces the first experiment results where HEFT and CD-LS (classic model) and CA-LS and CA-D (contention-aware model) are compared on the same physical footing via `replayed_speedup_vs_heft`.

**Validation:**
- Regenerated CSV contains all replay columns with no NaN values
- HEFT rows: `replayed_speedup_vs_heft == 1.0`
- `replay_overhead_ratio >= 0` for all rows
- `replayed_communication_count >= communication_count` for all rows
- Full test suite passes

**What is NOT in this phase:**
- Modifying scheduler algorithms
- Changing replay semantics
- Running experiments beyond the existing `final_grid_small` grid

---

## Phase 17 — Final Documentation and Reproducibility Cleanup

**Status:** Planned (not yet implemented).

**Goal:** Make the project fully reproducible and ready for final submission.

**Deliverables:**
- Updated `README.md`:
  - Project description
  - Installation instructions
  - Example single-run commands
  - Example experiment commands
  - Known limitations section
  - Reproducibility note with seeds and configuration
- Updated `PROJECT_CONTEXT.md` if any implementation decisions changed during Phases 11–16
- Final test pass confirming 917+ tests (current full suite count)
- Notes for the final report on implemented vs. deferred features

**Validation:**

```bash
python -m pytest tests/ -q
python -m src.experiment_runner  # or equivalent CLI
python -m src.plots --csv results/raw/final_grid_small.csv --out results/plots/final_grid_small/with_error
```

---

## Phase Summary Table

| Phase | Name | Key Output | Status |
|-------|------|------------|--------|
| 0 | Scaffold | Directory structure, stubs, config, context docs | Complete |
| 1 | Core Models | `models.py` dataclasses and shared types | Complete |
| 2 | DAG Generator | `dag_generator.py` | Complete |
| 3 | NoC Topology | `noc.py` with 2D mesh and XY routing | Complete |
| 4 | Schedule State | `schedule_state.py` with interval reservations | Complete |
| 5 | HEFT Baseline | `heft_scheduler.py`, initial CLI | Complete |
| 6 | CA-LS | `contention_scheduler.py` | Complete |
| 7 | Classical Duplication | `classical_dup_scheduler.py` | Complete |
| 8 | Proposed CA-D | `proposed_scheduler.py` | Complete |
| 9 | Experiments | `metrics.py`, `experiment_runner.py` | Complete |
| 10 | Plots | `plots.py`, figures | Complete |
| 11 | Final Experiments | `final_grid_small` diagnostic CSV, plots, summary | Complete |
| 12 | Fair Contention Replay | `contention_replay.py`, 60 tests | Complete |
| 13 | Fair Replay Metrics | Replay columns in experiment runner, 30 tests | Complete |
| 14 | Graph Families | `src/graph_families.py`, benchmark generators | Planned |
| 15 | Improve ProposedScheduler | Recursive duplication, redundant removal | Planned |
| 16 | Fair Replay Plots / Regeneration | Regenerated CSV + replay comparison plots | Planned |
| 17 | Final Documentation | README, reproducibility, final cleanup | Planned |
