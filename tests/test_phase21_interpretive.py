"""
Phase 21 -- Lightweight quality checks for the interpretive figure dataset.

Tests:
  1.  CSV exists and is non-empty.
  2.  All expected DAG families are present.
  3.  All expected schedulers are present.
  4.  All expected CCR values are present.
  5.  Row count == 48  (4 DAG x 4 CCR x 3 schedulers).
  6.  TIR >= 1.0 for all rows.
  7.  HEFT speedup vs HEFT == 1.0 (within tolerance).
  8.  replay_overhead_ratio is finite and positive.
  9.  remote_communication_volume_ratio in [0.0, 1.0] for all rows.
  10. remote_vol <= total_vol for all rows.
  11. native_makespan and replayed_makespan are positive.
  12. HEFT has no duplicate instances.
  13. All PNG and PDF figures exist and are non-empty.
  14. Markdown summary exists and is non-trivial.
"""

import math
from pathlib import Path

import pytest
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "results" / "summary" / "phase21_interpretive_single_run.csv"
FIG_DIR  = ROOT / "results" / "figures" / "phase21_interpretive"
SUMMARY_PATH = ROOT / "results" / "summary" / "phase21_interpretive_summary.md"

EXPECTED_DAG_FAMILIES = {"chain", "fork", "out_tree", "fork_join"}
EXPECTED_SCHEDULERS   = {"heft", "cdls", "cad"}
EXPECTED_CCR          = {0.1, 1.0, 5.0, 10.0}

EXPECTED_FIGURES = [
    "fig1_dag_family_topologies",
    "fig2_scheduler_concept",
    "fig3_native_vs_replay",
    "fig4a_fork_gantt",
    "fig4b_out_tree_gantt",
    "fig4c_fork_join_gantt",
    "fig5_ccr_sweep_replayed_speedup",
    "fig6_replay_overhead_ratio",
    "fig7_task_instance_ratio",
    "fig8_remote_comm_volume_ratio",
]

CCR_VALUES = [0.1, 1.0, 5.0, 10.0]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def df():
    assert CSV_PATH.exists(), f"CSV not found: {CSV_PATH}"
    return pd.read_csv(CSV_PATH)


# ---------------------------------------------------------------------------
# 1. CSV exists
# ---------------------------------------------------------------------------

def test_csv_exists():
    assert CSV_PATH.exists(), f"CSV not found: {CSV_PATH}"


# ---------------------------------------------------------------------------
# 2. Non-empty
# ---------------------------------------------------------------------------

def test_csv_non_empty(df):
    assert len(df) > 0, "CSV is empty"


# ---------------------------------------------------------------------------
# 3. Expected DAG families
# ---------------------------------------------------------------------------

def test_all_dag_families(df):
    found = set(df["dag_family"].unique())
    missing = EXPECTED_DAG_FAMILIES - found
    assert not missing, f"Missing DAG families: {missing}"


# ---------------------------------------------------------------------------
# 4. Expected schedulers
# ---------------------------------------------------------------------------

def test_all_schedulers(df):
    found = set(df["scheduler"].unique())
    missing = EXPECTED_SCHEDULERS - found
    assert not missing, f"Missing schedulers: {missing}"


# ---------------------------------------------------------------------------
# 5. Expected CCR values
# ---------------------------------------------------------------------------

def test_all_ccr_values(df):
    found = set(df["ccr"].unique())
    for ccr in EXPECTED_CCR:
        assert any(abs(c - ccr) < 1e-9 for c in found), f"CCR={ccr} not found"


# ---------------------------------------------------------------------------
# 6. Row count
# ---------------------------------------------------------------------------

def test_row_count(df):
    assert len(df) == 48, (
        f"Expected 48 rows (4 DAG x 4 CCR x 3 schedulers), got {len(df)}"
    )


# ---------------------------------------------------------------------------
# 7. TIR >= 1.0
# ---------------------------------------------------------------------------

def test_tir_geq_one(df):
    bad = df[df["task_instance_ratio"] < 1.0 - 1e-9]
    assert len(bad) == 0, (
        f"{len(bad)} rows have TIR < 1.0:\n"
        f"{bad[['dag_family', 'ccr', 'scheduler', 'task_instance_ratio']]}"
    )


