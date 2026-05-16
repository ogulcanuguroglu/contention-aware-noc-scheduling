# PROJECT CONTEXT

## Title
A Contention-Aware Duplication Heuristic for Directed Acyclic Graph Scheduling on Network-on-Chip Systems

## Course
CMP720 – Embedded System Design, Hacettepe University, M.S. Computer Engineering

## Authors
- Barış Büyükyılmaz
- Ogulcan Uğuroğlu

---

## Project Goal

Implement a Python-based simulation framework for evaluating contention-aware task duplication heuristics for Directed Acyclic Graph (DAG) scheduling on Network-on-Chip (NoC) systems.

The framework simulates **static, offline scheduling** of DAG workloads on 2D mesh NoC architectures, considering:
- Task computation costs
- Communication costs and volumes
- Processor assignment and processor availability
- Precedence constraints
- Inter-processor communication routing
- Link-level contention on NoC links
- Selective task duplication

**Main objective:** reduce makespan in communication-intensive DAG workloads while avoiding unnecessary task duplication.

---

## Core Papers

### Primary Reference
Oliver Sinnen, Andrea To, Manpreet Kaur.  
"Contention-aware scheduling with task duplication."  
*Journal of Parallel and Distributed Computing*, 71 (2011), 77–86.

### Project Proposal
Barış Büyükyılmaz, Ogulcan Uğuroğlu.  
"A Contention-Aware Duplication Heuristic for DAG Scheduling on NoC Systems."  
CMP720 Extended Project Proposal, Hacettepe University.

---

## Key Terminology

| Term | Abbreviation | Meaning |
|------|-------------|---------|
| Directed Acyclic Graph | DAG | Application task graph |
| Network-on-Chip | NoC | On-chip communication network |
| Earliest Finish Time | EFT | Earliest time at which a task can complete on a processor |
| Data Ready Time | DRT | Earliest time at which all required input data has arrived at a processor |
| Communication-to-Computation Ratio | CCR | Ratio between total communication weight and total computation weight |
| Heterogeneous Earliest Finish Time | HEFT | Classic list scheduling heuristic; used here as a HEFT-like baseline in a homogeneous setting |

---

## Architecture

### Not a cycle-accurate simulator
This project implements a **trace-based / reservation-based scheduler simulator**. It does not simulate router microarchitecture, flits, virtual channels, cache effects, or cycle-accurate hardware behavior.

### NoC Model
- **Topology:** 2D mesh
- **Routing:** deterministic XY routing
- **Processors:** homogeneous processors placed on mesh coordinates
- **Links:** explicit directed links between neighboring mesh nodes
- **Contention:** two communications contend when they require the same directed link during overlapping time intervals
- **Sizes evaluated:** 4×4 and 8×8 meshes, corresponding to 16 and 64 processors

### Scheduling Model
- Static and offline; all scheduling decisions are made before execution
- Non-preemptive task execution
- Deterministic task computation times
- Deterministic communication volumes
- Each processor executes at most one task at a time
- Each task has exactly one primary execution instance
- Duplicated task instances are allowed
- Local communication cost is zero
- Remote communication is routed through NoC links
- A child task can start only after all required parent data has arrived

---

## Communication Model

For all schedulers, the base communication duration from processor `pk` to processor `pl` is:

```text
duration(i→j, pk→pl) = alpha * hop_count(pk, pl) + beta * communication_volume(i, j)
```

where `alpha` and `beta` are configurable parameters. Local communication, where source and destination processors are the same, has zero cost.

For contention-aware schedulers:
- Each remote communication reserves time intervals on every directed link along its XY route.
- If a required link is busy, the communication waits until a feasible non-overlapping interval is available.
- Data arrival time is the finish time of the communication after the last link on the route.
- Data arrival time contributes to Data Ready Time (DRT).

This implementation uses a whole-route reservation approximation: a remote communication reserves all directed links on its XY route for the same communication interval. This is a scheduler-level reservation model, not a per-flit or cycle-accurate NoC simulation.

---

## Decision Rule for Duplication

Duplication of a predecessor task is applied only when it reduces the child task's earliest finish time:

```text
Delta_EFT = EFT_no_dup - EFT_dup
```

The threshold used differs by scheduler:

- **CD-LS** applies duplication when `Delta_EFT > 0` (exact zero threshold, analytic model).
- **Proposed CA-D** applies duplication when `Delta_EFT > EPS` where `EPS` is a small floating-point epsilon, for robustness under the contention-aware model.

In the proposed scheduler, `EFT_dup` must be evaluated with tentative scheduling via `ScheduleState.clone()`, so unsuccessful duplication candidates do not mutate the committed schedule.

**Improved ProposedScheduler (Phase 15A+15B):**

