# NoC DAG Scheduler

A contention-aware task duplication heuristic for DAG scheduling on Network-on-Chip systems.

**Course:** CMP720 – Embedded System Design, Hacettepe University, M.S.  
**Authors:** Barış Büyükyılmaz, Ogulcan Uğuroğlu  
**Primary reference:** Sinnen, To, Kaur (2011). *Contention-aware scheduling with task duplication.* JPDC 71:77–86.

---

## 1. Project Summary

This project implements a Python-based simulation framework for evaluating contention-aware task duplication heuristics for Directed Acyclic Graph (DAG) scheduling on 2D mesh Network-on-Chip (NoC) architectures.

The framework simulates **static, offline scheduling** of DAG workloads. All scheduling decisions are made before execution using reservation-based timing: processor intervals and NoC link intervals are reserved analytically to derive task start/finish times. The project is not a cycle-accurate hardware simulator and does not model router microarchitecture, flit-level pipelining, virtual channels, or cache effects.

The work is inspired by the contention-aware scheduling with task duplication approach of Sinnen et al. (2011), adapted to a 2D mesh NoC with deterministic XY routing.

**The improved ProposedScheduler is a NoC-focused, paper-inspired greedy recursive duplication heuristic with conservative redundant duplicate pruning.**

It is not a full exact reimplementation of Sinnen et al. Algorithm 3. Specific deviations from the paper are documented in [docs/known_limitations.md](docs/known_limitations.md).

---

## 2. Implemented Schedulers

Four schedulers are compared. All use the same upward-rank (HEFT-style) priority ordering.

### HEFT-like Baseline (HEFT)

- **Duplication:** No
- **Link reservation:** No — `link_intervals` is empty after scheduling
- **CommunicationInstance objects:** Not created
- **Native makespan interpretation:** Communication cost is analytic (`alpha * hop_count + beta * vol`). Contention is not modeled. Native makespan may underestimate the true execution time when link congestion is present.

### Contention-Aware List Scheduler (CA-LS)

- **Duplication:** No
- **Link reservation:** Yes — explicit interval reservation on every XY route link
- **CommunicationInstance objects:** Created for every remote communication
- **Native makespan interpretation:** Reflects realistic contention-induced delays. DRT (Data Ready Time) accounts for actual communication finish times including waiting on occupied links.

### Classical Duplication Scheduler (CD-LS)

- **Duplication:** Yes — parent-only duplication using the analytic communication model
- **Link reservation:** No — `link_intervals` is empty after scheduling
- **CommunicationInstance objects:** Not created
- **Native makespan interpretation:** Analytic, contention-free. Duplication decisions are based on the optimistic `Delta_EFT > 0` rule without modeling link contention. Native makespan may be overly optimistic.

### Proposed Contention-Aware Duplication Scheduler (CA-D)

- **Duplication:** Yes — greedy recursive ancestor duplication + conservative redundant duplicate pruning (Phases 15A+15B)
- **Link reservation:** Yes — explicit interval reservation on every XY route link
- **CommunicationInstance objects:** Created for every remote communication
- **Native makespan interpretation:** Contention-aware. Duplication decisions are evaluated under the contention model using `ScheduleState.clone()` for tentative probing. Reflects realistic link contention. Native makespan closely matches replayed makespan.

### Scheduler Comparison

| Property | HEFT | CA-LS | CD-LS | CA-D |
|---|---|---|---|---|
| Task duplication | No | No | Yes (parent-only) | Yes (recursive ancestors) |
| Link contention model | No | Yes | No | Yes |
| Link interval reservation | No | Yes | No | Yes |
| CommunicationInstance objects | No | Yes | No | Yes |
| `link_intervals` after scheduling | Empty | Populated | Empty | Populated |
| Multiple TaskInstance per task | No | No | Yes | Yes |

---

## 3. Communication and NoC Model

### Topology

- 2D mesh of homogeneous processors
- Processors identified by integer IDs with row-major coordinate mapping: `pid = y * cols + x`
- Configurable mesh size (default in Phase 16 experiments: 4×4, 16 processors)

### Routing

- Deterministic XY routing: first move horizontally (x), then vertically (y)
- Route length equals Manhattan distance between processor coordinates
- Routes are minimal-hop and deadlock-free

