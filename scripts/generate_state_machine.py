# -*- coding: utf-8 -*-
"""Generate a clean CA-D state machine diagram (PNG + SVG)."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.patheffects as pe
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "results" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Colours ────────────────────────────────────────────────────────────────
NAVY     = "#0B2E4F"
BURGUNDY = "#8B1A2B"
WHITE    = "#FFFFFF"
LGREY    = "#F0F0F0"
DGREY    = "#333333"
MGREY    = "#888888"
GREEN    = "#1A6B1A"
BGGREEN  = "#D6F0D6"

# ── Layout constants ────────────────────────────────────────────────────────
FIG_W, FIG_H = 7.5, 14
NODE_W, NODE_H = 4.2, 0.72
DIAMOND_W, DIAMOND_H = 3.0, 0.80
X_CENTER = FIG_W / 2

# vertical positions (top of each node, in figure coords 0-FIG_H)
# we'll work in axes-data coordinates with figsize-matched axes
NODES = [
    # (id,           label_line1,                      label_line2,                     y,     kind)
    ("init",    "INIT",                           "ScheduleState oluştur",           13.2,  "navy"),
    ("rank",    "RANK",                           "Upward rank hesapla",             11.9,  "navy"),
    ("select",  "SELECT",                         "En yüksek öncelikli hazır task",  10.6,  "navy"),
    ("explore", "EXPLORE",                        "state.clone() × 16 işlemci",      9.3,  "burgundy"),
    ("dup",     "DUPLICATE",                      "ΔEFT hesapla + recursive ata dup",7.85, "burgundy"),
    ("commit",  "COMMIT",                         "En iyi candidate'ı promote et",   6.55,  "navy"),
    ("check",   "Tüm tasklar\nzamanlandı mı?",   "",                                5.25,  "diamond"),
    ("prune",   "PRUNE",                          "Gereksiz kopyaları temizle",       3.7,  "green"),
    ("done",    "DONE",                           "Final schedule döndür",            2.4,  "navy"),
]

ARROWS = [
    # (from_id, to_id, label,   side)
    ("init",    "rank",    "",        "center"),
    ("rank",    "select",  "",        "center"),
    ("select",  "explore", "",        "center"),
    ("explore", "dup",     "",        "center"),
    ("dup",     "commit",  "",        "center"),
    ("commit",  "check",   "",        "center"),
    ("check",   "prune",   "Evet",    "center"),
    ("prune",   "done",    "",        "center"),
    # loop back
    ("check",   "select",  "Hayır",   "loop"),
]


def node_center(n):
    return (X_CENTER, n[3] - NODE_H / 2)


def node_top(n):
    return (X_CENTER, n[3])


def node_bottom(n):
    return (X_CENTER, n[3] - NODE_H)


def draw_rounded_rect(ax, cx, cy, w, h, fc, ec, lw=1.5, radius=0.18):
    x = cx - w / 2
    y = cy - h / 2
    bp = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=fc, edgecolor=ec, linewidth=lw, zorder=3
    )
    ax.add_patch(bp)


def draw_diamond(ax, cx, cy, w, h, fc, ec, lw=1.5):
    dx, dy = w / 2, h / 2
    pts = [(cx, cy + dy), (cx + dx, cy), (cx, cy - dy), (cx - dx, cy)]
    diamond = plt.Polygon(pts, facecolor=fc, edgecolor=ec,
                          linewidth=lw, zorder=3)
    ax.add_patch(diamond)


def draw_arrow(ax, x1, y1, x2, y2, color=DGREY, lw=1.8):
    ax.annotate(
        "", xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(
            arrowstyle="-|>",
            color=color,
            lw=lw,
            mutation_scale=14,
        ),
        zorder=2,
    )


def main():
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    ax.set_xlim(0, FIG_W)
    ax.set_ylim(0, FIG_H)
    ax.axis("off")
    fig.patch.set_facecolor(WHITE)

    # title
    ax.text(
        X_CENTER, FIG_H - 0.35,
        "CA-D Scheduler — State Machine",
        ha="center", va="center",
        fontsize=13, fontweight="bold", color=NAVY,
    )

    node_map = {n[0]: n for n in NODES}

    # ── Draw nodes ─────────────────────────────────────────────────────────
    for nid, l1, l2, y, kind in NODES:
        cx = X_CENTER
        cy = y - NODE_H / 2

        if kind == "diamond":
            draw_diamond(ax, cx, cy, DIAMOND_W, DIAMOND_H,
                         fc="#FFF8E7", ec=BURGUNDY, lw=2.0)
            ax.text(cx, cy, l1, ha="center", va="center",
                    fontsize=9, fontweight="bold", color=BURGUNDY, zorder=4)
            continue

        # colour scheme
        if kind == "navy":
            fc, ec, tc = NAVY, NAVY, WHITE
        elif kind == "burgundy":
            fc, ec, tc = BURGUNDY, BURGUNDY, WHITE
        elif kind == "green":
            fc, ec, tc = BGGREEN, GREEN, GREEN

        draw_rounded_rect(ax, cx, cy, NODE_W, NODE_H, fc=fc, ec=ec, lw=2.0)

        # label
        ax.text(cx, cy + 0.12, l1, ha="center", va="center",
                fontsize=10.5, fontweight="bold", color=tc, zorder=4)
        if l2:
            ax.text(cx, cy - 0.17, l2, ha="center", va="center",
                    fontsize=7.8, color=tc, alpha=0.88, zorder=4)

    # ── Draw arrows ─────────────────────────────────────────────────────────
    for fid, tid, label, side in ARROWS:
        fn = node_map[fid]
        tn = node_map[tid]

        if side == "center":
            x1, y1 = X_CENTER, fn[3] - NODE_H          # bottom of from
            x2, y2 = X_CENTER, tn[3]                    # top of to
            # for diamond: adjust
            if fn[4] == "diamond":
                y1 = fn[3] - NODE_H / 2 - DIAMOND_H / 2
            if tn[4] == "diamond":
                y2 = tn[3] - NODE_H / 2 + DIAMOND_H / 2

            draw_arrow(ax, x1, y1, x2, y2)

            if label:
                ax.text(x1 + 0.25, (y1 + y2) / 2, label,
                        ha="left", va="center",
                        fontsize=8.5, color=GREEN, fontweight="bold")

        elif side == "loop":
            # Hayır: go right from diamond, up, left back to SELECT
            check = node_map["check"]
            sel   = node_map["select"]

            cx_d = X_CENTER + DIAMOND_W / 2   # right tip of diamond
            cy_d = check[3] - NODE_H / 2      # diamond center y

            # right elbow x
            rx = X_CENTER + NODE_W / 2 + 0.65

            sel_cy = sel[3] - NODE_H / 2      # select center y
            sel_rx = X_CENTER + NODE_W / 2    # right edge of SELECT

            pts = [
                (cx_d,  cy_d),
                (rx,    cy_d),
                (rx,    sel_cy),
                (sel_rx, sel_cy),
            ]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            ax.plot(xs, ys, color=MGREY, lw=1.8, zorder=2, solid_capstyle="round")
            # arrowhead
            ax.annotate(
                "", xy=(sel_rx, sel_cy),
                xytext=(sel_rx + 0.01, sel_cy),
                arrowprops=dict(arrowstyle="-|>", color=MGREY, lw=1.8,
                                mutation_scale=13),
                zorder=2,
            )
            # label
            ax.text(cx_d + 0.12, cy_d + 0.18, label,
                    ha="left", va="bottom",
                    fontsize=8.5, color=BURGUNDY, fontweight="bold")

    # ── Legend ──────────────────────────────────────────────────────────────
    legend_y = 1.45
    legend_x = 0.55
    items = [
        (NAVY,    WHITE, "List scheduling adımı"),
        (BURGUNDY, WHITE, "Contention-aware işlem"),
        (BGGREEN,  GREEN, "Post-schedule temizlik"),
        ("#FFF8E7", BURGUNDY, "Karar noktası"),
    ]
    for i, (fc, tc, desc) in enumerate(items):
        lx = legend_x
        ly = legend_y - i * 0.38
        draw_rounded_rect(ax, lx + 0.2, ly, 0.38, 0.26,
                          fc=fc, ec=BURGUNDY if tc == GREEN else fc,
                          lw=1.2, radius=0.06)
        ax.text(lx + 0.46, ly, desc,
                ha="left", va="center", fontsize=7.8, color=DGREY)

    ax.text(legend_x + 0.2, legend_y + 0.42, "Açıklama",
            ha="center", va="center", fontsize=8.5,
            fontweight="bold", color=DGREY)

    # ── Side annotations ────────────────────────────────────────────────────
    annots = [
        (5.15, 9.3 - NODE_H / 2, "state.clone()\nher işlemci için\nkorumalı dal"),
        (5.15, 7.85 - NODE_H / 2, "ΔEFT = EFT_no_dup\n       − EFT_dup > ε"),
        (5.15, 3.7 - NODE_H / 2,  "4 koşul sağlanırsa\nkopya silinir"),
    ]
    for ax_x, ay, txt in annots:
        ax.text(ax_x + 0.08, ay, txt,
                ha="left", va="center",
                fontsize=7.2, color=MGREY,
                style="italic",
                bbox=dict(boxstyle="round,pad=0.3", fc=LGREY,
                          ec=MGREY, alpha=0.8, lw=0.8))
        ax.annotate(
            "", xy=(X_CENTER + NODE_W / 2, ay),
            xytext=(ax_x + 0.07, ay),
            arrowprops=dict(arrowstyle="-", color=MGREY,
                            lw=0.8, linestyle="dashed"),
            zorder=1,
        )

    plt.tight_layout(pad=0.4)

    png_path = OUT_DIR / "cad_state_machine.png"
    svg_path = OUT_DIR / "cad_state_machine.svg"
    fig.savefig(str(png_path), dpi=180, bbox_inches="tight",
                facecolor=WHITE)
    fig.savefig(str(svg_path), format="svg", bbox_inches="tight",
                facecolor=WHITE)
    plt.close(fig)

    print(f"PNG: {png_path}")
    print(f"SVG: {svg_path}")
    print("Open: open", png_path)


if __name__ == "__main__":
    main()
