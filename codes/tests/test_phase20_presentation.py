"""
Phase 20 — Lightweight quality checks for the presentation figure dataset.

Tests:
  1. CSV exists and is non-empty.
  2. All expected DAG families are present.
  3. All expected schedulers are present.
  4. All expected CCR values are present.
  5. TIR >= 1.0 for all rows.
  6. HEFT replayed speedup vs HEFT == 1.0 (within tolerance).
  7. replay_overhead_ratio is finite and positive.
  8. Figures exist as both PNG and PDF.
  9. native_makespan and replayed_makespan are positive.
  10. duplicate_instance_count >= 0; == 0 for HEFT.
"""

import math
from pathlib import Path

import pytest
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "results" / "summary" / "phase20_presentation_single_run.csv"
FIG_DIR  = ROOT / "results" / "figures" / "phase20_presentation"

EXPECTED_DAG_FAMILIES = {"chain", "fork", "out_tree", "fork_join"}
EXPECTED_SCHEDULERS   = {"heft", "cdls", "cad"}
EXPECTED_CCR          = {0.1, 1.0, 5.0, 10.0}
EXPECTED_FIGURES      = [
    "fig1_scheduler_concept",
    "fig2_native_vs_replay",
    "fig3_ccr_sweep_speedup",
    "fig4_out_tree_gantt",
    "fig5_replay_overhead",
    "fig6_task_instance_ratio",
    "fig7_speedup_vs_tir",
]


# ---------------------------------------------------------------------------
# Fixture: load CSV once per session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def df():
    assert CSV_PATH.exists(), f"CSV not found: {CSV_PATH}"
    return pd.read_csv(CSV_PATH)


# ---------------------------------------------------------------------------
# 1. CSV exists and is non-empty
# ---------------------------------------------------------------------------

def test_csv_exists():
    assert CSV_PATH.exists(), f"CSV not found: {CSV_PATH}"


def test_csv_non_empty(df):
    assert len(df) > 0, "CSV is empty"


# ---------------------------------------------------------------------------
# 2. All expected DAG families present
# ---------------------------------------------------------------------------

def test_all_dag_families(df):
    found = set(df["dag_family"].unique())
    missing = EXPECTED_DAG_FAMILIES - found
    assert not missing, f"Missing DAG families: {missing}"


# ---------------------------------------------------------------------------
# 3. All expected schedulers present
# ---------------------------------------------------------------------------

def test_all_schedulers(df):
    found = set(df["scheduler"].unique())
    missing = EXPECTED_SCHEDULERS - found
    assert not missing, f"Missing schedulers: {missing}"


# ---------------------------------------------------------------------------
# 4. All expected CCR values present
# ---------------------------------------------------------------------------

def test_all_ccr_values(df):
    found = set(df["ccr"].unique())
    for ccr in EXPECTED_CCR:
        assert any(abs(c - ccr) < 1e-9 for c in found), f"CCR={ccr} not found"


# ---------------------------------------------------------------------------
# 5. TIR >= 1.0 for all rows
# ---------------------------------------------------------------------------

def test_tir_geq_one(df):
    violations = df[df["task_instance_ratio"] < 1.0 - 1e-9]
    assert len(violations) == 0, (
        f"{len(violations)} rows have TIR < 1.0:\n{violations[['dag_family','ccr','scheduler','task_instance_ratio']]}"
    )


# ---------------------------------------------------------------------------
# 6. HEFT speedup vs HEFT == 1.0
# ---------------------------------------------------------------------------

def test_heft_speedup_is_one(df):
    heft_rows = df[df["scheduler"] == "heft"]
    bad = heft_rows[abs(heft_rows["speedup_vs_heft_replayed"] - 1.0) > 1e-6]
    assert len(bad) == 0, (
        f"HEFT speedup vs HEFT != 1.0 for {len(bad)} rows:\n"
        f"{bad[['dag_family','ccr','speedup_vs_heft_replayed']]}"
    )


# ---------------------------------------------------------------------------
# 7. replay_overhead_ratio is finite and positive
# ---------------------------------------------------------------------------

def test_replay_overhead_finite_positive(df):
    for _, row in df.iterrows():
        val = row["replay_overhead_ratio"]
        assert math.isfinite(val), (
            f"Non-finite replay_overhead_ratio={val} at "
            f"{row['dag_family']} CCR={row['ccr']} {row['scheduler']}"
        )
        assert val > 0, (
            f"Non-positive replay_overhead_ratio={val} at "
            f"{row['dag_family']} CCR={row['ccr']} {row['scheduler']}"
        )


