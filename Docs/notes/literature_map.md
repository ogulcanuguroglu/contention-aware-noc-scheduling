# Literature Map

This document explains how each reference paper should be used in the project.

The project is based primarily on contention-aware task duplication scheduling for DAG applications on NoC-based multicore systems.

Important scope rule:

- The primary algorithmic reference is Sinnen et al. 2011.
- The NoC paper is used to justify the Network-on-Chip / MPSoC context.
- The remaining papers are secondary references for related work, comparison, and future work.
- Secondary papers should not redefine the implemented scheduler unless explicitly planned as a future extension.

---

## 1. Primary Algorithmic Reference

### Sinnen et al. 2011 — Contention-aware scheduling with task duplication

**Local path**

`docs/papers/primary/sinnen_2011_contention_aware_scheduling_with_task_duplication.pdf`

**Role in this project**

This is the primary reference paper.

The project is inspired by its core idea:

- represent applications as Directed Acyclic Graphs (DAGs),
- schedule tasks statically on multiple processors,
- model communication contention by scheduling task-graph edges onto communication links,
- use task duplication to reduce or avoid inter-processor communication,
- compare contention-aware duplication against list scheduling and classical duplication baselines.

**Concepts used in the implementation**

- DAG scheduling model.
- Task computation cost.
- Edge communication cost.
- List scheduling priority.
- Bottom-level / upward-rank style priority.
- Data-ready time.
- Earliest finish time.
- Insertion-based scheduling.
- Communication contention through link reservations.
- Multiple task instances due to duplication.
- Source-instance selection when a predecessor is duplicated.
- Comparison against:
  - list scheduling without duplication,
  - contention-aware list scheduling,
  - duplication without contention awareness,
  - contention-aware duplication.

**Important paper details**

Sinnen et al. argue that classical scheduling models ignore contention for communication resources and therefore can produce unrealistic schedules. Their contention model schedules task-graph edges on communication links. They also emphasize that when a task has multiple duplicated instances, the scheduler must carefully choose which instance sends the communication. This is done by tentatively scheduling communication edges on possible routes. The paper’s algorithm uses list scheduling, non-increasing bottom-level priority, tentative scheduling, recursive critical-parent duplication, and redundant task removal.

**Implemented in this project**

- Static DAG scheduling.
- Link-level communication reservation.
- Four scheduler comparison structure:
  - HEFT-like / LS-style baseline,
  - contention-aware list scheduler,
  - classical duplication scheduler,
  - proposed contention-aware duplication scheduler.
- Tentative clone-based evaluation.
- Source-instance selection among duplicated predecessors.
- Parent duplication based on `Delta_EFT > 0`.

**Simplified or not implemented**

- No recursive critical ancestor duplication.
- No redundant duplicate removal.
- No half-duplex network variant.
- No exact recreation of the paper’s ideal switch / one-port system.
- No re-simulation of classical schedules under the contention model.
- No exact reproduction of the paper’s random graph families yet.

**How to use in writing**

Use this paper as the main foundation for:

- problem definition,
- contention-aware communication model,
- task duplication motivation,
- baseline scheduler selection,
- algorithm comparison,
- limitations and future work.

---

## 2. NoC / MPSoC Context Reference

### Tang et al. 2017 — Optimization of Duplication-Based Schedules on Network-on-Chip Based MPSoCs

**Local path**

`docs/papers/noc/tang_2017_optimization_duplication_based_schedules_noc_mpsoc.pdf`

**Role in this project**

This paper supports the NoC-based multicore system context.

It explains why task and communication co-scheduling matters in Network-on-Chip based Multi-Processor System-on-Chip systems.

**Concepts relevant to this project**

- NoC-based MPSoCs.
- Computation and communication co-scheduling.
- Communication contention in NoC systems.
- Task duplication to reduce communication latency.
- Difference between contention-free and contention-aware scheduling.
- Optimization of duplication-based schedules when mapping and duplication decisions are known.