# ---------------------------------------------------------------------------
# 8. HEFT speedup == 1.0
# ---------------------------------------------------------------------------

def test_heft_speedup_is_one(df):
    heft = df[df["scheduler"] == "heft"]
    bad = heft[abs(heft["speedup_vs_heft_replayed"] - 1.0) > 1e-6]
    assert len(bad) == 0, (
        f"HEFT speedup != 1.0 for {len(bad)} rows:\n"
        f"{bad[['dag_family', 'ccr', 'speedup_vs_heft_replayed']]}"
    )


# ---------------------------------------------------------------------------
# 9. replay_overhead_ratio finite and positive
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
# 10. RCVR in [0.0, 1.0]
# ---------------------------------------------------------------------------

def test_rcvr_in_range(df):
    for _, row in df.iterrows():
        val = row["remote_communication_volume_ratio"]
        assert math.isfinite(val), (
            f"Non-finite RCVR at {row['dag_family']} CCR={row['ccr']} {row['scheduler']}"
        )
        assert -1e-9 <= val <= 1.0 + 1e-9, (
            f"RCVR={val:.6f} out of [0,1] at "
            f"{row['dag_family']} CCR={row['ccr']} {row['scheduler']}"
        )


# ---------------------------------------------------------------------------
# 11. remote_vol <= total_vol
# ---------------------------------------------------------------------------

def test_remote_vol_leq_total(df):
    bad = df[
        df["remote_communication_volume"] > df["total_communication_volume"] + 1e-6
    ]
    assert len(bad) == 0, (
        f"{len(bad)} rows have remote_vol > total_vol:\n"
        f"{bad[['dag_family', 'ccr', 'scheduler', 'remote_communication_volume', 'total_communication_volume']]}"
    )


# ---------------------------------------------------------------------------
# 12. Makespans positive
# ---------------------------------------------------------------------------

def test_makespans_positive(df):
    for col in ["native_makespan", "replayed_makespan"]:
        bad = df[df[col] <= 0]
        assert len(bad) == 0, f"{len(bad)} rows have non-positive {col}"


# ---------------------------------------------------------------------------
# 13. HEFT has no duplicates
# ---------------------------------------------------------------------------

def test_heft_no_duplicates(df):
    heft = df[df["scheduler"] == "heft"]
    bad = heft[heft["duplicate_instance_count"] != 0]
    assert len(bad) == 0, (
        f"HEFT has non-zero duplicates in {len(bad)} rows:\n"
        f"{bad[['dag_family', 'ccr', 'duplicate_instance_count']]}"
    )


# ---------------------------------------------------------------------------
# 14. PNG and PDF figures exist and are non-empty
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stem", EXPECTED_FIGURES)
def test_figure_png_exists(stem):
    p = FIG_DIR / f"{stem}.png"
    assert p.exists(), f"PNG not found: {p}"
    assert p.stat().st_size > 1000, f"PNG suspiciously small: {p}"


@pytest.mark.parametrize("stem", EXPECTED_FIGURES)
def test_figure_pdf_exists(stem):
    p = FIG_DIR / f"{stem}.pdf"
    assert p.exists(), f"PDF not found: {p}"
    assert p.stat().st_size > 1000, f"PDF suspiciously small: {p}"


# ---------------------------------------------------------------------------
# 15. Markdown summary exists and non-trivial
# ---------------------------------------------------------------------------

def test_markdown_summary_exists():
    assert SUMMARY_PATH.exists(), f"Summary not found: {SUMMARY_PATH}"
    assert SUMMARY_PATH.stat().st_size > 500, "Summary is suspiciously small"


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------

def test_chain_all_schedulers_equal_tir(df):
    """Chain: all schedulers have TIR=1.0 (no net duplication on a linear chain)."""
    chain = df[df["dag_family"] == "chain"]
    bad = chain[abs(chain["task_instance_ratio"] - 1.0) > 1e-6]
    assert len(bad) == 0, (
        f"Chain has TIR != 1.0 for {len(bad)} rows:\n"
        f"{bad[['ccr', 'scheduler', 'task_instance_ratio']]}"
    )