# ---------------------------------------------------------------------------
# 8. Figures exist as both PNG and PDF
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stem", EXPECTED_FIGURES)
def test_figure_png_exists(stem):
    path = FIG_DIR / f"{stem}.png"
    assert path.exists(), f"PNG not found: {path}"


@pytest.mark.parametrize("stem", EXPECTED_FIGURES)
def test_figure_pdf_exists(stem):
    path = FIG_DIR / f"{stem}.pdf"
    assert path.exists(), f"PDF not found: {path}"


def test_markdown_summary_exists():
    path = FIG_DIR / "phase20_presentation_summary.md"
    assert path.exists(), f"Markdown summary not found: {path}"
    assert path.stat().st_size > 500, "Markdown summary is suspiciously small"


# ---------------------------------------------------------------------------
# 9. native_makespan and replayed_makespan are positive
# ---------------------------------------------------------------------------

def test_makespans_positive(df):
    for col in ["native_makespan", "replayed_makespan"]:
        bad = df[df[col] <= 0]
        assert len(bad) == 0, f"{len(bad)} rows have non-positive {col}"


# ---------------------------------------------------------------------------
# 10. duplicate_instance_count >= 0; == 0 for HEFT
# ---------------------------------------------------------------------------

def test_duplicate_count_nonneg(df):
    bad = df[df["duplicate_instance_count"] < 0]
    assert len(bad) == 0, f"{len(bad)} rows have negative duplicate_instance_count"


def test_heft_has_no_duplicates(df):
    heft = df[df["scheduler"] == "heft"]
    bad = heft[heft["duplicate_instance_count"] != 0]
    assert len(bad) == 0, (
        f"HEFT has non-zero duplicates in {len(bad)} rows:\n"
        f"{bad[['dag_family','ccr','duplicate_instance_count']]}"
    )


# ---------------------------------------------------------------------------
# 11. Structural assertions: speedup > 1.0 where expected
# ---------------------------------------------------------------------------

def test_fork_ccr5_cdls_speedup_above_one(df):
    """Fork at CCR=5.0: CD-LS should outperform HEFT after replay."""
    row = df[(df["dag_family"] == "fork") &
             (df["scheduler"] == "cdls") &
             (abs(df["ccr"] - 5.0) < 1e-9)]
    assert len(row) == 1
    assert row["speedup_vs_heft_replayed"].values[0] > 1.0, \
        "CD-LS should beat HEFT on fork at CCR=5.0"


def test_cad_better_than_cdls_on_out_tree_ccr5(df):
    """Out-tree CCR=5.0: CA-D should outperform CD-LS."""
    cad  = df[(df["dag_family"] == "out_tree") & (df["scheduler"] == "cad")  & (abs(df["ccr"] - 5.0) < 1e-9)]
    cdls = df[(df["dag_family"] == "out_tree") & (df["scheduler"] == "cdls") & (abs(df["ccr"] - 5.0) < 1e-9)]
    assert cad["speedup_vs_heft_replayed"].values[0] > cdls["speedup_vs_heft_replayed"].values[0], \
        "CA-D should outperform CD-LS on out-tree at CCR=5.0"


def test_cad_overhead_one_on_fork_join(df):
    """CA-D replay overhead should be 1.0 on fork-join (contention-aware model is accurate)."""
    rows = df[(df["dag_family"] == "fork_join") & (df["scheduler"] == "cad")]
    for _, row in rows.iterrows():
        assert abs(row["replay_overhead_ratio"] - 1.0) < 1e-4, (
            f"CA-D fork-join overhead = {row['replay_overhead_ratio']:.4f} at CCR={row['ccr']} "
            f"(expected ~1.0)"
        )


def test_chain_all_schedulers_equal(df):
    """Chain: all schedulers should produce equal native makespan."""
    for ccr in CCR_VALUES:
        sub = df[(df["dag_family"] == "chain") & (abs(df["ccr"] - ccr) < 1e-9)]
        native_vals = sub["native_makespan"].values
        if len(native_vals) > 1:
            assert max(native_vals) - min(native_vals) < 1e-6, \
                f"Chain CCR={ccr}: schedulers differ in native makespan: {native_vals}"


# Use module-level variable for parametrize
CCR_VALUES = [0.1, 1.0, 5.0, 10.0]
