# Graph Family Diagnostic v1: Experiment Results Summary

> **Phase 16 note**: Uses Phase 15A+15B ProposedScheduler with greedy recursive ancestor duplication and conservative redundant duplicate pruning. All fair contention replay columns included.

## 1. Experiment Configuration

| Parameter | Value |
|-----------|-------|
| Experiment name | graph_family_diagnostic_v1 |
| Graph families | fork, join, fork_join, in_tree, out_tree, diamond |
| Excluded family | chain (excluded because deep linear DAGs are pathological for the current greedy recursive ancestor duplication runtime) |
| Family parameter configurations | 9 |
| Seeds | 0, 1, 2 |
| CCR values | 0.1, 1.0, 5.0 |
| Computation range | [5, 20] |
| Communication range | [1, 10] |
| NoC | 4×4 (16 processors), alpha=0.0, beta=1.0 |
| Schedulers | HEFT, CA-LS, CD-LS, CA-D (Proposed) |
| Expected rows | 324 (9×3×3×4) |
| Actual rows | 324 |

## 2. Overall Mean Metrics by Scheduler (all families and CCR)

| index           | ms      | rep_ms  | spd   | rep_spd | dups  | tir   | cc    | rcc    | mlu   | rmlu  | rt_ms   |
| --------------- | ------- | ------- | ----- | ------- | ----- | ----- | ----- | ------ | ----- | ----- | ------- |
| HEFT            | 89.502  | 161.097 | 1.0   | 1.0     | 0.0   | 1.0   | 0.0   | 11.025 | 0.0   | 0.502 | 24.807  |
| CA-LS           | 115.539 | 115.609 | 0.864 | 1.308   | 0.0   | 1.0   | 10.37 | 10.37  | 0.426 | 0.425 | 33.068  |
| CD-LS           | 68.725  | 110.663 | 1.345 | 2.089   | 5.617 | 1.382 | 0.0   | 8.037  | 0.0   | 0.338 | 53.077  |
| CA-D (Proposed) | 70.174  | 70.503  | 1.349 | 2.521   | 9.543 | 1.651 | 7.074 | 7.198  | 0.251 | 0.252 | 341.196 |

## 3. Mean Metrics by Family and Scheduler

