"""
Export a real scheduler run to schedule_output.json for use by demo.html.

Uses the project's existing modules without any modification.  Run from the
project root:

    python scripts/export_demo_json.py

Output: schedule_output.json (written next to this invocation, i.e. the CWD
        which should be the project root).

Parameters are fixed so the output is deterministic and reproducible.

Note on duplication_steps:
    The EFT_no_dup / EFT_dup / Delta_EFT values computed inside
    ProposedScheduler._evaluate_duplications() are local variables that are
    not currently surfaced by the scheduler API.  Instrumenting that method
    requires modifying proposed_scheduler.py, which is out of scope here.
    "duplication_steps" is therefore exported as an empty list.  A future
    step can add a lightweight tracing wrapper around ProposedScheduler to
    collect these values without touching the core logic.
"""

import json
import sys
from pathlib import Path

# Allow "from src.xxx import ..." when run from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.dag_generator import generate_dag
from src.heft_scheduler import HEFTScheduler
from src.metrics import schedule_summary, speedup
from src.models import DAGGraph
from src.noc import MeshNoC
from src.proposed_scheduler import ProposedScheduler

# ── Fixed parameters ──────────────────────────────────────────────────────────
ROWS      = 4
COLS      = 4
ALPHA     = 1.0
BETA      = 1.0
N_TASKS   = 9
EDGE_PROB = 0.4
CCR       = 1.0
COMP_MIN  = 5
COMP_MAX  = 20
SEED      = 42

OUTPUT_PATH = Path("schedule_output.json")


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _link_to_list(link):
    """Convert a Link dataclass to [source_processor, destination_processor]."""
    return [link.source_processor, link.destination_processor]


def _serialise_task_instances(state):
    """Return a list of dicts for every TaskInstance in the schedule."""
    result = []
    for instances in state.task_instances.values():
        for inst in instances:
            result.append({
                "id":         inst.task_id,
                "proc":       inst.processor_id,
                "start":      round(inst.start_time, 6),
                "finish":     round(inst.finish_time, 6),
                "is_primary": inst.is_primary,
            })
    result.sort(key=lambda d: (d["id"], d["proc"]))
    return result


def _serialise_communications(state):
    """Return a list of dicts for every CommunicationInstance in the schedule."""
    result = []
    for ci in state.communication_instances:
        result.append({
            "src_task": ci.source_task,
            "dst_task": ci.target_task,
            "src_proc": ci.source_processor,
            "dst_proc": ci.destination_processor,
            "route":    [_link_to_list(lnk) for lnk in ci.route],
            "start":    round(ci.start_time, 6),
            "finish":   round(ci.finish_time, 6),
            "volume":   round(ci.communication_volume, 6),
        })
    result.sort(key=lambda d: (d["src_task"], d["dst_task"], d["src_proc"]))
    return result


def _serialise_metrics(state, baseline_makespan=None):
    """Return schedule_summary dict with an optional speedup field."""
    summary = schedule_summary(state)
    # Round all floats for readability
    out = {k: round(v, 6) if isinstance(v, float) else v
           for k, v in summary.items()}
    if baseline_makespan is not None:
        out["speedup_vs_heft"] = round(
            speedup(baseline_makespan, summary["makespan"]), 6
        )
    return out


# ── Main export ───────────────────────────────────────────────────────────────

def main():
    # 1. Build NoC
    noc = MeshNoC(rows=ROWS, cols=COLS, alpha=ALPHA, beta=BETA)

    # 2. Generate DAG (same seed → identical graph every run)
    dag_nx = generate_dag(
        n_tasks=N_TASKS,
        edge_prob=EDGE_PROB,
        ccr=CCR,
        comp_range=(COMP_MIN, COMP_MAX),
        seed=SEED,
    )
    dag = DAGGraph(dag_nx)

    # 3. Upward ranks and priority order (shared by all schedulers)
    heft_sched = HEFTScheduler(noc)
    ranks       = heft_sched.compute_upward_ranks(dag)
    priority    = heft_sched.task_priority_order(dag)

    # 4. Run HEFT
    heft_state   = heft_sched.schedule(dag)
    heft_makespan = schedule_summary(heft_state)["makespan"]

    # 5. Run Proposed (CA-D)
    prop_state = ProposedScheduler(noc).schedule(dag)

    # 6. Assemble JSON payload
    noc_processors = [
        {"id": pid, "x": noc.to_coordinates(pid)[0], "y": noc.to_coordinates(pid)[1]}
        for pid in noc.processor_ids()
    ]

    dag_tasks = [
        {
            "id":        tid,
            "comp_cost": round(dag.computation_cost(tid), 6),
            "rank":      round(ranks[tid], 6),
        }
        for tid in sorted(dag.task_ids())
    ]

    dag_edges = [
        {
            "src":    src,
            "dst":    dst,
            "volume": round(dag.communication_volume(src, dst), 6),
        }
        for src, dst in sorted(dag.edge_ids())
    ]

    payload = {
        "metadata": {
            "description": "Real scheduler output for HTML demo",
            "rows":      ROWS,
            "cols":      COLS,
            "alpha":     ALPHA,
            "beta":      BETA,
            "seed":      SEED,
            "n_tasks":   N_TASKS,
            "edge_prob": EDGE_PROB,
            "ccr":       CCR,
        },
        "noc": {
            "rows":       ROWS,
            "cols":       COLS,
            "alpha":      ALPHA,
            "beta":       BETA,
            "processors": noc_processors,
        },
        "dag": {
            "tasks":          dag_tasks,
            "edges":          dag_edges,
            "priority_order": priority,
        },
        "heft_schedule": {
            "tasks":          _serialise_task_instances(heft_state),
            "communications": _serialise_communications(heft_state),
            "metrics":        _serialise_metrics(heft_state),
        },
        "proposed_schedule": {
            "tasks":          _serialise_task_instances(prop_state),
            "communications": _serialise_communications(prop_state),
            # Requires instrumentation of ProposedScheduler._evaluate_duplications()
            # to capture EFT_no_dup, EFT_dup, Delta_EFT per predecessor per task.
            # Left empty until that tracing step is added.
            "duplication_steps": [],
            "metrics":           _serialise_metrics(prop_state, heft_makespan),
        },
    }

    # 7. Write JSON
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    print(f"Wrote {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()