def test_chain_all_schedulers_equal_makespans(df):
    """Chain: all schedulers produce equal native makespan at each CCR."""
    for ccr in CCR_VALUES:
        sub = df[(df["dag_family"] == "chain") & (abs(df["ccr"] - ccr) < 1e-9)]
        vals = sub["native_makespan"].values
        if len(vals) > 1:
            assert max(vals) - min(vals) < 1e-4, (
                f"Chain CCR={ccr}: schedulers differ in native makespan: {vals}"
            )


def test_heft_chain_rcvr_equals_cdls(df):
    """Chain RCVR should be identical for HEFT and CD-LS (neither places dups on chain)."""
    for ccr in CCR_VALUES:
        h = df[(df["dag_family"] == "chain") & (df["scheduler"] == "heft") &
               (abs(df["ccr"] - ccr) < 1e-9)]["remote_communication_volume_ratio"]
        c = df[(df["dag_family"] == "chain") & (df["scheduler"] == "cdls") &
               (abs(df["ccr"] - ccr) < 1e-9)]["remote_communication_volume_ratio"]
        if not h.empty and not c.empty:
            assert abs(h.values[0] - c.values[0]) < 1e-6, (
                f"Chain CCR={ccr}: HEFT RCVR={h.values[0]:.4f} != CD-LS RCVR={c.values[0]:.4f}"
            )


def test_fork_cdls_cad_equal_tir(df):
    """Fork: CD-LS and CA-D should have identical TIR (single-level topology)."""
    for ccr in CCR_VALUES:
        cdls_row = df[(df["dag_family"] == "fork") & (df["scheduler"] == "cdls") &
                      (abs(df["ccr"] - ccr) < 1e-9)]
        cad_row  = df[(df["dag_family"] == "fork") & (df["scheduler"] == "cad") &
                      (abs(df["ccr"] - ccr) < 1e-9)]
        if cdls_row.empty or cad_row.empty:
            continue
        assert abs(cdls_row["task_instance_ratio"].values[0] -
                   cad_row["task_instance_ratio"].values[0]) < 1e-6, (
            f"Fork CCR={ccr}: CD-LS TIR={cdls_row['task_instance_ratio'].values[0]:.4f} "
            f"!= CA-D TIR={cad_row['task_instance_ratio'].values[0]:.4f}"
        )


def test_out_tree_cad_speedup_geq_cdls(df):
    """Out-tree: CA-D replayed speedup >= CD-LS at each CCR."""
    for ccr in CCR_VALUES:
        cad  = df[(df["dag_family"] == "out_tree") & (df["scheduler"] == "cad") &
                  (abs(df["ccr"] - ccr) < 1e-9)]
        cdls = df[(df["dag_family"] == "out_tree") & (df["scheduler"] == "cdls") &
                  (abs(df["ccr"] - ccr) < 1e-9)]
        if cad.empty or cdls.empty:
            continue
        cad_spd  = cad["speedup_vs_heft_replayed"].values[0]
        cdls_spd = cdls["speedup_vs_heft_replayed"].values[0]
        assert cad_spd >= cdls_spd - 1e-4, (
            f"Out-tree CCR={ccr}: CA-D speedup={cad_spd:.4f} < CD-LS speedup={cdls_spd:.4f}"
        )


def test_duplicate_count_nonneg(df):
    bad = df[df["duplicate_instance_count"] < 0]
    assert len(bad) == 0, f"{len(bad)} rows have negative duplicate_instance_count"


def test_total_instances_consistent(df):
    """total_task_instances == original_task_count + duplicate_instance_count."""
    diff = (df["total_task_instances"] -
            df["original_task_count"] -
            df["duplicate_instance_count"])
    bad = df[abs(diff) > 0.5]
    assert len(bad) == 0, (
        f"{len(bad)} rows have inconsistent instance counts:\n"
        f"{bad[['dag_family', 'ccr', 'scheduler', 'original_task_count', 'total_task_instances', 'duplicate_instance_count']]}"
    )
