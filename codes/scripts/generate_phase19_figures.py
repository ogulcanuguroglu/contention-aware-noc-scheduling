"""
Phase 19 Part F — IEEE-style figure generation
===============================================
Reads phase19_multiseed_main.csv and phase19_alpha_sensitivity.csv,
then generates 8 figures (PNG 300 DPI + PDF each).

Figures:
  figA — Multi-seed replayed speedup vs HEFT with 95% CI error bars (by CCR)
  figB — Native-model optimism: replay overhead ratio distribution (by scheduler+DAG)
  figC — Duplication efficiency distribution (CA-D vs CD-LS, by DAG)
  figD — Task Instance Ratio (TIR) distribution by CCR and scheduler
  figE — Link load imbalance and total link busy time (by scheduler+DAG)
  figF — Mechanism Gantt case study (out-tree CCR=5.0 seed=0)
  figG — Link usage: n_used_links and link_max_busy_time heatmap (DAG × CCR)
  figH — Alpha sensitivity: replayed speedup vs CCR for out-tree and fork-join

Output: results/figures/phase19/figA_*.{png,pdf} ...

Run from repository root:
    python scripts/generate_phase19_figures.py
"""

import sys
import math
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

from src.noc import MeshNoC
from src.models import DAGGraph
from src.graph_families import generate_out_tree_dag, generate_fork_join_dag
from src.heft_scheduler import HEFTScheduler
from src.classical_dup_scheduler import ClassicalDuplicationScheduler
from src.proposed_scheduler import ProposedScheduler
from src.plots import matplotlib  # ensures Agg backend

OUT_DIR = ROOT / "results" / "figures" / "phase19"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MAIN_CSV = ROOT / "results" / "summary" / "phase19_multiseed_main.csv"
SENS_CSV = ROOT / "results" / "summary" / "phase19_alpha_sensitivity.csv"

# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

SCHED_ORDER = ["heft", "cdls", "cad"]
SCHED_LABEL = {"heft": "HEFT", "cdls": "CD-LS", "cad": "CA-D"}
SCHED_COLOR = {"heft": "#4477AA", "cdls": "#EE6677", "cad": "#228833"}
SCHED_MARKER = {"heft": "o", "cdls": "s", "cad": "D"}

DAG_ORDER = ["chain", "fork", "out_tree", "fork_join"]
DAG_LABEL = {"chain": "Chain", "fork": "Fork", "out_tree": "Out-tree", "fork_join": "Fork-join"}

CCR_VALUES = [0.1, 1.0, 5.0, 10.0]

plt.rcParams.update({
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "figure.dpi": 100,
})


def save_fig(fig, name: str) -> None:
    for ext in ("png", "pdf"):
        path = OUT_DIR / f"{name}.{ext}"
        fig.savefig(path, dpi=300, bbox_inches="tight")
    print(f"  Saved {name}.png/.pdf", flush=True)
    plt.close(fig)


def _z95(n: int) -> float:
    """95% CI half-width = 1.96 * std / sqrt(n)."""
    return 1.96


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    df_main = pd.read_csv(MAIN_CSV)
    df_sens = pd.read_csv(SENS_CSV)
    # Convert NaN-marked empty strings back to NaN
    for col in ["duplication_efficiency", "makespan_reduction_per_dup"]:
        if col in df_main.columns:
            df_main[col] = pd.to_numeric(df_main[col], errors="coerce")
        if col in df_sens.columns:
            df_sens[col] = pd.to_numeric(df_sens[col], errors="coerce")
    return df_main, df_sens


# ---------------------------------------------------------------------------
# Fig A: Multi-seed replayed speedup vs HEFT with error bars
# ---------------------------------------------------------------------------