**Implemented in this project**

- 2D mesh NoC model.
- Deterministic XY routing.
- Explicit link interval reservation.
- Communication contention through occupied NoC links.
- Metrics for link utilization.

**Not implemented**

- Integer Linear Programming (ILP).
- Optimization with known mapping and duplication strategy.
- Exact reproduction of the paper’s CF-ILP or CA-ILP.
- Real application benchmark set from the paper.

**How to use in writing**

Use this paper to justify why the project moves from a generic communication network model to a NoC-based setting.

Do not use this paper to redefine the core heuristic algorithm.

---

## 3. List Scheduling and Duplication Reference

### Tang et al. 2010 — List scheduling with duplication for heterogeneous computing systems

**Local path**

`docs/papers/duplication/tang_2010_list_scheduling_with_duplication_hefd.pdf`

**Role in this project**

This is a secondary reference for list scheduling with task duplication.

**Concepts relevant to this project**

- List scheduling.
- Earliest finish time.
- Parent task duplication.
- Duplication as a way to reduce task start time.
- Comparison with HEFT-like methods.

**Implemented in this project**

- HEFT-like list scheduling baseline.
- Parent-only duplication in CD-LS and CA-D.
- Earliest finish time based processor selection.

**Not implemented**

- Heterogeneous processor model.
- HEFD priority model.
- Heterogeneous computation and communication weights.
- Dynamic environment extension.

**How to use in writing**

Use this paper in related work to show that parent duplication has been used in list scheduling algorithms.

Do not claim that the implementation is HEFD.

---

## 4. Improved / Limited Duplication Reference

### Bansal et al. 2003 — An improved duplication strategy for scheduling precedence constrained graphs in multiprocessor systems

**Local path**

`docs/papers/duplication/bansal_2003_improved_duplication_strategy.pdf`

**Role in this project**

This is a secondary reference for selective or improved duplication strategies.

**Concepts relevant to this project**

- Duplication can reduce communication delay.
- Blind duplication can increase schedule length or resource usage.
- Improved duplication strategies attempt to avoid unnecessary duplication.
- Duplication is especially useful when communication latency is significant.

**Implemented in this project**

- Selective duplication using `Delta_EFT > 0`.
- Duplicate only when it improves earliest finish time.

**Not implemented**

- Exact Bansal algorithm.
- Processor-limited strategy from that work.
- Paper-specific benchmark reproduction.

**How to use in writing**

Use this paper to motivate why duplication must be selective rather than unconditional.

---

## 5. Resource-Aware / Reduced Duplication Reference

### Mei et al. 2014 — A resource-aware scheduling algorithm with reduced task duplication

**Local path**

`docs/papers/duplication/mei_2014_resource_aware_reduced_duplication.pdf`

**Role in this project**

This is a future-work reference.

**Concepts relevant to this project**

- Task duplication can waste resources.
- Some duplicated tasks may not reduce makespan.
- Reduced duplication can preserve performance while lowering resource usage.
- Resource-aware scheduling is important when processor or memory resources are limited.

**Implemented in this project**

- Basic duplicate count and task instance ratio metrics.
- Duplicate only when `Delta_EFT > 0`.

**Not implemented**

- Redundant duplicate removal.
- Resource-aware pruning.
- Memory-aware duplication control.
- Explicit resource consumption optimization.

**How to use in writing**

Use this paper to justify the limitation:

> The current scheduler does not remove redundant duplicates after scheduling. Resource-aware duplicate pruning is future work.

---

## 6. Bottom-Up Duplication Reference

### Bozdag et al. 2006 — A task duplication based bottom-up scheduling algorithm for heterogeneous environments

**Local path**

`docs/papers/duplication/bozdag_2006_task_duplication_bottom_up_scheduling_dbus.pdf`

**Role in this project**

This is a secondary reference for bottom-up duplication and ancestor-oriented duplication.

**Concepts relevant to this project**

