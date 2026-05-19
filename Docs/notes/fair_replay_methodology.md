# Fair Contention Replay Methodology

This note documents the Phase 12–13 fair contention replay evaluation layer. It is intended to clarify the methodology without changing `PHASE_PLAN.md` or any source-code behavior.

## 1. Motivation

The project compares four schedulers:

| Scheduler | Duplication | Native Link Contention | Link Reservations in Native Schedule |
|---|---:|---:|---:|
| HEFT-like baseline | No | No | No |
| CA-LS / Contention-Aware List Scheduler | No | Yes | Yes |
| CD-LS / Classical Duplication Scheduler | Yes | No | No |
| CA-D / Proposed Scheduler | Yes | Yes | Yes |

The native makespan of these schedulers is not always directly comparable because HEFT and CD-LS are contention-blind, while CA-LS and CA-D explicitly reserve NoC links. In particular, CD-LS may look very strong because it ignores the contention that its communication pattern would create on a real NoC.

Fair contention replay addresses this by taking each scheduler's task placement and replaying it under the same contention-aware 2D mesh NoC model.

## 2. What Fair Replay Is

Fair replay is a **placement-preserving post-hoc contention evaluation**.

It preserves, for every scheduled task instance:

- `task_id`
- `processor_id`
- `is_primary`

It does **not** preserve the original task start and finish times. Instead, it recomputes them under the contention-aware NoC model using link-interval reservation.

Therefore, fair replay produces a second makespan:

- **Native makespan:** the makespan produced by the scheduler's own model.
- **Replayed makespan:** the makespan after replaying the same task placement under the common contention-aware NoC model.

This distinction is essential when interpreting results.

## 3. What Fair Replay Is Not

Fair replay is **not** an exact reproduction of the original schedule timing.

It is also not a new scheduler. It does not search for a better processor assignment, does not create new duplicates, and does not remove duplicates. It only re-evaluates the already-produced placement under a common communication contention model.

## 4. Replay Semantics

Given an original `ScheduleState`, `replay_under_contention(dag, state, noc)` constructs a new `ScheduleState`.

The replay process:

1. Extracts task instances from the original state.
2. Preserves their task-to-processor placement and primary/duplicate status.
3. Recomputes task start/finish times in a deterministic order.
4. For each remote predecessor communication, reserves the corresponding XY route links.
5. Materializes remote communications as `CommunicationInstance` objects.
6. Produces a replayed schedule with processor intervals, link intervals, task instances, and communication instances.

Local communication remains zero-cost and does not create a `CommunicationInstance`.

## 5. Source-Instance Selection During Replay

If a predecessor task has multiple instances, replay selects the source instance that gives the earliest data arrival time.

The tie-break rule is:

1. Smaller arrival time wins.
2. If arrival times are equal, local communication is preferred over remote communication.
3. If still tied, the smaller processor ID is preferred.

This means fair replay is **placement-preserving but source-reselecting**. It preserves where task instances exist, but it may choose the best predecessor instance during replay rather than preserving an implicit source choice from the original scheduler.

This is intentional: it gives each scheduler's placement a fair best-effort evaluation under the same NoC contention model.

## 6. Replay Metrics

Phase 13 integrates replay metrics into the experiment runner.

`run_single_experiment()` adds the following direct replay columns:

| Column | Meaning |
|---|---|
| `replayed_makespan` | Makespan after contention replay |
| `replayed_communication_count` | Number of remote communications materialized during replay |
| `replayed_max_link_utilization` | Maximum link utilization in the replayed schedule |
| `replay_overhead_ratio` | `replayed_makespan / makespan` |
| `replayed_vs_original_delta` | `replayed_makespan - makespan` |

`run_experiment_grid()` additionally adds:

| Column | Meaning |
|---|---|
| `replayed_speedup_vs_heft` | HEFT replayed makespan divided by the scheduler's replayed makespan for the same workload group |

This gives both native and replay-based comparisons.

## 7. Interpretation Guidelines

### HEFT-like baseline

HEFT does not reserve links in its native schedule. Its native makespan can therefore underestimate the true cost of remote communication. Replay reveals the contention-aware cost of the same placement.

### CA-LS

CA-LS already schedules remote communications with link reservations. Its replayed makespan should usually be close to its native makespan, unless replay ordering/source-selection semantics differ from the native scheduler's exact choices.

### CD-LS

CD-LS uses duplication but ignores link contention. Its native makespan can be optimistic. Replay is especially important for CD-LS because it shows what happens when the same duplicated placement is evaluated under link contention.

### Proposed CA-D

CA-D already performs contention-aware duplication. Its replayed makespan should generally be consistent with the native model. Differences should be interpreted as effects of replay ordering and source reselection.

## 8. How to Present This in the Report

Recommended wording:

> In addition to each scheduler's native makespan, we perform a fair contention replay. This replay preserves the task-to-processor placement and duplicate instances produced by each scheduler, but recomputes task start times and remote communication reservations under a common 2D mesh NoC contention model. This allows contention-blind and contention-aware schedulers to be compared under the same communication model.

Important distinction:

- Use **native makespan** to describe what each scheduler predicts under its own model.
- Use **replayed makespan** to compare placements under a common contention-aware NoC model.

## 9. Relationship to the Proposal Communication Penalty

The initial proposal described a scalar contention penalty:

```text
CP = lambda1 * U(route) + lambda2 * B(route) + lambda3 * L(route)
```

The implementation does not use this scalar formula directly. Instead, it uses:

```text
remote communication duration = alpha * hop_count + beta * communication_volume
```

and models contention by explicit link-interval reservation. In this implementation, contention emerges as waiting time caused by occupied NoC links, rather than being added as a precomputed scalar penalty.

A safe report statement is:

> The scalar CP model was an initial abstraction. The final implementation realizes contention through explicit link-interval reservation on XY-routed NoC links, which is closer to the edge/link scheduling model used in contention-aware scheduling literature.

## 10. Documentation Notes

The actual implementation uses the following DAG attribute names:

| Concept | Implementation Attribute |
|---|---|
| Task computation cost | `computation_cost` |
| Edge communication volume | `communication_volume` |

If older notes use `weight` or `volume`, they should be interpreted as shorthand only. The code convention is `computation_cost` and `communication_volume`.

## 11. Current Limitations

Fair replay currently does not solve these limitations:

- It does not add recursive ancestor duplication.
- It does not remove redundant duplicates.
- It does not search for a new placement.
- It does not model packet/flit-level NoC timing.
- It does not model router buffers, adaptive routing, multicast, energy, or memory pressure.

Those remain future phases.
