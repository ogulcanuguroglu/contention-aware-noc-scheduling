# Phase 19 — Raw Makespan Table (seed=0)

**NoC:** 4×4 mesh, alpha=0.0, beta=1.0.
**Schedulers:** HEFT (contention-blind, no duplication), CD-LS (contention-blind, parent-only duplication), Proposed CA-D (contention-aware, greedy recursive ancestor duplication + conservative pruning).
**Makespan unit:** arbitrary time units (AU). All values from seed=0.

## Native and Replayed Makespan

| DAG family | CCR | Scheduler | Native makespan | Replayed makespan | Replayed speedup vs HEFT |
|------------|-----|-----------|----------------:|------------------:|-------------------------:|
| Chain | 0.1 | HEFT | 132.58 | 132.58 | 1.000× |
| Chain | 0.1 | CD-LS | 132.58 | 132.58 | 1.000× |
| Chain | 0.1 | CA-D | 132.58 | 132.58 | 1.000× |
| Chain | 1.0 | HEFT | 132.58 | 132.58 | 1.000× |
| Chain | 1.0 | CD-LS | 132.58 | 132.58 | 1.000× |
| Chain | 1.0 | CA-D | 132.58 | 132.58 | 1.000× |
| Chain | 5.0 | HEFT | 132.58 | 132.58 | 1.000× |
| Chain | 5.0 | CD-LS | 132.58 | 132.58 | 1.000× |
| Chain | 5.0 | CA-D | 132.58 | 132.58 | 1.000× |
| Chain | 10.0 | HEFT | 132.58 | 132.58 | 1.000× |
| Chain | 10.0 | CD-LS | 132.58 | 132.58 | 1.000× |
| Chain | 10.0 | CA-D | 132.58 | 132.58 | 1.000× |
| Fork | 0.1 | HEFT | 33.83 | 38.47 | 1.000× |
| Fork | 0.1 | CD-LS | 33.25 | 33.25 | 1.157× |
| Fork | 0.1 | CA-D | 33.25 | 33.25 | 1.157× |
| Fork | 1.0 | HEFT | 50.44 | 93.46 | 1.000× |
| Fork | 1.0 | CD-LS | 33.25 | 33.25 | 2.811× |
| Fork | 1.0 | CA-D | 33.25 | 33.25 | 2.811× |
| Fork | 5.0 | HEFT | 92.36 | 92.36 | 1.000× |
| Fork | 5.0 | CD-LS | 33.25 | 33.25 | 2.778× |
| Fork | 5.0 | CA-D | 33.25 | 33.25 | 2.778× |
| Fork | 10.0 | HEFT | 108.30 | 108.30 | 1.000× |
| Fork | 10.0 | CD-LS | 33.25 | 33.25 | 3.258× |
| Fork | 10.0 | CA-D | 33.25 | 33.25 | 3.258× |
| Out-tree | 0.1 | HEFT | 40.80 | 40.80 | 1.000× |
| Out-tree | 0.1 | CD-LS | 40.80 | 40.80 | 1.000× |
| Out-tree | 0.1 | CA-D | 40.80 | 40.80 | 1.000× |
| Out-tree | 1.0 | HEFT | 61.29 | 92.29 | 1.000× |
| Out-tree | 1.0 | CD-LS | 46.42 | 56.60 | 1.631× |
| Out-tree | 1.0 | CA-D | 40.80 | 40.80 | 2.262× |
| Out-tree | 5.0 | HEFT | 84.45 | 84.45 | 1.000× |
| Out-tree | 5.0 | CD-LS | 52.96 | 52.96 | 1.595× |
| Out-tree | 5.0 | CA-D | 40.80 | 40.80 | 2.070× |
| Out-tree | 10.0 | HEFT | 84.45 | 84.45 | 1.000× |
| Out-tree | 10.0 | CD-LS | 52.96 | 52.96 | 1.595× |
| Out-tree | 10.0 | CA-D | 40.80 | 40.80 | 2.070× |
| Fork-join | 0.1 | HEFT | 71.32 | 72.33 | 1.000× |
| Fork-join | 0.1 | CD-LS | 70.05 | 70.05 | 1.033× |
| Fork-join | 0.1 | CA-D | 70.05 | 70.05 | 1.033× |
| Fork-join | 1.0 | HEFT | 86.83 | 99.64 | 1.000× |
| Fork-join | 1.0 | CD-LS | 82.81 | 95.62 | 1.042× |
| Fork-join | 1.0 | CA-D | 82.81 | 82.81 | 1.203× |
| Fork-join | 5.0 | HEFT | 157.96 | 157.96 | 1.000× |
| Fork-join | 5.0 | CD-LS | 124.26 | 154.84 | 1.020× |
| Fork-join | 5.0 | CA-D | 117.70 | 117.70 | 1.342× |
| Fork-join | 10.0 | HEFT | 178.22 | 178.22 | 1.000× |
| Fork-join | 10.0 | CD-LS | 188.32 | 260.52 | **0.684×** |
| Fork-join | 10.0 | CA-D | 141.83 | 141.83 | 1.257× |

**Note:** Bold 0.684× for CD-LS fork-join CCR=10.0 indicates that CD-LS produces a schedule
WORSE than HEFT under fair replay — the contention-blind model was severely optimistic.
HEFT native makespan at CCR=10.0 is lower than CD-LS native because HEFT does not
attempt duplication (no extra task copies to schedule), and the contention-blind CD-LS
schedule creates heavy link traffic that collapses under replay.

## Replay Overhead (replayed/native)

Replay overhead > 1.0× reveals cases where the scheduler's native model was optimistic.
CA-D overhead is 1.0× in all fork-join cases (contention-aware model predicts accurately).
CD-LS overhead is 1.25× at fork-join CCR=5.0 and 1.38× at CCR=10.0 (contention-blind
model underestimates the effect of link contention caused by duplicate placements).
