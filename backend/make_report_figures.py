"""Generate the draft-report figures from the live pipeline reports.

Outputs three PNGs into ../report_media/:
  fig_pipeline.png    - pipeline architecture flow (Implementation)
  fig_coverage.png    - field coverage by encoding style (Evaluation)
  fig_ml.png          - ML feature importances + accuracy (Evaluation)
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as patches

from db import dataDir

outDir = Path(__file__).resolve().parent.parent / "report_media"
outDir.mkdir(exist_ok=True)


def makePipelineFigure() -> None:
    fig, ax = plt.subplots(figsize=(10, 2.6))
    ax.axis("off")
    boxes = [
        ("MEI XML sources\n.xml / .mei\nMEI 2013-5.1\nbatch or upload", "#dbeafe"),
        ("Import\nfallback XPath,\nstyle + version\ndetection, warnings", "#dcfce7"),
        ("SQLite\n7 tables,\nforeign keys,\nindexes", "#fef9c3"),
        ("Flask REST API\n10 endpoints\n+ dashboard", "#fae8ff"),
        ("Export\ncatalogue-style\nMEI 5.1", "#ffe4e6"),
    ]
    x = 0.01
    width = 0.17
    for label, color in boxes:
        ax.add_patch(patches.FancyBboxPatch(
            (x, 0.2), width, 0.6, boxstyle="round,pad=0.012",
            facecolor=color, edgecolor="#334155", linewidth=1.2,
        ))
        ax.text(x + width / 2, 0.5, label, ha="center", va="center", fontsize=8.5)
        if x + width < 0.95:
            ax.annotate("", xy=(x + width + 0.035, 0.5), xytext=(x + width + 0.005, 0.5),
                        arrowprops=dict(arrowstyle="->", color="#334155", lw=1.4))
        x = x + width + 0.038
    # Validation loop arrow underneath
    with open(dataDir / "validation_report.json", encoding="utf-8") as handle:
        validation = json.load(handle)
    checkCount = f"{validation['total_checks']:,}"
    ax.annotate("", xy=(0.095, 0.16), xytext=(0.44, 0.16),
                arrowprops=dict(arrowstyle="->", color="#b91c1c", lw=1.3, linestyle="--"))
    ax.text(0.27, 0.05, f"validate_mei.py: {checkCount} checks compare stored fields with source XML",
            ha="center", fontsize=8, color="#b91c1c")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.savefig(outDir / "fig_pipeline.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def makeCoverageFigure() -> None:
    with open(dataDir / "import_report.json", encoding="utf-8") as handle:
        report = json.load(handle)
    fields = ["title", "year_composed", "subtitle", "genre", "key_signature", "catalogue_number", "dedication"]
    styles = [("catalogue", "#2563eb"), ("notation", "#16a34a"), ("hybrid", "#d97706")]
    fig, ax = plt.subplots(figsize=(9, 4))
    barWidth = 0.26
    for offset, (style, color) in enumerate(styles):
        coverage = report["field_coverage_by_style"][style]
        values = [coverage[f]["percent"] for f in fields]
        positions = [i + (offset - 1) * barWidth for i in range(len(fields))]
        ax.bar(positions, values, barWidth, label=f"{style} (n={coverage[fields[0]]['total']})", color=color)
    ax.set_xticks(range(len(fields)))
    ax.set_xticklabels(fields, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("Coverage (%)")
    ax.set_ylim(0, 105)
    ax.legend(fontsize=9)
    totalFiles = sum(report["field_coverage_by_style"][style][fields[0]]["total"] for style, _ in styles)
    ax.set_title(f"Field coverage by detected encoding style ({totalFiles} files)", fontsize=11)
    ax.grid(axis="y", alpha=0.3)
    fig.savefig(outDir / "fig_coverage.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def makeMlFigure() -> None:
    with open(dataDir / "ml_style_report.json", encoding="utf-8") as handle:
        report = json.load(handle)
    top = report["feature_importances"][:10][::-1]
    names = [x["element"] for x in top]
    values = [x["importance"] for x in top]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), gridspec_kw={"width_ratios": [3, 2]})
    axes[0].barh(names, values, color="#2563eb")
    axes[0].set_title("Random forest feature importances (top 10)", fontsize=10)
    axes[0].set_xlabel("Importance")
    axes[0].grid(axis="x", alpha=0.3)

    models = report["models"]
    labels = ["Random\nforest", "Logistic\nregression"]
    accs = [models["random_forest"]["cv_accuracy"] * 100, models["logistic_regression"]["cv_accuracy"] * 100]
    bars = axes[1].bar(labels, accs, color=["#16a34a", "#94a3b8"], width=0.55)
    for bar, acc in zip(bars, accs):
        axes[1].text(bar.get_x() + bar.get_width() / 2, acc + 1, f"{acc:.1f}%", ha="center", fontsize=10)
    axes[1].set_ylim(0, 108)
    axes[1].set_ylabel("5-fold CV accuracy (%)")
    axes[1].set_title("Style classification accuracy", fontsize=10)
    axes[1].grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(outDir / "fig_ml.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    makePipelineFigure()
    makeCoverageFigure()
    makeMlFigure()
    print(f"Figures written to {outDir}")
