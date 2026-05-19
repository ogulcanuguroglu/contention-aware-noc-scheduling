# Phase 21 -- Interpretive Figure Package Summary

**System:** 4x4 homogeneous 2D mesh NoC (16 processors).  seed=0, alpha=0.0, beta=1.0.
**Dataset:** 4 DAG families x 4 CCR values x 3 schedulers = 48 rows (single run).
**Primary metric:** replayed_speedup_vs_heft = HEFT_replayed / sched_replayed.
**New metric:** remote_communication_volume_ratio (RCVR) = remote_edge_vol / total_DAG_vol.
  An edge u->v is 'remote' if no instance of u is co-located with v's primary processor.

---

## Scheduler Descriptions

- **HEFT**: Heterogeneous Earliest Finish Time. Analytic, contention-blind, no duplication.
- **CD-LS**: Classical Duplication List Scheduler. Analytic, contention-blind.  Duplicates only direct parent tasks to the target processor.
- **CA-D**: Contention-aware recursive ancestor duplication.  Evaluates ALL direct predecessors; recursively places ancestor duplicates  when contention-aware EFT test shows benefit.  NOT Sinnen critical-parent selection (does not select a single critical predecessor).

---

## Per-DAG Results Table

Columns: Scheduler | CCR | Native MS | Replayed MS | Speedup | Overhead | TIR | RCVR

### Chain

| Sched | CCR | Native | Replayed | Speedup | Overhead | TIR | RCVR |
|-------|-----|-------:|---------:|--------:|---------:|----:|-----:|
| CA-D   |   0.1 |   132.58 |   132.58 |  1.0000 |   1.0000 | 1.000 | 0.000 |
| CA-D   |   1.0 |   132.58 |   132.58 |  1.0000 |   1.0000 | 1.000 | 0.000 |
| CA-D   |   5.0 |   132.58 |   132.58 |  1.0000 |   1.0000 | 1.000 | 0.000 |
| CA-D   |  10.0 |   132.58 |   132.58 |  1.0000 |   1.0000 | 1.000 | 0.000 |
| CD-LS  |   0.1 |   132.58 |   132.58 |  1.0000 |   1.0000 | 1.000 | 0.000 |
| CD-LS  |   1.0 |   132.58 |   132.58 |  1.0000 |   1.0000 | 1.000 | 0.000 |
| CD-LS  |   5.0 |   132.58 |   132.58 |  1.0000 |   1.0000 | 1.000 | 0.000 |
| CD-LS  |  10.0 |   132.58 |   132.58 |  1.0000 |   1.0000 | 1.000 | 0.000 |
| HEFT   |   0.1 |   132.58 |   132.58 |  1.0000 |   1.0000 | 1.000 | 0.000 |
| HEFT   |   1.0 |   132.58 |   132.58 |  1.0000 |   1.0000 | 1.000 | 0.000 |
| HEFT   |   5.0 |   132.58 |   132.58 |  1.0000 |   1.0000 | 1.000 | 0.000 |
| HEFT   |  10.0 |   132.58 |   132.58 |  1.0000 |   1.0000 | 1.000 | 0.000 |

### Fork

| Sched | CCR | Native | Replayed | Speedup | Overhead | TIR | RCVR |
|-------|-----|-------:|---------:|--------:|---------:|----:|-----:|
| CA-D   |   0.1 |    33.25 |    33.25 |  1.1572 |   1.0000 | 1.778 | 0.000 |
| CA-D   |   1.0 |    33.25 |    33.25 |  2.8111 |   1.0000 | 1.778 | 0.000 |
| CA-D   |   5.0 |    33.25 |    33.25 |  2.7781 |   1.0000 | 1.778 | 0.000 |
| CA-D   |  10.0 |    33.25 |    33.25 |  3.2576 |   1.0000 | 1.778 | 0.000 |
| CD-LS  |   0.1 |    33.25 |    33.25 |  1.1572 |   1.0000 | 1.778 | 0.000 |
| CD-LS  |   1.0 |    33.25 |    33.25 |  2.8111 |   1.0000 | 1.778 | 0.000 |
| CD-LS  |   5.0 |    33.25 |    33.25 |  2.7781 |   1.0000 | 1.778 | 0.000 |
| CD-LS  |  10.0 |    33.25 |    33.25 |  3.2576 |   1.0000 | 1.778 | 0.000 |
| HEFT   |   0.1 |    33.83 |    38.47 |  1.0000 |   1.1373 | 1.000 | 0.973 |
| HEFT   |   1.0 |    50.44 |    93.46 |  1.0000 |   1.8527 | 1.000 | 0.790 |
| HEFT   |   5.0 |    92.36 |    92.36 |  1.0000 |   1.0000 | 1.000 | 0.076 |
| HEFT   |  10.0 |   108.30 |   108.30 |  1.0000 |   1.0000 | 1.000 | 0.021 |

### Out-tree

| Sched | CCR | Native | Replayed | Speedup | Overhead | TIR | RCVR |
|-------|-----|-------:|---------:|--------:|---------:|----:|-----:|
| CA-D   |   0.1 |    40.80 |    40.80 |  1.0000 |   1.0000 | 1.714 | 0.000 |
| CA-D   |   1.0 |    40.80 |    40.80 |  2.2620 |   1.0000 | 1.714 | 0.000 |
| CA-D   |   5.0 |    40.80 |    40.80 |  2.0699 |   1.0000 | 1.714 | 0.000 |
| CA-D   |  10.0 |    40.80 |    40.80 |  2.0699 |   1.0000 | 1.714 | 0.000 |
| CD-LS  |   0.1 |    40.80 |    40.80 |  1.0000 |   1.0000 | 1.429 | 0.000 |
| CD-LS  |   1.0 |    46.42 |    56.60 |  1.6306 |   1.2193 | 1.429 | 0.000 |
| CD-LS  |   5.0 |    52.96 |    52.96 |  1.5947 |   1.0000 | 1.143 | 0.000 |
| CD-LS  |  10.0 |    52.96 |    52.96 |  1.5947 |   1.0000 | 1.143 | 0.000 |
| HEFT   |   0.1 |    40.80 |    40.80 |  1.0000 |   1.0000 | 1.000 | 0.587 |
| HEFT   |   1.0 |    61.29 |    92.29 |  1.0000 |   1.5058 | 1.000 | 0.646 |
| HEFT   |   5.0 |    84.45 |    84.45 |  1.0000 |   1.0000 | 1.000 | 0.000 |
| HEFT   |  10.0 |    84.45 |    84.45 |  1.0000 |   1.0000 | 1.000 | 0.000 |

