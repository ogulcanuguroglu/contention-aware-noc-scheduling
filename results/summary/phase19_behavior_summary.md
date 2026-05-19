# Phase 19 — Scheduler Behavior Summary

**Dataset:** 4 DAG families × 4 CCR values × 20 seeds = 320 cases per scheduler.
**NoC:** 4×4 mesh, alpha=0.0, beta=1.0. Metrics averaged over 20 seeds.
**Replayed speedup vs HEFT:** primary comparison metric (fair contention-aware evaluation).

## Per-DAG Mean Performance (over all CCR and seeds)

| DAG family | Scheduler | Mean replayed speedup | Mean replay overhead | Mean TIR | Mean dup. efficiency |
|------------|-----------|----------------------:|---------------------:|---------:|---------------------:|
| Chain | HEFT | 1.000× | 1.000× | 1.000 | — |
| Chain | CD-LS | 1.000× | 1.000× | 1.000 | — |
| Chain | CA-D | 1.000× | 1.000× | 1.000 | — |
| Fork | HEFT | 1.000× | 1.337× | 1.000 | — |
| Fork | CD-LS | 2.787× | 1.000× | 1.778 | 2.30 |
| Fork | CA-D | 2.787× | 1.000× | 1.778 | 2.30 |
| Out-tree | HEFT | 1.000× | 1.027× | 1.000 | — |
| Out-tree | CD-LS | 1.343× | 1.017× | 1.254 | 2.02 |
| Out-tree | CA-D | 1.593× | 1.000× | 1.714 | 0.83 |
| Fork-join | HEFT | 1.000× | 1.064× | 1.000 | — |
| Fork-join | CD-LS | 1.081× | 1.261× | 1.246 | 0.33 |
| Fork-join | CA-D | 1.359× | 1.000× | 1.371 | 0.92 |

**TIR** = Task Instance Ratio = total instances / primary task count (1.0 = no duplication).
**Dup. efficiency** = (replayed_speedup − 1) / (TIR − 1); undefined (—) when TIR = 1.0.

## Key Behavioral Observations

### Chain DAG
- Linear dependencies leave no room for parallelism via duplication.
- All three schedulers produce identical makespans at all CCR values.
- TIR = 1.0 for all (no duplicates placed that survive the schedule).
- Result: duplication does not help linear chains.

### Fork DAG (single-level)
- On a fork (root → 8 leaves), parent-only duplication (CD-LS) and recursive ancestor
  duplication (CA-D) make the same placement decision: duplicate the root near each leaf.
- CD-LS and CA-D produce identical results (same TIR, same makespan) on this topology.
- HEFT suffers a 1.34× replay overhead (contention from uncoordinated remote transfers).
- Duplication eliminates all remote transfers → zero contention → replay overhead = 1.0×.
- **Structure-dependent benefit**: this speedup (2.79× mean) is specific to fork topology
  where eliminating one communication edge removes all traffic from one processor.

### Out-tree DAG (two-level, branching factor 2)
- CA-D places recursive ancestor duplicates (mean 54.7 extra placements per case vs 0 for CD-LS).
- CA-D achieves a consistently better replayed speedup than CD-LS (1.59× vs 1.34× mean).
- CA-D replay overhead = 1.00× (contention-aware model is accurate).
- CD-LS replay overhead = 1.017× (small optimism from ignoring link reservations).
- **Recursive duplication is beneficial here**: CA-D's greedy recursive ancestor placement
  eliminates multi-hop ancestor communication that CD-LS cannot address.

### Fork-join DAG (4 branches, 3 tasks per branch)
- This is the most demanding topology for the contention-aware distinction.
- CD-LS native speedup (1.27× at CCR=5.0, seed=0) collapses to 1.02× under fair replay,
  revealing severe contention-blind optimism. At CCR=10.0, CD-LS replay speedup drops
  to 0.684× — worse than HEFT — confirming that contention-blind duplication can
  actively harm schedule quality under fair evaluation.
- CA-D replay overhead = 1.00× (contention-aware model predicts exactly).
- CA-D achieves 1.36× mean replayed speedup vs HEFT, consistent with its native prediction.
- **Replay consistency** is the key differentiator: CA-D's native prediction matches its
  replayed performance; CD-LS cannot predict its own real-world behavior.

## Native-Model Optimism Summary

| Scheduler | Chain | Fork | Out-tree | Fork-join |
|-----------|-------|------|----------|-----------|
| HEFT | 1.00× | 1.34× | 1.03× | 1.06× |
| CD-LS | 1.00× | 1.00× | 1.02× | **1.26×** |
| CA-D | 1.00× | 1.00× | 1.00× | 1.00× |

HEFT's overhead on fork reflects that HEFT's analytical model cannot predict the
contention introduced by its own remote-communication-heavy schedules.
CD-LS's fork-join overhead (1.26× mean, up to 1.38× at CCR=10.0) reflects the same
failure mode applied to a duplicating scheduler: the new duplicate placements create
additional link traffic that the contention-blind model does not account for.
CA-D's consistent 1.0× overhead confirms that the contention-aware scheduling model
accurately predicts the replayed outcome across all topologies and CCR values tested.

## Duplication Efficiency

- Duplication efficiency = (replayed_speedup − 1) / (TIR − 1) measures benefit per
  extra task instance. Higher is better; 0 means no speedup despite duplication.
- Fork: efficiency 2.30 for both CD-LS and CA-D (same schedule on one-level fork).
- Out-tree: CD-LS efficiency 2.02 vs CA-D 0.83 — CD-LS places fewer duplicates but
  each achieves a larger marginal speedup; CA-D places many more for a smaller per-unit gain.
- Fork-join: CD-LS efficiency 0.33 (low; many duplicates, little net benefit under replay)
  vs CA-D 0.92 (higher; fewer duplicates, each contributing meaningfully to makespan).
