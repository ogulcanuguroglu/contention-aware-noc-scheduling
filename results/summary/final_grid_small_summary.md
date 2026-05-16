# Final Grid Small: Experiment Results Summary

> **Note**: This is a small diagnostic grid used for Phase 11 validation. It should not be presented as the full final evaluation grid. The broader methodology and paper alignment are defined in results/summary/project_alignment_audit.md.

## 1. Experiment Configuration

| Parameter | Value |
|-----------|-------|
| Seeds | 0, 1, 2 |
| Task counts | 20, 40 |
| Edge probabilities | 0.25, 0.40 |
| CCR values | 0.1, 1.0, 5.0 |
| Computation range | [5, 20] |
| NoC size | 4x4 (16 processors) |
| alpha | 0.0 |
| beta | 1.0 |
| Schedulers | HEFT, CA-LS, CD-LS, CA-D (Proposed) |
| Total rows | 144 (3 seeds x 2 tasks x 2 edge_prob x 3 CCR x 1 NoC x 4 schedulers) |

## 2. Mean Metrics per Scheduler (all configurations)

| Scheduler       | makespan | speedup_vs_heft | task_instance_ratio | communication_count | max_link_utilization | runtime_ms |
| --------------- | -------- | --------------- | ------------------- | ------------------- | -------------------- | ---------- |
| HEFT            | 177.148  | 1.0             | 1.0                 | 0.0                 | 0.0                  | 96.031     |
| CA-LS           | 237.147  | 0.855           | 1.0                 | 93.861              | 0.493                | 167.553    |
| CD-LS           | 172.523  | 1.032           | 1.237               | 0.0                 | 0.0                  | 541.069    |
| CA-D (Proposed) | 189.264  | 0.957           | 1.308               | 108.028             | 0.452                | 5473.772   |

## 3. Best-Scheduler Counts (minimum makespan per workload instance)

- **HEFT**: 16
- **CA-LS**: 0
- **CD-LS**: 20
- **CA-D (Proposed)**: 0

## 4. CCR Trend: Speedup vs HEFT per Scheduler

| Scheduler       | CCR=0.1 | CCR=1.0 | CCR=5.0 |
| --------------- | ------- | ------- | ------- |
| HEFT            | 1.0     | 1.0     | 1.0     |
| CA-LS           | 1.0     | 0.995   | 0.57    |
| CD-LS           | 1.0     | 1.01    | 1.087   |
| CA-D (Proposed) | 1.0     | 1.005   | 0.867   |

## 5. Interpretation

**HEFT** provides the scheduling baseline. Its speedup_vs_heft is always 1.0
by definition because all other schedulers' makespans are normalized against it.
HEFT uses the classic communication model with no link reservation, so its
reported makespan does not account for actual NoC contention.

**CA-LS** models link-level contention explicitly. This produces a longer
reported makespan than HEFT on average (mean speedup 0.855) because it reveals
the actual communication delays that HEFT ignores. At high CCR (5.0), CA-LS
speedup drops to 0.57 -- contention forces communications to queue heavily on
shared links, and without duplication, CA-LS cannot avoid this overhead. CA-LS
wins zero workload instances in terms of raw makespan.

**CD-LS** uses task duplication to eliminate inter-processor communication.
Because duplicated tasks execute locally, many remote communications are avoided
entirely. CD-LS produces the shortest makespans most often (20 of 36 workload
instances) and achieves speedup > 1.0 at CCR >= 1.0. Its advantage grows with
CCR: 1.087x speedup at CCR=5.0. The classic communication model it uses
(no link reservation) is optimistic but enables aggressive duplication.
Note: CD-LS communication_count is 0 because the classical scheduler computes
communication costs analytically and does not materialize CommunicationInstance
or link-reservation objects. Logical DAG communications still exist and are
factored into EFT estimates; they simply have no link-interval representation.

**CA-D (Proposed)** combines contention-aware reservation with selective
parent duplication (Delta_EFT > 0 rule under the contention model). On this
small grid, CA-D has a mean task_instance_ratio of 1.308, which is higher than
CD-LS (1.237). The extra duplications do not translate into lower makespan
because CA-D also models and reserves link-level communications realistically,
including the communications required to place duplicate tasks. The reservation
overhead prevents CA-D from matching CD-LS's optimistic makespan on this
diagnostic grid. CA-D remains between CA-LS and CD-LS in makespan at high CCR,
but does not beat HEFT on this small diagnostic grid (mean speedup 0.957).

**Model comparison note**: HEFT and CD-LS use the classic model (no link
reservation), so their reported makespans are optimistic estimates of actual
execution. CA-LS and CA-D model link contention explicitly; their reported
makespans reflect realistic NoC execution. Comparing them directly by makespan
number is comparing two different communication models. A fair comparison would
simulate all schedules under the contention model, which is deferred to future
work following Sinnen et al. 2011.

**CCR trends**: At CCR=0.1 all schedulers match HEFT (computation dominates).
At CCR=1.0 CD-LS and CA-D show small improvements. At CCR=5.0 CD-LS gains
strongly (1.087x) while CA-LS drops sharply (0.57x) due to heavy contention
without duplication.

## 6. Warnings and Limitations

- **No recursive ancestor duplication**: The proposed scheduler duplicates only
  direct parent tasks. Recursive critical-ancestor duplication (planned for
  Phase 13) could further reduce makespan.
- **No redundant duplicate removal**: Duplicated tasks that no longer reduce
  any child's EFT remain in the schedule, inflating task_instance_ratio.
- **Homogeneous processors**: All 16 processors have identical computation
  capacity. Heterogeneous models are not implemented.
- **Small grid**: Only 3 seeds x 2 task counts x 2 edge probabilities x 3 CCR
  values were tested. Results may not generalize to extreme configurations
  (very large DAGs, dense graphs, or CCR > 5).
- **Fixed NoC size**: Only the 4x4 mesh was tested. Larger meshes would
  increase contention and potentially widen the advantage of CA-D.
- **alpha=0.0**: The per-hop latency term is disabled. The communication
  duration formula is `alpha * hop_count + beta * volume`; with alpha=0.0
  this reduces to `beta * volume`. Hop count still determines the XY route
  and the number of reserved NoC links, but it does not multiply the
  bandwidth term beta * volume.
