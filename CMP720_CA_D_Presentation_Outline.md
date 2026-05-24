# CMP720 CA-D Scheduling — Presentation Outline

## Slide Count: 12 main + 3 backup = 15 total
## Estimated time: 11–13 minutes (main) + 5 min Q&A

---

## Slide 01 — Title
**Section:** —
**Message:** Project overview: contention-aware recursive duplication on NoC.
**Notes:** ~30 seconds. Welcome and introduce yourself.

---

## Slide 02 — Problem Definition
**Section:** 1. Problem
**Message:** Scheduling on NoC must model both computation and link-level contention.
**Key points:**
- DAGs: tasks + data dependencies
- NoC: physical links shared by multiple communications
- Link contention = serialization delay
- Classical schedulers ignore link sharing
- Task duplication can help but adds overhead
**Notes:** ~75 seconds.

---

## Slide 03 — Proposed Methodology Reminder
**Section:** 2. Proposal Summary
**Message:** Combine task duplication with contention-aware NoC scheduling.
**Key points:**
- HEFT baseline: analytic comm, no link reservation
- CD-LS: parent duplication, still analytic
- CA-D proposed: contention-aware recursive ancestor duplication
- Evaluation via replay mechanism
**Notes:** ~75 seconds.

---

## Slide 04 — Implemented System Architecture
**Section:** 3. Implementation
**Message:** A complete simulation framework was implemented.
**Key points:**
- DAG Generator (4 families)
- MeshNoC model (4x4, XY routing)
- Three scheduler modules
- ScheduleState (processor + link intervals)
- replay_under_contention()
- Metrics and figure pipeline
**Notes:** ~60 seconds.

---

## Slide 05 — Methodology Updates
**Section:** 3. Implementation
**Message:** Contention modelled as explicit link-interval reservation, not a scalar penalty.
**Key points:**
- Scalar penalty → explicit link_intervals dict
- earliest_route_slot() finds joint-free slot on all route links
- probe_communication_arrival() for read-only CA-D evaluation
- CA-D is NOT Sinnen critical-parent selection
- Pruning implemented but did not trigger significantly
**Notes:** ~90 seconds.

---

## Slide 06 — Scheduler Comparison: HEFT, CD-LS, CA-D
**Section:** 3. Implementation
**Message:** CA-D combines recursive duplication with contention-aware route reservation.
**Figure:** fig2_scheduler_concept.png
**Notes:** ~75 seconds.

---

## Slide 07 — Why Replay Is Needed
**Section:** 3. Implementation
**Message:** Replay exposes hidden contention in contention-blind schedules.
**Figure:** fig3_native_vs_replay.png
**Key points:**
- Native model may allow simultaneous link use
- Replay serializes transfers on shared links
- Overhead ratio = replayed / native
**Notes:** ~60 seconds.

---

## Slide 08 — DAG Families Used for Evaluation
**Section:** 4. Results
**Message:** Different DAG structures stress different scheduler behaviors.
**Figure:** fig1_dag_family_topologies.png
**Key points:**
- Chain: negative control (no parallelism)
- Fork: parent dup sufficient
- Out-tree: recursive dup beneficial
- Fork-join: most sensitive to contention
**Notes:** ~60 seconds.

---

## Slide 09 — Schedule Examples: Out-tree Gantt Charts
**Section:** 4. Results
**Message:** CA-D changes placement by putting ancestor copies near consuming tasks.
**Figure:** fig4b_out_tree_gantt.png
**Notes:** ~75 seconds.

---

## Slide 10 — Results: CCR Sweep and Replay Overhead
**Section:** 4. Results
**Message:** CA-D is most useful when recursive duplication and contention-awareness both matter.
**Figures:** fig5_ccr_sweep_replayed_speedup.png + fig6_replay_overhead_ratio.png
**Key observations:**
- Chain: all equal
- Fork: CD-LS = CA-D
- Out-tree: CA-D > CD-LS
- Fork-join: CD-LS can drop below 1.0; CA-D stable
**Notes:** ~90 seconds.

---

## Slide 11 — Duplication Cost and Remote Communication Reduction
**Section:** 4. Results
**Message:** CA-D trades extra task instances for reduced remote communication.
**Figures:** fig7_task_instance_ratio.png + fig8_remote_comm_volume_ratio.png
**Notes:** ~75 seconds.

---

## Slide 12 — Discussion, Limitations, and Future Work
**Section:** 5. Conclusions
**Message:** Functional results, honest limitations, clear next steps.
**3 columns:**
- Achievements: full framework, fair replay, new RCVR metric, 4 DAG x 4 CCR x 20 seeds
- Limitations: synthetic DAGs, greedy heuristic, not full Sinnen, pruning not triggered
- Future Work: real DAGs, energy cost, larger NoC, more algorithms
**Notes:** ~90 seconds.

---

## BACKUP Slide B1 — Communication Model Details
Communication duration formula, parameter table, alpha sensitivity note.

## BACKUP Slide B2 — CA-D Pseudo-code
Simplified pseudo-code for CA-D scheduling loop and recursive ancestor placement.

## BACKUP Slide B3 — Metric Definitions
TIR, RCVR, speedup, overhead, CCR — formal definitions.

---

## Figures Used

| Slide | Figure file |
|-------|------------|
| 6 | fig2_scheduler_concept.png |
| 7 | fig3_native_vs_replay.png |
| 8 | fig1_dag_family_topologies.png |
| 9 | fig4b_out_tree_gantt.png |
| 10 | fig5_ccr_sweep_replayed_speedup.png |
| 10 | fig6_replay_overhead_ratio.png |
| 11 | fig7_task_instance_ratio.png |
| 11 | fig8_remote_comm_volume_ratio.png |

All from: results/figures/phase21_interpretive/

## Figures omitted (available for backup discussion)
- fig4a_fork_gantt.png — fork Gantt (less informative than out-tree for this presentation)
- fig4c_fork_join_gantt.png — fork-join Gantt (discussed verbally in slide 10/12)

## Estimated presentation time
- Slides 1–12: ~11–13 minutes
- Q&A: up to 5 minutes
- Backup slides: on demand during Q&A
