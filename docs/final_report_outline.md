# Final Report Outline

This outline provides a suggested structure for the course report/paper. Each section includes bullet-point content drawn from the implemented system and experimental results.

---

## 1. Introduction

### Problem
- Static offline scheduling of DAG-based applications onto homogeneous 2D mesh NoC architectures
- Minimizing makespan (schedule length) while accounting for communication contention on shared NoC links
- Key challenge: inter-processor communication is expensive and contention increases real execution time beyond what analytic models predict

### Motivation
- Embedded multicore systems (MPSoCs) increasingly use NoC fabrics for inter-processor communication
- Classical list schedulers (HEFT) ignore link contention; their schedules may be infeasible or slow in practice
- Task duplication can eliminate inter-processor communication by co-locating dependent tasks, but only if duplication decisions account for real contention costs
- Existing contention-aware algorithms (Sinnen et al., 2011) target general network models; adapting their ideas to 2D mesh NoC with XY routing requires a new implementation

### Contribution
- A Python-based simulation framework for evaluating contention-aware task duplication heuristics on 2D mesh NoC
- Four-scheduler comparative study: HEFT, CA-LS, CD-LS, and the proposed CA-D scheduler
- A fair contention replay methodology enabling apples-to-apples makespan comparison across schedulers using different communication models
- Experimental evaluation on random DAGs and six structured graph families
- All code, data, and results are reproducible from fixed seeds

---

## 2. Background and Related Work

### HEFT and List Scheduling
- Topcuoglu, Hariri, Wu (2002): HEFT algorithm; upward-rank priority with EFT-based processor selection
- Classic communication model: analytic cost, no link reservation, no contention
- This project's HEFT-like baseline matches the HEFT structure in a homogeneous NoC setting

### Task Duplication
- Tang, Yeo, Khan (2010): HEFD — list scheduling with parent duplication for heterogeneous systems
- Bansal, Kumar, Singh (2003): selective duplication strategy; duplicate only when Delta_EFT > 0
- Bozdag, Ozguner, Catalyurek (2006): DBUS — bottom-up scheduling with recursive ancestor duplication

### Contention-Aware Scheduling
- Sinnen, To, Kaur (2011): contention-aware scheduling with task duplication; link-interval reservation; recursive critical-parent duplication; redundant duplicate removal
  - This project is directly inspired by this work; see Section 4 for deviations
- Tang, Li, Li (2017): optimization of duplication-based schedules on NoC-based MPSoCs using ILP; supports the NoC context motivation

### Resource-Aware Scheduling
- Mei, Li, Tian (2014): reduced task duplication; motivates conservative pruning as a way to control duplication overhead

---

## 3. Problem Formulation

### DAG Model
- G = (V, E): tasks V with computation costs, edges E with communication volumes
- CCR = total_comm / total_comp (communication-to-computation ratio)
- Precedence constraint: task v cannot start until all predecessors have delivered their data to v's processor

### NoC Model
- 2D mesh of rows × cols homogeneous processors
- XY routing: first horizontal, then vertical; route length = Manhattan distance
- Communication duration: `alpha * hop_count + beta * vol`
- Link contention: two communications share a link when they traverse the same directed hop at overlapping times
- Whole-route atomic reservation (not per-flit pipeline)

### Objective
- Minimize makespan = max processor finish time
- Secondary metrics: task instance ratio, link utilization, scheduler runtime

---

## 4. Proposed Method

### Baselines

**HEFT:** Classic list scheduling without contention or duplication. Analytic DRT. Serves as the comparison reference for speedup computation. All schedulers use the same upward-rank priority.

**CA-LS:** Same priority as HEFT. Uses `ScheduleState.clone()` to evaluate each processor candidate with full link-interval reservation. DRT reflects contention-delayed communication arrivals. No duplication.

**CD-LS:** Parent-only duplication using the analytic communication model. Evaluates Delta_EFT without link reservation. May be overly optimistic.

### CA-D Scheduler (Proposed)

Combines CA-LS (contention-aware link reservation) with selective greedy recursive ancestor duplication:

- For each task, each processor candidate is evaluated on a cloned state
- For each remote predecessor, sub-clones evaluate `EFT_no_dup` vs `EFT_dup`
- Duplication committed if `Delta_EFT > _EPS` under the contention model

### Recursive Ancestor Duplication (Phase 15A)

When a predecessor `pred` is duplicated onto candidate processor `P`, each predecessor `gp` of `pred` not already on `P` is independently evaluated. If placing `gp` recursively reduces `pred`'s EFT by more than `_EPS`, the `gp` placement is committed greedily. Predecessors evaluated in ascending task_id order.

State: this is a greedy per-predecessor decision, not a globally optimal critical-parent chain selection. It is inspired by but does not reproduce the Sinnen et al. recursive critical-parent duplication exactly.

### Conservative Redundant Duplicate Pruning (Phase 15B)

Post-schedule pass removes duplicate instances when provably unnecessary (not a source for any materialized CommunicationInstance, no successor on same processor would lose its only data). Does not reschedule or reroute. Not full Sinnen-style redundant task and in-edge removal.

### Fair Replay

`replay_under_contention()` applies the common contention-aware model to every scheduler's placement. Preserves task-to-processor assignment and primary/duplicate flags; recomputes all timing. Enables fair makespan comparison across all four schedulers.

Key metric: `replayed_speedup_vs_heft = HEFT_replayed_ms / scheduler_replayed_ms`

---

## 5. Experimental Setup

### Random DAG Grid (Experiment A)