### Communication duration

```
duration(src → dst, vol) = alpha * hop_count(src, dst) + beta * vol
```

- `alpha`: per-hop latency coefficient (set to 0.0 in Phase 16 experiments)
- `beta`: per-unit-volume bandwidth coefficient (set to 1.0 in Phase 16 experiments)
- Local communication (same processor): zero cost, no link reservation, no CommunicationInstance

### Link interval reservation

- Remote communication is reserved as a single atomic interval on every directed link along the XY route simultaneously (whole-route reservation, not pipeline flit propagation)
- If any required link is busy, the communication waits until all route links are simultaneously free
- `ScheduleState.earliest_route_slot()` finds the first feasible simultaneous gap across all route links
- Contention emerges as waiting time caused by occupied links

### Link utilization

- `max_link_utilization` and `replayed_max_link_utilization` are ratios in [0, 1], not percentages
- A value of 0.5 means the busiest link was occupied for 50% of the total schedule duration

### What is not modeled

No router buffers, packet/flit-level simulation, wormhole routing, multicast, adaptive routing, energy consumption, memory hierarchy, or half-duplex links.

---

## 4. Fair Replay Evaluation

### The problem

HEFT and CD-LS use the analytic (contention-free) communication model. CA-LS and CA-D use explicit link-interval reservation. Comparing native makespans directly mixes two different communication models and can be misleading.

### Fair replay

`replay_under_contention(dag, state, noc)` takes a committed `ScheduleState` from any scheduler and produces a fresh `ScheduleState` that:

- **Preserves:** task-to-processor assignment (`task_id`, `processor_id`, `is_primary` flag)
- **Does not preserve:** original start/finish times
- **Recomputes:** all task timing and remote communication reservations under the common contention-aware NoC model

This is a placement-preserving post-hoc evaluation, not a new scheduler. It does not search for a better processor assignment, create new duplicates, or remove duplicates.

### Replay metrics

| Metric | Meaning |
|---|---|
| `replayed_makespan` | Makespan after contention replay |
| `replay_overhead_ratio` | `replayed_makespan / native_makespan` |
| `replayed_speedup_vs_heft` | HEFT's replayed makespan / scheduler's replayed makespan |

- CA-LS and CA-D: `replay_overhead_ratio ≈ 1.0` (already model contention natively)
- HEFT and CD-LS: `replay_overhead_ratio ≥ 1.0` (contention-free model was optimistic)

### Recommended comparison metric

Use `replayed_speedup_vs_heft` as the primary comparison metric in tables and figures. It levels the field across all four schedulers by evaluating every placement under the same physical NoC contention model.

---

## 5. Workload Generation

### Random DAGs

`src/dag_generator.py` generates synthetic random DAGs with exact CCR control.

```
CCR = total_communication_volume / total_computation_cost
```

Edge volumes are globally scaled after generation to achieve the target CCR exactly. Isolated subgraphs are avoided via a chain-edge fallback policy.

### Graph families

`src/graph_families.py` provides deterministic structured DAG generators:

| Family | Structure |
|---|---|
| `fork` | One root → k parallel leaves |
| `join` | k sources → one sink |
| `fork_join` | Root → k parallel branches → sink |
| `in_tree` | All paths converge to one root (reduction tree) |
| `out_tree` | One root fans out to all leaves (broadcast tree) |
| `diamond` | Layered series-parallel with complete bipartite inter-layer edges |

All families support CCR scaling and reproducible random cost assignment via `seed`.

**Chain family:** A `chain` generator exists in `src/graph_families.py` but is excluded from the Phase 16 graph-family diagnostic grid. Deep linear chains are a worst-case for the greedy recursive ancestor duplication in ProposedScheduler, causing runtimes of minutes per run even at small task counts.

---

## 6. Results

### Active experiment CSVs

| File | Description | Rows |
|---|---|---|
| `results/raw/final_grid_small_v2.csv` | Random DAG grid: n_tasks=20, 2 edge probs, 3 CCR, 3 seeds, 4×4 NoC, 4 schedulers | 72 |
| `results/raw/graph_family_diagnostic_v1.csv` | Graph family grid: 6 families, 9 configs, 3 CCR, 3 seeds, 4×4 NoC, 4 schedulers | 324 |

