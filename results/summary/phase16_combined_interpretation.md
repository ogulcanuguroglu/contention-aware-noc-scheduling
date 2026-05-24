# Phase 16 Combined Interpretation

> **Scope**: Phase 16 regenerates and extends the experiment results using the Phase
> 15A+15B improved ProposedScheduler. This document interprets both the random-DAG
> (final_grid_small_v2, 72 rows) and graph-family (graph_family_diagnostic_v1,
> 324 rows) experiments under both native and fair-replay evaluation.

---

## 1. Native vs Replayed Evaluation Distinction

Two makespans are reported for every scheduled run:

**Native makespan** — the makespan predicted by the scheduler's own communication model:
- HEFT and CD-LS use the analytic (contention-free) model: `duration = alpha × hops + beta × vol`.
  No link intervals are reserved; link_intervals is empty after scheduling.
- CA-LS and CA-D use explicit link-interval reservation. DRT includes contention-induced waiting.

**Replayed makespan** — the makespan after `replay_under_contention()` reapplies the same
task placement under the common contention-aware NoC model. Only the task-to-processor
assignment and primary/duplicate flags are preserved; all timing is recomputed.

`replay_overhead_ratio = replayed_makespan / native_makespan`.
- CA-LS and CA-D: ratio ≈ 1.0 (already contention-aware natively).
- HEFT and CD-LS: ratio ≥ 1.0 (contention-free model may have been over-optimistic).

`replayed_speedup_vs_heft` is the fair common-model comparison: HEFT's replayed makespan
divided by the scheduler's replayed makespan for the same workload instance.

---

## 2. Random DAG Results Summary (final_grid_small_v2)

| Scheduler | Native speedup | Replayed speedup | TIR | Replay overhead |
|-----------|---------------|-----------------|-----|-----------------|
| HEFT | 1.000 | 1.000 | 1.000 | 1.436 |
| CA-LS | 0.875 | 1.158 | 1.000 | 1.000 |
| CD-LS | 1.055 | 1.078 | 1.306 | 1.397 |
| CA-D | 1.050 | 1.474 | 2.261 | 1.025 |

Best-scheduler wins (native): HEFT=7, CA-LS=0,
CD-LS=4, CA-D=7 of 18 workload instances.

Best-scheduler wins (replayed): HEFT=6, CA-LS=1,
CD-LS=0, CA-D=11 of 18 workload instances.

---

## 3. Graph Family Results Summary (graph_family_diagnostic_v1)

| Scheduler | Native speedup | Replayed speedup | TIR | Runtime (ms) |
|-----------|---------------|-----------------|-----|--------------|
| HEFT | 1.000 | 1.000 | 1.000 | 24.8 |
| CA-LS | 0.864 | 1.308 | 1.000 | 33.1 |
| CD-LS | 1.345 | 2.089 | 1.382 | 53.1 |
| CA-D | 1.349 | 2.521 | 1.651 | 341.2 |

Best-scheduler wins (native): HEFT=19, CA-LS=0,
CD-LS=49, CA-D=13 of 81 workload instances.

Best-scheduler wins (replayed): HEFT=13, CA-LS=4,
CD-LS=25, CA-D=39 of 81 workload instances.

---

## 4. What the Improved ProposedScheduler Achieves

The improved ProposedScheduler (Phase 15A+15B) is a NoC-focused, paper-inspired greedy
recursive duplication heuristic with conservative redundant duplicate pruning.

Compared to the parent-only ProposedScheduler from Phase 8:
- **Recursive ancestor duplication** (Phase 15A): recursively explores beneficial
  predecessor ancestors and duplicates them when `Delta_EFT > EPS` under the contention
  model. This can reduce makespan on DAGs with long critical communication chains
  (fork-join, in-tree, diamond) by placing ancestor chains locally.
- **Conservative duplicate pruning** (Phase 15B): post-schedule pass removes duplicate
  instances that are provably unnecessary (not a remote communication source, not the only
  local predecessor for any successor). This reduces task_instance_ratio without
  increasing makespan.

The result is a scheduler that takes more aggressive duplication decisions than parent-only
CA-D but avoids carrying obviously redundant copies. Task instance ratio for CA-D:
2.261 (random DAGs) and 1.651 (graph families).

CA-D's replay_overhead_ratio is close to 1.0 in both experiments (1.025 random,
1.002 graph families), confirming that its
contention-aware model is internally consistent with the replay model.

---

## 5. Where CD-LS Remains Optimistic

CD-LS uses the analytic (contention-free) communication model. Its native makespan
ignores the link contention that its placement would cause in a real NoC.

Replay overhead for CD-LS (random): 1.397. This shows how much of CD-LS's
native advantage disappears when evaluated under the contention model.

Native best-wins for CD-LS: 4 of 18 (random) and
49 of 81 (families) workload instances.
Replayed best-wins: 0 (random) and
25 (families).