def fig_a_multiseed_speedup(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.5), sharey=False)

    for ax, dag_name in zip(axes, DAG_ORDER):
        sub = df[df["dag_family"] == dag_name]
        for sched in SCHED_ORDER:
            s = sub[sub["scheduler"] == sched]
            grp = s.groupby("ccr")["replayed_speedup_vs_heft"]
            means = [grp.get_group(c).mean() if c in grp.groups else np.nan for c in CCR_VALUES]
            stds = [grp.get_group(c).std() if c in grp.groups else np.nan for c in CCR_VALUES]
            ns = [grp.get_group(c).count() if c in grp.groups else 0 for c in CCR_VALUES]
            ci = [1.96 * s / math.sqrt(n) if n > 1 else 0 for s, n in zip(stds, ns)]
            ax.errorbar(
                CCR_VALUES, means, yerr=ci,
                label=SCHED_LABEL[sched],
                color=SCHED_COLOR[sched],
                marker=SCHED_MARKER[sched],
                markersize=5, linewidth=1.2, capsize=3,
            )
        ax.axhline(1.0, color="gray", linestyle="--", linewidth=0.8)
        ax.set_xscale("log")
        ax.set_xlim(0.08, 15)
        ax.set_xlabel("CCR")
        ax.set_title(DAG_LABEL[dag_name])
        ax.set_ylabel("Replayed speedup vs HEFT" if ax == axes[0] else "")
        ax.grid(True, alpha=0.3)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3,
               bbox_to_anchor=(0.5, 1.02), frameon=True)
    fig.suptitle("Fig A — Multi-seed replayed speedup vs HEFT (mean ± 95% CI, 20 seeds)", y=1.06)
    save_fig(fig, "figA_multiseed_speedup")


# ---------------------------------------------------------------------------
# Fig B: Replay overhead ratio distribution (native-model optimism)
# ---------------------------------------------------------------------------

def fig_b_replay_overhead(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)

    for ax, sched in zip(axes, ["cdls", "cad"]):
        s = df[df["scheduler"] == sched]
        data = [s[s["dag_family"] == dag]["replay_overhead_ratio"].dropna().values
                for dag in DAG_ORDER]
        bp = ax.boxplot(data, labels=[DAG_LABEL[d] for d in DAG_ORDER],
                        patch_artist=True, notch=False,
                        medianprops={"color": "black", "linewidth": 1.5})
        for patch in bp["boxes"]:
            patch.set_facecolor(SCHED_COLOR[sched])
            patch.set_alpha(0.6)
        ax.axhline(1.0, color="gray", linestyle="--", linewidth=0.8, label="No overhead")
        ax.set_title(f"{SCHED_LABEL[sched]}")
        ax.set_xlabel("DAG family")
        ax.set_ylabel("Replay overhead ratio (replayed/native)" if ax == axes[0] else "")
        ax.grid(True, axis="y", alpha=0.3)

    fig.suptitle("Fig B — Native-model optimism: replay overhead ratio (all CCR, 20 seeds)")
    handles = [mpatches.Patch(facecolor=SCHED_COLOR[s], alpha=0.6, label=SCHED_LABEL[s])
               for s in ["cdls", "cad"]]
    handles.append(plt.Line2D([0], [0], color="gray", linestyle="--", label="No overhead"))
    fig.legend(handles=handles, loc="upper right", frameon=True)
    save_fig(fig, "figB_replay_overhead")


# ---------------------------------------------------------------------------
# Fig C: Duplication efficiency (CA-D vs CD-LS)
# ---------------------------------------------------------------------------

def fig_c_duplication_efficiency(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.5), sharey=False)

    for ax, dag_name in zip(axes, DAG_ORDER):
        sub = df[df["dag_family"] == dag_name]
        for sched in ["cdls", "cad"]:
            s = sub[sub["scheduler"] == sched]
            grp = s.groupby("ccr")["duplication_efficiency"]
            vals = []
            for c in CCR_VALUES:
                if c in grp.groups:
                    v = grp.get_group(c).dropna()
                    vals.append(v.mean() if len(v) > 0 else np.nan)
                else:
                    vals.append(np.nan)
            ax.plot(
                CCR_VALUES, vals,
                label=SCHED_LABEL[sched],
                color=SCHED_COLOR[sched],
                marker=SCHED_MARKER[sched],
                markersize=5, linewidth=1.2,
            )
        ax.axhline(0.0, color="gray", linestyle="--", linewidth=0.8)
        ax.set_xscale("log")
        ax.set_xlim(0.08, 15)
        ax.set_xlabel("CCR")
        ax.set_title(DAG_LABEL[dag_name])
        ax.set_ylabel("Duplication efficiency\n(speedup−1)/(TIR−1)" if ax == axes[0] else "")
        ax.grid(True, alpha=0.3)

    handles, labels = axes[-1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2,
               bbox_to_anchor=(0.5, 1.02), frameon=True)
    fig.suptitle("Fig C — Duplication efficiency by CCR (mean over 20 seeds)", y=1.06)
    save_fig(fig, "figC_duplication_efficiency")