- Bottom-up task duplication.
- Critical-path or ancestor-based duplication.
- Duplication can be used beyond direct parents.
- Heterogeneous environments.

**Implemented in this project**

- Direct parent duplication only.
- Upward-rank / bottom-level style priority.

**Not implemented**

- Full bottom-up scheduling.
- Recursive ancestor duplication.
- Heterogeneous processor model.

**How to use in writing**

Use this paper to discuss why recursive ancestor duplication is a meaningful future extension.

---

## 7. Clustering-Based Duplication Reference

### He et al. 2019 — A Novel Task-Duplication Based Clustering Algorithm for Heterogeneous Computing Environments

**Local path**

`docs/papers/duplication/he_2019_task_duplication_based_clustering_tdca.pdf`

**Role in this project**

This is a related-work and future-work reference.

**Concepts relevant to this project**

- Task clustering.
- Duplication-based clustering.
- Heterogeneous computing environments.
- Scheduling can be approached by clustering tasks before mapping.

**Implemented in this project**

- None directly.

**Not implemented**

- Clustering.
- Cluster-level scheduling.
- Heterogeneous system model.

**How to use in writing**

Use this paper only as related work.

Do not add clustering to the current implementation unless it becomes a separate future phase.

---

## 8. Energy-Aware Duplication Reference

### Liang and Pang 2017 — A Novel, Energy-Aware Task Duplication-Based Scheduling Algorithm of Parallel Tasks on Clusters

**Local path**

`docs/papers/duplication/liang_2017_energy_aware_duplication_scheduling.pdf`

**Role in this project**

This is a future-work reference for energy-aware scheduling.

**Concepts relevant to this project**

- Task duplication can increase energy consumption.
- Energy-aware scheduling trades off makespan and energy.
- Parallel task scheduling on clusters.

**Implemented in this project**

- No explicit energy model.
- No power model.
- No energy metric.

**Not implemented**

- Energy-aware objective.
- Dynamic voltage/frequency scaling.
- Power-aware processor selection.

**How to use in writing**

Use this paper only in the future work section.

Suggested future work sentence:

> Since duplication increases computation and memory pressure, future extensions may incorporate energy-aware duplication decisions.

---

## 9. Current Project Positioning

This project should be described as:

> A paper-inspired implementation of contention-aware task duplication for DAG scheduling on a 2D mesh NoC, using explicit link-interval reservation and selective parent duplication.

It is not a full reimplementation of Sinnen et al. 2011.

The main differences are:

| Aspect | Sinnen et al. 2011 | This project |
|---|---|---|
| Target network | Ideal switch / one-port and half-duplex variants | 2D mesh NoC |
| Routing | General route model | Deterministic XY routing |
| Duplication | Recursive critical-parent duplication | Direct parent duplication only |
| Redundant duplicate removal | Yes | No |
| Communication model | Edge scheduling on communication links | Directed NoC link interval reservation |
| Workloads | Random, SP, trees, fork, fork-join | Random DAGs so far |
| Evaluation | Speedup under contention simulation | Makespan, speedup vs HEFT, utilization, runtime |
| Processor model | Homogeneous processors | Homogeneous processors |
| Objective | Schedule length / speedup | Makespan plus resource metrics |

---

## 10. How Agents Should Use These Papers

When generating implementation prompts or modifying code:

1. Treat Sinnen et al. 2011 as the primary algorithmic reference.
2. Treat the NoC paper as architectural motivation, not as a requirement to implement ILP.
3. Treat the duplication papers as related work and future work.
4. Do not add energy-aware scheduling, clustering, heterogeneity, or ILP unless explicitly requested.
5. Do not claim the current project fully reproduces any paper’s exact experiments.
6. Use the papers to explain design trade-offs and limitations.
7. Keep the current implementation scope:
   - static DAG scheduling,
   - homogeneous processors,
   - 2D mesh NoC,
   - XY routing,
   - parent-only duplication,
   - explicit link-level contention.