The difference between native and replayed best-wins directly quantifies how many
CD-LS "wins" are artefacts of the optimistic communication model rather than genuine
makespan reductions under realistic NoC conditions.

---

## 6. Where CA-LS Helps or Hurts

CA-LS reserves NoC links without task duplication. At low CCR (computation-dominated),
its link reservations add overhead without benefit. At high CCR, without duplication, it
cannot avoid the remote communication bottleneck — it can only queue communications more
carefully, which does not reduce the total volume.

Mean native speedup for CA-LS: 0.875 (random), 0.864 (families).
Both below 1.0 on average, meaning CA-LS produces longer makespans than HEFT in this
small-NoC, low-alpha configuration. This is because HEFT's analytic model is optimistic
and CA-LS pays the cost of realistic contention modeling without the benefit of duplication.

CA-LS wins 0 workload instances natively and 1 (random)
/ 4 (families) under replay. Its replay overhead ≈ 1.0
confirms that the CA-LS model is internally consistent.

---

## 7. Runtime Trade-off

| Experiment | Scheduler | Mean runtime (ms) |
|------------|-----------|-------------------|
| Random DAGs | HEFT | 44.2 |
| Random DAGs | CA-D | 10431.0 |
| Families | HEFT | 24.8 |
| Families | CA-D | 341.2 |

CA-D is the most expensive scheduler due to exhaustive sub-clone evaluation for every
(task × processor × predecessor) triple and additional recursive ancestor traversal.
HEFT is the fastest. Runtime ratio CA-D/HEFT: 236.1× (random).

This runtime gap is a known limitation. Greedy recursive duplication adds ancestor-chain
traversal to the existing clone overhead. For large DAGs on large meshes, CA-D may
require significant computation budget.

---

## 8. Final Report Recommendations

1. **Model clarity**: Explicitly state in the paper that HEFT and CD-LS use the analytic
   model and CA-LS / CA-D use link-interval reservation. Make this distinction in every
   table header and figure caption.

2. **Primary comparison metric**: Use `replayed_speedup_vs_heft` as the fair comparison
   baseline in the paper's main result tables, since it levels the field across the two
   communication models. Report native speedup as a secondary "predicted" metric.

3. **Replay overhead column**: Include `replay_overhead_ratio` to show how optimistic each
   scheduler's native model is relative to the physical contention model.

4. **CA-D framing**: Present CA-D as "a NoC-focused, paper-inspired greedy recursive
   duplication heuristic with conservative redundant duplicate pruning," not as a full
   reproduction of Sinnen et al. Algorithm 3. Explicitly state that parent-only duplication
   was the Phase 8 baseline and recursive ancestor duplication is the Phase 15A improvement.

5. **Graph families**: Use the graph_family_diagnostic_v1 results to discuss how scheduler
   behavior varies by DAG structure. Fork and out-tree show the clearest duplication
   benefits among the included graph families. Chain was excluded from the graph-family
   grid because deep linear DAGs are pathological for the current recursive duplication
   runtime. Diamond shows the highest contention due to dense inter-layer edges.

6. **Limitations to disclose**: greedy (not optimal) recursive duplication; conservative
   (not full Sinnen-style) pruning; synthetic DAGs only; homogeneous processors; alpha=0;
   small NoC; high CA-D runtime.

---

## 9. Grid Reduction Note

Both experiments were reduced from their originally planned sizes due to ProposedScheduler
runtime constraints introduced by Phase 15A greedy recursive ancestor duplication:

- **Random DAG grid** (final_grid_small_v2): planned 144 rows (n_tasks=[20,40]); reduced
  to **72 rows** (n_tasks=[20] only). Dense 40-task random DAGs caused ProposedScheduler
  runs to exceed 2 minutes each, making the full grid infeasible.

- **Graph family grid** (graph_family_diagnostic_v1): planned 396 rows (11 configs including
  chain n_tasks=20 and n_tasks=40); reduced to **324 rows** (9 configs, chain excluded
  entirely). Even chain n_tasks=20 caused ProposedScheduler to hang due to the maximum
  ancestor chain depth in linear topologies.

These are **runtime-motivated limitations**, not failed or partial runs. No NaN rows or
timeout placeholder rows are present in either CSV. All included rows are complete and
validated. The reductions are documented in each experiment's summary configuration table.

---

## 10. Recommended Next Phase

**Phase 17 — Final Documentation and Reproducibility Cleanup**

Goals:
- Update `README.md` with installation instructions, example commands, reproducibility note.
- Add a `requirements.txt` run-check.
- Add a one-command experiment entry point: `python scripts/run_all_experiments.py`.
- Ensure all CSV files in `results/raw/` are consistent with Phase 15A+15B scheduler.
- Final test run confirming the full suite (1039+ tests) passes.
- Draft final report sections based on the summaries in `results/summary/`.

All algorithmic development (Phases 0–15B) is complete. Phase 16 results are ready for
the paper. Phase 17 is documentation and packaging only.
