"""
Contention Explainer Figures
=============================
Educational figures showing exactly how link contention is modelled,
detected, and affects scheduling in this project.

Four figures:

  figA_link_contention_mechanism
      Illustrative timeline: two communications sharing a link.
      Left panel: naive analytic model (no conflict visible).
      Right panel: contention-aware model (second comm pushed back).

  figB_earliest_route_slot
      Algorithm walkthrough: how earliest_route_slot() finds the first
      joint-free time slot across all links on a route.
      Shows existing intervals, a new request, and how the candidate
      is advanced step by step.

  figC_native_vs_replayed_bars
      Bar chart from the Phase 21 CSV (fork-join, all CCR values) comparing
      native makespan (scheduler's own prediction) vs replayed makespan
      (ground-truth under contention).  Highlights the gap that reveals
      contention-blind optimism in HEFT and CD-LS.

  figD_link_utilization_timeline
      Actual link-interval data for fork-join at CCR=10 (real scheduler run).
      Shows per-link busy-time bars for HEFT and CA-D side by side, making
      the "hidden" link contention in HEFT's schedule visible.

Run from repository root:
    python scripts/generate_contention_explainer_figures.py
"""

import sys
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np
import pandas as pd

from src.noc import MeshNoC
from src.graph_families import generate_fork_join_dag
from src.models import DAGGraph
from src.heft_scheduler import HEFTScheduler
from src.classical_dup_scheduler import ClassicalDuplicationScheduler
from src.proposed_scheduler import ProposedScheduler
from src.contention_replay import replay_under_contention
from src.schedule_state import ScheduleState
from src.metrics import link_busy_time

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

OUT_DIR = ROOT / "results" / "figures" / "contention_explainer"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CSV_PATH = ROOT / "results" / "summary" / "phase21_interpretive_single_run.csv"

NOC_ROWS, NOC_COLS = 4, 4
ALPHA, BETA, SEED = 0.0, 1.0, 0

SCHED_COLOR = {"heft": "#2166AC", "cdls": "#D6604D", "cad": "#1A9850"}
SCHED_LABEL = {"heft": "HEFT",    "cdls": "CD-LS",   "cad": "CA-D"}

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 12,
    "axes.titlesize": 13,
    "axes.labelsize": 12,
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
    "legend.fontsize": 11,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.grid": True,
    "grid.alpha": 0.2,
    "grid.linestyle": "--",
})


def save_fig(fig: plt.Figure, stem: str) -> None:
    for ext in ("png", "pdf"):
        fig.savefig(OUT_DIR / f"{stem}.{ext}", dpi=150, bbox_inches="tight")
    print(f"  Saved {stem}.png/.pdf", flush=True)
    plt.close(fig)


# ===========================================================================
# Figure A — Link contention mechanism (illustrative)
# ===========================================================================
#
# Scenario: two tasks (T1, T2) on P0 and P2, both sending data to P8
# (a processor two hops away).  Their routes both share the link P4->P8.
# Under the analytic model both start at t=0; under contention-aware
# scheduling the second is pushed to t=10.
#
# Hardcoded values chosen for clarity, not from a real run.
# ===========================================================================

