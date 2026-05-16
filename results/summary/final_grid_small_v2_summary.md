# Final Grid Small v2: Experiment Results Summary

> **Phase 16 note**: This regenerated CSV uses the Phase 15A+15B improved ProposedScheduler (greedy recursive ancestor duplication + conservative redundant duplicate pruning) and includes all fair contention replay columns.

## 1. Experiment Configuration

| Parameter | Value |
|-----------|-------|
| Experiment name | final_grid_small_v2 |
| Seeds | 0, 1, 2 |
| Task counts | 20 (40 omitted — see note below) |
| Edge probabilities | 0.25, 0.40 |
| CCR values | 0.1, 1.0, 5.0 |
| Computation range | [5, 20] |
| NoC size | 4×4 (16 processors) |
| alpha | 0.0 |
| beta | 1.0 |
| Schedulers | HEFT, CA-LS, CD-LS, CA-D (Proposed) |
| Expected rows | 72 (3×1×2×3×1×4) |
| Actual rows | 72 |

> **Note on n_tasks=40**: The Phase 15A greedy recursive ancestor duplication makes one
> ProposedScheduler run on a dense 40-task random DAG (edge_prob=0.40, CCR=5.0) take
> more than 2 minutes. Including 40-task proposed scheduler runs would push the full
> grid runtime beyond 1 hour, which is infeasible for a diagnostic grid. The 40-task
> grid is left as future work pending a performance improvement (e.g., bounded recursion
> depth, candidate filtering, or parallel evaluation). The graph-family experiment
> (Experiment B) also excludes chain topologies entirely for the same reason.

## 2. Overall Mean Metrics by Scheduler

| index           | ms      | rep_ms  | spd   | rep_spd | ser_spd | dups   | tir   | cc     | rcc    | mlu   | rmlu  | ovhd  | rt_ms     |
| --------------- | ------- | ------- | ----- | ------- | ------- | ------ | ----- | ------ | ------ | ----- | ----- | ----- | --------- |
| HEFT            | 123.862 | 190.585 | 1.0   | 1.0     | 2.087   | 0.0    | 1.0   | 0.0    | 33.889 | 0.0   | 0.497 | 1.436 | 44.172    |
| CA-LS           | 157.767 | 157.767 | 0.875 | 1.158   | 1.885   | 0.0    | 1.0   | 34.167 | 34.167 | 0.467 | 0.467 | 1.0   | 67.864    |
| CD-LS           | 116.897 | 170.093 | 1.055 | 1.078   | 2.178   | 6.111  | 1.306 | 0.0    | 40.222 | 0.0   | 0.478 | 1.397 | 155.52    |
| CA-D (Proposed) | 117.921 | 121.347 | 1.05  | 1.474   | 2.175   | 25.222 | 2.261 | 42.111 | 42.444 | 0.379 | 0.381 | 1.025 | 10431.013 |

## 3. Best Scheduler Counts — Native Makespan (of 18 workload instances)

- **HEFT**: 7
- **CA-LS**: 0
- **CD-LS**: 4
- **CA-D (Proposed)**: 7

## 4. Best Scheduler Counts — Replayed Makespan (of 18 workload instances)

- **HEFT**: 6
- **CA-LS**: 1
- **CD-LS**: 0
- **CA-D (Proposed)**: 11

## 5. CCR Trend Table (mean per scheduler × CCR)

