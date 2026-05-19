"""
Phase 18B-3 (Visual Cleanup): Report-quality figure generation.

Changes from Phase 18B-2:
  - Two NoC topology figures: fig0a (generic, all procs same color) and
    fig0b (Case 3 Proposed CA-D procs highlighted, computed dynamically).
  - DAG topology clean/full mode: clean mode omits c= and v= labels for
    presentation; full mode keeps them for appendix reference.
  - Gantt multi-panel figures: compact active-processor rows per scheduler;
    caption note added to every multi-panel figure.
  - Bar chart legend: custom handles for "Native speedup (gray)" and
    "Replayed speedup (scheduler color)" — no longer misleads with a
    single-color legend entry for replayed bars.
  - Replay overhead caption (fig3d): uses precise per-scheduler wording
    instead of generic "all contention-blind models underestimate" claim.
  - TIR caption (fig2d): full definition included.

Diagnostic conclusion (Phase 18B-DIAG): no scheduler bugs.
  - HEFT serialization at CCR=5.0 is expected: remote DRT >> local queue delay.
  - CD-LS = CA-D on fork is expected: one-level DAG, same duplication decision.
  - CA-D T9 duplicate on fork-join is necessary for local data delivery to T13.

Cases:
  Case 1 — out_tree (depth=2, bf=2, CCR=5.0, seed=0): recursive duplication story
  Case 2 — fork (n_branches=8, CCR=5.0, seed=0): duplication benefit story
  Case 3 — fork_join (n_branches=4, bl=3, CCR=5.0, seed=0): replay fairness story

Run from repository root:
    python scripts/generate_phase18_figures.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.lines as mlines
import networkx as nx
import numpy as np

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
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMP_RANGE = (5, 20)
COMM_RANGE = (1, 10)
NOC_ROWS = 4
NOC_COLS = 4

DPI = 300
FIGURE_WIDTH = 10

SCHEDULER_LABELS = {
    "heft": "HEFT",
    "cdls": "CD-LS",
    "cals": "CA-LS",
    "cad": "Proposed CA-D",
}

# Identity colors used for replayed bars and TIR/overhead single-bar charts
SCHEDULER_COLORS = {
    "heft": "#4C72B0",
    "cdls": "#DD8452",
    "cals": "#55A868",
    "cad": "#C44E52",
}

# Native bars are neutral gray regardless of scheduler
NATIVE_BAR_COLOR = "#b0b8c4"

TASK_PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B2",
    "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD",
    "#2f7b46", "#b34a4a", "#3a5c8a", "#7a4a9a", "#9a7a2a",
    "#4a8a7a", "#8a4a4a",
]

# fig0a and fig0b live in the base directory; case figures in subdirectories.
EXPECTED_BASE_STEMS: list[str] = [
    "fig0a_noc_topology_generic",
    "fig0b_noc_topology_case3_used",
]

EXPECTED_FIGURES: dict[str, list[str]] = {
    "out_tree_small": [
        "fig1a_dag_topology",
        "fig1b_heft_gantt",
        "fig1c_cad_gantt",
        "fig1d_heft_vs_cad",
        "fig1e_speedup_bars",
    ],
    "fork_duplication": [
        "fig2a_dag_topology",
        "fig2b_three_scheduler_gantt",
        "fig2c_speedup_bars",
        "fig2d_tir_bars",
    ],
    "fork_join_replay": [
        "fig3a_dag_topology",
        "fig3b_replay_speedup_bars",
        "fig3c_three_scheduler_gantt",
        "fig3d_replay_overhead_bars",
    ],
}

_COMPACT_NOTE = (
    "Processor rows are compacted per scheduler; "
    "only processors with scheduled task instances are shown."
)


# ---------------------------------------------------------------------------
# Output directory management
# ---------------------------------------------------------------------------

def ensure_output_dirs(base: Path) -> dict[str, Path]:
    dirs = {
        "out_tree": base / "out_tree_small",
        "fork": base / "fork_duplication",
        "fork_join": base / "fork_join_replay",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def save_figure(fig: plt.Figure, outdir: Path, stem: str) -> None:
    """Save figure as both PNG (300 DPI) and PDF."""
    png_path = outdir / f"{stem}.png"
    pdf_path = outdir / f"{stem}.pdf"
    fig.savefig(png_path, dpi=DPI, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)
    size_kb = png_path.stat().st_size // 1024
    print(f"  Saved {stem}.png ({size_kb} KB) + .pdf", flush=True)


# ---------------------------------------------------------------------------
# Figure 0: standalone NoC topology (two variants)
# ---------------------------------------------------------------------------

def generate_noc_topology_figure(base: Path, noc: MeshNoC,
                                  stem: str,
                                  highlight_procs: list[int] | None = None) -> None:
    """Draw 4×4 MeshNoC grid with labeled processors and directed links.

    stem: output filename stem (e.g. "fig0a_noc_topology_generic")
    highlight_procs: processor IDs to color in red; None = all same neutral blue.
    """
    rows, cols = noc.rows, noc.cols
    fig, ax = plt.subplots(figsize=(5.5, 5.5))

    # Draw horizontal and vertical undirected links
    link_kw = dict(color="#888888", linewidth=1.2, zorder=1)
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                ax.plot([c, c + 1], [rows - 1 - r, rows - 1 - r], **link_kw)
            if r + 1 < rows:
                ax.plot([c, c], [rows - 1 - r, rows - 1 - (r + 1)], **link_kw)

    # Draw processor nodes
    highlight_set = set(highlight_procs) if highlight_procs else set()
    for r in range(rows):
        for c in range(cols):
            pid = r * cols + c
            x, y = c, rows - 1 - r
            color = "#C44E52" if pid in highlight_set else "#4C72B0"
            circle = plt.Circle((x, y), 0.35, color=color, zorder=2, alpha=0.92)
            ax.add_patch(circle)
            ax.text(x, y, f"P{pid}", ha="center", va="center",
                    fontsize=8, color="white", fontweight="bold", zorder=3)

    # XY routing annotation arrows
    ax.annotate("", xy=(2.5, rows - 0.3), xytext=(0.5, rows - 0.3),
                arrowprops=dict(arrowstyle="->", color="#333333", lw=1.4))
    ax.text(1.5, rows - 0.12, "X direction first", ha="center", va="bottom",
            fontsize=7.5, color="#333333")
    ax.annotate("", xy=(-0.5, rows - 2.5), xytext=(-0.5, rows - 0.5),
                arrowprops=dict(arrowstyle="->", color="#333333", lw=1.4))
    ax.text(-0.85, rows - 1.5, "then Y", ha="center", va="center",
            fontsize=7.5, color="#333333", rotation=90)

    # Legend only when highlights are present
    if highlight_set:
        used_patch = mpatches.Patch(color="#C44E52", label="Used by Proposed CA-D (Case 3)")
        other_patch = mpatches.Patch(color="#4C72B0", label="Other processor")
        ax.legend(handles=[used_patch, other_patch], fontsize=7.5,
                  loc="lower right", framealpha=0.9)

    ax.set_xlim(-1.1, cols - 0.5)
    ax.set_ylim(-0.7, rows + 0.3)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("4×4 MeshNoC, XY Routing\nalpha=0.0, beta=1.0",
                 fontsize=11, fontweight="bold", pad=8)

    fig.tight_layout()
    save_figure(fig, base, stem)


# ---------------------------------------------------------------------------
# DAG topology drawing
# ---------------------------------------------------------------------------

def _layered_positions(dag: DAGGraph) -> dict[int, tuple[float, float]]:
    """Compute y-layer (topological depth) and spread x evenly within each layer."""
    g = dag.graph
    topo = list(nx.topological_sort(g))
    depth: dict[int, int] = {}
    for node in topo:
        preds = list(g.predecessors(node))
        depth[node] = 0 if not preds else max(depth[p] for p in preds) + 1

    by_layer: dict[int, list[int]] = {}
    for node, d in depth.items():
        by_layer.setdefault(d, []).append(node)

    pos: dict[int, tuple[float, float]] = {}
    max_layer = max(by_layer.keys())
    for layer, nodes in by_layer.items():
        nodes_sorted = sorted(nodes)
        n = len(nodes_sorted)
        for i, node in enumerate(nodes_sorted):
            x = (i - (n - 1) / 2.0)
            y = max_layer - layer
            pos[node] = (x, y)
    return pos


def draw_dag_topology(dag: DAGGraph, ax: plt.Axes, title: str,
                      mode: str = "clean",
                      show_edge_labels: bool = True,
                      edge_label_fontsize: float = 6.5) -> None:
    """Draw a layered DAG topology.

    mode="clean"  — node T{n} labels only; no c= or v= annotations; no legend.
                    Use for presentation / main-text figures.
    mode="full"   — adds c={cost} below each node, v={vol} on each edge,
                    and a c/v legend in the bottom-right corner.
                    Use for appendix reference figures.

    show_edge_labels and edge_label_fontsize are respected only in mode="full".
    """
    g = dag.graph
    pos = _layered_positions(dag)
    node_colors = [TASK_PALETTE[tid % len(TASK_PALETTE)] for tid in sorted(g.nodes())]

    nx.draw_networkx_nodes(g, pos, ax=ax, node_color=node_colors,
                           node_size=700, alpha=0.93)
    nx.draw_networkx_labels(g, pos, ax=ax,
                            labels={n: f"T{n}" for n in g.nodes()},
                            font_size=8, font_color="white", font_weight="bold")
    nx.draw_networkx_edges(g, pos, ax=ax, arrows=True,
                           arrowstyle="-|>", arrowsize=18,
                           edge_color="#555555", width=1.4,
                           connectionstyle="arc3,rad=0.05")

    if mode == "full":
        if show_edge_labels:
            edge_labels = {
                (u, v): f"v={dag.communication_volume(u, v):.1f}"
                for u, v in g.edges()
            }
            nx.draw_networkx_edge_labels(g, pos, edge_labels, ax=ax,
                                         font_size=edge_label_fontsize, label_pos=0.38,
                                         bbox=dict(boxstyle="round,pad=0.15",
                                                   fc="white", alpha=0.75, ec="none"))

        pos_lower = {k: (v[0], v[1] - 0.32) for k, v in pos.items()}
        nx.draw_networkx_labels(g, pos_lower, ax=ax,
                                labels={tid: f"c={dag.computation_cost(tid):.1f}"
                                        for tid in g.nodes()},
                                font_size=6, font_color="#333333")

        # Legend bottom-right to avoid overlap with bottom-layer nodes
        legend_text = "c = computation cost\nv = communication volume"
        ax.text(0.98, 0.02, legend_text, transform=ax.transAxes,
                fontsize=6.5, color="#444444", va="bottom", ha="right",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", alpha=0.8,
                          ec="#cccccc"))

    ax.set_title(title, fontsize=10, fontweight="bold", pad=6)
    ax.axis("off")


# ---------------------------------------------------------------------------
# Gantt chart drawing
# ---------------------------------------------------------------------------

def _collect_active_procs(state) -> list[int]:
    procs = set()
    for instances in state.task_instances.values():
        for inst in instances:
            procs.add(inst.processor_id)
    return sorted(procs)


def draw_gantt(state, dag: DAGGraph, ax: plt.Axes, title: str,
               max_time: float | None = None,
               proc_universe: list[int] | None = None,
               show_legend: bool = True,
               min_label_width: float = 3.0,
               label_fontsize: float = 6.5) -> None:
    """Draw a horizontal Gantt chart.

    Makespan annotation is placed inside the axes (bottom-right corner)
    using axes-fraction coordinates so it never overlaps with the title.
    When proc_universe is None, only active processors for this schedule
    are shown (compact rows per scheduler).
    """
    rows: list[tuple[int, int, float, float, bool]] = []
    for task_id, instances in state.task_instances.items():
        for inst in instances:
            rows.append((inst.processor_id, task_id,
                         inst.start_time, inst.finish_time, inst.is_primary))

    if not rows:
        ax.set_title(title, fontsize=9, fontweight="bold")
        ax.text(0.5, 0.5, "(no tasks)", ha="center", va="center",
                transform=ax.transAxes)
        return

    all_procs = proc_universe if proc_universe is not None else _collect_active_procs(state)
    proc_y = {p: i for i, p in enumerate(all_procs)}
    bar_height = 0.72

    for proc_id, task_id, start, finish, is_primary in rows:
        if proc_id not in proc_y:
            continue
        color = TASK_PALETTE[task_id % len(TASK_PALETTE)]
        y = proc_y[proc_id]
        hatch = "" if is_primary else "///"
        rect = mpatches.FancyBboxPatch(
            (start, y - bar_height / 2), finish - start, bar_height,
            boxstyle="square,pad=0.0",
            facecolor=color, edgecolor="white", linewidth=0.7,
            hatch=hatch, alpha=0.88,
        )
        ax.add_patch(rect)
        if (finish - start) >= min_label_width:
            mid = (start + finish) / 2
            ax.text(mid, y, f"T{task_id}", ha="center", va="center",
                    fontsize=label_fontsize, color="white", fontweight="bold",
                    clip_on=True)

    makespan = state.max_processor_finish_time()
    if max_time is None:
        max_time = makespan * 1.08

    ax.axvline(makespan, color="#333333", linewidth=1.1, linestyle="--", alpha=0.75)
    ax.text(0.98, 0.04, f"makespan = {makespan:.1f}",
            ha="right", va="bottom", fontsize=7.5, color="#222222",
            transform=ax.transAxes,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#aaaaaa",
                      alpha=0.85, linewidth=0.6))

    ax.set_xlim(0, max_time)
    ax.set_ylim(-0.55, len(all_procs) - 0.45)
    ax.set_yticks(list(proc_y.values()))
    ax.set_yticklabels([f"P{p}" for p in all_procs], fontsize=7.5)
    ax.set_xlabel("Time (AU)", fontsize=8)
    ax.set_title(title, fontsize=9, fontweight="bold", pad=4)
    ax.grid(axis="x", linestyle=":", alpha=0.4)

    if show_legend:
        primary_patch = mpatches.Patch(facecolor="#777777", label="Primary")
        dup_patch = mpatches.Patch(facecolor="#777777", hatch="///", label="Duplicate")
        ax.legend(handles=[primary_patch, dup_patch], fontsize=6.5,
                  loc="upper left", framealpha=0.85)


# ---------------------------------------------------------------------------
# Scheduler runners
# ---------------------------------------------------------------------------

def run_all_schedulers(dag: DAGGraph, noc: MeshNoC) -> dict[str, object]:
    states: dict[str, object] = {}
    print("    Running HEFT ...", flush=True)
    states["heft"] = HEFTScheduler(noc).schedule(dag)
    print("    Running CD-LS ...", flush=True)
    states["cdls"] = ClassicalDuplicationScheduler(noc).schedule(dag)
    print("    Running Proposed CA-D ...", flush=True)
    states["cad"] = ProposedScheduler(noc).schedule(dag)
    return states


def compute_replayed(dag: DAGGraph, states: dict[str, object],
                     noc: MeshNoC) -> dict[str, object]:
    replayed: dict[str, object] = {}
    for key, state in states.items():
        replayed[key] = replay_under_contention(dag, state, noc)
    return replayed


def collect_metrics(states: dict[str, object],
                    replayed: dict[str, object]) -> dict[str, dict]:
    heft_native_ms = states["heft"].max_processor_finish_time()
    heft_replay_ms = replayed["heft"].max_processor_finish_time()

    metrics: dict[str, dict] = {}
    for key in states:
        native_ms = states[key].max_processor_finish_time()
        replay_ms = replayed[key].max_processor_finish_time()
        metrics[key] = {
            "native_makespan": native_ms,
            "native_speedup": heft_native_ms / native_ms if native_ms > 0 else 1.0,
            "replayed_makespan": replay_ms,
            "replayed_speedup": heft_replay_ms / replay_ms if replay_ms > 0 else 1.0,
            "replay_overhead": replay_ms / native_ms if native_ms > 0 else 1.0,
            "dup_count": count_duplicate_tasks(states[key]),
            "tir": task_instance_ratio(states[key]),
            "comm_count": count_communication_instances(states[key]),
            "replayed_comm_count": count_communication_instances(replayed[key]),
        }
    return metrics


# ---------------------------------------------------------------------------
# Shared bar chart helpers
# ---------------------------------------------------------------------------

def make_speedup_bar_chart(ax: plt.Axes,
                           metrics: dict[str, dict],
                           scheduler_keys: list[str],
                           title: str,
                           subtitle: str = "") -> None:
    """Grouped bar chart: native speedup (light gray) vs replayed speedup (identity color).

    Legend uses custom handles so the entries do not mislead:
      "Native speedup (gray)"          — neutral gray patch
      "Replayed speedup (scheduler color)" — medium gray patch with descriptive label
      "HEFT baseline (1.0×)"           — dashed line
    """
    labels = [SCHEDULER_LABELS[k] for k in scheduler_keys]
    native = [metrics[k]["native_speedup"] for k in scheduler_keys]
    replayed = [metrics[k]["replayed_speedup"] for k in scheduler_keys]

    x = np.arange(len(scheduler_keys))
    width = 0.36

    bars1 = ax.bar(x - width / 2, native, width,
                   color=NATIVE_BAR_COLOR, edgecolor="white", linewidth=0.8,
                   alpha=0.85)
    bars2 = ax.bar(x + width / 2, replayed, width,
                   color=[SCHEDULER_COLORS[k] for k in scheduler_keys],
                   edgecolor="white", linewidth=0.8, alpha=0.92)

    ax.axhline(1.0, color="black", linewidth=0.9, linestyle="--", alpha=0.45)

    for bar in list(bars1) + list(bars2):
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, h + 0.03,
                f"{h:.2f}×", ha="center", va="bottom", fontsize=7.5)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Speedup vs HEFT", fontsize=9)
    full_title = f"{title}\n{subtitle}" if subtitle else title
    ax.set_title(full_title, fontsize=10, fontweight="bold", pad=5)

    # Custom legend: native patch, replayed patch (variable color), HEFT line
    native_patch = mpatches.Patch(color=NATIVE_BAR_COLOR, alpha=0.85,
                                   label="Native speedup (gray)")
    replayed_patch = mpatches.Patch(color="#888888", alpha=0.92,
                                     label="Replayed speedup (scheduler color)")
    heft_line = mlines.Line2D([], [], color="black", linewidth=0.9,
                               linestyle="--", alpha=0.6,
                               label="HEFT baseline (1.0×)")
    ax.legend(handles=[native_patch, replayed_patch, heft_line],
              fontsize=8, loc="upper left")

    top = max(max(native), max(replayed))
    ax.set_ylim(0, top * 1.28 + 0.35)


# ---------------------------------------------------------------------------
# Case 1: out_tree_small — recursive duplication story
# ---------------------------------------------------------------------------

def case1_out_tree(outdir: Path, noc: MeshNoC) -> dict[str, dict]:
    print("\n[Case 1] out_tree depth=2 bf=2 CCR=5.0 seed=0", flush=True)
    dag_g = generate_out_tree_dag(depth=2, branching_factor=2,
                                  comp_range=COMP_RANGE, comm_range=COMM_RANGE,
                                  ccr=5.0, seed=0)
    dag = DAGGraph(dag_g)
    print(f"  DAG: {dag.number_of_tasks()} tasks, {dag.number_of_edges()} edges", flush=True)

    states = run_all_schedulers(dag, noc)
    replayed = compute_replayed(dag, states, noc)
    m = collect_metrics(states, replayed)
    for k, v in m.items():
        print(f"  {SCHEDULER_LABELS.get(k, k)}: native_ms={v['native_makespan']:.2f} "
              f"replayed_ms={v['replayed_makespan']:.2f} "
              f"replayed_speedup={v['replayed_speedup']:.3f} "
              f"dup={v['dup_count']} tir={v['tir']:.3f}", flush=True)

    heft_ms = m["heft"]["native_makespan"]
    max_time = heft_ms * 1.06

    # Figure 1a: DAG topology — clean mode for presentation
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    draw_dag_topology(dag, ax, "Out-tree DAG topology\n(depth=2, bf=2, CCR=5.0, seed=0)",
                      mode="clean")
    save_figure(fig, outdir, "fig1a_dag_topology")

    # Figure 1b: HEFT Gantt — appendix quality
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, 3.2))
    draw_gantt(states["heft"], dag, ax, "HEFT baseline", max_time=max_time)
    fig.tight_layout()
    save_figure(fig, outdir, "fig1b_heft_gantt")

    # Figure 1c: CA-D Gantt — appendix quality
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, 3.8))
    draw_gantt(states["cad"], dag, ax, "Proposed CA-D", max_time=max_time)
    fig.tight_layout()
    save_figure(fig, outdir, "fig1c_cad_gantt")

    # Figure 1d: main presentation — HEFT vs CA-D side-by-side
    fig, axes = plt.subplots(1, 2, figsize=(FIGURE_WIDTH + 2, 4.2))
    draw_gantt(states["heft"], dag, axes[0], "HEFT baseline", max_time=max_time)
    draw_gantt(states["cad"], dag, axes[1], "Proposed CA-D", max_time=max_time,
               show_legend=True)
    fig.suptitle("Out-tree DAG: HEFT vs Proposed CA-D",
                 fontsize=12, fontweight="bold")
    fig.text(0.5, 0.01,
             "Hatched bars = duplicate task instances.  "
             f"Proposed CA-D achieves {m['cad']['replayed_speedup']:.2f}× replayed speedup vs HEFT "
             f"(HEFT serializes at CCR=5.0; this is expected — see text).  "
             + _COMPACT_NOTE,
             ha="center", fontsize=7.0, style="italic", color="#444444",
             wrap=True)
    fig.subplots_adjust(top=0.88, bottom=0.16, left=0.07, right=0.97, wspace=0.30)
    save_figure(fig, outdir, "fig1d_heft_vs_cad")

    # Figure 1e: speedup bars — neutral native / identity replayed colors
    fig, ax = plt.subplots(figsize=(7, 4.2))
    make_speedup_bar_chart(ax, m, ["heft", "cdls", "cad"],
                           "Native vs Replayed Speedup vs HEFT",
                           subtitle="Out-tree, depth=2, bf=2, CCR=5.0")
    fig.tight_layout()
    save_figure(fig, outdir, "fig1e_speedup_bars")

    print(f"  Case 1 done.", flush=True)
    return m


# ---------------------------------------------------------------------------
# Case 2: fork_duplication — duplication benefit story
# ---------------------------------------------------------------------------

def case2_fork(outdir: Path, noc: MeshNoC) -> dict[str, dict]:
    print("\n[Case 2] fork n_branches=8 CCR=5.0 seed=0", flush=True)
    dag_g = generate_fork_dag(n_branches=8,
                              comp_range=COMP_RANGE, comm_range=COMM_RANGE,
                              ccr=5.0, seed=0)
    dag = DAGGraph(dag_g)
    print(f"  DAG: {dag.number_of_tasks()} tasks, {dag.number_of_edges()} edges", flush=True)

    states = run_all_schedulers(dag, noc)
    replayed = compute_replayed(dag, states, noc)
    m = collect_metrics(states, replayed)
    for k, v in m.items():
        print(f"  {SCHEDULER_LABELS.get(k, k)}: native_ms={v['native_makespan']:.2f} "
              f"replayed_ms={v['replayed_makespan']:.2f} "
              f"replayed_speedup={v['replayed_speedup']:.3f} "
              f"dup={v['dup_count']} tir={v['tir']:.3f}", flush=True)

    # Compact per-scheduler rows: union of 8 procs makes HEFT panel too sparse
    all_used: set[int] = set()
    for key in ("heft", "cdls", "cad"):
        all_used.update(_collect_active_procs(states[key]))
    proc_universe = sorted(all_used)
    n_empty_heft = len(proc_universe) - len(_collect_active_procs(states["heft"]))
    if n_empty_heft > 5:
        print(f"  NOTE: union proc_universe gives HEFT {n_empty_heft} empty rows; "
              f"using per-scheduler rows for readability.", flush=True)
        proc_universe = None

    max_time = max(m[k]["native_makespan"] for k in m) * 1.06

    # Figure 2a: DAG topology — clean mode for presentation
    fig, ax = plt.subplots(figsize=(8.5, 3.5))
    draw_dag_topology(dag, ax, "Fork DAG topology  (n_branches=8, CCR=5.0, seed=0)",
                      mode="clean")
    save_figure(fig, outdir, "fig2a_dag_topology")

    # Figure 2b: three-panel Gantt — Fork DAG: Duplication Benefit
    fig, axes = plt.subplots(1, 3, figsize=(FIGURE_WIDTH + 5, 5.2),
                             gridspec_kw={"wspace": 0.32})
    draw_gantt(states["heft"], dag, axes[0], "HEFT",
               max_time=max_time, proc_universe=proc_universe)
    draw_gantt(states["cdls"], dag, axes[1], "CD-LS",
               max_time=max_time, proc_universe=proc_universe)
    draw_gantt(states["cad"], dag, axes[2], "Proposed CA-D",
               max_time=max_time, proc_universe=proc_universe)
    fig.suptitle("Fork DAG: Duplication Benefit  (n_branches=8, CCR=5.0)",
                 fontsize=11, fontweight="bold")
    fig.text(0.5, 0.01, _COMPACT_NOTE,
             ha="center", fontsize=7.5, style="italic", color="#444444")
    fig.subplots_adjust(top=0.88, bottom=0.09)
    save_figure(fig, outdir, "fig2b_three_scheduler_gantt")

    # Figure 2c: speedup bars — neutral native / identity replayed
    fig, ax = plt.subplots(figsize=(7, 4.2))
    make_speedup_bar_chart(ax, m, ["heft", "cdls", "cad"],
                           "Native vs Replayed Speedup vs HEFT",
                           subtitle="Fork DAG, n_branches=8, CCR=5.0")
    fig.tight_layout()
    save_figure(fig, outdir, "fig2c_speedup_bars")

    # Figure 2d: TIR bars — scheduler identity colors, single-bar per scheduler
    fig, ax = plt.subplots(figsize=(6, 4.2))
    keys_order = ["heft", "cdls", "cad"]
    tirs = [m[k]["tir"] for k in keys_order]
    labels = [SCHEDULER_LABELS[k] for k in keys_order]
    bars = ax.bar(labels, tirs,
                  color=[SCHEDULER_COLORS[k] for k in keys_order],
                  alpha=0.88, edgecolor="white")
    ax.axhline(1.0, color="black", linewidth=0.9, linestyle="--", alpha=0.45,
               label="No duplication (TIR = 1.0)")
    for bar, v in zip(bars, tirs):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.02,
                f"{v:.2f}", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Task Instance Ratio (TIR)", fontsize=9)
    ax.set_title("Task Instance Ratio\nFork DAG, n_branches=8, CCR=5.0",
                 fontsize=10, fontweight="bold", pad=5)
    ax.legend(fontsize=8)
    ax.set_ylim(0, max(tirs) * 1.3 + 0.2)
    fig.tight_layout()
    save_figure(fig, outdir, "fig2d_tir_bars")

    print(f"  Case 2 done.", flush=True)
    return m


# ---------------------------------------------------------------------------
# Case 3: fork_join_replay — replay fairness story
# ---------------------------------------------------------------------------

def case3_fork_join(outdir: Path, noc: MeshNoC) -> tuple[dict[str, dict], list[int]]:
    """Returns (metrics, cad_active_procs) so main() can highlight the correct
    processors in fig0b without hardcoding."""
    print("\n[Case 3] fork_join n_branches=4 bl=3 CCR=5.0 seed=0", flush=True)
    dag_g = generate_fork_join_dag(n_branches=4, branch_length=3,
                                   comp_range=COMP_RANGE, comm_range=COMM_RANGE,
                                   ccr=5.0, seed=0)
    dag = DAGGraph(dag_g)
    print(f"  DAG: {dag.number_of_tasks()} tasks, {dag.number_of_edges()} edges", flush=True)

    states = run_all_schedulers(dag, noc)
    replayed = compute_replayed(dag, states, noc)
    m = collect_metrics(states, replayed)
    for k, v in m.items():
        print(f"  {SCHEDULER_LABELS.get(k, k)}: native_ms={v['native_makespan']:.2f} "
              f"replayed_ms={v['replayed_makespan']:.2f} "
              f"replayed_speedup={v['replayed_speedup']:.3f} "
              f"dup={v['dup_count']} tir={v['tir']:.3f}", flush=True)

    cad_procs = _collect_active_procs(states["cad"])
    max_time = max(m[k]["native_makespan"] for k in m) * 1.06

    # Figure 3a: DAG topology — clean mode, fork_join 14 tasks, larger figure
    fig, ax = plt.subplots(figsize=(9, 5.5))
    draw_dag_topology(dag, ax,
                      "Fork-join DAG topology  (n_branches=4, bl=3, CCR=5.0, seed=0)",
                      mode="clean")
    save_figure(fig, outdir, "fig3a_dag_topology")

    # Figure 3b: replay fairness — neutral native / identity replayed colors
    fig, ax = plt.subplots(figsize=(8, 4.8))
    make_speedup_bar_chart(ax, m, ["heft", "cdls", "cad"],
                           "Native vs Replayed Speedup",
                           subtitle="Fork-join DAG, n_branches=4, bl=3, CCR=5.0")
    # Annotate CD-LS collapse gap
    cdls_native = m["cdls"]["native_speedup"]
    cdls_replay = m["cdls"]["replayed_speedup"]
    if cdls_native > cdls_replay + 0.05:
        gap = cdls_native - cdls_replay
        sched_keys = ["heft", "cdls", "cad"]
        x_cdls = float(sched_keys.index("cdls"))
        ax.annotate(
            f"−{gap:.2f}× under replay\n(CD-LS native model\nwas optimistic)",
            xy=(x_cdls - 0.18, cdls_native + 0.04),
            xytext=(x_cdls + 0.7, cdls_native + 0.25),
            fontsize=7.5, color="#8b0000",
            arrowprops=dict(arrowstyle="->", color="#8b0000", lw=1.2,
                            connectionstyle="arc3,rad=-0.2"),
        )
    fig.tight_layout()
    save_figure(fig, outdir, "fig3b_replay_speedup_bars")

    # Figure 3c: three-panel Gantt — appendix quality
    fig, axes = plt.subplots(1, 3, figsize=(FIGURE_WIDTH + 5, 6.0),
                             gridspec_kw={"wspace": 0.32})
    draw_gantt(states["heft"], dag, axes[0], "HEFT",
               max_time=max_time, min_label_width=7.0, label_fontsize=6.0)
    draw_gantt(states["cdls"], dag, axes[1], "CD-LS",
               max_time=max_time, min_label_width=7.0, label_fontsize=6.0)
    draw_gantt(states["cad"], dag, axes[2], "Proposed CA-D",
               max_time=max_time, min_label_width=7.0, label_fontsize=6.0)
    fig.suptitle("Fork-join DAG: Schedule Comparison  (n_branches=4, bl=3, CCR=5.0)",
                 fontsize=10, fontweight="bold")
    fig.text(0.5, 0.01, _COMPACT_NOTE,
             ha="center", fontsize=7.5, style="italic", color="#444444")
    fig.subplots_adjust(top=0.88, bottom=0.09)
    save_figure(fig, outdir, "fig3c_three_scheduler_gantt")

    # Figure 3d: replay overhead — main figure, scheduler identity colors
    fig, ax = plt.subplots(figsize=(7, 4.2))
    keys_order = ["heft", "cdls", "cad"]
    overheads = [m[k]["replay_overhead"] for k in keys_order]
    labels = [SCHEDULER_LABELS[k] for k in keys_order]
    bars = ax.bar(labels, overheads,
                  color=[SCHEDULER_COLORS[k] for k in keys_order],
                  alpha=0.88, edgecolor="white")
    ax.axhline(1.0, color="black", linewidth=0.9, linestyle="--", alpha=0.5,
               label="No overhead (ratio = 1.0)")
    for bar, v in zip(bars, overheads):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.012,
                f"{v:.2f}×", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Replay overhead ratio\n(replayed makespan / native makespan)", fontsize=9)
    ax.set_title("Replay Overhead Ratio\nFork-join DAG, n_branches=4, bl=3, CCR=5.0",
                 fontsize=10, fontweight="bold", pad=5)
    ax.legend(fontsize=8)
    ax.set_ylim(0, max(overheads) * 1.35 + 0.12)
    fig.tight_layout()
    save_figure(fig, outdir, "fig3d_replay_overhead_bars")

    print(f"  Case 3 done.", flush=True)
    return m, cad_procs


# ---------------------------------------------------------------------------
# Figure captions
# ---------------------------------------------------------------------------

def write_captions(base: Path, metrics: dict[str, dict],
                   cad_procs_case3: list[int]) -> None:
    m1 = metrics["case1"]
    m2 = metrics["case2"]
    m3 = metrics["case3"]
    cad_proc_str = ", ".join(f"P{p}" for p in cad_procs_case3)

    lines = [
        "# Phase 18 Figure Captions",
        "",
        "Generated by `scripts/generate_phase18_figures.py` (Phase 18B-3).",
        "All figures exported as PNG (300 DPI) and PDF.",
        "NoC: 4×4 homogeneous mesh, alpha=0.0, beta=1.0.",
        "Schedulers: HEFT (contention-blind baseline, no duplication),",
        "CD-LS (contention-blind, parent-only duplication),",
        "Proposed CA-D (contention-aware, greedy recursive ancestor duplication",
        "with conservative redundant duplicate pruning).",
        "",
        "Diagnostic note (Phase 18B-DIAG): no scheduler bugs were found.",
        "HEFT serialization at CCR=5.0 is algorithmically correct.",
        "CD-LS = CA-D on the fork DAG is structurally expected.",
        "CA-D duplicates on fork-join are all necessary for local data delivery.",
        "",
        "DAG topology figures use clean mode (node T{n} labels only).",
        "Full mode (with c= cost and v= volume annotations) is available",
        "via draw_dag_topology(..., mode='full') for appendix versions.",
        "",
        "Multi-panel Gantt figures use compact active-processor rows per scheduler.",
        "Only processors with at least one scheduled task instance are shown in each panel.",
        "",
        "---",
        "",
        "## Figure 0 — NoC Topology",
        "",
        "**fig0a_noc_topology_generic** — 4×4 mesh Network-on-Chip used in all Phase 18 examples.",
        "All processors (P0–P15) are shown in the same neutral color.",
        "Processors are labeled in row-major order (P0 top-left, P15 bottom-right).",
        "Horizontal and vertical links connect adjacent processors.",
        "Communication follows deterministic XY routing: traffic first moves in the X direction",
        "to the target column, then in the Y direction to the target row.",
        "With alpha=0.0 and beta=1.0, communication duration equals the data volume in",
        "arbitrary time units, independent of hop count.",
        "Note: with alpha=0.0, hop count does not increase transfer duration, but XY routing",
        "still determines which links are reserved and where contention can occur.",
        "  Recommended use: main text (NoC model illustration).",
        "",
        f"**fig0b_noc_topology_case3_used** — Same 4×4 MeshNoC topology, but highlighting",
        f"the processors used by Proposed CA-D in Case 3 ({cad_proc_str}, shown in red).",
        f"Note: with alpha=0.0, hop count does not increase transfer duration, but XY routing",
        f"still determines which links are reserved and where contention can occur.",
        "  Recommended use: main text alongside Case 3 schedule discussion.",
        "",
        "---",
        "",
        "## Case 1 — Out-tree Recursive Duplication",
        "",
        "**DAG:** Out-tree, depth=2, branching_factor=2, CCR=5.0, seed=0 (7 tasks, 6 edges).",
        "Root T0 fans out to two intermediate tasks (T1, T2),",
        "each of which fans out to two leaf tasks (T3–T6).",
        "",
        "**fig1a_dag_topology** — DAG structure (clean mode: task identifiers T{n} only).",
        "  Recommended use: main text (topology illustration).",
        "",
        f"**fig1b_heft_gantt** — HEFT baseline schedule (makespan = {m1['heft']['native_makespan']:.1f} AU).",
        "HEFT does not model link contention and does not perform task duplication.",
        "At CCR=5.0, remote data-ready time exceeds local queue delay for every child task,",
        "so HEFT places all tasks sequentially on P0. This is algorithmically correct behavior,",
        "not a scheduler error (diagnostic sanity tests with zero communication confirmed",
        "that HEFT parallelizes when communication is cheap).",
        "  Recommended use: appendix / supplement.",
        "",
        f"**fig1c_cad_gantt** — Proposed CA-D schedule (makespan = {m1['cad']['native_makespan']:.1f} AU,",
        f"dup_count = {m1['cad']['dup_count']}, TIR = {m1['cad']['tir']:.2f}).",
        "Proposed CA-D is a NoC-focused, paper-inspired greedy recursive duplication heuristic",
        "with conservative redundant duplicate pruning.",
        "Ancestor tasks are duplicated onto target processors to eliminate inter-processor",
        "communication. Hatched bars represent duplicate task instances.",
        "  Recommended use: appendix / supplement.",
        "",
        f"**fig1d_heft_vs_cad** — Side-by-side comparison: HEFT baseline (left) and",
        "Proposed CA-D (right).",
        f"Before duplication, all tasks execute sequentially on P0",
        f"(makespan = {m1['heft']['native_makespan']:.1f} AU).",
        "After greedy recursive ancestor duplication, tasks are distributed across",
        f"processors with all communication eliminated",
        f"(makespan = {m1['cad']['native_makespan']:.1f} AU,",
        f"replayed speedup = {m1['cad']['replayed_speedup']:.2f}×).",
        "Hatched bars are duplicate task instances.",
        "HEFT serialization at CCR=5.0 is expected; see fig1b caption.",
        "Processor rows are compacted per scheduler (caption note on figure).",
        "  Recommended use: presentation / main text.",
        "",
        f"**fig1e_speedup_bars** — Native and replayed speedup relative to HEFT for HEFT,",
        "CD-LS, and Proposed CA-D.",
        "Gray bars show native speedup (all schedulers); colored bars show replayed speedup",
        "(scheduler identity color).",
        f"Proposed CA-D achieves {m1['cad']['replayed_speedup']:.2f}× replayed speedup;",
        f"CD-LS achieves {m1['cdls']['replayed_speedup']:.2f}×.",
        "Native and replayed values coincide on this DAG because duplication eliminates",
        "all inter-processor communication, so no contention occurs under replay.",
        "  Recommended use: main text or supplement.",
        "",
        "---",
        "",
        "## Case 2 — Fork Duplication Benefit",
        "",
        "**DAG:** Fork, n_branches=8, CCR=5.0, seed=0 (9 tasks, 8 edges).",
        "Root T0 distributes work to 8 independent leaf tasks.",
        "At CCR=5.0, the T0→leaf communication dominates schedule length.",
        "Duplicating T0 locally on each leaf's processor eliminates all outgoing communication.",
        "",
        "**fig2a_dag_topology** — Fork DAG structure (clean mode: task identifiers T{n} only).",
        "  Recommended use: main text (topology illustration).",
        "",
        f"**fig2b_three_scheduler_gantt** — Three-panel schedule: HEFT",
        f"(makespan = {m2['heft']['native_makespan']:.1f} AU), CD-LS",
        f"(makespan = {m2['cdls']['native_makespan']:.1f} AU), Proposed CA-D",
        f"(makespan = {m2['cad']['native_makespan']:.1f} AU).",
        "Processor rows are compacted per scheduler (caption note on figure).",
        "At CCR=5.0, HEFT queues most leaves on P0 because remote data-ready time",
        "(T0.finish + communication volume) exceeds queue delay on P0.",
        "CD-LS and Proposed CA-D produce identical schedules on this DAG.",
        "On a one-level fork DAG, parent-only duplication (CD-LS) and recursive ancestor",
        "duplication (Proposed CA-D) reduce to the same decision: duplicate the root T0",
        "near each leaf. This case demonstrates the duplication benefit but not the",
        "algorithmic difference between the two schedulers.",
        "  Recommended use: main text.",
        "",
        "**fig2c_speedup_bars** — Native vs replayed speedup.",
        "Gray bars = native (all schedulers); colored bars = replayed (scheduler identity color).",
        f"CD-LS and Proposed CA-D both achieve {m2['cad']['replayed_speedup']:.2f}× replayed",
        "speedup vs HEFT. No contention occurs after duplication, so native and replayed",
        "values are equal for the duplication schedulers.",
        "  Recommended use: main text or supplement.",
        "",
        "**fig2d_tir_bars** — Task Instance Ratio per scheduler.",
        "Task Instance Ratio (TIR) = total scheduled task instances / original DAG task count.",
        "TIR=1.0 means no duplication.",
        f"HEFT: TIR = {m2['heft']['tir']:.2f}; CD-LS: TIR = {m2['cdls']['tir']:.2f};",
        f"Proposed CA-D: TIR = {m2['cad']['tir']:.2f}.",
        "CD-LS and Proposed CA-D have equal TIR on this fork DAG because they place",
        "the same duplicate instances.",
        "  Recommended use: supplement.",
        "",
        "---",
        "",
        "## Case 3 — Fork-join Replay Fairness",
        "",
        "**DAG:** Fork-join, n_branches=4, branch_length=3, CCR=5.0, seed=0 (14 tasks, 16 edges).",
        "Root T0 forks into 4 parallel branches (3 tasks each), converging at a single sink T13.",
        "",
        "**fig3a_dag_topology** — Fork-join DAG structure (clean mode: task identifiers T{n} only).",
        "  Recommended use: main text (topology illustration).",
        "",
        "**fig3b_replay_speedup_bars** — Native vs replayed speedup.",
        "Gray bars = native (all schedulers); colored bars = replayed (scheduler identity color).",
        "In this fork-join case, CD-LS underestimates makespan under native evaluation,",
        "while Proposed CA-D remains stable under replay.",
        f"CD-LS native speedup ({m3['cdls']['native_speedup']:.2f}×) collapses to",
        f"{m3['cdls']['replayed_speedup']:.2f}× under fair replay, revealing that the",
        "CD-LS contention-blind model was optimistic.",
        f"Proposed CA-D already accounts for contention; its replayed speedup",
        f"({m3['cad']['replayed_speedup']:.2f}×) is consistent with its native result.",
        "The T9 duplicate in the Proposed CA-D schedule provides local data to T13 on P0,",
        "avoiding a remote arrival that would be 43 time units late.",
        "  Recommended use: presentation / main text.",
        "",
        f"**fig3c_three_scheduler_gantt** — Three-panel schedule: HEFT",
        f"(makespan = {m3['heft']['native_makespan']:.1f} AU), CD-LS",
        f"(makespan = {m3['cdls']['native_makespan']:.1f} AU), Proposed CA-D",
        f"(makespan = {m3['cad']['native_makespan']:.1f} AU).",
        "Hatched bars are duplicate instances.",
        "Processor rows are compacted per scheduler (caption note on figure).",
        "  Recommended use: appendix.",
        "",
        "**fig3d_replay_overhead_bars** — Replay overhead ratio",
        "(replayed makespan / native makespan) per scheduler.",
        f"HEFT: {m3['heft']['replay_overhead']:.2f}×; CD-LS: {m3['cdls']['replay_overhead']:.2f}×;",
        f"Proposed CA-D: {m3['cad']['replay_overhead']:.2f}×.",
        "In this fork-join case, CD-LS underestimates makespan under native evaluation,",
        "while Proposed CA-D remains stable under replay.",
        "Proposed CA-D overhead = 1.0× confirms that its contention-aware model",
        "accurately predicts the replayed result.",
        "  Recommended use: main text.",
        "",
        "---",
        "",
        "## Recommended Use",
        "",
        "| Figure | Recommended use |",
        "|--------|----------------|",
        "| fig0a_noc_topology_generic | Main text — NoC model illustration (generic) |",
        "| fig0b_noc_topology_case3_used | Main text — NoC model with Case 3 CA-D procs |",
        "| fig1a_dag_topology | Main text — topology illustration |",
        "| fig1d_heft_vs_cad | Presentation / main text |",
        "| fig1e_speedup_bars | Main text or supplement |",
        "| fig2a_dag_topology | Main text — topology illustration |",
        "| fig2b_three_scheduler_gantt | Main text |",
        "| fig2c_speedup_bars | Main text or supplement |",
        "| fig3a_dag_topology | Main text — topology illustration |",
        "| fig3b_replay_speedup_bars | Presentation / main text |",
        "| fig3d_replay_overhead_bars | Main text |",
        "| fig1b_heft_gantt | Appendix / supplement |",
        "| fig1c_cad_gantt | Appendix / supplement |",
        "| fig2d_tir_bars | Supplement |",
        "| fig3c_three_scheduler_gantt | Appendix |",
        "",
    ]
    path = base / "figure_captions.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Wrote figure_captions.md ({path.stat().st_size // 1024} KB)", flush=True)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_outputs(base: Path, dirs: dict[str, Path]) -> tuple[int, int, int, list[str]]:
    """Check all expected files exist and are non-empty. Return (png, pdf, md, warnings)."""
    problems: list[str] = []
    png_count = 0
    pdf_count = 0
    md_count = 0

    # fig0a/fig0b in base directory
    for stem in EXPECTED_BASE_STEMS:
        for ext in ("png", "pdf"):
            path = base / f"{stem}.{ext}"
            if not path.exists() or path.stat().st_size == 0:
                problems.append(f"MISSING or EMPTY: {stem}.{ext}")
            elif ext == "png":
                png_count += 1
            else:
                pdf_count += 1

    # case figures in subdirectories
    dir_map = {
        "out_tree_small": dirs["out_tree"],
        "fork_duplication": dirs["fork"],
        "fork_join_replay": dirs["fork_join"],
    }
    for case_name, stems in EXPECTED_FIGURES.items():
        d = dir_map[case_name]
        for stem in stems:
            for ext in ("png", "pdf"):
                path = d / f"{stem}.{ext}"
                if not path.exists() or path.stat().st_size == 0:
                    problems.append(f"MISSING or EMPTY: {case_name}/{stem}.{ext}")
                elif ext == "png":
                    png_count += 1
                else:
                    pdf_count += 1

    # captions
    md_path = base / "figure_captions.md"
    if not md_path.exists() or md_path.stat().st_size == 0:
        problems.append("MISSING or EMPTY: figure_captions.md")
    else:
        md_count += 1

    return png_count, pdf_count, md_count, problems


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    base = ROOT / "results" / "figures" / "phase18"
    dirs = ensure_output_dirs(base)
    print(f"Output base: {base}", flush=True)
    print(f"DPI: {DPI}", flush=True)

    noc = MeshNoC(rows=NOC_ROWS, cols=NOC_COLS, alpha=0.0, beta=1.0)

    t0 = time.time()

    # Figure 0a: generic topology (no highlights) — generated first
    print("\n[Fig 0a] 4×4 MeshNoC generic topology", flush=True)
    generate_noc_topology_figure(base, noc, "fig0a_noc_topology_generic",
                                  highlight_procs=None)

    m1 = case1_out_tree(dirs["out_tree"], noc)
    m2 = case2_fork(dirs["fork"], noc)
    m3, cad_procs_case3 = case3_fork_join(dirs["fork_join"], noc)
    elapsed = time.time() - t0

    # Figure 0b: Case 3 CA-D procs highlighted — generated after Case 3
    print(f"\n[Fig 0b] 4×4 MeshNoC Case 3 CA-D procs: {cad_procs_case3}", flush=True)
    generate_noc_topology_figure(base, noc, "fig0b_noc_topology_case3_used",
                                  highlight_procs=cad_procs_case3)

    write_captions(base, {"case1": m1, "case2": m2, "case3": m3},
                   cad_procs_case3=cad_procs_case3)

    print("\n[Validation]", flush=True)
    png_count, pdf_count, md_count, problems = validate_outputs(base, dirs)
    if problems:
        for p in problems:
            print(f"  WARNING: {p}", flush=True)
    else:
        print(f"  PNG files:  {png_count} (all exist and non-empty)", flush=True)
        print(f"  PDF files:  {pdf_count} (all exist and non-empty)", flush=True)
        print(f"  MD files:   {md_count} (figure_captions.md exists and non-empty)", flush=True)

    print(f"\n[Generated files]", flush=True)
    for f in sorted(base.rglob("*.png")):
        kb = f.stat().st_size // 1024
        print(f"  {f.relative_to(base)}  ({kb} KB)", flush=True)

    print(f"\n[Summary] Total time: {elapsed:.1f}s", flush=True)
    print("\nCase 1 (out_tree depth=2 bf=2 CCR=5.0):", flush=True)
    for k in ["heft", "cdls", "cad"]:
        print(f"  {SCHEDULER_LABELS[k]:16s}: native={m1[k]['native_speedup']:.3f}× "
              f"replayed={m1[k]['replayed_speedup']:.3f}× "
              f"dup={m1[k]['dup_count']}", flush=True)

    print("\nCase 2 (fork n_branches=8 CCR=5.0):", flush=True)
    for k in ["heft", "cdls", "cad"]:
        print(f"  {SCHEDULER_LABELS[k]:16s}: native={m2[k]['native_speedup']:.3f}× "
              f"replayed={m2[k]['replayed_speedup']:.3f}× "
              f"dup={m2[k]['dup_count']}", flush=True)

    print("\nCase 3 (fork_join n_branches=4 bl=3 CCR=5.0):", flush=True)
    for k in ["heft", "cdls", "cad"]:
        print(f"  {SCHEDULER_LABELS[k]:16s}: native={m3[k]['native_speedup']:.3f}× "
              f"replayed={m3[k]['replayed_speedup']:.3f}× "
              f"overhead={m3[k]['replay_overhead']:.3f}×", flush=True)


if __name__ == "__main__":
    main()