# ---------------------------------------------------------------------------
# Fig D: Task Instance Ratio (TIR) by CCR and scheduler
# ---------------------------------------------------------------------------

def fig_d_tir(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.5), sharey=False)

    for ax, dag_name in zip(axes, DAG_ORDER):
        sub = df[df["dag_family"] == dag_name]
        for sched in SCHED_ORDER:
            s = sub[sub["scheduler"] == sched]
            grp = s.groupby("ccr")["task_instance_ratio"]
            means = [grp.get_group(c).mean() if c in grp.groups else np.nan for c in CCR_VALUES]
            ax.plot(
                CCR_VALUES, means,
                label=SCHED_LABEL[sched],
                color=SCHED_COLOR[sched],
                marker=SCHED_MARKER[sched],
                markersize=5, linewidth=1.2,
            )
        ax.axhline(1.0, color="gray", linestyle="--", linewidth=0.8)
        ax.set_xscale("log")
        ax.set_xlim(0.08, 15)
        ax.set_xlabel("CCR")
        ax.set_title(DAG_LABEL[dag_name])
        ax.set_ylabel("Task Instance Ratio (TIR)" if ax == axes[0] else "")
        ax.grid(True, alpha=0.3)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3,
               bbox_to_anchor=(0.5, 1.02), frameon=True)
    fig.suptitle("Fig D — Task Instance Ratio by CCR (mean over 20 seeds)", y=1.06)
    save_fig(fig, "figD_tir")


# ---------------------------------------------------------------------------
# Fig E: Link load imbalance and contention penalty
# ---------------------------------------------------------------------------

def fig_e_link_contention(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 4, figsize=(13, 6))

    for col_idx, dag_name in enumerate(DAG_ORDER):
        sub = df[df["dag_family"] == dag_name]

        # Top: link load imbalance by CCR
        ax_top = axes[0][col_idx]
        for sched in ["cdls", "cad"]:
            s = sub[sub["scheduler"] == sched]
            grp = s.groupby("ccr")["link_load_imbalance"]
            means = [grp.get_group(c).mean() if c in grp.groups else np.nan for c in CCR_VALUES]
            ax_top.plot(
                CCR_VALUES, means,
                label=SCHED_LABEL[sched],
                color=SCHED_COLOR[sched],
                marker=SCHED_MARKER[sched],
                markersize=4, linewidth=1.2,
            )
        ax_top.set_xscale("log")
        ax_top.set_xlim(0.08, 15)
        ax_top.set_title(DAG_LABEL[dag_name])
        ax_top.set_ylabel("Link load imbalance" if col_idx == 0 else "")
        ax_top.grid(True, alpha=0.3)

        # Bottom: normalized contention penalty by CCR
        ax_bot = axes[1][col_idx]
        for sched in ["cdls", "cad"]:
            s = sub[sub["scheduler"] == sched]
            grp = s.groupby("ccr")["normalized_contention_penalty"]
            means = [grp.get_group(c).mean() if c in grp.groups else np.nan for c in CCR_VALUES]
            ax_bot.plot(
                CCR_VALUES, means,
                label=SCHED_LABEL[sched],
                color=SCHED_COLOR[sched],
                marker=SCHED_MARKER[sched],
                markersize=4, linewidth=1.2,
            )
        ax_bot.axhline(0.0, color="gray", linestyle="--", linewidth=0.8)
        ax_bot.set_xscale("log")
        ax_bot.set_xlim(0.08, 15)
        ax_bot.set_xlabel("CCR")
        ax_bot.set_ylabel("Normalized contention penalty" if col_idx == 0 else "")
        ax_bot.grid(True, alpha=0.3)

    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2,
               bbox_to_anchor=(0.5, 1.01), frameon=True)
    fig.suptitle("Fig E — Link load imbalance (top) and normalized contention penalty (bottom)", y=1.03)
    fig.tight_layout()
    save_fig(fig, "figE_link_contention")