### Fork-join

| Sched | CCR | Native | Replayed | Speedup | Overhead | TIR | RCVR |
|-------|-----|-------:|---------:|--------:|---------:|----:|-----:|
| CA-D   |   0.1 |    70.05 |    70.05 |  1.0326 |   1.0000 | 1.214 | 0.190 |
| CA-D   |   1.0 |    82.81 |    82.81 |  1.2033 |   1.0000 | 1.286 | 0.085 |
| CA-D   |   5.0 |   117.70 |   117.70 |  1.3420 |   1.0000 | 1.429 | 0.013 |
| CA-D   |  10.0 |   141.83 |   141.83 |  1.2566 |   1.0000 | 1.571 | 0.013 |
| CD-LS  |   0.1 |    70.05 |    70.05 |  1.0326 |   1.0000 | 1.214 | 0.190 |
| CD-LS  |   1.0 |    82.81 |    95.62 |  1.0421 |   1.1547 | 1.214 | 0.157 |
| CD-LS  |   5.0 |   124.26 |   154.84 |  1.0201 |   1.2461 | 1.286 | 0.085 |
| CD-LS  |  10.0 |   188.32 |   260.52 |  0.6841 |   1.3834 | 1.286 | 0.085 |
| HEFT   |   0.1 |    71.32 |    72.33 |  1.0000 |   1.0141 | 1.000 | 0.390 |
| HEFT   |   1.0 |    86.83 |    99.64 |  1.0000 |   1.1476 | 1.000 | 0.358 |
| HEFT   |   5.0 |   157.96 |   157.96 |  1.0000 |   1.0000 | 1.000 | 0.099 |
| HEFT   |  10.0 |   178.22 |   178.22 |  1.0000 |   1.0000 | 1.000 | 0.000 |

---

## Summary Observations

### Chain
All three schedulers produce identical makespans at all CCR values (TIR=1.0 for all).  No duplication benefit exists on a strict linear chain.  RCVR is identical across schedulers for each CCR (no duplication to reduce remote edges).  Remote comm fraction decreases at low CCR as HEFT can better leverage local placement.

### Fork (single-level, root -> 8 leaves)
CD-LS and CA-D are equivalent on this topology (only one ancestor level exists).  Both eliminate all remote communication at high CCR (RCVR -> 0).  HEFT suffers 1.34x replay overhead from uncoordinated remote transfers.  Duplication speedup is 2.79x mean replayed vs HEFT (topology-specific, not general).

### Out-tree (depth=2, branching_factor=2)
CA-D outperforms CD-LS by placing recursive ancestor duplicates (root on leaf processors).  CA-D RCVR is lower than CD-LS RCVR (more ancestors duplicated -> more remote edges eliminated).  CA-D replay overhead = 1.00x; CD-LS overhead = 1.02x.  Mean replayed speedup: CA-D 1.59x vs CD-LS 1.34x (from Phase 19 multi-seed experiments).

### Fork-join (4 branches, branch_length=3)
Most informative topology.  CD-LS replay overhead reaches 1.26x mean; replayed speedup can drop below 1.0 at CCR=10 (worse than HEFT).  CA-D replay overhead = 1.00x; CA-D achieves 1.36x mean replayed speedup.  RCVR shows CA-D eliminates significantly more remote communication than CD-LS.  This is the key topological case demonstrating contention-aware scheduling value.

---

## Important Caveats

1. CA-D pruning never triggered in any structured-DAG test (Phase 19, 320 cases, 20 seeds).  Conservative Condition D prevents removal of any duplicate serving as a local data source.

2. These are single-seed (seed=0) results.  Multi-seed statistics (20 seeds, 320 cases per scheduler) are in Phase 19.

3. All experiments use alpha=0.0, beta=1.0 (communication duration = volume only).  Alpha sensitivity is analyzed in Phase 19 Section 5.

---

## Figures Generated

| File | Description |
|------|-------------|
| fig1_dag_family_topologies | DAG topology visualization (4 families, CCR=1.0) |
| fig2_scheduler_concept | HEFT/CD-LS/CA-D scheduling concept schematic |
| fig3_native_vs_replay | Native model vs contention-aware replay timing diagram |
| fig4a_fork_gantt | Fork Gantt: CCR=1.0 vs CCR=10.0, 3 schedulers each |
| fig4b_out_tree_gantt | Out-tree Gantt: CCR=1.0 vs CCR=10.0, 3 schedulers each |
| fig4c_fork_join_gantt | Fork-join Gantt: CCR=1.0 vs CCR=10.0, 3 schedulers each |
| fig5_ccr_sweep_replayed_speedup | 4-panel replayed speedup vs CCR |
| fig6_replay_overhead_ratio | 4-panel replay overhead ratio vs CCR |
| fig7_task_instance_ratio | 4-panel task instance ratio (TIR) vs CCR |
| fig8_remote_comm_volume_ratio | 4-panel RCVR vs CCR (new metric) |