The improved ProposedScheduler is a NoC-focused, paper-inspired greedy recursive duplication heuristic with conservative redundant duplicate pruning.

- **Greedy recursive ancestor duplication (Phase 15A):** When duplicating a direct predecessor onto a candidate processor, the scheduler recursively explores that predecessor's own predecessors and duplicates them when `Delta_EFT > EPS` under the contention model. This is evaluated greedily in ascending task_id order. It is inspired by the recursive critical-parent duplication concept from contention-aware scheduling literature but does not reproduce Sinnen et al. Algorithm 3 exactly.
- **Conservative redundant duplicate pruning (Phase 15B):** After the full schedule is constructed, a single post-schedule pass removes duplicate instances that are provably unnecessary (not a source for any materialized CommunicationInstance, no successor on the same processor would lose its only data). The pass does not reschedule, reroute communications, or remove link intervals.

---

## Target Baselines

| Algorithm | Duplication | Contention-Aware | Purpose |
|-----------|-------------|------------------|---------|
| HEFT-like | No | No | Classic list scheduling baseline |
| CA-LS | No | Yes | Effect of contention-aware communication scheduling |
| Classical Duplication | Yes | No | Effect of duplication without contention awareness |
| Proposed CA-D | Yes — greedy recursive ancestors + conservative pruning | Yes | Main method |

---

## Evaluation Metrics