def figA_link_contention_mechanism() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.5))
    fig.suptitle(
        "Fig A -- Link Contention: why two communications cannot overlap on a shared link",
        fontsize=14, fontweight="bold", y=1.02,
    )

    bar_h = 0.38
    # Three communications: A, B, C all pass through the same link
    comms = [
        {"label": "Comm T1->T3 (P0->P8)", "vol": 10, "color": "#2166AC"},
        {"label": "Comm T2->T4 (P4->P8)", "vol": 10, "color": "#D6604D"},
        {"label": "Comm T5->T6 (P2->P8)", "vol": 10, "color": "#1A9850"},
    ]
    dur = 10  # beta=1.0, volume=10 => duration=10

    # ------------------------------------------------------------------
    # Left panel: analytic (contention-blind) model
    # ------------------------------------------------------------------
    ax = axes[0]
    ax.set_title("A -- Analytic (contention-blind) model\n"
                 "Each comm estimated independently. Link sharing NOT modelled.",
                 fontsize=12, fontweight="bold")
    y_positions = [2.0, 1.0, 0.0]
    for i, (comm, y) in enumerate(zip(comms, y_positions)):
        ax.barh(y, dur, left=0.0, height=bar_h,
                color=comm["color"], alpha=0.85, edgecolor="black", linewidth=1)
        ax.text(dur / 2, y, comm["label"],
                ha="center", va="center", fontsize=9.5,
                fontweight="bold", color="white")

    ax.set_xlim(-1, 36)
    ax.set_ylim(-0.6, 2.7)
    ax.set_xlabel("Time", fontsize=12)
    ax.set_yticks([0, 1, 2])
    ax.set_yticklabels(["Comm 3 (vol=10)", "Comm 2 (vol=10)", "Comm 1 (vol=10)"],
                       fontsize=10)
    ax.axvline(dur, color="#333333", lw=2, linestyle=":")
    ax.text(dur + 0.3, 2.5, f"predicted\nmakespan={dur}", ha="left",
            fontsize=10, color="#333333", fontweight="bold")
    ax.text(5.0, -0.5,
            "All 3 comms predict finish_time = 10\n(same link used simultaneously -- ignored!)",
            ha="center", fontsize=9.5, color="#CC0000",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#FFF0F0",
                      edgecolor="#CC0000", linewidth=1.3))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, axis="x", alpha=0.25)

    # ------------------------------------------------------------------
    # Right panel: contention-aware model (serialized)
    # ------------------------------------------------------------------
    ax = axes[1]
    ax.set_title("B -- Contention-aware model\n"
                 "earliest_route_slot() serializes comms sharing the link.",
                 fontsize=12, fontweight="bold")

    starts = [0, dur, dur * 2]   # each comm must wait for the previous
    for i, (comm, y, start) in enumerate(zip(comms, y_positions, starts)):
        ax.barh(y, dur, left=start, height=bar_h,
                color=comm["color"], alpha=0.85, edgecolor="black", linewidth=1)
        ax.text(start + dur / 2, y, comm["label"],
                ha="center", va="center", fontsize=9.5,
                fontweight="bold", color="white")
        if i > 0:
            # Show the wait (blocked) period
            ax.barh(y, start, left=0.0, height=bar_h,
                    color="#DDDDDD", alpha=0.55, edgecolor="#AAAAAA",
                    linewidth=0.8, linestyle="--")
            ax.text(start / 2, y, "blocked", ha="center", va="center",
                    fontsize=8.5, color="#888888", style="italic")

    ax.set_xlim(-1, 36)
    ax.set_ylim(-0.6, 2.7)
    ax.set_xlabel("Time", fontsize=12)
    ax.set_yticks([0, 1, 2])
    ax.set_yticklabels(["Comm 3 (vol=10)", "Comm 2 (vol=10)", "Comm 1 (vol=10)"],
                       fontsize=10)
    actual_ms = dur * len(comms)
    ax.axvline(actual_ms, color="#CC0000", lw=2, linestyle=":")
    ax.text(actual_ms + 0.3, 2.5, f"actual\nmakespan={actual_ms}", ha="left",
            fontsize=10, color="#CC0000", fontweight="bold")
    ax.annotate("", xy=(actual_ms, -0.35), xytext=(0, -0.35),
                arrowprops=dict(arrowstyle="<->", color="#CC0000", lw=1.5))
    ax.text(actual_ms / 2, -0.55,
            f"3x longer than predicted  (overhead = {len(comms)}.0x)",
            ha="center", fontsize=10, color="#CC0000", fontweight="bold")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, axis="x", alpha=0.25)

    # Shared annotation: link icon
    fig.text(0.5, -0.02,
             "Shared link (e.g., P4->P8 on XY route): only one communication may occupy it at a time.",
             ha="center", fontsize=11, color="#444444",
             bbox=dict(boxstyle="round,pad=0.4", facecolor="#F0F8FF",
                       edgecolor="#2166AC", linewidth=1.2))

    fig.tight_layout(rect=[0, 0.06, 1, 1])
    save_fig(fig, "figA_link_contention_mechanism")