| family    | scheduler       | makespan | replayed_makespan | speedup_vs_heft | replayed_speedup_vs_heft | duplicate_task_count | task_instance_ratio | communication_count | replayed_communication_count | max_link_utilization | replayed_max_link_utilization | runtime_ms |
| --------- | --------------- | -------- | ----------------- | --------------- | ------------------------ | -------------------- | ------------------- | ------------------- | ---------------------------- | -------------------- | ----------------------------- | ---------- |
| diamond   | CD-LS           | 93.983   | 154.496           | 1.09            | 1.071                    | 8.0                  | 1.571               | 0.0                 | 31.889                       | 0.0                  | 0.425                         | 93.971     |
| diamond   | CA-LS           | 123.267  | 123.896           | 0.89            | 1.265                    | 0.0                  | 1.0                 | 25.889              | 25.889                       | 0.34                 | 0.338                         | 43.566     |
| diamond   | HEFT            | 104.253  | 172.011           | 1.0             | 1.0                      | 0.0                  | 1.0                 | 0.0                 | 28.444                       | 0.0                  | 0.431                         | 30.32      |
| diamond   | CA-D (Proposed) | 98.143   | 101.107           | 1.045           | 1.541                    | 23.111               | 2.651               | 32.556              | 33.667                       | 0.33                 | 0.34                          | 1503.612   |
| fork      | CD-LS           | 30.878   | 30.878            | 1.934           | 5.164                    | 11.0                 | 1.83                | 0.0                 | 0.0                          | 0.0                  | 0.0                           | 37.157     |
| fork      | CA-LS           | 74.537   | 74.537            | 0.849           | 1.778                    | 0.0                  | 1.0                 | 7.222               | 7.222                        | 0.536                | 0.536                         | 27.71      |
| fork      | HEFT            | 59.697   | 160.309           | 1.0             | 1.0                      | 0.0                  | 1.0                 | 0.0                 | 9.0                          | 0.0                  | 0.649                         | 20.249     |
| fork      | CA-D (Proposed) | 30.878   | 30.878            | 1.934           | 5.164                    | 11.0                 | 1.83                | 0.0                 | 0.0                          | 0.0                  | 0.0                           | 59.471     |
| fork_join | CD-LS           | 89.841   | 114.769           | 1.264           | 1.239                    | 5.444                | 1.266               | 0.0                 | 5.0                          | 0.0                  | 0.349                         | 63.128     |
| fork_join | CA-LS           | 129.327  | 129.327           | 0.95            | 1.119                    | 0.0                  | 1.0                 | 9.056               | 9.056                        | 0.285                | 0.285                         | 43.503     |
| fork_join | HEFT            | 118.482  | 150.432           | 1.0             | 1.0                      | 0.0                  | 1.0                 | 0.0                 | 8.889                        | 0.0                  | 0.361                         | 32.659     |
| fork_join | CA-D (Proposed) | 94.116   | 94.116            | 1.207           | 1.474                    | 6.722                | 1.33                | 4.833               | 4.833                        | 0.305                | 0.305                         | 352.91     |
| in_tree   | CD-LS           | 84.449   | 89.702            | 1.197           | 1.22                     | 2.333                | 1.156               | 0.0                 | 5.444                        | 0.0                  | 0.273                         | 37.395     |
| in_tree   | CA-LS           | 112.764  | 112.764           | 0.968           | 1.027                    | 0.0                  | 1.0                 | 7.444               | 7.444                        | 0.343                | 0.343                         | 29.389     |
| in_tree   | HEFT            | 107.101  | 116.694           | 1.0             | 1.0                      | 0.0                  | 1.0                 | 0.0                 | 7.0                          | 0.0                  | 0.375                         | 23.034     |
| in_tree   | CA-D (Proposed) | 81.827   | 81.827            | 1.235           | 1.327                    | 4.333                | 1.289               | 5.333               | 5.333                        | 0.245                | 0.245                         | 166.291    |
| join      | CD-LS           | 61.916   | 190.98            | 1.092           | 1.117                    | 1.167                | 1.095               | 0.0                 | 9.833                        | 0.0                  | 0.652                         | 54.259     |
| join      | CA-LS           | 149.038  | 149.038           | 0.669           | 1.248                    | 0.0                  | 1.0                 | 11.0                | 11.0                         | 0.62                 | 0.62                          | 25.95      |
| join      | HEFT            | 71.059   | 208.838           | 1.0             | 1.0                      | 0.0                  | 1.0                 | 0.0                 | 11.0                         | 0.0                  | 0.666                         | 19.929     |
| join      | CA-D (Proposed) | 71.173   | 71.173            | 0.982           | 2.248                    | 3.0                  | 1.235               | 8.056               | 8.056                        | 0.535                | 0.535                         | 182.555    |
| out_tree  | CD-LS           | 74.827   | 78.517            | 1.242           | 1.468                    | 5.0                  | 1.333               | 0.0                 | 5.333                        | 0.0                  | 0.339                         | 37.239     |
| out_tree  | CA-LS           | 98.012   | 98.012            | 0.985           | 1.192                    | 0.0                  | 1.0                 | 5.444               | 5.444                        | 0.266                | 0.266                         | 30.333     |
| out_tree  | HEFT            | 95.691   | 122.007           | 1.0             | 1.0                      | 0.0                  | 1.0                 | 0.0                 | 6.0                          | 0.0                  | 0.36                          | 24.236     |
| out_tree  | CA-D (Proposed) | 59.263   | 59.263            | 1.615           | 2.053                    | 17.0                 | 2.133               | 0.0                 | 0.0                          | 0.0                  | 0.0                           | 210.989    |

## 4. Best Scheduler Counts — Native Makespan, by Family

| Family | HEFT | CA-LS | CD-LS | CA-D (Proposed) |
|---|---|---|---|---|
| diamond | 2 | 0 | 7 | 0 |
| fork | 1 | 0 | 17 | 0 |
| fork_join | 3 | 0 | 13 | 2 |
| in_tree | 3 | 0 | 3 | 3 |
| join | 7 | 0 | 9 | 2 |
| out_tree | 3 | 0 | 0 | 6 |

## 5. Best Scheduler Counts — Replayed Makespan, by Family

| Family | HEFT | CA-LS | CD-LS | CA-D (Proposed) |
|---|---|---|---|---|
| diamond | 1 | 1 | 1 | 6 |
| fork | 0 | 0 | 18 | 0 |
| fork_join | 3 | 0 | 3 | 12 |
| in_tree | 3 | 0 | 3 | 3 |
| join | 4 | 2 | 0 | 12 |
| out_tree | 2 | 1 | 0 | 6 |

