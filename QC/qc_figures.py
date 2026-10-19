#!/usr/bin/env python3
"""qc_figures.py - redraw every QC figure from the CSVs in this folder (run after qc_suite.py and compare_v1_v2.py)."""
import csv, os
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
HERE = os.path.dirname(os.path.abspath(__file__))
MAG, GREY, INK = "#C0006A", "#cfc8d6", "#211b26"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.spines.top": False, "axes.spines.right": False})
R = lambda p: list(csv.DictReader(open(os.path.join(HERE, p), encoding="utf-8-sig")))
def hbar(path, labels, vals, colors, xlabel, xmax, title, fmt="{:g}"):
    h = 0.6 + 0.22 * len(labels)
    fig, ax = plt.subplots(figsize=(5.2, h)); y = range(len(labels))[::-1]
    ax.barh(list(y), vals, color=colors, height=0.7)
    for yi, v in zip(y, vals): ax.text(v + xmax * 0.01, yi, fmt.format(v), va="center", fontsize=7, color=INK)
    ax.set_yticks(list(y)); ax.set_yticklabels(labels); ax.set_xlim(0, xmax); ax.set_xlabel(xlabel); ax.set_title(title, loc="left", fontsize=9)
    fig.tight_layout(); fig.savefig(os.path.join(HERE, path), dpi=200); plt.close(fig)
d = R("01_field_completeness/field_completeness.csv")
hbar("01_field_completeness/field_completeness.png", [r["field"] for r in d], [float(r["pct_filled"]) for r in d],
     [MAG if r["group"] == "core" else GREY for r in d], "% of rows filled", 105, "QC 01  Field completeness (core fields in magenta)")
d = R("02_reagent_identifier_completeness/identifier_tiers.csv")
hbar("02_reagent_identifier_completeness/identifier_tiers.png", [r["identifier_tier"] for r in d], [int(r["n_antibodies"]) for r in d],
     [GREY if r["identifier_tier"] == "anonymous" else MAG for r in d], "primary antibodies", max(int(r["n_antibodies"]) for r in d) * 1.15,
     "QC 02  Reagent identifiers")
d = R("03_test_retest_v1_v2/agreement.csv"); d = [r for r in d if r["field"] != "aligned rows"]
hbar("03_test_retest_v1_v2/agreement.png", [r["field"] for r in d], [float(r["agreement_pct"]) for r in d],
     [MAG] * len(d), "% agreement, v1 vs v2 (aligned rows)", 105, "QC 03  Test-retest agreement")
d = R("04_cross_paper_corroboration/corroboration.csv")
hbar("04_cross_paper_corroboration/corroboration.png", ["antibody target", "species -> clade"], [float(r["pct"]) for r in d],
     [MAG] * len(d), "% consistent across papers", 105, "QC 04  Cross-paper corroboration")
d = R("05_controlled_vocabulary/vocab_conformance.csv")
hbar("05_controlled_vocabulary/vocab_conformance.png", [r["field"] for r in d], [float(r["in_controlled_vocab_pct"]) for r in d],
     [MAG] * len(d), "% of rows", 105, "QC 05  Controlled vocabulary")
d = R("06_catalogue_format_validity/catalogue_format.csv")
hbar("06_catalogue_format_validity/catalogue_format.png", [r["format_class"] for r in d], [int(r["n_distinct_catalogue_numbers"]) for r in d],
     [GREY if r["format_class"] == "unrecognized" else MAG for r in d], "distinct catalogue numbers",
     max(int(r["n_distinct_catalogue_numbers"]) for r in d) * 1.15, "QC 06  Catalogue-number syntax")
d = R("08_honest_abstention/abstention.csv")
fl = [r for r in d if "flagged" in r["metric"]]
hbar("08_honest_abstention/abstention.png", [r["metric"] for r in fl], [int(r["value"]) for r in fl], [MAG] * len(fl),
     "cells", max(int(r["value"]) for r in fl) * 1.2, "QC 08  Values the model flagged instead of asserting")
print("QC figures redrawn")