# ---------------------------------------------------------------------------
# Fig F: Mechanism Gantt case study (out-tree CCR=5.0 seed=0)
# ---------------------------------------------------------------------------

def _gantt_panel(ax, state, title: str) -> None:
    """Draw compact Gantt on ax from a ScheduleState."""
    active_procs = sorted({
        inst.processor_id
        for insts in state.task_instances.values()
        for inst in insts
    })
    proc_row = {pid: i for i, pid in enumerate(active_procs)}
    n_rows = len(active_procs)

    colors = plt.cm.tab10.colors
    task_color = {}
    for tid in state.task_instances:
        task_color[tid] = colors[tid % 10]

    for tid, insts in state.task_instances.items():
        for inst in insts:
            row = proc_row[inst.processor_id]
            color = task_color[tid]
            hatch = "//" if not inst.is_primary else ""
            ax.barh(
                row, inst.finish_time - inst.start_time,
                left=inst.start_time,
                height=0.6,
                color=color, edgecolor="black", linewidth=0.5,
                hatch=hatch, alpha=0.85,
            )
            mid = (inst.start_time + inst.finish_time) / 2
            ax.text(mid, row, f"T{tid}", ha="center", va="center",
                    fontsize=6, fontweight="bold")

    ax.set_yticks(range(n_rows))
    ax.set_yticklabels([f"P{p}" for p in active_procs], fontsize=7)
    ms = state.max_processor_finish_time()
    ax.set_xlim(0, ms * 1.05)
    ax.set_title(f"{title}\nmakespan={ms:.1f}", fontsize=9)
    ax.set_xlabel("Time (AU)", fontsize=8)
    ax.grid(True, axis="x", alpha=0.3)


def fig_f_gantt_case_study() -> None:
    noc = MeshNoC(rows=4, cols=4, alpha=0.0, beta=1.0)
    g = generate_out_tree_dag(depth=2, branching_factor=2, ccr=5.0, seed=0)
    dag = DAGGraph(g)

    states = {
        "HEFT": HEFTScheduler(noc).schedule(dag),
        "CD-LS": ClassicalDuplicationScheduler(noc).schedule(dag),
        "CA-D": ProposedScheduler(noc).schedule(dag),
    }

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.5))
    for ax, (label, state) in zip(axes, states.items()):
        _gantt_panel(ax, state, label)

    hatch_patch = mpatches.Patch(facecolor="white", edgecolor="black",
                                 hatch="//", label="Duplicate instance")
    prim_patch = mpatches.Patch(facecolor="white", edgecolor="black", label="Primary instance")
    fig.legend(handles=[prim_patch, hatch_patch], loc="upper center", ncol=2,
               bbox_to_anchor=(0.5, 1.03), frameon=True)
    fig.suptitle("Fig F — Out-tree (depth=2, bf=2, CCR=5.0, seed=0): three-scheduler Gantt",
                 y=1.08)
    fig.tight_layout()
    save_fig(fig, "figF_gantt_case_study")


# ---------------------------------------------------------------------------
# Fig G: Link usage heatmap (DAG × CCR, metric = n_used_links)
# ---------------------------------------------------------------------------