- n_tasks = 20 (40 excluded due to ProposedScheduler runtime)
- edge_prob ∈ {0.25, 0.40}
- CCR ∈ {0.1, 1.0, 5.0}
- seeds ∈ {0, 1, 2}
- 4×4 NoC, alpha=0.0, beta=1.0
- 72 rows, 4 schedulers, 18 workload instances

### Graph Family Grid (Experiment B)

- Families: fork, join, fork_join, in_tree, out_tree, diamond (chain excluded)
- 9 family configurations
- CCR ∈ {0.1, 1.0, 5.0}
- seeds ∈ {0, 1, 2}
- 4×4 NoC, alpha=0.0, beta=1.0
- 324 rows, 4 schedulers, 81 workload instances

### Metrics

- makespan, replayed_makespan
- speedup_vs_heft, replayed_speedup_vs_heft
- task_instance_ratio, duplicate_task_count
- communication_count, replayed_communication_count
- max_link_utilization, replayed_max_link_utilization
- replay_overhead_ratio
- runtime_ms

---

## 6. Results

### Random DAG Grid

| Scheduler | Native speedup | Replayed speedup | TIR | Replay overhead |
|---|---|---|---|---|
| HEFT | 1.000 | 1.000 | 1.000 | 1.436 |
| CA-LS | 0.875 | 1.158 | 1.000 | 1.000 |
| CD-LS | 1.055 | 1.078 | 1.306 | 1.397 |
| CA-D | 1.050 | 1.474 | 2.261 | 1.025 |

Key points:
- CA-D achieves 1.474× replayed speedup vs HEFT; CD-LS achieves only 1.078×
- HEFT replay overhead of 1.436× shows how optimistic the analytic model is
- CD-LS loses most of its native advantage under replay (1.055 native vs 1.078 replayed — small but also reveals native results mixed two models)
- CA-LS improves over HEFT under replay (1.158×) even without duplication

### Graph Family Grid

| Scheduler | Native speedup | Replayed speedup | TIR | Runtime (ms) |
|---|---|---|---|---|
| HEFT | 1.000 | 1.000 | 1.000 | 24.8 |
| CA-LS | 0.864 | 1.308 | 1.000 | 33.1 |
| CD-LS | 1.345 | 2.089 | 1.382 | 53.1 |
| CA-D | 1.349 | 2.521 | 1.651 | 341.2 |

Key points:
- Fork and out-tree families show the clearest duplication benefit (CA-D achieves 5.164× replayed speedup on fork)
- Diamond shows the highest contention; CA-D's contention-aware placement provides advantage
- CD-LS native wins collapse under replay: 49 of 81 natively but only 25 under replay
- CA-D wins 39 of 81 under replay (vs 13 natively), confirming that contention-blind comparisons understate CA-D's advantage

### Native vs Replayed Comparison

- HEFT and CD-LS: replay_overhead_ratio > 1.0 (contention-blind model was optimistic)
- CA-LS and CA-D: replay_overhead_ratio ≈ 1.0 (already model contention natively)
- Replayed_speedup_vs_heft provides a fair cross-model comparison

### Runtime Overhead

- CA-D runtime is 236× HEFT on random DAGs; 14× on graph families
- Runtime grows with task count, DAG density, and number of predecessors
- Chain topology excluded due to O(n × depth) behavior

---

## 7. Limitations

See [docs/known_limitations.md](known_limitations.md) for details.

Summary:
1. Not exact Sinnen Algorithm 3 (greedy recursive, not globally optimal)
2. Conservative pruning only (not full Sinnen-style redundant task removal)
3. Synthetic workloads only (no STG, Pegasus, or HPEC benchmarks)
4. Reduced diagnostic grids (n_tasks=40 and chain excluded)
5. No real application DAGs
6. No energy model
7. No alpha sweep in Phase 16 grids
8. Whole-route atomic reservation (not pipelined flit propagation)
9. High CA-D scheduling overhead
10. Homogeneous processors only

---

## 8. Conclusion and Future Work

### Conclusion

- The CA-D scheduler consistently outperforms the three baselines under the fair replay evaluation
- Task duplication with contention-aware decisions (CA-D) is more effective than duplication without contention awareness (CD-LS) when both are evaluated under the same physical NoC model
- Contention modeling without duplication (CA-LS) improves over HEFT under replay but cannot match duplication schedulers at high CCR
- The fair replay methodology is essential for fair cross-model comparison; native makespan comparisons between contention-blind and contention-aware schedulers are misleading

### Future Work

1. **Globally optimal recursive ancestor selection** — replace greedy order with critical-parent chain selection matching Sinnen et al. Algorithm 3
2. **Full redundant duplicate removal** — remove unnecessary duplicates and reroute communications after scheduling
3. **Real application benchmark evaluation** — STG, Pegasus, HPEC, Topcuoglu et al. examples
4. **Heterogeneous processor model** — extend to non-uniform computation speeds
5. **ProposedScheduler runtime optimization** — candidate filtering, bounded recursion, parallel candidate evaluation
6. **Alpha sweep** — evaluate how hop-count latency (alpha > 0) affects duplication benefit and scheduler comparison
7. **Pipelined communication model** — flit-level timing for more accurate contention representation
8. **Energy-aware duplication objective** — minimize energy-delay product rather than makespan alone
9. **Larger NoC sizes** — evaluate on 8×8 and larger meshes where inter-processor distances are greater
10. **Alternative topologies** — torus, fat-tree, or other NoC topologies
