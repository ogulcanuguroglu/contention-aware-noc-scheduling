# PROJECT CONTEXT

## Title
A Contention-Aware Duplication Heuristic for DAG Scheduling on NoC Systems

## Course
CMP720 – Embedded System Design, Hacettepe University, M.S. Computer Engineering

## Authors
- Barış Büyükyılmaz
- Ogulcan Uğuroğlu

---

## Project Goal

Implement a Python-based simulation framework for evaluating contention-aware task
duplication heuristics for Directed Acyclic Graph (DAG) scheduling on Network-on-Chip
(NoC) systems.

The framework simulates **static, offline scheduling** of DAG workloads on 2D mesh NoC
architectures, considering:
- Task computation costs
- Communication costs and volumes
- Processor assignment and availability
- Precedence constraints
- Inter-processor communication routing
- Link-level contention on NoC links
- Selective task duplication

**Main objective:** Reduce makespan in communication-intensive DAG workloads while
avoiding unnecessary task duplication.

---

## Core Papers

### Primary Reference
Oliver Sinnen, Andrea To, Manpreet Kaur.
"Contention-aware scheduling with task duplication."
*Journal of Parallel and Distributed Computing*, 71 (2011) 77–86.

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
| Earliest Finish Time | EFT | Earliest a task can complete on a processor |
| Data Ready Time | DRT | Earliest time all input data arrives at a processor |
| Communication-to-Computation Ratio | CCR | Ratio of total edge weight to total node weight |
| Heterogeneous Earliest Finish Time | HEFT | Classic list scheduling heuristic (used here in homogeneous setting) |

---

## Architecture

### Not a cycle-accurate simulator
This project implements a **trace-based / reservation-based scheduler simulator**.
No hardware simulation is performed.

### NoC Model
- **Topology:** 2D mesh
- **Routing:** Deterministic XY routing
- **Links:** Each link has an explicit interval schedule
- **Contention:** Two communications contend when they reserve the same link at overlapping times
- **Sizes evaluated:** 4×4 and 8×8 (16 and 64 processors)

### Scheduling Model
- Static and offline (all decisions made before execution)
- Non-preemptive task execution
- Deterministic computation times
- Deterministic communication volumes
- Each processor executes at most one task at a time
- Each task has exactly one primary execution instance
- Duplicated task instances are allowed
- Local communication cost is zero
- Remote communication is routed through NoC links

---

## Communication Model

For all schedulers, communication duration on a route from processor pk to pl is:

```
duration(i→j, k→l) = alpha * hop_count(k, l) + beta * communication_volume(i, j)
```

where `alpha` and `beta` are configurable parameters. Local communication (same processor)
has zero cost.

For contention-aware schedulers:
- Each communication reserves link intervals along its XY route
- Contention forces later communications to wait
- Data arrival time = finish time of the communication on the last link of the route
- This arrival time enters the Data Ready Time (DRT) computation

---

## Decision Rule for Duplication

Duplication of a parent task vi for child task vj is applied if:

```
Delta_EFT = EFT_no_dup - EFT_dup > 0
```

This ensures duplication is only performed when it leads to an actual reduction in
completion time under the contention-aware communication model.

---

## Target Baselines (Final Comparison)

| Algorithm | Duplication | Contention-Aware |
|-----------|-------------|-----------------|
| HEFT-like | No          | No              |
| CA-LS     | No          | Yes             |
| Classical Dup | Yes     | No              |
| **Proposed (CA-D)** | **Yes** | **Yes** |

---

## Evaluation Metrics

- Makespan (schedule length)
- Speedup over HEFT baseline
- Average communication latency
- Average link utilization
- Maximum link utilization
- Duplication count
- Duplication ratio (instances / |V|)
- Scheduler runtime

---

## Synthetic Workload Parameters

| Parameter | Values |
|-----------|--------|
| Task count | 20, 50, 100 |
| Edge probability | 0.15, 0.30 |
| Computation cost range | [10, 100] |
| CCR values | 0.1, 1.0, 5.0 |
| Multiple random seeds | Yes |

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

**Excluded:** GPU programming, CUDA, external NoC simulators (BookSim), multiprocessing,
complex GUI, machine learning.

---

## Module Structure

```
src/
  main.py               — CLI entry point and experiment orchestration
  models.py             — Core dataclasses: Task, Edge, DAG, Processor, NoC
  dag_generator.py      — Synthetic random DAG generation with CCR control
  noc.py                — 2D mesh NoC model, XY routing, link interval scheduling
  schedule_state.py     — Mutable schedule state: processor and link reservations
  heft_scheduler.py     — HEFT-like baseline (no duplication, no contention)
  contention_scheduler.py — Contention-aware list scheduler (no duplication)
  proposed_scheduler.py — Proposed contention-aware duplication scheduler
  metrics.py            — Metrics calculation functions
  experiment_runner.py  — Batch experiment execution
  plots.py              — Visualization functions

tests/
  test_dag_generator.py
  test_noc.py
  test_schedule_state.py

configs/
  default.yaml

results/
  raw/
  plots/
```

---

## Simplifications vs. Paper

| Paper Feature | This Implementation | Reason |
|---------------|--------------------|----|
| Star/switch network | 2D mesh NoC | Proposal explicitly targets NoC |
| Full edge scheduling on every link | Reservation-based interval model | Sufficient for trace-based simulation |
| Recursive critical ancestor duplication | Critical parent only (initially) | Staged implementation |
| Redundant duplicate removal | Not in initial phases | Staged implementation |
| Heterogeneous processors | Homogeneous processors | Project scope |

---

## Implementation Principles

1. Each module stays focused on one responsibility.
2. Use `dataclass` for core model objects.
3. Use type hints throughout.
4. Prefer small, testable functions.
5. Add docstrings for nontrivial functions.
6. No hidden global state.
7. All random generation is reproducible via seeds.
8. Do not over-engineer.
9. Do not implement later phases early.
10. Each phase must leave the project in a runnable state.
