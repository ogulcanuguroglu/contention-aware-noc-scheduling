# PHASE PLAN

## Overview

The project is implemented in staged phases. Each phase must leave the codebase
runnable and testable. No phase skips tests. No placeholder code that silently passes.

---

## Phase 0 — Project Scaffold

**Goal:** Set up directory structure, dependencies, configuration, and empty module stubs.
No scheduling logic. No models yet.

**Deliverables:**
- `requirements.txt`
- `configs/default.yaml`
- `src/__init__.py` and all empty module stubs with module-level docstrings
- `tests/__init__.py` and empty test file stubs
- `results/raw/` and `results/plots/` directories (with `.gitkeep`)
- Validate: `python -m pytest tests/ --collect-only` runs without import errors

**What is NOT in this phase:**
- Any dataclass or model definition
- Any scheduling logic
- Any DAG generation

---

## Phase 1 — Core Models

**Goal:** Define all core data structures used throughout the project.

**Deliverables:**
- `src/models.py`: `Task`, `Edge`, `DAGGraph`, `Processor`, `NoCConfig`
  dataclasses with full type hints and docstrings
- `tests/test_models.py`: basic construction and field validation tests

**What is NOT in this phase:**
- DAG generation (random graphs)
- NoC routing
- Scheduling logic

---

## Phase 2 — DAG Generator

**Goal:** Generate synthetic random DAGs with controllable CCR, task count, and topology.

**Deliverables:**
- `src/dag_generator.py`: `generate_dag(n_tasks, edge_prob, ccr, comp_range, seed)`
  Returns a `networkx.DiGraph` with `weight` (computation) on nodes and
  `volume` (communication) on edges. Guaranteed acyclic. Guaranteed connected
  (every node reachable from at least one source).
- CCR is enforced by scaling edge weights after generation.
- `tests/test_dag_generator.py`: acyclicity, connectivity, CCR tolerance, reproducibility

**What is NOT in this phase:**
- NoC model
- Scheduling

---

## Phase 3 — NoC Model

**Goal:** Implement the 2D mesh NoC with XY routing and link-level interval scheduling.

**Deliverables:**
- `src/noc.py`:
  - `MeshNoC(rows, cols, alpha, beta)` class
  - `get_route(src_proc, dst_proc) -> list[Link]`
  - `communication_duration(volume, hop_count) -> float`
  - `Link` with `reserve(start, duration) -> finish_time` using non-overlapping intervals
  - `link_utilization() -> float`
- `tests/test_noc.py`: routing correctness, XY path, link reservation, contention detection

**What is NOT in this phase:**
- Scheduler integration
- Schedule state

---

## Phase 4 — Schedule State

**Goal:** Implement the mutable scheduling state object that tracks processor and link
reservations.

**Deliverables:**
- `src/schedule_state.py`: `ScheduleState` class
  - Processor interval list per processor (non-overlapping)
  - Link interval list per link (non-overlapping)
  - `earliest_slot(processor_id, duration, not_before) -> start_time`
  - `reserve_task(task_id, processor_id, start_time, finish_time)`
  - `reserve_communication(edge, src_proc, dst_proc, route, volume) -> finish_time`
  - `data_ready_time(task_id, processor_id) -> float` (considering all parents)
  - `clone() -> ScheduleState` for tentative scheduling
- `tests/test_schedule_state.py`: task reservation, communication reservation,
  contention ordering, DRT calculation

**What is NOT in this phase:**
- Any scheduler

---

## Phase 5 — HEFT-like Baseline Scheduler

**Goal:** Implement the classic list scheduling baseline without duplication or contention.

**Deliverables:**
- `src/heft_scheduler.py`: `HEFTScheduler`
  - Upward rank priority computation
  - List scheduling with EFT-based processor selection
  - Uses classic communication model (no link reservations, no contention)
  - Insertion technique for scheduling tasks in processor gaps
- `src/metrics.py` (initial): `compute_makespan`, `compute_speedup`
- `src/main.py` (initial): basic CLI that runs HEFT on a generated DAG and prints makespan
- Validate: `python src/main.py --scheduler heft --tasks 20 --ccr 1.0 --seed 42`

