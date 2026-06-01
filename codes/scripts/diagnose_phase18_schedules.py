"""
Phase 18B-DIAG: Scheduler Behavior Diagnostic Script.

Inspects, reports, and validates scheduler behavior for the three Phase 18 figure cases.
Does NOT modify any scheduler, metric, or replay logic.

Run from repository root:
    python scripts/diagnose_phase18_schedules.py
"""

import sys
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import copy

from src.noc import MeshNoC
from src.models import DAGGraph
from src.graph_families import (
    generate_out_tree_dag,
    generate_fork_dag,
    generate_fork_join_dag,
)
from src.heft_scheduler import HEFTScheduler
from src.classical_dup_scheduler import ClassicalDuplicationScheduler
from src.proposed_scheduler import ProposedScheduler
from src.contention_replay import replay_under_contention
from src.metrics import (
    count_duplicate_tasks,
    task_instance_ratio,
    count_communication_instances,
    max_link_utilization,
    compute_makespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def separator(title=""):
    w = 70
    if title:
        pad = (w - len(title) - 2) // 2
        print(f"\n{'='*pad} {title} {'='*(w-pad-len(title)-2)}")
    else:
        print("\n" + "=" * w)


def print_instance_table(state, dag, label):
    print(f"\n  {label} — task instances (sorted by start_time):")
    rows = []
    for tid, instances in state.task_instances.items():
        for inst in instances:
            rows.append((inst.start_time, inst.task_id, inst.processor_id,
                         inst.finish_time, inst.is_primary))
    rows.sort()
    print(f"  {'start':>8}  {'tid':>4}  {'proc':>5}  {'finish':>8}  {'primary'}")
    for start, tid, proc, finish, primary in rows:
        p_str = "PRIMARY" if primary else "dup    "
        print(f"  {start:8.3f}  T{tid:>3}  P{proc:>4}  {finish:8.3f}  {p_str}")


def print_metrics(state, replayed, label):
    ms = compute_makespan(state)
    rms = compute_makespan(replayed)
    heft_ms = None  # filled by caller
    dup = count_duplicate_tasks(state)
    tir = task_instance_ratio(state)
    comm = count_communication_instances(state)
    rcomm = count_communication_instances(replayed)
    mlu = max_link_utilization(state, ms)
    rmlu = max_link_utilization(replayed, rms)
    primary = sum(1 for insts in state.task_instances.values()
                  for i in insts if i.is_primary)
    total = sum(len(insts) for insts in state.task_instances.values())
    print(f"\n  [{label}]")
    print(f"    native makespan:          {ms:.4f}")
    print(f"    replayed makespan:        {rms:.4f}")
    print(f"    replay overhead ratio:    {rms/ms:.4f}")
    print(f"    primary task count:       {primary}")
    print(f"    total task instances:     {total}")
    print(f"    duplicate_task_count:     {dup}")
    print(f"    task_instance_ratio:      {tir:.4f}")
    print(f"    communication_count:      {comm}")
    print(f"    replayed_comm_count:      {rcomm}")
    print(f"    max_link_utilization:     {mlu:.4f}")
    print(f"    replayed_max_link_util:   {rmlu:.4f}")
    return ms


def check_dependency_correctness(state, dag, label, noc, use_comms=True):
    """Return list of violation strings (empty = all good)."""
    violations = []
    _EPS = 1e-6

    comm_map = {}  # (source_task, dest_proc) -> list of finish_time
    if use_comms:
        for ci in state.communication_instances:
            key = (ci.source_task, ci.destination_processor)
            comm_map.setdefault(key, []).append(ci.finish_time)

    for task_id in dag.task_ids():
        preds = dag.predecessors(task_id)
        if not preds:
            continue

        primary_insts = [i for i in state.task_instances.get(task_id, []) if i.is_primary]
        if not primary_insts:
            violations.append(f"  T{task_id}: no primary instance!")
            continue

        for v_inst in primary_insts:
            proc = v_inst.processor_id
            start = v_inst.start_time

            for pred in preds:
                pred_insts = state.task_instances.get(pred, [])
                if not pred_insts:
                    violations.append(
                        f"  T{task_id} on P{proc}: pred T{pred} has no instance!")
                    continue

                # Check: local instance or comm covers the dependency
                local_ok = any(
                    inst.processor_id == proc and inst.finish_time <= start + _EPS
                    for inst in pred_insts
                )
                if local_ok:
                    continue

                # For schedulers using comms: check CommunicationInstance
                if use_comms:
                    comm_ok = any(
                        ft <= start + _EPS
                        for ft in comm_map.get((pred, proc), [])
                    )
                    if comm_ok:
                        continue
                else:
                    # Analytic: find best-arrival from any pred instance
                    vol = dag.communication_volume(pred, task_id)
                    best_arr = min(
                        inst.finish_time if inst.processor_id == proc
                        else inst.finish_time + noc.communication_duration(
                            inst.processor_id, proc, vol)
                        for inst in pred_insts
                    )
                    if best_arr <= start + _EPS:
                        continue

                violations.append(
                    f"  T{task_id}(P{proc},start={start:.3f}): "
                    f"pred T{pred} not satisfied (no local/comm coverage)"
                )
    return violations


# ---------------------------------------------------------------------------
# Section 1: Full schedule reconstruction and metrics
# ---------------------------------------------------------------------------

def section1_reconstruct(noc):
    separator("SECTION 1: SCHEDULE RECONSTRUCTION & METRICS")
    results = {}

    cases = [
        ("case1_out_tree",
         generate_out_tree_dag(depth=2, branching_factor=2, ccr=5.0,
                               comp_range=(5, 20), comm_range=(1, 10), seed=0)),
        ("case2_fork",
         generate_fork_dag(n_branches=8, ccr=5.0,
                           comp_range=(5, 20), comm_range=(1, 10), seed=0)),
        ("case3_fork_join",
         generate_fork_join_dag(n_branches=4, branch_length=3, ccr=5.0,
                                comp_range=(5, 20), comm_range=(1, 10), seed=0)),
    ]

    for case_name, dag_g in cases:
        dag = DAGGraph(dag_g)
        separator(f"{case_name}: {dag.number_of_tasks()} tasks, "
                  f"{dag.number_of_edges()} edges")

        print("\n  DAG task costs:")
        for tid in sorted(dag.task_ids()):
            succs = dag.successors(tid)
            preds = dag.predecessors(tid)
            cost = dag.computation_cost(tid)
            edge_info = []
            for s in succs:
                edge_info.append(f"T{tid}->T{s}={dag.communication_volume(tid,s):.2f}")
            print(f"    T{tid}: cost={cost:.3f}, preds={sorted(preds)}, succs={sorted(succs)}, "
                  f"edges=[{', '.join(edge_info)}]")

        total_comp = sum(dag.computation_cost(t) for t in dag.task_ids())
        total_comm = sum(dag.communication_volume(u, v) for u, v in dag_g.edges())
        print(f"\n  total_comp={total_comp:.3f}  total_comm={total_comm:.3f}  "
              f"actual_ccr={total_comm/total_comp:.4f}")

        case_results = {}
        schedulers = {
            "HEFT": (HEFTScheduler(noc), False),
            "CD-LS": (ClassicalDuplicationScheduler(noc), False),
            "CA-D": (ProposedScheduler(noc), True),
        }
        heft_ms = None
        heft_replay_ms = None
        for sched_name, (sched, uses_comms) in schedulers.items():
            state = sched.schedule(dag)
            replayed = replay_under_contention(dag, state, noc)
            ms = print_metrics(state, replayed, sched_name)
            if heft_ms is None:
                heft_ms = ms
                heft_replay_ms = compute_makespan(replayed)
            spd = heft_replay_ms / compute_makespan(replayed)
            print(f"    replayed_speedup_vs_heft: {spd:.4f}")
            print_instance_table(state, dag, sched_name)
            case_results[sched_name] = {
                "state": state, "replayed": replayed,
                "dag": dag, "uses_comms": uses_comms
            }

        results[case_name] = case_results

    return results


# ---------------------------------------------------------------------------
# Section 2: HEFT processor choice analysis
# ---------------------------------------------------------------------------

def section2_heft_analysis(noc):
    separator("SECTION 2: HEFT PROCESSOR CHOICE ANALYSIS")

    for case_name, dag_g, dag_label in [
        ("out_tree", generate_out_tree_dag(depth=2, branching_factor=2, ccr=5.0,
                                           comp_range=(5, 20), comm_range=(1, 10), seed=0),
         "Case 1 out_tree"),
        ("fork", generate_fork_dag(n_branches=8, ccr=5.0,
                                   comp_range=(5, 20), comm_range=(1, 10), seed=0),
         "Case 2 fork"),
    ]:
        dag = DAGGraph(dag_g)
        heft = HEFTScheduler(noc)
        ranks = heft.compute_upward_ranks(dag)
        priority_order = heft.task_priority_order(dag)
        avg_hc = heft.average_hop_count()

        print(f"\n  [{dag_label}] avg_hop_count={avg_hc:.4f}  "
              f"(alpha=0.0 so comm_cost = beta*vol = vol)")
        print(f"  Priority order: {priority_order}")
        for tid in sorted(dag.task_ids()):
            print(f"    T{tid}: rank={ranks[tid]:.4f}, "
                  f"comp={dag.computation_cost(tid):.3f}, "
                  f"preds={sorted(dag.predecessors(tid))}, "
                  f"succs={sorted(dag.successors(tid))}")

        # Step through HEFT scheduling to show EFT per processor for each task
        from src.schedule_state import ScheduleState
        state = ScheduleState(noc)
        scheduled = set()
        all_tasks = set(dag.task_ids())
        priority_pos = {tid: i for i, tid in enumerate(priority_order)}

        print(f"\n  HEFT step-by-step (showing P0 vs best remote):")
        while len(scheduled) < len(all_tasks):
            ready = [t for t in all_tasks - scheduled
                     if all(p in scheduled for p in dag.predecessors(t))]
            task_id = min(ready, key=lambda t: priority_pos[t])
            comp_cost = dag.computation_cost(task_id)

            candidate_rows = []
            for proc in noc.processor_ids():
                drt = heft.estimate_data_ready_time(dag, state, task_id, proc)
                start = state.earliest_slot(proc, comp_cost, not_before=drt)
                finish = start + comp_cost
                candidate_rows.append((finish, proc, drt, start))
            candidate_rows.sort()

            best_finish, best_proc, best_drt, best_start = candidate_rows[0]
            print(f"\n    Task T{task_id} (comp={comp_cost:.3f}):")
            print(f"      {'proc':>5}  {'DRT':>8}  {'start':>8}  {'EFT':>8}")
            shown = set()
            # show P0 always, best proc always, and one remote if different
            for finish, proc, drt, start in candidate_rows:
                if proc == 0 or proc == best_proc or proc == candidate_rows[0][1]:
                    tag = " <-- SELECTED" if proc == best_proc else ""
                    print(f"      P{proc:>4}  {drt:8.3f}  {start:8.3f}  {finish:8.3f}{tag}")
                    shown.add(proc)
                if len(shown) >= 5:
                    break
            # also show a non-zero proc not yet shown
            for finish, proc, drt, start in candidate_rows:
                if proc not in shown and proc != 0:
                    print(f"      P{proc:>4}  {drt:8.3f}  {start:8.3f}  {finish:8.3f}")
                    break

            state.reserve_task(task_id=task_id, processor_id=best_proc,
                               start_time=best_start, finish_time=best_finish,
                               is_primary=True)
            scheduled.add(task_id)


# ---------------------------------------------------------------------------
# Section 3: Low-communication sanity variants (HEFT only)
# ---------------------------------------------------------------------------

def section3_low_comm_variants(noc):
    separator("SECTION 3: LOW-COMMUNICATION SANITY VARIANTS (HEFT)")

    for case_name, dag_g in [
        ("out_tree", generate_out_tree_dag(depth=2, branching_factor=2, ccr=5.0,
                                           comp_range=(5, 20), comm_range=(1, 10), seed=0)),
        ("fork", generate_fork_dag(n_branches=8, ccr=5.0,
                                   comp_range=(5, 20), comm_range=(1, 10), seed=0)),
    ]:
        print(f"\n  [{case_name}]")
        base_dag = DAGGraph(dag_g)

        # Variant A: zero communication volumes
        import networkx as nx
        dag_a = dag_g.copy()
        for u, v in dag_a.edges():
            dag_a[u][v]["communication_volume"] = 0.0
        dag_zero = DAGGraph(dag_a)
        state_a = HEFTScheduler(noc).schedule(dag_zero)
        procs_a = sorted({i.processor_id for insts in state_a.task_instances.values()
                          for i in insts if i.is_primary})
        ms_a = compute_makespan(state_a)
        print(f"    Variant A (vol=0.0): makespan={ms_a:.3f}, "
              f"unique procs used={procs_a}")
        rows_a = sorted(
            [(i.start_time, i.task_id, i.processor_id)
             for insts in state_a.task_instances.values()
             for i in insts if i.is_primary]
        )
        for s, tid, p in rows_a:
            print(f"      T{tid} -> P{p} (start={s:.3f})")

        # Variant B: low CCR (ccr=0.1) — regenerate with same seed/structure
        dag_b_g = None
        if "out_tree" in case_name:
            dag_b_g = generate_out_tree_dag(depth=2, branching_factor=2, ccr=0.1,
                                             comp_range=(5, 20), comm_range=(1, 10), seed=0)
        else:
            dag_b_g = generate_fork_dag(n_branches=8, ccr=0.1,
                                         comp_range=(5, 20), comm_range=(1, 10), seed=0)
        dag_b = DAGGraph(dag_b_g)
        state_b = HEFTScheduler(noc).schedule(dag_b)
        procs_b = sorted({i.processor_id for insts in state_b.task_instances.values()
                          for i in insts if i.is_primary})
        ms_b = compute_makespan(state_b)
        total_comp_b = sum(dag_b.computation_cost(t) for t in dag_b.task_ids())
        total_comm_b = sum(dag_b_g[u][v]["communication_volume"] for u, v in dag_b_g.edges())
        print(f"    Variant B (ccr=0.1, actual={total_comm_b/total_comp_b:.4f}): "
              f"makespan={ms_b:.3f}, unique procs used={procs_b}")
        rows_b = sorted(
            [(i.start_time, i.task_id, i.processor_id)
             for insts in state_b.task_instances.values()
             for i in insts if i.is_primary]
        )
        for s, tid, p in rows_b:
            print(f"      T{tid} -> P{p} (start={s:.3f})")

        # Variant C: beta=0, alpha=0
        noc_zero = MeshNoC(rows=4, cols=4, alpha=0.0, beta=0.0)
        state_c = HEFTScheduler(noc_zero).schedule(base_dag)
        procs_c = sorted({i.processor_id for insts in state_c.task_instances.values()
                          for i in insts if i.is_primary})
        ms_c = compute_makespan(state_c)
        print(f"    Variant C (beta=0, alpha=0): makespan={ms_c:.3f}, "
              f"unique procs used={procs_c}")
        rows_c = sorted(
            [(i.start_time, i.task_id, i.processor_id)
             for insts in state_c.task_instances.values()
             for i in insts if i.is_primary]
        )
        for s, tid, p in rows_c:
            print(f"      T{tid} -> P{p} (start={s:.3f})")


# ---------------------------------------------------------------------------
# Section 4: CD-LS vs CA-D on fork
# ---------------------------------------------------------------------------

def section4_cdls_vs_cad_fork(noc):
    separator("SECTION 4: CD-LS vs CA-D ON FORK (Case 2)")
    dag_g = generate_fork_dag(n_branches=8, ccr=5.0,
                              comp_range=(5, 20), comm_range=(1, 10), seed=0)
    dag = DAGGraph(dag_g)

    state_cdls = ClassicalDuplicationScheduler(noc).schedule(dag)
    state_cad = ProposedScheduler(noc).schedule(dag)
    replayed_cdls = replay_under_contention(dag, state_cdls, noc)
    replayed_cad = replay_under_contention(dag, state_cad, noc)

    print(f"\n  Fork structure:")
    print(f"    T0 (root): preds=[], succs={sorted(dag.successors(0))}")
    print(f"    Leaves: {sorted(dag.task_ids()) if len(dag.task_ids()) <= 12 else '...'}")
    print(f"    Max dag depth: {max(len(dag.predecessors(t)) for t in dag.task_ids())+1}")

    for label, state, replayed in [("CD-LS", state_cdls, replayed_cdls),
                                     ("CA-D", state_cad, replayed_cad)]:
        print(f"\n  [{label}]")
        print(f"    makespan: {compute_makespan(state):.4f}")
        print(f"    replayed: {compute_makespan(replayed):.4f}")
        print(f"    dup_count: {count_duplicate_tasks(state)}")
        print(f"    tir: {task_instance_ratio(state):.4f}")
        print(f"    comm_instances: {count_communication_instances(state)}")
        print(f"    replayed_comms: {count_communication_instances(replayed)}")
        print(f"    task instances:")
        for tid in sorted(state.task_instances.keys()):
            for inst in sorted(state.task_instances[tid], key=lambda i: i.processor_id):
                tag = "PRIMARY" if inst.is_primary else "dup    "
                print(f"      T{tid} P{inst.processor_id}: [{inst.start_time:.3f},{inst.finish_time:.3f}] {tag}")

    # Check if assignments are identical
    cdls_assign = {tid: sorted([(i.processor_id, i.is_primary)
                                 for i in insts], key=lambda x: x[0])
                   for tid, insts in state_cdls.task_instances.items()}
    cad_assign = {tid: sorted([(i.processor_id, i.is_primary)
                                for i in insts], key=lambda x: x[0])
                  for tid, insts in state_cad.task_instances.items()}

    if cdls_assign == cad_assign:
        print("\n  RESULT: CD-LS and CA-D produce IDENTICAL task assignments.")
        print("  REASON: Fork DAG has only one ancestor level.")
        print("  - CD-LS: duplicates T0 (direct parent) whenever Delta_EFT > 0.")
        print("  - CA-D: duplicates T0 (direct parent) recursively, but T0 has no")
        print("    predecessors so recursive step terminates immediately at T0.")
        print("  - Both evaluate exactly the same duplication decision under different")
        print("    communication models. At alpha=0 beta=1, the contention-aware model")
        print("    and the classic analytic model agree on the local vs remote timing")
        print("    when no other communications are in flight.")
        print("  CONCLUSION: Fork case illustrates duplication benefit, but NOT")
        print("    the CA-D vs CD-LS distinction. A deeper DAG is needed for that.")
    else:
        diffs = []
        for tid in sorted(set(cdls_assign) | set(cad_assign)):
            if cdls_assign.get(tid) != cad_assign.get(tid):
                diffs.append(f"T{tid}: cdls={cdls_assign.get(tid)} cad={cad_assign.get(tid)}")
        print(f"\n  RESULT: CD-LS and CA-D differ on {len(diffs)} tasks:")
        for d in diffs:
            print(f"    {d}")


# ---------------------------------------------------------------------------
# Section 5: CA-D duplicate audit on fork-join
# ---------------------------------------------------------------------------

def section5_cad_duplicate_audit(noc):
    separator("SECTION 5: CA-D DUPLICATE AUDIT ON FORK-JOIN (Case 3)")
    dag_g = generate_fork_join_dag(n_branches=4, branch_length=3, ccr=5.0,
                                   comp_range=(5, 20), comm_range=(1, 10), seed=0)
    dag = DAGGraph(dag_g)
    state = ProposedScheduler(noc).schedule(dag)

    print(f"\n  Fork-join structure (n_branches=4, branch_length=3, 14 tasks):")
    print(f"    Root: T0, Sink: T13")
    print(f"    Branch 0: T1->T2->T3")
    print(f"    Branch 1: T4->T5->T6")
    print(f"    Branch 2: T7->T8->T9")
    print(f"    Branch 3: T10->T11->T12")
    print(f"    All branch ends -> T13")

    print(f"\n  All task instances:")
    for tid in sorted(state.task_instances.keys()):
        for inst in sorted(state.task_instances[tid], key=lambda i: i.processor_id):
            tag = "PRIMARY" if inst.is_primary else "DUP    "
            print(f"    T{tid:>2} P{inst.processor_id:>2}: [{inst.start_time:.3f},{inst.finish_time:.3f}] {tag}")

    print(f"\n  Duplicate analysis:")
    # Find comm instances keyed by source
    comm_by_source = {}
    for ci in state.communication_instances:
        key = (ci.source_task, ci.source_processor)
        comm_by_source.setdefault(key, []).append(ci)

    dup_instances = [
        (tid, inst)
        for tid, insts in state.task_instances.items()
        for inst in insts
        if not inst.is_primary
    ]

    for tid, inst in sorted(dup_instances, key=lambda x: (x[0], x[1].processor_id)):
        proc = inst.processor_id
        start = inst.start_time
        finish = inst.finish_time

        # Find primary instance
        primary = next(i for i in state.task_instances[tid] if i.is_primary)

        # Successors on same processor
        succs = dag.successors(tid)
        succ_insts_same_proc = []
        for s in succs:
            for si in state.task_instances.get(s, []):
                if si.processor_id == proc:
                    succ_insts_same_proc.append((s, si))

        # Is this dup used as source in any CommunicationInstance?
        comm_from_dup = comm_by_source.get((tid, proc), [])

        # Determine usage class
        local_use = len(succ_insts_same_proc) > 0
        remote_use = len(comm_from_dup) > 0

        if local_use:
            usage = "A: local source for successor"
        elif remote_use:
            usage = "B: remote source in CommunicationInstance"
        else:
            usage = "C: APPARENTLY UNUSED"

        print(f"\n    DUP T{tid} on P{proc}: [{start:.3f},{finish:.3f}]")
        print(f"      primary: P{primary.processor_id} [{primary.start_time:.3f},{primary.finish_time:.3f}]")
        print(f"      succs of T{tid}: {sorted(succs)}")
        print(f"      succ instances on P{proc}: {[(f'T{s}', f'P{si.processor_id}', si.start_time) for s, si in succ_insts_same_proc]}")
        print(f"      comm from this dup: {[(ci.target_task, ci.destination_processor, ci.finish_time) for ci in comm_from_dup]}")
        print(f"      usage class: {usage}")

        # Check timing: does T{tid} dup finish before successor start?
        for s, si in succ_insts_same_proc:
            gap = si.start_time - finish
            print(f"      T{s} starts at {si.start_time:.3f}, dup finishes {finish:.3f}, gap={gap:.4f}")
            if gap < -1e-9:
                print(f"      WARNING: successor T{s} starts BEFORE dup T{tid} finishes!")


# ---------------------------------------------------------------------------
# Section 6: Dependency correctness validation
# ---------------------------------------------------------------------------

def section6_dependency_check(results, noc):
    separator("SECTION 6: DEPENDENCY CORRECTNESS CHECK")
    all_ok = True
    for case_name, case_results in results.items():
        for sched_name, data in case_results.items():
            state = data["state"]
            dag = data["dag"]
            uses_comms = data["uses_comms"]
            violations = check_dependency_correctness(
                state, dag, f"{case_name}/{sched_name}", noc, use_comms=uses_comms
            )
            if violations:
                all_ok = False
                print(f"\n  {case_name} {sched_name}: {len(violations)} VIOLATIONS:")
                for v in violations:
                    print(f"    {v}")
            else:
                print(f"  {case_name} {sched_name}: OK — no dependency violations")
    if all_ok:
        print("\n  All schedules passed dependency correctness check.")
    return all_ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    noc = MeshNoC(rows=4, cols=4, alpha=0.0, beta=1.0)

    results = section1_reconstruct(noc)
    section2_heft_analysis(noc)
    section3_low_comm_variants(noc)
    section4_cdls_vs_cad_fork(noc)
    section5_cad_duplicate_audit(noc)
    all_ok = section6_dependency_check(results, noc)

    separator("DONE")
    print(f"  Dependency check: {'PASS' if all_ok else 'FAIL — see violations above'}")


if __name__ == "__main__":
    main()
