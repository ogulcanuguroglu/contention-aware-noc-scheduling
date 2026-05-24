# CMP720 Master Project Presentation
**Student:** Oğulcan Uğuroğlu
**Supervisor:** Prof. Dr. Sinnen
**Topic:** Contention-Aware Task Duplication for DAG Scheduling on NoC

---

## Slide 1: Problem Definition — Network Contention in DAG Scheduling

- **The Illusion of Ideal Networks:** Classical DAG schedulers (e.g., HEFT) calculate inter-processor communication costs analytically, completely ignoring physical network traffic and link sharing.
- **The Reality of Contention:** In 2D-Mesh NoC architectures, multiple parallel tasks routing data across shared links create severe queuing delays, making native makespan predictions highly optimistic.
- **The Core Research Question:** "Should we wait for data through a congested multi-hop path, or is it more efficient to duplicate the predecessor task locally?"
- **Our Core Focus:** Developing CA-D (Contention-Aware Duplication), an offline scheduling heuristic that models physical NoC link reservations to make traffic-aware duplication decisions.

<!-- Speaker notes: In this project we solve the problem of statically assigning workloads on multi-core NoC systems. Algorithms like HEFT assume the network is always idle. We aim to close this optimism gap by modeling real-world network contention. -->

---

## Slide 2: Target Framework & System Models

- **Application Model (DAG):** Directed Acyclic Graphs where vertices represent computation costs and directed edges define data dependency volumes.
- **Communication-to-Computation Ratio (CCR):** Evaluated across a wide spectrum (0.1 to 10.0).
- **Platform Model:** A 4×4 homogeneous 2D Mesh Network-on-Chip (16 processors).
- **Deterministic XY Routing:** Packets move strictly along the X-axis first, then the Y-axis.
- **Link-Level Slot Reservation:** Analytical delays are replaced by directional, atomic interval reservations mapped directly on physical NoC link channels.

<!-- Speaker notes: Instead of multiplying data transfers by simple coefficients, we process them as timed interval reservations on directional links along the XY routing path. -->

---

## Slide 3: Implementation Status — The 4-Scheduler Evaluation

- **Custom Python Simulation Framework:** Developed a lightweight, reservation-based hardware execution simulator optimized for heavy state-cloning.
- The four schedulers form a 2×2 design matrix isolating the contributions of duplication and contention-awareness independently.

| Scheduler | Task Duplication | NoC Contention Model | Role |
|---|---|---|---|
| HEFT Baseline | No | No | Contention-blind, duplication-free list scheduler |
| CA-LS | No | Yes | No duplication; strict physical NoC reservations |
| CD-LS | Yes | No | Parent task replication; contention-blind network |
| **CA-D (Proposed)** | **Yes** | **Yes** | **Co-optimizes contention modeling + recursive duplication** |

<!-- Speaker notes: We developed 4 schedulers on the same infrastructure so we can isolate the effect of both duplication and contention-awareness independently. -->

---

## Slide 4: Architectural Deviations & Design Decisions

- **Deviation 1: Custom Interval Simulator over Cycle-Accurate Tools (BookSim)** — Required for sub-microsecond state cloning during scheduler exploration.
- **Decision 2: The "Fair Replay" Module** — Contention-blind schedulers produce falsely optimistic execution end times. We built a validation engine that enforces final placements on the same physical NoC model to extract true makespans.
- **Decision 3: Structural Shallow-Copy Optimization** — Replaced `deepcopy` with shared immutable infrastructure to prevent recursion bottlenecks in the clone-discard pattern.

<!-- Speaker notes: One of our biggest innovations was the 'Fair Replay' module. Because HEFT does not see traffic, it looks very fast on paper. We re-run all algorithms' placement plans under the same physical NoC rules to make the comparison fair. -->

---

## Slide 5: Deep Dive I — The CA-D Scheduling Pipeline

- **Stage 1: Upward Priority Ranking** — Critical path priority assignment.
- **Stage 2: Candidate Processor Exploration** — 4×4 grid evaluation for each ready task.
- **Stage 3: Isolated State Branching** — Clone-Discard pattern prevents data pollution across candidate evaluations.
- **Stage 4: Best Candidate Promotion** — Minimizes Earliest Finish Time (EFT) across all candidates.
- **Stage 5: Post-Processing Clean-up** — Conservative pruning removes redundant task copies.

<!-- Speaker notes: Our CA-D algorithm works like a 5-stage pipeline. The 'Clone-Discard' software pattern we invented prevents uncertain trials from permanently polluting the scheduling table. -->

---

## Slide 6: Deep Dive II — Recursive Ancestor Duplication Mechanics

- **The Core Evaluation Metric (ΔèEFT):**
  - *Baseline (EFT_no_dup):* Leave predecessor remote; suffer NoC contention delay.
  - *Duplicated (EFT_dup):* Replicate predecessor locally on the target core.
  - *Commit Rule:* ΔEFT = EFT_no_dup − EFT_dup > ε
