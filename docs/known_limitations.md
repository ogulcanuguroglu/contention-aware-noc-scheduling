# Known Limitations

This document lists the known limitations of the project with their impact and possible future work directions.

---

## 1. Not an exact Sinnen et al. Algorithm 3 implementation

**Description:** The ProposedScheduler (CA-D) is inspired by the recursive critical-parent duplication algorithm described in Sinnen, To, Kaur (2011). However, it does not reproduce Algorithm 3 exactly. Specific deviations:

- The paper uses an ideal-switch or half-duplex network model. This project uses a 2D mesh NoC with deterministic XY routing.
- The paper's critical-parent selection identifies the predecessor that causes the largest DRT delay, then recursively duplicates its critical parent chain. This project's recursive duplication is greedy: it evaluates each predecessor independently in ascending task_id order and duplicates those that reduce EFT by more than `_EPS`. No globally optimal critical-parent chain selection is performed.
- The paper removes redundant duplicate tasks and their associated in-edges after scheduling (full redundant task removal). This project's pruning is conservative and does not remove link intervals or reroute communications.

**Impact:** The scheduler may not achieve the same duplication depth or makespan as an exact Algorithm 3 implementation. It may duplicate suboptimal ancestors or retain necessary duplicates that a globally optimal approach would remove.

**Possible future work:** Implement the exact critical-parent chain selection with global optimality; implement full redundant task and in-edge removal.

---

## 2. Greedy recursive ancestor duplication

**Description:** Ancestor duplication in `_place_recursive_duplicate` is greedy: predecessors are evaluated independently in ascending `task_id` order. Committing an earlier predecessor's duplication affects the state seen by later predecessors, but no backtracking is performed.

**Impact:** The greedy order may produce different (not necessarily worse, but not guaranteed better) results than an exhaustive or optimal ancestor selection strategy.

**Possible future work:** Evaluate all ancestor subsets and choose the combination that minimizes EFT; add bounded recursion depth or candidate filtering to reduce runtime.

---

## 3. Conservative pruning only

**Description:** `_prune_redundant_duplicates` removes a duplicate instance only when all four conditions hold simultaneously (not primary, other instance exists, not a source for any materialized CommunicationInstance, no successor would lose its only data source on the same processor). The pruning does not reschedule tasks, reroute communications, or remove link intervals.

**Impact:** Some provably redundant duplicates may be retained if they are technically removable only after rerouting communications. `task_instance_ratio` and `duplicate_task_count` may be higher than an optimal pruning strategy would produce.

**Possible future work:** Implement full Sinnen-style redundant task and in-edge removal with communication rerouting; evaluate the effect on task_instance_ratio and makespan.

---

## 4. Synthetic workloads only

**Description:** All experiments use synthetically generated DAGs: random Erdős–Rényi DAGs and structured graph families (fork, join, fork_join, in_tree, out_tree, diamond). No publicly available real-application DAG benchmarks were used.

**Impact:** Results may not generalize to the communication patterns, task count distributions, or structural properties of real HPC or embedded applications.

**Possible future work:** Evaluate on Standard Task Graph Set (STG), Pegasus workflow DAGs, HPEC Graph Challenge benchmarks, or Topcuoglu et al. HEFT paper examples.

---

## 5. Reduced final diagnostic grids

**Description:** Phase 16 experiments use smaller grids than originally planned:

- **Experiment A (final_grid_small_v2):** n_tasks=40 excluded. Dense 40-task DAGs cause ProposedScheduler to take >2 minutes per run.
- **Experiment B (graph_family_diagnostic_v1):** chain family excluded entirely. Even chain n_tasks=20 causes ProposedScheduler to hang due to the maximum ancestor chain depth in linear topologies.

**Impact:** Statistical coverage is reduced. Results may not reflect behavior at larger task counts or on chain-structured workloads.

**Possible future work:** Implement bounded recursion depth or candidate filtering to make ProposedScheduler feasible on large/deep DAGs; then re-run the full planned grids.

---

## 6. Chain family excluded from graph-family grid

**Description:** The `chain` graph family generator exists in `src/graph_families.py` and works correctly for HEFT, CA-LS, and CD-LS. It is excluded from Phase 16 experiments because the greedy recursive ancestor duplication in ProposedScheduler traverses the full chain depth per task placement, making runtime exponential in chain length.

**Impact:** No Phase 16 experimental results for chain-structured workloads.

**Possible future work:** Implement recursion depth limiting or ancestor candidate filtering; run chain diagnostics with bounded depth.

---

## 7. No real application DAGs

**Description:** No real-world application task graphs from production workloads (scientific workflows, signal processing pipelines, multimedia applications) were evaluated.

**Impact:** The practical relevance of the scheduler's performance on embedded or HPC workloads cannot be verified from the current results.

**Possible future work:** Obtain real DAG benchmarks and adapt them to the homogeneous NoC model by ignoring heterogeneous computation weights or applying normalization.

---

## 8. No energy model

**Description:** No power or energy objective is included. Task duplication increases computation and therefore energy consumption, but this project only minimizes makespan.

**Impact:** CA-D may produce energy-inefficient schedules due to redundant task executions. The `task_instance_ratio` metric provides a proxy for computation overhead, but no watt-second metric is computed.

**Possible future work:** Add an energy cost model based on computation counts and communication volume; explore energy-makespan trade-off (cf. Liang and Pang, 2017).

---

## 9. No alpha sweep in final diagnostic grids

**Description:** All Phase 16 experiments fix `alpha=0.0`. The per-hop latency term in `duration = alpha * hop_count + beta * vol` is disabled. Only the volume-dependent term `beta × vol` contributes to communication duration.

**Impact:** The effect of hop-count distance on scheduler behavior (spatial locality, placement of tasks near communication partners) is not captured in the Phase 16 results. At `alpha=0.0`, two tasks on diagonally opposite processors of the mesh have the same communication duration as two neighboring tasks (if volume is the same).

**Possible future work:** Run experiments with `alpha > 0` to study how hop-count latency affects duplication benefit and scheduler comparison.

---

## 10. No per-flit or cycle-level NoC simulation

**Description:** Communication is reserved as a single atomic interval on all route links simultaneously (whole-route reservation). Real NoC routers use pipelined flit transmission: a message departs the source router before the tail flit leaves, and different flits may occupy different links at the same time.

**Impact:** Whole-route reservation overestimates link occupancy time compared to pipelined flit propagation. Two communications on overlapping routes may be serialized in this model even if their flits would not actually conflict in a real pipelined router.

**Possible future work:** Implement a pipeline-style flit-level communication model or use a wormhole routing timing approximation.

---

## 11. High scheduling overhead of ProposedScheduler (CA-D)

**Description:** For a DAG with `n` tasks and `p` processors, ProposedScheduler creates O(n × p × parents(t)) state clones per scheduling step, each of which may involve further clones for recursive ancestor probing. Observed runtimes:

- n_tasks=20, 4×4 NoC: CA-D ~10 s per run (vs HEFT < 0.1 s)
- n_tasks=40, 4×4 NoC, high CCR: CA-D >120 s per run

**Impact:** Large DAGs, large meshes, or dense ancestor graphs make CA-D practically infeasible without optimization. The Phase 16 grids were reduced because of this constraint. The runtime ratio CA-D/HEFT is approximately 236× in Experiment A.

**Possible future work:** Candidate filtering (evaluate only processors near existing task instances), bounded recursion depth, early termination when Delta_EFT is provably zero, parallel evaluation of processor candidates.
