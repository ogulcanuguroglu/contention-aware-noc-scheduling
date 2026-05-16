# Reproducibility

This document describes how to set up the environment and reproduce all Phase 16 experimental results.

---

## Environment

- **Python:** 3.12 (developed and tested on Python 3.12.10)
- **Package management:** pip with `requirements.txt`
- **Test framework:** pytest ≥ 7.4

All random number generation uses `numpy.default_rng(seed)` with fixed seeds (0, 1, 2 in all Phase 16 experiments). The same seed and Python/NumPy version always produce identical DAG structures and cost assignments.

---

## Setup

### Create and activate a virtual environment

**Linux / macOS:**
```bash
python -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

**Dependencies (`requirements.txt`):**
```
networkx>=3.2
numpy>=1.26
pandas>=2.1
matplotlib>=3.8
PyYAML>=6.0
pytest>=7.4
```

All dependencies are pure Python or have standard binary wheels. No GPU, CUDA, or external NoC simulator is required.

---

## Test Command

Run the full test suite to verify the installation:

```bash
python -m pytest tests/ -q
```

Expected output at Phase 17 cleanup:
```
1039 passed in ...
```

All tests are deterministic. If any test fails after a clean install, check the Python and package versions against `requirements.txt`.

---

## Experiment Commands

Run experiments from the project root directory. Use `-u` (unbuffered mode) for real-time progress output.

### Experiment A — random DAG grid

```bash
python -u scripts/run_final_experiments.py
```

### Experiment B — graph family grid

```bash
python -u scripts/run_graph_family_experiments.py
```

### Combined analysis

```bash
python scripts/analyze_results.py
```

The analysis script requires both Experiment A and B CSVs to exist.

---

## Expected Outputs

After running all three commands:

### Experiment A outputs

| File | Description |
|---|---|
| `results/raw/final_grid_small_v2.csv` | 72-row CSV with all metrics and replay columns |
| `results/plots/final_grid_small_v2/no_error/*.png` | 10 line plots without error bars |
| `results/plots/final_grid_small_v2/with_error/*.png` | 10 line plots with error bars |
| `results/summary/final_grid_small_v2_summary.md` | Experiment A summary with tables and interpretation |

### Experiment B outputs

| File | Description |
|---|---|
| `results/raw/graph_family_diagnostic_v1.csv` | 324-row CSV with all metrics and replay columns |
| `results/plots/graph_family_diagnostic_v1/no_error/*.png` | 9 bar charts by family |
| `results/summary/graph_family_diagnostic_v1_summary.md` | Experiment B summary with family-level tables |

### Combined analysis output

| File | Description |
|---|---|
| `results/summary/phase16_combined_interpretation.md` | Cross-experiment analysis and final report recommendations |

---

## Runtime Notes

### Experiment A runtime

Approximately 30–60 minutes on a modern laptop (dominated by ProposedScheduler on n_tasks=20 with edge_prob=0.40 and CCR=5.0).

### Experiment B runtime

Approximately 15–30 minutes on a modern laptop.

### ProposedScheduler behavior

- Greedy recursive ancestor duplication makes CA-D significantly slower than the other schedulers
- Runtime scales with task count, DAG density, and number of predecessors per task
- Progress is printed after every scheduler run; ProposedScheduler runs print additional heartbeat messages
- A partial checkpoint CSV (`*.partial.csv`) is written after every complete workload group (all 4 schedulers done). If the script is interrupted, the partial CSV contains all completed rows in raw (pre-relative-metrics) form

### Excluded configurations

- **n_tasks=40:** excluded from Experiment A because ProposedScheduler takes >2 minutes per run on dense 40-task DAGs
- **Chain family:** excluded from Experiment B because linear topology causes ProposedScheduler to traverse the full chain depth per task, resulting in hangs even at n_tasks=20

These exclusions are documented in the partial-result notes in `results/summary/phase16_combined_interpretation.md`.

---

## Reproduction Notes

### Seeds

Phase 16 uses seeds [0, 1, 2] for all experiments. Changing seeds produces different DAG instances with the same structural parameters.

### NoC configuration

All Phase 16 experiments use a 4×4 mesh (16 processors) with `alpha=0.0`, `beta=1.0`. Changing these parameters requires re-running experiments.

### Scheduler behavior

All scheduler algorithms are deterministic given the same seed, DAG, and NoC. The schedule produced by a given scheduler is the same on every run.

### Default config

`configs/default.yaml` is the legacy Phase 9 configuration. The Phase 16 experiment scripts (`scripts/run_final_experiments.py`, `scripts/run_graph_family_experiments.py`) use inline hardcoded configurations and do not read `configs/default.yaml`.