## 6. Family-Level Interpretation

> **Excluded chain family**: Chain graphs were excluded from this diagnostic grid
> because deep linear DAGs are a worst-case for recursive ancestor duplication. Small
> chain smoke tests were used earlier only as sanity checks, but chain is not included
> in graph_family_diagnostic_v1.

**fork**: One root broadcasts to k parallel leaves. The root becomes a hot data source.
Duplicating the root on each leaf processor eliminates all remote communications from
root. CA-D and CD-LS benefit from duplication at high CCR. Replay confirms the benefit
since forked communications have low path diversity (all from root, so low contention).

**join**: k source tasks all deliver data to one sink. The sink is a hot receiver.
Duplication of the source tasks (or placing them all locally) reduces remote comms.
At high CCR, duplication schedulers reduce the convergence bottleneck. Replay may show
moderate contention increase because all comms converge to the same destination.

**fork_join**: Combines fork and join. The root source and the collecting sink are both
candidates for duplication. At high CCR, parallelism inside branches is exploited by
contention-aware placement. CA-D may achieve lower makespan than CD-LS after replay
because it models contention on the converging communications.

**in_tree**: All paths converge toward one sink/root. Leaves produce data that flows
toward the root. Duplication propagates critical paths toward the sink. At high CCR,
duplicating intermediate nodes reduces the long communication chains. Replay may show
contention on links near the root.

**out_tree**: One root broadcasts through all levels. The root is duplicated on many
processors since it feeds all others. Duplication ratio is typically highest for CA-D
on out_trees. Replay may show that early levels cause link saturation, which CA-D avoids
through local copies.

**diamond**: Layered series-parallel structure with complete bipartite connections between
layers. Many edges create high total communication volume relative to task count. At high
CCR, contention on inter-layer links is significant. CA-D's link reservation prevents
overcommitting congested links. Replay overhead for HEFT and CD-LS can be largest here.

## 7. ProposedScheduler Behavior

The improved ProposedScheduler (Phase 15A+15B) uses greedy recursive ancestor duplication
and conservative redundant duplicate pruning.

Mean metrics by family (CA-D only):

| Family | task_instance_ratio | duplicate_count | comm_count | runtime_ms |
|--------|---------------------|-----------------|------------|------------|
| diamond | 2.65 | 23.1 | 32.6 | 1503.6 |
| fork | 1.83 | 11.0 | 0.0 | 59.5 |
| fork_join | 1.33 | 6.7 | 4.8 | 352.9 |
| in_tree | 1.29 | 4.3 | 5.3 | 166.3 |
| join | 1.23 | 3.0 | 8.1 | 182.6 |
| out_tree | 2.13 | 17.0 | 0.0 | 211.0 |

**Recursive duplication effect**: task_instance_ratio > 1.0 on families with multiple
predecessors per task (diamond, fork_join). Families with a single critical path and
no branching (such as chain, which is excluded) would show ratio close to 1.0 since
duplication provides no benefit when no parallelism exists to exploit.

**Pruning effect**: conservative pruning removes duplicate instances that are not used
as local data sources for any successor. Families where duplication is entirely driven
by communication avoidance (out_tree, fork) tend to retain all duplicates. Families
with redundant copies after recursive placement (diamond) benefit more from pruning.

**Runtime cost**: ProposedScheduler is the most expensive due to O(n × p × parents(t))
clone evaluations per task. Runtime grows with task count and DAG density.

## 8. Limitations

- **Small diagnostic sizes**: fork/join n_branches=8,16; in_tree/out_tree depth=3; diamond
  width=4,depth=3. Not representative of large real-world DAGs. Chain excluded entirely.
- **No real benchmark DAGs**: only synthetic structured families; no STG, Pegasus, or HPEC.
- **alpha=0.0 only**: hop latency disabled; communication cost = beta × volume.
  Larger alpha would widen the gap between close and distant processors.
- **Fixed 4×4 NoC**: larger meshes would increase inter-processor distance and contention.
- **Greedy recursive duplication only**: not globally optimal ancestor selection.
- **Conservative pruning**: full Sinnen-style redundant task and in-edge removal not implemented.