**What is NOT in this phase:**
- Contention model
- Duplication

---

## Phase 6 — Contention-Aware List Scheduler (No Duplication)

**Goal:** Extend list scheduling to use the full contention-aware NoC communication model.

**Deliverables:**
- `src/contention_scheduler.py`: `ContentionAwareScheduler`
  - Same upward rank priority as HEFT
  - Uses `ScheduleState` with link-level reservations
  - `data_ready_time` uses actual edge finish times on links
  - No duplication
- Extended `src/main.py`: `--scheduler ca_ls` option
- Validate: same DAG, CA-LS makespan >= HEFT (expected for most DAGs), both produce
  valid schedules

**What is NOT in this phase:**
- Task duplication

---

## Phase 7 — Classical Duplication Scheduler (No Contention)

**Goal:** Implement duplication-based scheduling using the classic communication model.

**Deliverables:**
- `src/classical_dup_scheduler.py`: `ClassicalDuplicationScheduler`
  - Parent-only duplication (not recursive ancestor yet)
  - Uses classic communication model (no link reservations)
  - Delta_EFT decision rule (but contention-free EFT)
- Extended `src/main.py`: `--scheduler classical_dup` option
- Validate: duplication ratio > 1 for high-CCR DAGs, makespan improvement over HEFT

**What is NOT in this phase:**
- Contention-aware model applied to duplication decisions

---

## Phase 8 — Proposed Contention-Aware Duplication Scheduler

**Goal:** Implement the main contribution: contention-aware task duplication heuristic.

**Deliverables:**
- `src/proposed_scheduler.py`: `ProposedScheduler`
  - Bottom-level priority (from Sinnen et al.)
  - For each task, evaluates parent duplication using tentative scheduling
  - Uses `ScheduleState.clone()` for tentative evaluation
  - Delta_EFT decision rule under contention-aware communication model
  - Applies duplication only when Delta_EFT > 0
- Extended `src/main.py`: `--scheduler proposed` option
- Validate: for high-CCR DAGs, makespan improvement over CA-LS baseline

**Optional extensions (not required):**
- Recursive critical ancestor duplication
- Redundant duplicate removal

---

## Phase 9 — Metrics and Experiment Runner

**Goal:** Implement full metrics calculation and batch experiment execution.

**Deliverables:**
- `src/metrics.py` (complete):
  - `compute_makespan`
  - `compute_speedup`
  - `compute_avg_communication_latency`
  - `compute_avg_link_utilization`
  - `compute_max_link_utilization`
  - `compute_duplication_count`
  - `compute_duplication_ratio`
  - `compute_scheduler_runtime`
- `src/experiment_runner.py`: `run_experiments(config) -> pd.DataFrame`
  - Iterates over all scheduler × DAG configuration × seed combinations
  - Saves raw CSV to `results/raw/`
- Extended `src/main.py`: `--mode experiment` runs the full batch
- Validate: CSV file produced, columns match expected metrics

---

## Phase 10 — Plots and Visualization

**Goal:** Produce publication-quality comparison plots.

**Deliverables:**
- `src/plots.py`:
  - Makespan vs CCR per scheduler (line plot)
  - Speedup vs task count per scheduler (line plot)
  - Link utilization vs CCR (bar plot)
  - Duplication ratio vs CCR (bar plot)
- Saved to `results/plots/`
- Validate: PNG files produced in `results/plots/`

---

## Phase Summary Table

| Phase | Name | Key Output |
|-------|------|-----------|
| 0 | Scaffold | Directory structure, stubs, config |
| 1 | Core Models | `models.py` dataclasses |
| 2 | DAG Generator | `dag_generator.py` |
| 3 | NoC Model | `noc.py` with XY routing and link reservations |
| 4 | Schedule State | `schedule_state.py` |
| 5 | HEFT Baseline | `heft_scheduler.py`, initial `main.py` |
| 6 | CA-LS | `contention_scheduler.py` |
| 7 | Classical Dup | `classical_dup_scheduler.py` |
| 8 | Proposed CA-D | `proposed_scheduler.py` |
| 9 | Experiments | `metrics.py`, `experiment_runner.py` |
| 10 | Plots | `plots.py`, figures |
