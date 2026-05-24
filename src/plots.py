"""
Visualization functions for experiment results.

Produces comparison plots: makespan vs CCR, speedup vs CCR, link utilization,
task instance ratio, communication count, and scheduler runtime.
Saves figures to results/plots/.
Implemented in Phase 10; robustness and presentation cleanup applied after.

Backend note:
    matplotlib is configured to use the non-interactive Agg backend at import
    time so that figure creation and saving work in headless environments
    (tests, CI, remote servers) without requiring a display.
"""

import matplotlib
matplotlib.use("Agg")  # must be set before importing pyplot

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
from pathlib import Path


# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------

_DEFAULT_SCHEDULER_ORDER: list[str] = [
    "heft",
    "contention_aware",
    "classical_duplication",
    "proposed",
]

_SCHEDULER_LABELS: dict[str, str] = {
    "heft": "HEFT",
    "contention_aware": "CA-LS",
    "classical_duplication": "CD-LS",
    "proposed": "CA-D (Proposed)",
}

_SCHEDULER_COLORS: dict[str, str] = {
    "heft": "#1f77b4",
    "contention_aware": "#ff7f0e",
    "classical_duplication": "#2ca02c",
    "proposed": "#d62728",
}

_SCHEDULER_MARKERS: dict[str, str] = {
    "heft": "o",
    "contention_aware": "s",
    "classical_duplication": "^",
    "proposed": "D",
}

# Minimum columns required for load_results() to accept a CSV.
_REQUIRED_COLUMNS: list[str] = [
    "scheduler",
    "n_tasks",
    "ccr",
    "makespan",
    "speedup_vs_heft",
    "serial_speedup",
    "duplicate_task_count",
    "task_instance_ratio",
    "communication_count",
    "max_link_utilization",
    "runtime_ms",
    "baseline_makespan_heft",
    "normalized_makespan_vs_heft",
]

_SUMMARY_METRICS: list[str] = [
    "makespan",
    "speedup_vs_heft",
    "serial_speedup",
    "duplicate_task_count",
    "task_instance_ratio",
    "communication_count",
    "max_link_utilization",
    "runtime_ms",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_results(csv_path: str | Path) -> pd.DataFrame:
    """
    Load an experiment results CSV produced by src.experiment_runner.

    Validates that the file exists and that all required columns are present.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if required columns are missing.
    """
    p = Path(csv_path)
    if not p.exists():
        raise FileNotFoundError(f"Results CSV not found: {csv_path}")
    df = pd.read_csv(p)
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Missing required columns in {csv_path}: {missing}"
        )
    return df


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_results(
    df: pd.DataFrame,
    metric: str,
    group_by: list[str] | None = None,
) -> pd.DataFrame:
    """
    Group df by group_by columns and compute mean, std, and count of metric.

    Default group_by: ["scheduler", "ccr"].

    Returns a DataFrame with columns:
        <group_by columns>, <metric>_mean, <metric>_std, <metric>_count.

    Raises:
        ValueError: if metric is not a column in df.
        ValueError: if any group_by column is missing from df.
    """
    if group_by is None:
        group_by = ["scheduler", "ccr"]
    missing_cols = [c for c in group_by if c not in df.columns]
    if missing_cols:
        raise ValueError(
            f"group_by columns not found in DataFrame: {missing_cols}"
        )
    if metric not in df.columns:
        raise ValueError(
            f"Metric '{metric}' not found in DataFrame columns: {sorted(df.columns)}"
        )
    agg = (
        df.groupby(group_by)[metric]
        .agg(["mean", "std", "count"])
        .reset_index()
        .rename(columns={
            "mean": f"{metric}_mean",
            "std": f"{metric}_std",
            "count": f"{metric}_count",
        })
    )
    return agg


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _save_figure(fig: plt.Figure, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def _apply_ccr_xaxis(ax: plt.Axes, ccr_values: list) -> None:
    """
    Configure x-axis for CCR plots.

    Uses log scale when all CCR values are strictly positive (the common case).
    Falls back to linear scale if any value is <= 0 (e.g. ccr=0.0 experiments).
    In both cases the exact CCR tick positions are labelled.
    """
    if all(v > 0 for v in ccr_values):
        ax.set_xscale("log")
    ax.xaxis.set_major_locator(mticker.FixedLocator(ccr_values))
    ax.xaxis.set_minor_locator(mticker.NullLocator())
    ax.xaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{v:g}")
    )


# ---------------------------------------------------------------------------
# Core plot function
# ---------------------------------------------------------------------------