# ===========================================================================
# Figure B — earliest_route_slot algorithm walkthrough
# ===========================================================================

def figB_earliest_route_slot() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle(
        "Fig B -- How earliest_route_slot() finds the first joint-free slot on a route",
        fontsize=14, fontweight="bold", y=1.02,
    )

    # Scenario: route has 2 links (L1, L2).
    # L1 has reservations at [0,8) and [15,22).
    # L2 has reservations at [5,14).
    # New comm: duration=6, ready_time=0.
    # Walk through candidates: 0 (fails L1), 8 (fails L2), 14 (fails L1@15? no, 14+6=20 > 15),
    # 22 (passes both) -- let me verify:
    # candidate=0: L1 has [0,8) conflict (0<8 and 0<8). Push to 8.
    # candidate=8: L2 has [5,14), 8<14 and 5<14 -> conflict. Push to 14.
    # candidate=14: L1 has [15,22): 14+6=20 > 15, and 15 < 20 -> conflict. Push to 22.
    # candidate=22: L1 [0,8) no conflict. L1 [15,22) 22>=22 no conflict. L2 [5,14) no conflict.
    #   Answer: start=22.

    L1_ivs = [(0, 8), (15, 22)]
    L2_ivs = [(5, 14)]
    new_dur = 6
    ready = 0
    steps = [
        (0,  "0+6=6 conflicts L1[0,8). Push to 8.",   "fail_L1",  "#CC0000"),
        (8,  "8+6=14 conflicts L2[5,14). Push to 14.", "fail_L2",  "#D6604D"),
        (14, "14+6=20 conflicts L1[15,22). Push to 22.","fail_L1", "#CCBB44"),
        (22, "22+6=28. No conflict on L1 or L2. DONE!", "pass",    "#1A9850"),
    ]

    link_colors = {"L1 (P0->P4)": "#4477AA", "L2 (P4->P8)": "#AA3377"}
    iv_alpha = 0.5

    def _draw_link_panel(ax, title, highlight_step, fade_steps):
        ax.set_title(title, fontsize=12, fontweight="bold")
        ypos = {"L1 (P0->P4)": 1.5, "L2 (P4->P8)": 0.5}
        bar_h = 0.5

        # Existing reservations
        for lbl, ivs in [("L1 (P0->P4)", L1_ivs), ("L2 (P4->P8)", L2_ivs)]:
            y = ypos[lbl]
            color = link_colors[lbl]
            for start, end in ivs:
                ax.barh(y, end - start, left=start, height=bar_h,
                        color=color, alpha=0.55, edgecolor="black", linewidth=1.2)
                ax.text((start + end) / 2, y, f"[{start},{end})",
                        ha="center", va="center", fontsize=9, color="white",
                        fontweight="bold")

        # Draw all candidate steps
        for i, (cand, msg, status, color) in enumerate(steps):
            if i < len(steps) - 1 or highlight_step == i:
                # Draw the new comm block
                alpha = 0.85 if i == highlight_step else 0.25
                lw = 2.0 if i == highlight_step else 0.8
                for lbl_y in [1.5, 0.5]:
                    ax.barh(lbl_y - 0.0, new_dur, left=cand, height=bar_h,
                            color=color, alpha=alpha, edgecolor=color, linewidth=lw,
                            linestyle="--" if status.startswith("fail") else "-")

        ax.set_xlim(-1, 35)
        ax.set_ylim(-0.1, 2.5)
        ax.set_xlabel("Time", fontsize=11)
        ax.set_yticks([0.5, 1.5])
        ax.set_yticklabels(["L2 (P4->P8)", "L1 (P0->P4)"], fontsize=10)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(True, axis="x", alpha=0.25)

    # Left panel: show all steps annotated
    ax = axes[0]
    ax.set_title("Route has 2 links with existing reservations\nNew comm: duration=6, ready_time=0",
                 fontsize=12, fontweight="bold")

    ypos = {"L1 (P0->P4)": 1.5, "L2 (P4->P8)": 0.5}
    bar_h_l = 0.45

    for lbl, ivs in [("L1 (P0->P4)", L1_ivs), ("L2 (P4->P8)", L2_ivs)]:
        y = ypos[lbl]
        color = link_colors[lbl]
        for start, end in ivs:
            ax.barh(y, end - start, left=start, height=bar_h_l,
                    color=color, alpha=0.55, edgecolor="black", linewidth=1.2)
            ax.text((start + end) / 2, y, f"[{start},{end})",
                    ha="center", va="center", fontsize=9, color="white",
                    fontweight="bold")

    step_colors = ["#CC0000", "#D6604D", "#CCBB44", "#1A9850"]
    for i, (cand, msg, status, color) in enumerate(steps):
        alpha = 0.8 if i == len(steps) - 1 else 0.4
        lw = 2.0 if i == len(steps) - 1 else 1.2
        ls = "-" if i == len(steps) - 1 else "--"
        for lbl_y in [1.5, 0.5]:
            ax.barh(lbl_y, new_dur, left=cand, height=bar_h_l,
                    color=color, alpha=alpha, edgecolor=color,
                    linewidth=lw, linestyle=ls)
        # annotate
        arrow_y = 2.25 if i % 2 == 0 else 2.10
        ax.annotate(
            f"try t={cand}",
            xy=(cand, 1.5 + bar_h_l / 2), xytext=(cand + 0.5, arrow_y),
            arrowprops=dict(arrowstyle="->", color=color, lw=1.2),
            fontsize=8.5, color=color, fontweight="bold",
        )

    ax.set_xlim(-1, 35)
    ax.set_ylim(-0.5, 2.65)
    ax.set_xlabel("Time", fontsize=11)
    ax.set_yticks([0.5, 1.5])
    ax.set_yticklabels(["L2 (P4->P8)", "L1 (P0->P4)"], fontsize=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, axis="x", alpha=0.25)

    # Right panel: result explanation
    ax = axes[1]
    ax.set_title("Iteration trace and final result",
                 fontsize=12, fontweight="bold")
    ax.axis("off")

    pseudo = [
        "earliest_route_slot(route=[L1,L2], duration=6, not_before=0):",
        "",
        "  candidate = 0",
        "  L1 has [0,8):  0+6=6 overlaps [0,8)  -> conflict",
        "  -> candidate = 8",
        "",
        "  candidate = 8",
        "  L2 has [5,14): 8+6=14 overlaps [5,14) -> conflict",
        "  -> candidate = 14",
        "",
        "  candidate = 14",
        "  L1 has [15,22): 14+6=20 overlaps [15,22) -> conflict",
        "  -> candidate = 22",
        "",
        "  candidate = 22",
        "  L1 [0,8):   22 >= 8  -> no conflict",
        "  L1 [15,22): 22 >= 22 -> no conflict (back-to-back OK)",
        "  L2 [5,14):  22 >= 14 -> no conflict",
        "  -> return 22   (start_time = 22, finish_time = 28)",
    ]

    step_colors_text = {
        3: "#CC0000", 4: "#CC0000",
        7: "#D6604D", 8: "#D6604D",
        11: "#CCBB44", 12: "#CCBB44",
        15: "#1A9850", 16: "#1A9850", 17: "#1A9850", 18: "#1A9850",
    }

    for i, line in enumerate(pseudo):
        color = step_colors_text.get(i, "#222222")
        weight = "bold" if color != "#222222" else "normal"
        ax.text(0.02, 0.96 - i * 0.053, line,
                transform=ax.transAxes,
                fontsize=9.5, color=color, fontweight=weight,
                fontfamily="monospace", va="top")

    ax.text(0.02, 0.02,
            "Key rule: back-to-back intervals [a,b) and [b,c) do NOT overlap.\n"
            "This allows tightly packed back-to-back communications on a link.",
            transform=ax.transAxes, fontsize=9.5, color="#555555",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#F5F5F5",
                      edgecolor="#888888"))

    fig.tight_layout(rect=[0, 0.0, 1, 1])
    save_fig(fig, "figB_earliest_route_slot")