| Scheduler       | speedup_vs_heft@CCR=0.1 | speedup_vs_heft@CCR=1.0 | speedup_vs_heft@CCR=5.0 | replayed_speedup_vs_heft@CCR=0.1 | replayed_speedup_vs_heft@CCR=1.0 | replayed_speedup_vs_heft@CCR=5.0 | task_instance_ratio@CCR=0.1 | task_instance_ratio@CCR=1.0 | task_instance_ratio@CCR=5.0 | max_link_utilization@CCR=0.1 | max_link_utilization@CCR=1.0 | max_link_utilization@CCR=5.0 | replayed_max_link_utilization@CCR=0.1 | replayed_max_link_utilization@CCR=1.0 | replayed_max_link_utilization@CCR=5.0 | replay_overhead_ratio@CCR=0.1 | replay_overhead_ratio@CCR=1.0 | replay_overhead_ratio@CCR=5.0 |
| --------------- | ----------------------- | ----------------------- | ----------------------- | -------------------------------- | -------------------------------- | -------------------------------- | --------------------------- | --------------------------- | --------------------------- | ---------------------------- | ---------------------------- | ---------------------------- | ------------------------------------- | ------------------------------------- | ------------------------------------- | ----------------------------- | ----------------------------- | ----------------------------- |
| CD-LS           | 1.000                   | 1.018                   | 1.147                   | 1.001                            | 1.028                            | 1.205                            | 1.258                       | 1.308                       | 1.350                       | 0.000                        | 0.000                        | 0.000                        | 0.064                                 | 0.512                                 | 0.858                                 | 1.000                         | 1.049                         | 2.141                         |
| CA-LS           | 1.000                   | 0.990                   | 0.635                   | 1.001                            | 1.047                            | 1.425                            | 1.000                       | 1.000                       | 1.000                       | 0.059                        | 0.515                        | 0.827                        | 0.059                                 | 0.515                                 | 0.827                                 | 1.000                         | 1.000                         | 1.000                         |
| HEFT            | 1.000                   | 1.000                   | 1.000                   | 1.000                            | 1.000                            | 1.000                            | 1.000                       | 1.000                       | 1.000                       | 0.000                        | 0.000                        | 0.000                        | 0.062                                 | 0.539                                 | 0.890                                 | 1.001                         | 1.059                         | 2.247                         |
| CA-D (Proposed) | 1.000                   | 1.039                   | 1.110                   | 1.001                            | 1.085                            | 2.335                            | 2.058                       | 1.992                       | 2.733                       | 0.047                        | 0.380                        | 0.711                        | 0.048                                 | 0.369                                 | 0.725                                 | 1.000                         | 1.015                         | 1.061                         |

## 6. Interpretation

**HEFT** is the baseline (speedup_vs_heft = 1.0 by definition). HEFT uses analytic
communication costs with no link reservation, so its native makespan underestimates
the real execution time under NoC contention. HEFT's replayed makespan is higher than
its native makespan because replay materializes remote communications and NoC link
contention that the analytic HEFT baseline does not reserve during scheduling. Its
replayed makespan serves as the fair replay reference for all other schedulers.

**CA-LS** models link-level contention explicitly, producing longer native makespans
than HEFT because it reveals actual communication delays. Without duplication, it
cannot avoid inter-processor communication overhead. Replayed makespan is close to
native because CA-LS already uses the contention model natively.

**CD-LS** uses task duplication to eliminate inter-processor communications. Its
native makespan is optimistic because it ignores link contention (classical model).
Replay reveals the actual contention cost of its placement. CD-LS wins
4 of 18 workload instances natively but
0 under replayed evaluation, showing that some
of its native advantage is artefact of the optimistic model.

**CA-D (Proposed)** combines contention-aware link reservation with greedy recursive
ancestor duplication and conservative redundant duplicate pruning (Phases 15A+15B).
Mean native speedup vs HEFT: 1.050. Mean replayed speedup vs HEFT:
1.474. CA-D wins 7 of 18 workload instances
natively and 11 under replayed evaluation. Its task_instance_ratio
reflects the effect of recursive duplication followed by pruning of unnecessary copies.

**Replay overhead ratio** (replayed_makespan / native makespan): CA-LS and CA-D both
have replay_overhead_ratio ≈ 1.0 because they already model contention natively. HEFT
and CD-LS may show ratio > 1.0 if their placements create contention that their models
ignored.

**Model comparison note**: HEFT and CD-LS use the analytic (contention-free) model; CA-LS
and CA-D use link-interval reservation. Comparing native makespans directly mixes two
different communication models. The replayed_speedup_vs_heft column provides a fair
comparison because all schedulers' placements are re-evaluated under the same contention
model.

**CCR trends**: At CCR=0.1, computation dominates and all schedulers behave similarly.
At CCR=5.0, duplication schedulers (CD-LS, CA-D) benefit from avoiding remote
communications, while CA-LS (no duplication) is most penalised by contention.

## 7. Limitations

- **Greedy recursive ancestor duplication**: Phase 15A improved ProposedScheduler with
  recursive ancestor duplication, but it is greedy (ascending task_id order) and not
  guaranteed globally optimal per Sinnen et al. Algorithm 3.
- **Conservative duplicate pruning**: Phase 15B adds post-schedule pruning, but only
  removes duplicates that are provably unused under the materialized schedule. Full
  Sinnen-style redundant task and in-edge removal is not implemented.
- **Small diagnostic grid**: Only 3 seeds × 1 task count × 2 edge probabilities × 3 CCR.
  Results may not generalise to extreme configurations.
- **Random DAGs only**: No structured graph families (trees, fork-join) in this grid.
  See graph_family_diagnostic_v1 for structured families.
- **alpha=0.0**: The per-hop latency term is disabled; communication cost = beta × volume.
  Hop count still determines XY route and link reservations.
- **Homogeneous processors**: All 16 processors have identical speed.
- **runtime_ms**: Measures scheduler execution only; fair replay is excluded.