def plot_metric_vs_ccr(
    df: pd.DataFrame,
    metric: str,
    output_path: str | Path,
    title: str | None = None,
    ylabel: str | None = None,
    scheduler_order: list[str] | None = None,
    show_error: bool = True,
    reference_line_y: float | None = None,
) -> Path:
    """
    Plot mean metric vs CCR for each scheduler with optional error bars.

    Error bars are drawn when show_error=True and a scheduler has more than
    one observation per CCR value (i.e. multiple seeds).
    Uses the non-interactive Agg backend.

    Args:
        df:               Results DataFrame (from load_results or run_experiment_grid).
        metric:           Column name to plot on the y-axis.
        output_path:      Destination PNG path. Parent directories are created.
        title:            Figure title. Defaults to "<metric> vs CCR".
        ylabel:           Y-axis label. Defaults to metric name.
        scheduler_order:  Schedulers to include and their draw order.
        show_error:       Draw std error bars (default True). Set False to plot
                          mean lines only, useful when error bars dominate.
        reference_line_y: If given, draw a subtle horizontal dashed line at
                          this y value (e.g. 1.0 for the HEFT speedup baseline).

    Returns:
        Path to the saved PNG file.
    """
    if scheduler_order is None:
        scheduler_order = _DEFAULT_SCHEDULER_ORDER

    agg = aggregate_results(df, metric, ["scheduler", "ccr"])
    ccr_values = sorted(agg["ccr"].unique())

    mean_col = f"{metric}_mean"
    std_col = f"{metric}_std"
    count_col = f"{metric}_count"

    fig, ax = plt.subplots(figsize=(7, 4))

    if reference_line_y is not None:
        ax.axhline(
            y=reference_line_y,
            color="gray",
            linewidth=0.8,
            linestyle="--",
            zorder=0,
        )

    for sched in scheduler_order:
        sub = agg[agg["scheduler"] == sched].sort_values("ccr")
        if sub.empty:
            continue

        label = _SCHEDULER_LABELS.get(sched, sched)
        color = _SCHEDULER_COLORS.get(sched)
        marker = _SCHEDULER_MARKERS.get(sched, "o")

        has_error = (
            show_error
            and std_col in sub.columns
            and count_col in sub.columns
            and (sub[count_col] > 1).any()
            and sub[std_col].notna().any()
        )

        if has_error:
            ax.errorbar(
                sub["ccr"].values,
                sub[mean_col].values,
                yerr=sub[std_col].fillna(0).values,
                label=label,
                color=color,
                marker=marker,
                linewidth=1.5,
                markersize=6,
                capsize=3,
                capthick=1.0,
            )
        else:
            ax.plot(
                sub["ccr"].values,
                sub[mean_col].values,
                label=label,
                color=color,
                marker=marker,
                linewidth=1.5,
                markersize=6,
            )

    _apply_ccr_xaxis(ax, ccr_values)
    ax.set_xlabel("CCR (Communication-to-Computation Ratio)")
    ax.set_ylabel(ylabel if ylabel is not None else metric)
    ax.set_title(title if title is not None else f"{metric} vs CCR")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    plt.tight_layout()

    return _save_figure(fig, Path(output_path))


# ---------------------------------------------------------------------------
# Wrapper plot functions
# ---------------------------------------------------------------------------

def plot_makespan_vs_ccr(
    df: pd.DataFrame,
    output_path: str | Path,
    show_error: bool = True,
) -> Path:
    """Plot mean makespan vs CCR for each scheduler."""
    return plot_metric_vs_ccr(
        df, "makespan", output_path,
        title="Makespan vs CCR", ylabel="Makespan",
        show_error=show_error,
    )


def plot_speedup_vs_ccr(
    df: pd.DataFrame,
    output_path: str | Path,
    show_error: bool = True,
) -> Path:
    """Plot mean speedup over HEFT vs CCR for each scheduler."""
    return plot_metric_vs_ccr(
        df, "speedup_vs_heft", output_path,
        title="Speedup vs CCR", ylabel="Speedup over HEFT",
        show_error=show_error,
        reference_line_y=1.0,
    )


def plot_task_instance_ratio_vs_ccr(
    df: pd.DataFrame,
    output_path: str | Path,
    show_error: bool = True,
) -> Path:
    """Plot mean task instance ratio vs CCR for each scheduler."""
    return plot_metric_vs_ccr(
        df, "task_instance_ratio", output_path,
        title="Task Instance Ratio vs CCR", ylabel="Task Instance Ratio",
        show_error=show_error,
    )


def plot_communication_count_vs_ccr(
    df: pd.DataFrame,
    output_path: str | Path,
    show_error: bool = True,
) -> Path:
    """Plot mean communication instance count vs CCR for each scheduler."""
    return plot_metric_vs_ccr(
        df, "communication_count", output_path,
        title="Communication Count vs CCR", ylabel="Communication Count",
        show_error=show_error,
    )