- **Recursive Traversal:** If local duplication helps, recursively climb the ancestor tree to evaluate grandparents as well.
- **Cycle Guard Constraint:** A visiting set strictly blocks infinite loops during traversal.

<!-- Speaker notes: There is no blind copying here. If duplicating a parent is mathematically advantageous, we perform a backward recursive search looking at its parents as well. -->

---

## Slide 7: Deep Dive III — Best-Instance Selection & Pruning

- **Data Source Selection Rule (priority order):**
  1. Earliest Arrival Time (under link contention)
  2. Local Advantage (Tie-Breaker: prefer local copy)
  3. Determinism (Smaller Processor ID for stable ordering)
- **Conservative Redundant Pruning — Deleted if ALL hold:**
  1. Not a primary (first-scheduled) node instance
  2. At least one valid instance of the task remains on the chip
  3. No local successor or outgoing NoC communication depends on it

<!-- Speaker notes: Once scheduling is complete, the Conservative Pruning stage kicks in and safely removes copies that have no remaining demand and contribute nothing to performance. -->

---

## Slide 8: Experimental Setup & Target Workloads

- **960 Comprehensive Experimental Runs** across all scheduler × DAG × CCR combinations.
- **4 Target Structural DAG Families:** Chain, Fork, Out-tree, Fork-Join.
- **4 CCR Spectrum Points:** 0.1 (compute-bound), 1.0, 5.0, 10.0 (communication-bound).
- **Statistical Distribution:** 20 distinct random seeds per configuration for robust averages.

<!-- Speaker notes: We tested our algorithm with 4 deterministic graph families. Using 4 different CCR ratios and 20 seeds per scenario, we ran a total of 960 large experimental runs. -->

---

## Slide 9: Quantitative Performance — Replayed Speedup & Overhead

- **The Core Discovery (Replayed Speedup):** At high communication intensities (CCR=10.0), CA-D yields the highest speedup. Contention-blind duplication (CD-LS) *collapses*, performing significantly worse than HEFT (0.68× slowdown).
- **The Illusion Exposed (Replay Overhead):** HEFT and CD-LS show massive replay overhead bounds (38% to 85% optimistic error). CA-D maintains a perfect flat line at 1.0.
- **Key Takeaway:** Modeling NoC contention during scheduling is not optional at high CCR — it is the deciding factor between improvement and degradation.

<!-- Speaker notes: CD-LS, which duplicates without accounting for network traffic, performed even worse than HEFT at CCR=10. In the Replay Overhead chart, we proved that other algorithms present up to 85% illusory optimism, while CA-D matches real hardware 100%. -->

---

## Slide 10: Qualitative Performance — Fork-Join Gantt Chart Analysis

- **Visual Proof of Contention Avoidance:**
  - *HEFT Strategy:* Forced to stack independent tasks onto fewer cores to prevent high analytical multi-hop communication costs. Creates a narrow, tall schedule.
  - *CA-D Strategy:* Spatially distributes tasks across the 4×4 mesh tiles. Replicates high-frequency ancestor nodes directly onto target cores. Creates a wide, flat schedule.
- **The Outcome:** Shortens the global makespan by ~20% in dense Fork-Join workloads by trading SRAM for bandwidth.

<!-- Speaker notes: Looking at the Gantt chart, we see HEFT piling tasks onto a single processor. CA-D uses the full chip in a balanced way through duplications and compresses the finish time by 20%. -->

---

## Slide 11: Discussion & Embedded System Design Trade-offs

- **The Computational Cost:** Making contention-aware decisions requires recursive state cloning (~14× slower compilation runtime). Chain DAGs trigger maximum recursion depth.
- **Embedded Co-Design Trade-offs:**
  - *Memory vs. Bandwidth:* Task duplication reduces network congestion but consumes local instruction memory (SRAM).
  - *The Power Balance:* Excessive duplication increases dynamic switching power, making Conservative Pruning mandatory for power-constrained targets.
- **Scalability Note:** The heuristic remains offline (compile-time); runtime overhead on the target SoC is zero.

<!-- Speaker notes: CA-D makes very smart decisions but the cost is high compilation time and SRAM usage. For embedded systems, we can clearly see how vital the Pruning mechanism we designed is to prevent memory and power waste. -->

---

## Slide 12: Conclusions and Future Work

- **Current Status:** Physical 2D-Mesh NoC models, XY routing, recursive CA-D heuristic, and verification suites are fully implemented and experimentally validated.
- **Key Result:** CA-D consistently outperforms all baselines at CCR ≥ 5.0 while maintaining zero replay overhead — proving that contention-aware scheduling closes the simulation-to-hardware gap.
- **Future Work:**
  - Support for heterogeneous computing tiles (GPU/DSP cores)
  - Active physical power estimation models
  - Online adaptive scheduling variants

<!-- Speaker notes: In conclusion, we completed all planned software and testing processes. CA-D achieves its design goals: better makespan at high communication intensity, with provably accurate predictions. -->
