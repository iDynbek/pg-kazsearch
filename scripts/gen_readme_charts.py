#!/usr/bin/env python3
"""Generate README charts for pg_kazsearch benchmarks.

All numbers are read from eval/results/report.json (produced by
eval/run_eval.py) so the charts can never drift from actual measurements.
The head-to-head chart uses the same-sample comparison (fts_on_sample vs
trgm), which is the only apples-to-apples slice in the report.
"""

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)
REPORT = ROOT / "eval" / "results" / "report.json"


def load_report() -> dict:
    if not REPORT.exists():
        sys.exit(f"{REPORT} not found. Run `python3 eval/run_eval.py` first — "
                 "charts are generated from measured results only.")
    with REPORT.open("r", encoding="utf-8") as f:
        return json.load(f)


def chart_retrieval_quality(report: dict, k: str = "10"):
    fts = report["fts_on_sample"][k]
    trgm = report["trgm"][k]
    n = report.get("num_trgm_queries", report["num_queries"])

    metrics = [f"Recall@{k}", f"MRR@{k}", f"nDCG@{k}"]
    kazsearch = [fts["recall"], fts["mrr"], fts["ndcg"]]
    trgm_vals = [trgm["recall"], trgm["mrr"], trgm["ndcg"]]

    x = np.arange(len(metrics))
    w = 0.32

    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars1 = ax.bar(x - w/2, kazsearch, w, label="pg_kazsearch")
    bars2 = ax.bar(x + w/2, trgm_vals, w, label="pg_trgm")

    ax.bar_label(bars1, fmt="%.3f", padding=3, fontweight="bold")
    ax.bar_label(bars2, fmt="%.3f", padding=3)

    ax.set_ylabel("Score")
    ax.set_title(f"Retrieval Quality — {n} Queries (same sample for both)",
                 fontweight="bold", pad=12)
    ax.set_xticks(x)
    ax.set_xticklabels(metrics)
    ax.set_ylim(0, max(kazsearch + trgm_vals) * 1.18)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f"))
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(OUT / "retrieval_quality.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {OUT / 'retrieval_quality.png'}")


def chart_by_source(report: dict, k: str = "10"):
    by_source = report.get("fts_by_source")
    if not by_source:
        print("  (skipping by-source chart: report has no fts_by_source; rerun eval)")
        return

    sources = list(by_source.keys())
    recalls = [by_source[s]["metrics"][k]["recall"] for s in sources]
    counts = [by_source[s]["num_queries"] for s in sources]
    labels = [f"{s}\n(n={c})" for s, c in zip(sources, counts)]
    colors = ["#2ca02c" if s == "gold" else "#1f77b4" for s in sources]

    fig, ax = plt.subplots(figsize=(8, 4))
    bars = ax.bar(labels, recalls, color=colors, width=0.55)
    ax.bar_label(bars, fmt="%.3f", padding=3, fontweight="bold")

    ax.set_ylabel(f"Recall@{k}")
    ax.set_title("FTS Recall by Query Source — gold = human-written (honest), "
                 "others = corpus-derived (optimistic)", fontweight="bold", pad=12, fontsize=10)
    ax.set_ylim(0, max(recalls) * 1.2 if recalls else 1)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(OUT / "recall_by_source.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {OUT / 'recall_by_source.png'}")


def chart_improvement(report: dict, k: str = "10"):
    fts = report["fts_on_sample"][k]
    trgm = report["trgm"][k]

    metrics = [f"Recall@{k}", f"MRR@{k}", f"nDCG@{k}"]
    improvement = [
        ((fts["recall"] - trgm["recall"]) / trgm["recall"]) * 100 if trgm["recall"] else 0,
        ((fts["mrr"] - trgm["mrr"]) / trgm["mrr"]) * 100 if trgm["mrr"] else 0,
        ((fts["ndcg"] - trgm["ndcg"]) / trgm["ndcg"]) * 100 if trgm["ndcg"] else 0,
    ]

    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(metrics, improvement, color="#1f77b4", width=0.55)
    ax.bar_label(bars, labels=[f"{v:+.0f}%" for v in improvement], padding=3, fontweight="bold")

    ax.set_ylabel("Improvement over pg_trgm (%)")
    ax.set_title("pg_kazsearch vs pg_trgm — Relative Improvement", fontweight="bold", pad=12)
    ax.set_ylim(min(0, min(improvement) * 1.2), max(improvement) * 1.25 if improvement else 1)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(OUT / "improvement.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {OUT / 'improvement.png'}")


if __name__ == "__main__":
    print(f"Generating charts from {REPORT}...")
    report = load_report()
    chart_retrieval_quality(report)
    chart_by_source(report)
    chart_improvement(report)
    print("Done.")