def plot_link_utilization_vs_ccr(
    df: pd.DataFrame,
    output_path: str | Path,
    show_error: bool = True,
) -> Path:
    """Plot mean maximum link utilization vs CCR for each scheduler."""
    return plot_metric_vs_ccr(
        df, "max_link_utilization", output_path,
        title="Max Link Utilization vs CCR", ylabel="Max Link Utilization",
        show_error=show_error,
    )


# ---------------------------------------------------------------------------
# Runtime vs task count
# ---------------------------------------------------------------------------

def plot_runtime_vs_task_count(
    df: pd.DataFrame,
    output_path: str | Path,
    scheduler_order: list[str] | None = None,
    log_y: bool = True,
) -> Path:
    """
    Plot mean scheduler runtime (ms) vs number of tasks.

    Args:
        df:              Results DataFrame.
        output_path:     Destination PNG path.
        scheduler_order: Draw order for schedulers.
        log_y:           Prefer log scale on the y-axis (default True).
                         Falls back to linear if any aggregated mean is <= 0.

    Returns:
        Path to the saved PNG file.
    """
    if scheduler_order is None:
        scheduler_order = _DEFAULT_SCHEDULER_ORDER

    agg = aggregate_results(df, "runtime_ms", ["scheduler", "n_tasks"])

    fig, ax = plt.subplots(figsize=(7, 4))

    for sched in scheduler_order:
        sub = agg[agg["scheduler"] == sched].sort_values("n_tasks")
        if sub.empty:
            continue
        label = _SCHEDULER_LABELS.get(sched, sched)
        color = _SCHEDULER_COLORS.get(sched)
        marker = _SCHEDULER_MARKERS.get(sched, "o")
        ax.plot(
            sub["n_tasks"].values,
            sub["runtime_ms_mean"].values,
            label=label,
            color=color,
            marker=marker,
            linewidth=1.5,
            markersize=6,
        )

    if log_y and (agg["runtime_ms_mean"] > 0).all():
        ax.set_yscale("log")
    ax.set_xlabel("Number of Tasks")
    ax.set_ylabel("Runtime (ms)")
    ax.set_title("Scheduler Runtime vs Task Count")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    plt.tight_layout()

    return _save_figure(fig, Path(output_path))


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------

def generate_all_plots(
    csv_path: str | Path,
    output_dir: str | Path,
) -> list[Path]:
    """
    Load a results CSV and generate all six standard plots.

    Generates:
        makespan_vs_ccr.png
        speedup_vs_ccr.png
        task_instance_ratio_vs_ccr.png
        communication_count_vs_ccr.png
        max_link_utilization_vs_ccr.png
        runtime_vs_task_count.png

    Returns:
        List of Paths to the generated PNG files.
    """
    df = load_results(csv_path)
    out = Path(output_dir)
    return [
        plot_makespan_vs_ccr(df, out / "makespan_vs_ccr.png"),
        plot_speedup_vs_ccr(df, out / "speedup_vs_ccr.png"),
        plot_task_instance_ratio_vs_ccr(df, out / "task_instance_ratio_vs_ccr.png"),
        plot_communication_count_vs_ccr(df, out / "communication_count_vs_ccr.png"),
        plot_link_utilization_vs_ccr(df, out / "max_link_utilization_vs_ccr.png"),
        plot_runtime_vs_task_count(df, out / "runtime_vs_task_count.png"),
    ]


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def print_summary_table(
    df: pd.DataFrame,
    group_by: list[str] | None = None,
) -> pd.DataFrame:
    """
    Return a compact summary DataFrame with mean values of key metrics.

    Default group_by: ["scheduler"].

    The returned DataFrame is not printed automatically; callers decide how
    to display it (e.g. via .to_string() or to_markdown()).

    Raises:
        ValueError: if any group_by column is missing from df.
    """
    if group_by is None:
        group_by = ["scheduler"]
    missing_cols = [c for c in group_by if c not in df.columns]
    if missing_cols:
        raise ValueError(
            f"group_by columns not found in DataFrame: {missing_cols}"
        )
    available = [m for m in _SUMMARY_METRICS if m in df.columns]
    return df.groupby(group_by)[available].mean().reset_index()


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m src.plots",
        description="Generate Phase 10 analysis plots from an experiment results CSV.",
    )
    parser.add_argument("--csv", required=True, help="Path to results CSV file")
    parser.add_argument("--out", required=True, help="Output directory for PNG files")
    args = parser.parse_args()

    paths = generate_all_plots(args.csv, args.out)
    print("Generated plots:")
    for p in paths:
        print(f"  {p}")

    df = load_results(args.csv)
    summary = print_summary_table(df)
    print()
    print("Summary table (mean values per scheduler):")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    _cli()