Both grids are reduced diagnostic grids — not the full planned sizes — due to ProposedScheduler runtime limitations with n_tasks=40 and deep linear topologies. See [docs/known_limitations.md](docs/known_limitations.md).

### Active summaries

- `results/summary/final_grid_small_v2_summary.md` — per-scheduler mean metrics, best-wins counts, CCR trends, interpretation
- `results/summary/graph_family_diagnostic_v1_summary.md` — per-family per-scheduler metrics, family-level interpretation
- `results/summary/phase16_combined_interpretation.md` — combined analysis and final report recommendations

### Active plots

- `results/plots/final_grid_small_v2/no_error/` — 10 line plots (no error bars)
- `results/plots/final_grid_small_v2/with_error/` — 10 line plots (with error bars)
- `results/plots/graph_family_diagnostic_v1/no_error/` — 9 bar charts by graph family

### Legacy results (not used in Phase 16 analysis)

- `results/raw/final_grid_small.csv` — Phase 11 grid without replay columns
- `results/raw/smoke_phase9.csv`, `results/raw/differentiation_smoke.csv` — early diagnostic CSVs

---

## 7. How to Run Tests

```bash
python -m pytest tests/ -q
```

At the time of Phase 17 cleanup, the full suite contained **1039 passing tests** across 13 test modules. The test suite covers all scheduler modules, core models, DAG generation, NoC routing, schedule state, contention replay, experiment runner replay metrics, and graph families.

---

## 8. How to Reproduce Experiments

### Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### Run Experiment A (random DAG grid)

```bash
python -u scripts/run_final_experiments.py
```

Produces `results/raw/final_grid_small_v2.csv` (72 rows), plots in `results/plots/final_grid_small_v2/`, and summary in `results/summary/final_grid_small_v2_summary.md`.

### Run Experiment B (graph family grid)

```bash
python -u scripts/run_graph_family_experiments.py
```

Produces `results/raw/graph_family_diagnostic_v1.csv` (324 rows), plots in `results/plots/graph_family_diagnostic_v1/`, and summary in `results/summary/graph_family_diagnostic_v1_summary.md`.

### Run combined analysis

```bash
python scripts/analyze_results.py
```

Produces `results/summary/phase16_combined_interpretation.md` from both CSVs.

### Progress and checkpoints

Both experiment scripts print a startup banner, per-row progress lines, and ProposedScheduler heartbeat messages. A partial checkpoint CSV is written after every completed workload group (all four schedulers). The `-u` flag (unbuffered mode) is required for real-time progress visibility.

### Runtime notes

- ProposedScheduler is the most expensive scheduler due to exhaustive sub-clone evaluation for every (task × processor × predecessor) triple plus recursive ancestor traversal
- On the 4×4 NoC with n_tasks=20: CA-D takes ~10 s per run; HEFT takes < 0.1 s
- Deep linear chains and large dense DAGs cause especially long CA-D runtimes (this is why n_tasks=40 and chain topology were excluded from Phase 16 grids)

---

## 9. Known Limitations

See [docs/known_limitations.md](docs/known_limitations.md) for detailed descriptions with impact and future work notes.

Summary:

1. **Not exact Sinnen Algorithm 3** — greedy recursive ancestor duplication, not the globally optimal critical-parent chain selection from the paper
2. **Conservative pruning only** — post-schedule duplicate removal retains any duplicate where correctness cannot be confirmed; full Sinnen-style redundant task and in-edge removal is not implemented
3. **Synthetic workloads only** — no standard benchmark DAGs (STG, Pegasus, HPEC)
4. **Reduced final grids** — n_tasks=40 excluded from Experiment A; chain topology excluded from Experiment B
5. **No real application DAGs** — all evaluation is on random and structured synthetic DAGs
6. **No energy model** — no power or dynamic voltage/frequency scaling
7. **No alpha sweep** — Phase 16 experiments fix alpha=0.0 (hop-count latency disabled)
8. **No per-flit NoC simulation** — whole-route atomic reservation overestimates contention vs pipelined flit propagation
9. **High CA-D runtime** — exponential in depth for linear DAGs; polynomial but slow for large random DAGs
10. **Homogeneous processors only** — all processors have identical computation speed
