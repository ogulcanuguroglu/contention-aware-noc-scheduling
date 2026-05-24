# Results Guide

This document describes the active result files, their columns, and how to interpret the metrics.

---

## Active CSV Files

### `results/raw/final_grid_small_v2.csv` — 72 rows

Experiment A: random DAG grid with Phase 15A+15B ProposedScheduler and fair replay metrics.

**Configuration:** 3 seeds × 1 task count (n=20) × 2 edge probabilities × 3 CCR values × 4×4 NoC × 4 schedulers = 72 rows.

#### Workload columns

| Column | Type | Description |
|---|---|---|
| `scheduler` | str | Scheduler name: `heft`, `contention_aware`, `classical_duplication`, `proposed` |
| `n_tasks` | int | Number of tasks in the DAG |
| `edge_prob` | float | Erdős–Rényi edge probability used for DAG generation |
| `ccr` | float | Target CCR requested at generation time |
| `achieved_ccr` | float | Actual CCR after CCR scaling |
| `comp_min`, `comp_max` | float | Computation cost range [comp_min, comp_max] |
| `noc_rows`, `noc_cols` | int | Mesh dimensions |
| `processor_count` | int | Total processors (noc_rows × noc_cols) |
| `alpha`, `beta` | float | Communication duration coefficients |
| `seed` | int | Random seed used for DAG generation |
| `n_edges` | int | Number of edges in the generated DAG |
| `total_computation_work` | float | Sum of all task computation costs |

#### Native schedule metrics (scheduler's own model)

| Column | Description |
|---|---|
| `makespan` | Schedule length predicted by the scheduler's own communication model |
| `primary_task_count` | Number of primary task instances (should equal n_tasks) |
| `duplicate_task_count` | Number of duplicate task instances (0 for HEFT and CA-LS) |
| `task_instance_ratio` | total_instances / n_tasks (≥ 1.0; 1.0 means no duplication) |
| `communication_count` | Number of CommunicationInstance objects (0 for HEFT and CD-LS) |
| `max_link_utilization` | Max fraction of schedule duration that any link is busy (ratio in [0, 1]) |
| `speedup_vs_heft` | HEFT native makespan / scheduler native makespan for same workload |
| `normalized_makespan_vs_heft` | scheduler native makespan / HEFT native makespan |
| `baseline_makespan_heft` | HEFT native makespan for the same workload group |
| `serial_speedup` | total_computation_work / makespan |

#### Fair replay metrics (common contention model)

| Column | Description |
|---|---|
| `replayed_makespan` | Makespan after replaying the placement under the contention-aware NoC model |
| `replayed_communication_count` | Remote communications materialized during replay |
| `replayed_max_link_utilization` | Max link utilization in the replayed schedule (ratio in [0, 1]) |
| `replay_overhead_ratio` | replayed_makespan / makespan |
| `replayed_vs_original_delta` | replayed_makespan − makespan |
| `replayed_speedup_vs_heft` | HEFT replayed makespan / scheduler replayed makespan for same workload |

#### Scheduler runtime

| Column | Description |
|---|---|
| `runtime_ms` | Wall-clock time for scheduler.schedule() in milliseconds |

---

### `results/raw/graph_family_diagnostic_v1.csv` — 324 rows

Experiment B: structured graph family grid.

**Configuration:** 9 family configs × 3 CCR values × 3 seeds × 4 schedulers = 324 rows.

Families included: `fork`, `join`, `fork_join`, `in_tree`, `out_tree`, `diamond`.  
**Chain family excluded** — linear topology is pathological for greedy recursive ancestor duplication.

#### Workload columns (in addition to shared columns above)

| Column | Type | Description |
|---|---|---|
| `family` | str | Graph family name |
| `family_param_label` | str | Human-readable label for family parameters (e.g., `n_branches=8`) |

All remaining columns have the same meaning as in `final_grid_small_v2.csv`.

---

## Important Metrics

### Makespan

```
makespan = max over all processors { processor finish time }
```

The schedule length: the time from t=0 until the last task finishes. Lower is better.

For HEFT and CD-LS, makespan is computed using the analytic communication model. For CA-LS and CA-D, makespan reflects actual contention-aware communication timing.

### Replayed makespan

```
replayed_makespan = makespan computed by replay_under_contention()
```

The makespan produced by placing the scheduler's task assignment under the common contention-aware NoC model. Enables fair comparison across all four schedulers.

### speedup_vs_heft

```
speedup_vs_heft = HEFT native makespan / scheduler native makespan
```

The speedup of the scheduler's native makespan relative to HEFT's native makespan on the same workload. Values > 1.0 indicate the scheduler finishes faster than HEFT under its own model.

