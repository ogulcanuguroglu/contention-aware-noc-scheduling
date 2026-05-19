---
name: project-noc-dag-scheduler
description: Core project context for CMP720 DAG scheduler on 4x4 mesh NoC — phases, constraints, terminology
metadata:
  type: project
---

DAG scheduling on a 4x4 homogeneous 2D mesh NoC (16 processors), offline static scheduling.
Communication model: duration = alpha * hop_count + beta * volume. Main experiments: alpha=0.0, beta=1.0.

**Phase completion status (as of 2026-05-17):**
- Phases 1-18: core infrastructure, schedulers, evaluation
- Phase 19: multi-seed experiments (320 cases), alpha sensitivity, 8 IEEE figures, evaluation report
- Phase 20: presentation-oriented 7-figure set (generate_phase20_presentation_figures.py)
- Phase 21: interpretive figure package — COMPLETED (scripts/generate_phase21_interpretive_figures.py)

**Phase 21 outputs:**
- CSV: results/summary/phase21_interpretive_single_run.csv (48 rows: 4 DAG x 4 CCR x 3 schedulers, seed=0)
- Figures: results/figures/phase21_interpretive/ (10 figures x PNG+PDF)
  fig1_dag_family_topologies, fig2_scheduler_concept, fig3_native_vs_replay,
  fig4a_fork_gantt, fig4b_out_tree_gantt, fig4c_fork_join_gantt,
  fig5_ccr_sweep_replayed_speedup, fig6_replay_overhead_ratio,
  fig7_task_instance_ratio, fig8_remote_comm_volume_ratio
- Summary: results/summary/phase21_interpretive_summary.md
- Tests: tests/test_phase21_interpretive.py (41 tests, all pass)

**New metric in Phase 21:** remote_communication_volume_ratio (RCVR)
= sum of vol of DAG edges u->v where no instance of u is co-located with v's primary proc
/ total DAG edge volume

**Key immutable constraints:**
- Do NOT modify src/**, tests/** (adding new test files OK), results/raw/**, docs/**
- Do NOT stage or commit unless explicitly asked
- Do NOT modify existing Phase 16-20 result files

**Scheduler terminology:**
- HEFT: analytic, contention-blind, no duplication
- CD-LS: analytic, contention-blind, direct parent duplication only
- CA-D: contention-aware, greedy recursive ancestor duplication (NOT Sinnen critical-parent)
- Replay: replay_under_contention() preserves placement, recomputes timing with link reservations
- Fair speedup: HEFT_replayed / sched_replayed (both use contention-aware replay)

**Why:** This is the user's CMP720 Embedded System Design course project at Hacettepe University.

**How to apply:** Don't overclaim CA-D capabilities. Never say it implements Sinnen critical-parent selection. Don't present pruning as a main contribution (never triggered in structured-DAG tests).