# ===========================================================================
# Figure C — Native vs replayed makespan bars (from Phase 21 CSV)
# ===========================================================================

def figC_native_vs_replayed_bars() -> None:
    if not CSV_PATH.exists():
        print(f"  WARNING: {CSV_PATH} not found, skipping figC", flush=True)
        return

    df = pd.read_csv(CSV_PATH)
    # Focus on fork-join (most dramatic) across all CCR values
    fj = df[df["dag_family"] == "fork_join"].copy()

    sched_keys = ["heft", "cdls", "cad"]
    ccr_vals = sorted(fj["ccr"].unique())

    fig, axes = plt.subplots(1, len(ccr_vals), figsize=(18, 5.5), sharey=False)
    fig.suptitle(
        "Fig C -- Native makespan (scheduler's prediction) vs Replayed makespan (contention ground-truth)\n"
        "Fork-join DAG (4 branches, length=3) -- the topology most sensitive to contention",
        fontsize=13, fontweight="bold", y=1.03,
    )

    bar_w = 0.28
    x_native  = np.array([-bar_w, 0.0, bar_w])
    x_replay  = x_native + 0.65

    for ax, ccr in zip(axes, ccr_vals):
        sub = fj[abs(fj["ccr"] - ccr) < 1e-9]

        native_vals  = []
        replay_vals  = []
        overhead_pct = []
        for key in sched_keys:
            row = sub[sub["scheduler"] == key]
            n = row["native_makespan"].values[0]
            r = row["replayed_makespan"].values[0]
            native_vals.append(n)
            replay_vals.append(r)
            overhead_pct.append((r / n - 1.0) * 100.0)

        # native bars (lighter shade)
        for i, (key, n) in enumerate(zip(sched_keys, native_vals)):
            bar = ax.bar(x_native[i], n, width=bar_w - 0.02,
                         color=SCHED_COLOR[key], alpha=0.45,
                         edgecolor=SCHED_COLOR[key], linewidth=1.5,
                         label=f"{SCHED_LABEL[key]} native" if ax is axes[0] else "")
            ax.text(x_native[i], n + 1.0, f"{n:.0f}",
                    ha="center", fontsize=9, color=SCHED_COLOR[key])

        # replayed bars (full color)
        for i, (key, r, pct) in enumerate(zip(sched_keys, replay_vals, overhead_pct)):
            ax.bar(x_replay[i], r, width=bar_w - 0.02,
                   color=SCHED_COLOR[key], alpha=0.90,
                   edgecolor="black", linewidth=1.0,
                   label=f"{SCHED_LABEL[key]} replayed" if ax is axes[0] else "")
            ax.text(x_replay[i], r + 1.0, f"{r:.0f}",
                    ha="center", fontsize=9, color="black")
            # overhead annotation
            if pct > 0.5:
                ax.annotate(
                    f"+{pct:.0f}%\noverhead",
                    xy=(x_replay[i], r), xytext=(x_replay[i] + 0.18, r * 0.9),
                    arrowprops=dict(arrowstyle="->", color="#CC0000", lw=1.1),
                    fontsize=8, color="#CC0000", fontweight="bold",
                )

        # group labels
        for i, key in enumerate(sched_keys):
            ax.text((x_native[i] + x_replay[i]) / 2, -8,
                    SCHED_LABEL[key], ha="center", fontsize=10,
                    fontweight="bold", color=SCHED_COLOR[key])

        ax.set_xticks([])
        ax.set_xlim(-0.55, 1.05)
        ax.set_ylim(0, max(replay_vals) * 1.20)
        ax.set_title(f"CCR = {ccr}", fontsize=12, fontweight="bold")
        ax.set_ylabel("Makespan" if ax is axes[0] else "", fontsize=11)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(True, axis="y", alpha=0.25)

    # shared legend
    native_patch  = mpatches.Patch(facecolor="#AAAAAA", alpha=0.45,
                                   edgecolor="#666666", label="Native (scheduler's prediction)")
    replay_patch  = mpatches.Patch(facecolor="#AAAAAA", alpha=0.90,
                                   edgecolor="black", label="Replayed (contention ground-truth)")
    overhead_text = plt.Line2D([0], [0], color="#CC0000", lw=0,
                               marker="$+\\%$", markersize=12,
                               label="Overhead = (replayed/native - 1) x 100%")
    fig.legend(handles=[native_patch, replay_patch],
               loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.08),
               fontsize=11, frameon=True)
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    save_fig(fig, "figC_native_vs_replayed_bars")