**Caution:** Comparing native speedup across schedulers that use different communication models (HEFT/CD-LS analytic vs CA-LS/CA-D contention-aware) can be misleading. Use `replayed_speedup_vs_heft` for a fair comparison.

### replayed_speedup_vs_heft

```
replayed_speedup_vs_heft = HEFT replayed makespan / scheduler replayed makespan
```

The speedup relative to HEFT when both schedulers' placements are evaluated under the same contention-aware NoC model. This is the **recommended primary comparison metric** for cross-scheduler comparisons.

Values > 1.0 mean the scheduler's placement is faster than HEFT's placement under the shared contention model. Values < 1.0 mean the scheduler's placement is slower.

### duplicate_task_count

The number of duplicate (non-primary) task instances in the committed schedule. 0 for HEFT and CA-LS. Positive for CD-LS and CA-D.

### task_instance_ratio

```
task_instance_ratio = (primary_count + duplicate_count) / primary_count
```

The average number of task instances per original DAG task. 1.0 means no duplication. Higher values reflect more aggressive duplication. CA-D typically has higher TIR than CD-LS due to recursive ancestor duplication.

### communication_count

The number of `CommunicationInstance` objects created by the scheduler for remote communications. 0 for HEFT and CD-LS (analytic model, no CommunicationInstance objects). Positive for CA-LS and CA-D.

### replayed_communication_count

The number of remote communications materialized by replay. All four schedulers produce nonzero values if any tasks are placed on different processors. This is always ≥ 0; for CA-LS and CA-D it usually equals `communication_count`.

### max_link_utilization / replayed_max_link_utilization

```
max_link_utilization = max over all links { link_busy_time / makespan }
```

**Link utilization metrics are ratios in [0, 1], not percentages.** A value of 0.0 for HEFT and CD-LS means `link_intervals` is empty in the native schedule (no link reservation). After replay, HEFT and CD-LS acquire nonzero link utilization because replay materializes their communications.

### replay_overhead_ratio

```
replay_overhead_ratio = replayed_makespan / makespan
```

Measures how optimistic a scheduler's native communication model is relative to the physical contention model:

- **CA-LS, CA-D:** ratio ≈ 1.0 — already model contention natively
- **HEFT, CD-LS:** ratio ≥ 1.0 — analytic model was optimistic; contention revealed by replay

A ratio of 1.436 for HEFT (observed in Experiment A) means HEFT's native makespan underestimates the true execution time by ~44% when link contention is accounted for.

---

## How to Interpret Native vs Replay

### HEFT

Native makespan is computed analytically without modeling link contention. It can be a significant underestimate. HEFT's replayed makespan is higher than its native makespan and serves as the fair reference denominator for `replayed_speedup_vs_heft`.

### CA-LS

Already models contention natively. Native and replayed makespans are close. CA-LS does not duplicate tasks, so it cannot eliminate communication overhead; at high CCR it is penalized relative to duplication schedulers.

### CD-LS

Analytic model; ignores contention. Native makespan may be optimistic. CD-LS can appear to win more workloads natively than it does under replay. The difference between native and replayed best-wins directly quantifies how many CD-LS "wins" are artefacts of the optimistic model.

### CA-D

Already models contention natively. Native and replayed makespans are close (`replay_overhead_ratio ≈ 1.0`). Recursive ancestor duplication increases `task_instance_ratio` and `duplicate_task_count` but can significantly reduce makespan at high CCR on DAGs with long communication chains.

---

## Result Caveats

### Reduced grids

Phase 16 experiments use reduced diagnostic grids, not the originally planned full grids:

- **Experiment A:** n_tasks=40 excluded; ProposedScheduler exceeded 2 minutes per run on dense 40-task DAGs
- **Experiment B:** chain family excluded entirely; even chain n_tasks=20 caused ProposedScheduler to hang due to maximum ancestor chain depth in linear topologies

These are runtime-motivated reductions. No NaN rows or timeout placeholder rows are present. All included rows are complete and validated.

### Chain topology

The chain generator (`generate_chain_dag`) exists in `src/graph_families.py` but is not used in Phase 16 experiments. Deep linear DAGs expose the worst-case O(n × p × depth) behavior of the greedy recursive ancestor duplication.

### alpha=0.0

Phase 16 experiments disable the per-hop latency term (`alpha=0.0`). Communication cost equals `beta × vol` only. Hop count still determines which links are reserved, so contention can still occur between communications that share route links.

### Legacy CSVs

`results/raw/final_grid_small.csv` (Phase 11) and `results/raw/smoke_phase9.csv`, `results/raw/differentiation_smoke.csv` are earlier diagnostic results. They predate Phase 13 fair replay columns and Phase 15A+15B scheduler improvements. Do not use them for Phase 16 analysis.