**Native schedule metrics (scheduler's own model):**
- Makespan, also called schedule length
- Speedup over HEFT baseline (`speedup_vs_heft`)
- Average communication latency
- Average link utilization (ratio in [0, 1], not a percentage)
- Maximum link utilization (ratio in [0, 1], not a percentage)
- Duplication count
- Task instance ratio, defined as total task instances divided by number of original DAG tasks
- Scheduler runtime

**Fair replay metrics (common contention-aware model, Phase 12–13):**
- `replayed_makespan` — makespan after replaying the placement under the common contention-aware NoC model
- `replayed_speedup_vs_heft` — HEFT replayed makespan divided by the scheduler's replayed makespan for the same workload; recommended primary comparison metric
- `replay_overhead_ratio` — replayed_makespan / native makespan; values > 1.0 indicate the native model was optimistic
- `replayed_communication_count` — number of remote communications materialized during replay
- `replayed_max_link_utilization` — maximum link utilization in the replayed schedule (ratio in [0, 1])

---

## Synthetic Workload Parameters

### Random DAG generator parameters (general)

| Parameter | Values |
|-----------|--------|
| Task count | Configurable; see Phase 16 grid below |
| Edge probability | Configurable |
| Computation cost range | Configurable |
| CCR values | 0.1, 1.0, 5.0 |
| Random seeds | Multiple seeds, fixed and reproducible |

Random DAG generation avoids isolated trivial graphs via a chain-edge fallback connectivity policy.

### Graph family generators (Phase 14)

`src/graph_families.py` provides deterministic generators for: `chain`, `fork`, `join`, `fork_join`, `in_tree`, `out_tree`, `diamond`. All support CCR scaling and reproducible cost assignment.

**Note:** The `chain` family generator exists but is excluded from Phase 16 experiments because deep linear DAGs are a runtime pathology for the greedy recursive ancestor duplication in ProposedScheduler.

### Phase 16 active diagnostic grids

**Experiment A — random DAG grid (`final_grid_small_v2.csv`, 72 rows):**

| Parameter | Values |
|-----------|--------|
| n_tasks | 20 (40 excluded: ProposedScheduler >2 min per run on dense 40-task DAGs) |
| edge_prob | 0.25, 0.40 |
| CCR | 0.1, 1.0, 5.0 |
| Seeds | 0, 1, 2 |
| NoC | 4×4, alpha=0.0, beta=1.0 |

**Experiment B — graph family grid (`graph_family_diagnostic_v1.csv`, 324 rows):**

| Parameter | Values |
|-----------|--------|
| Families | fork, join, fork_join, in_tree, out_tree, diamond (chain excluded) |
| Family configs | 9 parameter sets |
| CCR | 0.1, 1.0, 5.0 |
| Seeds | 0, 1, 2 |
| NoC | 4×4, alpha=0.0, beta=1.0 |

Both grids are runtime-motivated reductions from the originally planned sizes. All included rows are complete and validated; no NaN values or timeout placeholders.

---

## Technology Stack

| Purpose | Library |
|---------|---------|
| DAG representation | networkx |
| Numerical operations | numpy |
| Result tables | pandas |
| Plots | matplotlib |
| Configuration | PyYAML |
| Tests | pytest |

**Excluded:** GPU programming, CUDA, external NoC simulators such as BookSim, multiprocessing, complex GUI, and machine learning.

---

## Module Structure

```text
src/
  main.py                   — Command-line interface and experiment orchestration
  models.py                 — Core dataclasses and shared types
  dag_generator.py          — Synthetic random DAG generation with CCR control
  noc.py                    — 2D mesh NoC topology and XY routing
  schedule_state.py         — Mutable schedule state: processor and link reservations
  heft_scheduler.py         — HEFT-like baseline, no duplication and no contention
  contention_scheduler.py   — Contention-aware list scheduler, no duplication
  classical_dup_scheduler.py — Classical duplication scheduler, no contention awareness
  proposed_scheduler.py     — Improved CA-D: greedy recursive ancestor duplication
                               + conservative redundant duplicate pruning (Phases 15A+15B)
  metrics.py                — Metrics calculation functions
  experiment_runner.py      — Batch experiment execution with fair replay integration
  plots.py                  — Visualization functions
  graph_families.py         — Deterministic graph family generators: chain, fork, join,
                               fork_join, in_tree, out_tree, diamond (Phase 14)
  contention_replay.py      — Fair contention replay evaluator: replay_under_contention()
                               for placement-preserving post-hoc makespan comparison (Phase 12)

tests/
  test_models.py
  test_dag_generator.py
  test_noc.py
  test_schedule_state.py
  test_heft_scheduler.py
  test_contention_scheduler.py
  test_classical_dup_scheduler.py
  test_proposed_scheduler.py
  test_contention_replay.py          — 60 tests for fair replay (Phase 12)
  test_experiment_replay_metrics.py  — 30 tests for replay metric integration (Phase 13)
  test_graph_families.py             — correctness tests for all graph family generators (Phase 14)

scripts/
  run_final_experiments.py           — Experiment A driver: final_grid_small_v2 (72 rows)
  run_graph_family_experiments.py    — Experiment B driver: graph_family_diagnostic_v1 (324 rows)
  analyze_results.py                 — Combined Phase 16 interpretation generator

configs/
  default.yaml

results/
  raw/
    final_grid_small_v2.csv          — 72 rows, active Phase 16 random DAG results
    graph_family_diagnostic_v1.csv   — 324 rows, active Phase 16 graph family results
  plots/
    final_grid_small_v2/             — 20 PNGs (no_error/ and with_error/ subdirs)
    graph_family_diagnostic_v1/      — 9 PNGs (no_error/ subdir)
  summary/
    final_grid_small_v2_summary.md
    graph_family_diagnostic_v1_summary.md
    phase16_combined_interpretation.md
    project_alignment_audit.md
```

---

## Simplifications vs. Paper

| Paper / Full Model Feature | This Implementation | Reason |
|----------------------------|--------------------|--------|
| General arbitrary topology | 2D mesh NoC | Proposal explicitly targets NoC systems |
| Cycle-accurate NoC behavior | Reservation-based link interval model | Sufficient for scheduler-level simulation |
| Recursive critical ancestor duplication | Implemented as a greedy ancestor heuristic (Phase 15A); not an exact Sinnen Algorithm 3 implementation | Greedy approach avoids exponential combinatorics; globally optimal ancestor selection is future work |
| Redundant duplicate removal | Implemented conservatively (Phase 15B); does not perform full Sinnen-style in-edge deletion or global rescheduling | Conservative pruning retains any duplicate where correctness cannot be confirmed without rerouting |
| Heterogeneous processors | Homogeneous processors | Project scope |
| Full runtime adaptivity | Static offline scheduling | Project scope |

---

## Implementation Principles

1. Each module must have one focused responsibility.
2. Use `dataclass` for core model objects.
3. Use type hints throughout.
4. Prefer small, testable functions.
5. Add docstrings for nontrivial functions.
6. Avoid hidden global state.
7. Random generation must be reproducible via seeds.
8. Do not over-engineer.
9. Do not implement later phases early.
10. Each phase must leave the project runnable and testable.
11. If a feature is simplified compared with the papers, document the simplification.
12. Do not rely on random experiments as the only validation; include small deterministic unit tests.

---

## Core Correctness Invariants

The implementation must preserve these invariants:

1. The generated application graph must be acyclic.
2. A processor cannot execute overlapping task intervals.
3. A directed NoC link cannot carry overlapping communication intervals.
4. A task cannot start before all required parent data has arrived.
5. Each original task must have exactly one primary execution instance.
6. Duplicated instances must not replace the primary instance unless the scheduler explicitly marks the primary assignment.
7. Tentative scheduling must not mutate the committed schedule unless the candidate is accepted.
8. Local communication must have zero cost and must not reserve NoC links.
9. All reported metrics must be computed from the committed final schedule.