# ===========================================================================
# Figure D — Link utilization timeline (real data: fork-join CCR=10)
# ===========================================================================

def figD_link_utilization() -> None:
    noc = MeshNoC(NOC_ROWS, NOC_COLS, alpha=ALPHA, beta=BETA)
    dag_raw = generate_fork_join_dag(
        n_branches=4, branch_length=3,
        comp_range=(5, 20), comm_range=(1, 10),
        ccr=10.0, seed=SEED,
    )
    dag = DAGGraph(dag_raw)

    schedulers = {
        "heft": HEFTScheduler(noc).schedule(dag),
        "cad":  ProposedScheduler(noc).schedule(dag),
    }
    replayed = {k: replay_under_contention(dag, v, noc) for k, v in schedulers.items()}

    fig, axes = plt.subplots(1, 2, figsize=(18, 6))
    fig.suptitle(
        "Fig D -- Link-interval utilization under replay: Fork-join, CCR=10.0, seed=0\n"
        "Each bar = one reserved communication interval on that directed NoC link.",
        fontsize=13, fontweight="bold", y=1.03,
    )

    for ax, (key, rep_state) in zip(axes, replayed.items()):
        busy = link_busy_time(rep_state)
        makespan = rep_state.max_processor_finish_time()

        # Collect intervals per link, show only links with activity
        active_links = {
            link: ivs
            for link, ivs in rep_state.link_intervals.items()
            if ivs
        }

        if not active_links:
            ax.text(0.5, 0.5, "No link activity", ha="center", va="center",
                    transform=ax.transAxes, fontsize=12)
            ax.set_title(f"{SCHED_LABEL[key]}", fontsize=13, fontweight="bold")
            continue

        link_list = sorted(active_links.keys(),
                           key=lambda L: -busy[L])  # busiest first

        # Show top-15 links max to keep figure readable
        link_list = link_list[:15]
        y_pos = {link: i for i, link in enumerate(link_list)}
        bar_h = 0.55

        for link in link_list:
            for iv in active_links[link]:
                y = y_pos[link]
                ax.barh(y, iv.finish_time - iv.start_time,
                        left=iv.start_time, height=bar_h,
                        color=SCHED_COLOR[key], alpha=0.70,
                        edgecolor="black", linewidth=0.6)

        ax.set_yticks(list(range(len(link_list))))
        ax.set_yticklabels(
            [f"P{lk.source_processor}->P{lk.destination_processor}  "
             f"({busy[lk]:.0f}AU)"
             for lk in link_list],
            fontsize=8.5,
        )
        ax.axvline(makespan, color="black", lw=1.5, linestyle="--", alpha=0.6)
        ax.text(makespan, len(link_list) - 0.5, f" MS={makespan:.1f}",
                fontsize=9, color="black")

        n_comms = len(rep_state.communication_instances)
        n_active = sum(1 for v in busy.values() if v > 0)
        util = sum(busy.values()) / (len(busy) * makespan) if makespan > 0 else 0

        ax.set_xlabel("Time", fontsize=11)
        ax.set_title(
            f"{SCHED_LABEL[key]}  --  {n_comms} comms, {n_active} active links\n"
            f"Makespan={makespan:.1f},  avg link util={util:.1%}",
            fontsize=12, fontweight="bold",
        )
        ax.grid(True, axis="x", alpha=0.25)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.tight_layout(rect=[0, 0.0, 1, 1])
    save_fig(fig, "figD_link_utilization")