def fig_g_link_heatmap(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.5))

    for ax, sched in zip(axes, ["cdls", "cad"]):
        sub = df[df["scheduler"] == sched]
        matrix = np.zeros((len(DAG_ORDER), len(CCR_VALUES)))
        for r, dag_name in enumerate(DAG_ORDER):
            for c, ccr in enumerate(CCR_VALUES):
                cell = sub[(sub["dag_family"] == dag_name) & (sub["ccr"] == ccr)]
                matrix[r, c] = cell["n_used_links"].mean()

        im = ax.imshow(matrix, aspect="auto", cmap="YlOrRd")
        ax.set_xticks(range(len(CCR_VALUES)))
        ax.set_xticklabels([str(c) for c in CCR_VALUES])
        ax.set_yticks(range(len(DAG_ORDER)))
        ax.set_yticklabels([DAG_LABEL[d] for d in DAG_ORDER])
        ax.set_xlabel("CCR")
        ax.set_title(f"{SCHED_LABEL[sched]}\nMean n_used_links")
        for r in range(len(DAG_ORDER)):
            for c in range(len(CCR_VALUES)):
                ax.text(c, r, f"{matrix[r, c]:.1f}",
                        ha="center", va="center", fontsize=8)
        plt.colorbar(im, ax=ax, shrink=0.8)

    fig.suptitle("Fig G — Mean number of used links per scheduler (20 seeds per cell)")
    fig.tight_layout()
    save_fig(fig, "figG_link_usage_heatmap")


# ---------------------------------------------------------------------------
# Fig H: Alpha sensitivity
# ---------------------------------------------------------------------------

def fig_h_alpha_sensitivity(df_sens: pd.DataFrame) -> None:
    sens_dags = ["out_tree", "fork_join"]
    alpha_vals = [0.0, 1.0, 5.0]
    ccr_vals = [1.0, 5.0]
    alpha_colors = {0.0: "#4477AA", 1.0: "#EE6677", 5.0: "#228833"}
    alpha_markers = {0.0: "o", 1.0: "s", 5.0: "D"}

    fig, axes = plt.subplots(2, 2, figsize=(10, 6), sharey=False)

    for row_idx, dag_name in enumerate(sens_dags):
        for col_idx, ccr in enumerate(ccr_vals):
            ax = axes[row_idx][col_idx]
            sub = df_sens[(df_sens["dag_family"] == dag_name) & (df_sens["ccr"] == ccr)]
            for alpha in alpha_vals:
                a_sub = sub[sub["alpha"] == alpha]
                for sched in ["cdls", "cad"]:
                    s = a_sub[a_sub["scheduler"] == sched]
                    mean_val = s["replayed_speedup_vs_heft"].mean()
                    std_val = s["replayed_speedup_vs_heft"].std()
                    n = len(s)
                    ci = 1.96 * std_val / math.sqrt(n) if n > 1 else 0
                    x_offset = SCHED_ORDER.index(sched) * 0.15 - 0.075
                    ax.errorbar(
                        alpha + x_offset, mean_val, yerr=ci,
                        color=SCHED_COLOR[sched],
                        marker=SCHED_MARKER[sched],
                        markersize=6, capsize=3, linewidth=0,
                        elinewidth=1.2,
                    )
            ax.axhline(1.0, color="gray", linestyle="--", linewidth=0.8)
            ax.set_xticks(alpha_vals)
            ax.set_xlabel("Alpha (hop latency weight)")
            ax.set_ylabel("Replayed speedup vs HEFT" if col_idx == 0 else "")
            ax.set_title(f"{DAG_LABEL[dag_name]} CCR={ccr}")
            ax.grid(True, alpha=0.3)

    handles = [
        mpatches.Patch(facecolor=SCHED_COLOR[s], label=SCHED_LABEL[s])
        for s in ["cdls", "cad"]
    ]
    fig.legend(handles=handles, loc="upper center", ncol=2,
               bbox_to_anchor=(0.5, 1.02), frameon=True)
    fig.suptitle("Fig H — Alpha sensitivity: replayed speedup vs HEFT (mean ± 95% CI, 10 seeds)",
                 y=1.04)
    fig.tight_layout()
    save_fig(fig, "figH_alpha_sensitivity")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("[Phase 19 Fig Gen] Loading CSVs...", flush=True)
    df_main, df_sens = load_data()

    print("  Generating figures...", flush=True)
    fig_a_multiseed_speedup(df_main)
    fig_b_replay_overhead(df_main)
    fig_c_duplication_efficiency(df_main)
    fig_d_tir(df_main)
    fig_e_link_contention(df_main)
    fig_f_gantt_case_study()
    fig_g_link_heatmap(df_main)
    fig_h_alpha_sensitivity(df_sens)

    print(f"\n[Done] All figures saved to {OUT_DIR.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