# ===========================================================================
# Figure E — Three communication models side by side (concept diagram)
# ===========================================================================

def figE_three_models() -> None:
    """Compare what HEFT, CD-LS, and CA-D do at scheduling time vs replay."""
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    fig.suptitle(
        "Fig E -- Three communication models: what each scheduler sees during scheduling",
        fontsize=14, fontweight="bold", y=1.02,
    )

    # We illustrate task T scheduling on P3, with predecessor T0 on P0.
    # The link P0->P3 already has a reservation at [0, 8).
    # T0 finishes at t=5.  Communication volume=4 (duration=4 with beta=1).
    # Ready time = 5 (when T0 finishes).
    #
    # HEFT/CD-LS: arrival = 5 + 4 = 9  (ignores the existing [0,8) reservation)
    # CA-D probe:  earliest_route_slot([L_0->3], 4, not_before=5) -> 8, arrival=12
    #              (sees [0,8) and pushes to t=8)
    # Replay: same as CA-D probe but commits the reservation

    existing_iv = (0, 8)   # existing comm on the link
    T0_finish = 5.0
    comm_dur = 4.0

    heft_start  = T0_finish                  # 5 (ignores existing)
    heft_finish = heft_start + comm_dur       # 9
    cad_start   = max(existing_iv[1], T0_finish)   # 8 (pushed past existing)
    cad_finish  = cad_start + comm_dur        # 12

    existing_color = "#CCCCCC"
    T0_color  = "#4477AA"
    comm_color_heft = "#D6604D"
    comm_color_cad  = "#1A9850"

    def _draw_panel(ax, title, subtitle, comm_start, comm_finish, comm_color,
                    shows_conflict: bool):
        ax.set_xlim(-0.5, 15.0)
        ax.set_ylim(-0.5, 2.2)
        ax.axis("off")
        ax.set_title(title, fontsize=13, fontweight="bold", pad=4)
        ax.text(0.5, 2.12, subtitle, ha="center", va="top", transform=ax.transAxes,
                fontsize=9.5, color="#555555", style="italic")

        bar_h = 0.38
        link_y = 1.2
        proc_y = 0.3

        # Processor timeline
        ax.barh(proc_y, T0_finish, left=0, height=bar_h,
                color=T0_color, alpha=0.85, edgecolor="black")
        ax.text(T0_finish / 2, proc_y, "T0  (fin=5)", ha="center", va="center",
                fontsize=9, fontweight="bold", color="white")

        # Link: existing reservation
        ax.barh(link_y, existing_iv[1] - existing_iv[0],
                left=existing_iv[0], height=bar_h,
                color=existing_color, alpha=0.70, edgecolor="#888888",
                linewidth=1, linestyle="--")
        ax.text((existing_iv[0] + existing_iv[1]) / 2, link_y,
                "existing\n[0,8)", ha="center", va="center",
                fontsize=8.5, color="#555555")

        # New comm
        ax.barh(link_y, comm_finish - comm_start, left=comm_start,
                height=bar_h, color=comm_color, alpha=0.85,
                edgecolor="black", linewidth=1.5)
        ax.text((comm_start + comm_finish) / 2, link_y,
                f"new comm\n[{comm_start:.0f},{comm_finish:.0f})",
                ha="center", va="center", fontsize=8.5,
                fontweight="bold", color="white")

        # Conflict indicator
        if shows_conflict:
            overlap_start = comm_start
            overlap_end = min(comm_finish, existing_iv[1])
            if overlap_end > overlap_start:
                ax.barh(link_y, overlap_end - overlap_start,
                        left=overlap_start, height=bar_h,
                        color="#CC0000", alpha=0.35, edgecolor="#CC0000",
                        linewidth=2.0, linestyle="-")
                ax.text(
                    (overlap_start + overlap_end) / 2, link_y + 0.35,
                    "CONFLICT\n(not detected!)",
                    ha="center", fontsize=9, color="#CC0000",
                    fontweight="bold",
                )

        # Arrow: T0 finish -> comm start
        ax.annotate("", xy=(comm_start, link_y),
                    xytext=(T0_finish, proc_y + bar_h),
                    arrowprops=dict(arrowstyle="->", color="#333333", lw=1.3))

        # Arrival time
        ax.axvline(comm_finish, color=comm_color, lw=2, linestyle=":")
        ax.text(comm_finish + 0.2, 0.0, f"arrival\n= {comm_finish:.0f}",
                ha="left", va="bottom", fontsize=9.5,
                color=comm_color, fontweight="bold")

        # Row labels
        ax.text(-0.3, proc_y, "Processor\n(T0)", ha="right", va="center",
                fontsize=9, color="#444444")
        ax.text(-0.3, link_y, "Link\nintervals", ha="right", va="center",
                fontsize=9, color="#444444")

    # Panel A: HEFT/CD-LS
    _draw_panel(
        axes[0],
        "A -- HEFT / CD-LS\n(analytic, contention-blind)",
        "arrival = T0.finish + beta*vol = 5 + 4 = 9\nNo link_intervals consulted.",
        comm_start=heft_start, comm_finish=heft_finish,
        comm_color=comm_color_heft, shows_conflict=True,
    )

    # Panel B: CA-D (probe during scheduling)
    _draw_panel(
        axes[1],
        "B -- CA-D during scheduling\n(probe_communication_arrival, read-only)",
        "arrival = earliest_route_slot([L], 4, not_before=5) = 8+4 = 12\nSees [0,8). Pushes to t=8.",
        comm_start=cad_start, comm_finish=cad_finish,
        comm_color=comm_color_cad, shows_conflict=False,
    )

    # Panel C: Replay (commit)
    _draw_panel(
        axes[2],
        "C -- Replay / CA-D scheduling\n(reserve_communication, commits reservation)",
        "Same as probe but reserves [8,12) on the link.\nNext comm will see this interval.",
        comm_start=cad_start, comm_finish=cad_finish,
        comm_color=comm_color_cad, shows_conflict=False,
    )
    # Add "reserved" marker on panel C
    ax = axes[2]
    ax.text(cad_start + (cad_finish - cad_start) / 2, 1.75,
            "reserved in\nlink_intervals", ha="center", fontsize=9,
            color=comm_color_cad, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                      edgecolor=comm_color_cad, alpha=0.9))

    fig.tight_layout(rect=[0, 0.0, 1, 1])
    save_fig(fig, "figE_three_models")


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    print("Contention Explainer Figures", flush=True)
    print("=" * 45, flush=True)

    print("\n[A] Link contention mechanism ...", flush=True)
    figA_link_contention_mechanism()

    print("\n[B] earliest_route_slot walkthrough ...", flush=True)
    figB_earliest_route_slot()

    print("\n[C] Native vs replayed bars (Phase 21 CSV) ...", flush=True)
    figC_native_vs_replayed_bars()

    print("\n[D] Link utilization timeline (fork-join CCR=10) ...", flush=True)
    figD_link_utilization()

    print("\n[E] Three communication models ...", flush=True)
    figE_three_models()

    print(f"\nDone -> {OUT_DIR.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
