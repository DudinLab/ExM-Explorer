#!/usr/bin/env python3
"""
fix_variants.py — Standardise exm_variant values in exm_database.csv.

Two categories of fixes:

  Group 1 — Canonical variants mislabelled as "other: X":
    e.g. "other: proExM (Chozinski protocol)" → "proExM"
    The protocol IS canonical; the extractor just added a citation or description.
    These are fixed automatically.

  Group 2 — Genuinely novel protocols:
    e.g. "other: TT-ExM", "other: LR-ExM", "other: X10ht"
    These have their own identity and are left exactly as-is per project policy
    (preserve detail, classify into Other later).

Writes a backup before modifying.

Usage:
    python fix_variants.py            # dry run — shows changes, writes nothing
    python fix_variants.py --apply    # applies fixes and writes CSV
"""

import argparse
import csv
import shutil
from collections import Counter
from pathlib import Path

CSV_FILE = Path(__file__).parent / "exm_database.csv"
BACKUP   = Path(__file__).parent / "exm_database_before_fix_variants.csv"

# ── Explicit mapping ────────────────────────────────────────────────────────────
#
# Every "other: X" value that maps to a canonical name is listed here explicitly.
# Anything NOT in this dict is left untouched.
#
# Canonical set: U-ExM | proExM | ExPath | ExFISH | TREx | Magnify | cryo-ExM | MAP | iterative-ExM

VARIANT_MAP = {

    # ── proExM — same protocol, different citation/description ─────────────────
    "other: proExM":                                                          "proExM",
    "other: proExM (protein-retention ExM)":                                  "proExM",
    "other: proExM (protein retention ExM)":                                  "proExM",
    "other: proExM (protein-retention expansion microscopy)":                 "proExM",
    "other: proExM (protein-retention ExM adapted from Tillberg et al. 2016 and Zhao et al. 2017)": "proExM",
    "other: proExM (protein-retention ExM, adapted from Tillberg et al. 2016)": "proExM",
    "other: proExM (protein-retention ExM based on M'saad et al. 2020)":      "proExM",
    "other: proExM (protein-retention ExM using AcX/MA-NHS anchoring)":       "proExM",
    "other: proExM (protein-retention ExM with AcX)":                         "proExM",
    "other: proExM (antibody-based ExM with MA-NHS anchoring)":               "proExM",
    "other: proExM (Chen et al. 2015 original ExM)":                          "proExM",
    "other: proExM (adapted from Asano et al. 2018)":                         "proExM",
    "other: proExM (Asano et al. 2018 protocol)":                             "proExM",
    "other: proExM (based on Chen et al. 2015 and Asano et al. 2018 protocols)": "proExM",
    "other: proExM (Chen 2015 + Chozinski 2016)":                             "proExM",
    "other: proExM (Chozinski protocol)":                                     "proExM",
    "other: proExM (Chozinski et al. 2016)":                                  "proExM",
    "other: proExM (Chozinski et al. 2016 protocol)":                         "proExM",
    "other: proExM (modified Chozinski et al. 2016)":                         "proExM",
    "other: proExM (AcX-based)":                                              "proExM",
    "other: proExM (based on Zhang et al. 2020 protocol)":                    "proExM",
    "other: proExM (modified 6x)":                                            "proExM",
    "other: proExM (referenced as Wang et al. 2020 eLife protocol)":          "proExM",
    "other: proExM (tissue expansion with proteinase K digestion, following Wang et al. 2020)": "proExM",
    "other: proExM with heat-SDS digestion for tissue":                        "proExM",
    "other: proExM with QDots":                                               "proExM",
    "other: proExM with LabelX nucleic acid anchoring":                       "proExM",
    "other: proExM with SNAP-tag DNA oligostrand labeling":                   "proExM",
    "other: proExM-heat disruption":                                          "proExM",
    "other: proExM-fungi":                                                    "proExM",
    "other: proExM-modified":                                                 "proExM",
    "other: proExM-adapted":                                                  "proExM",
    "other: proExM-adapted (MA-NHS anchoring)":                               "proExM",
    "other: proExM-adapted for plant tissue":                                 "proExM",
    "other: modified proExM for plant tissues":                               "proExM",
    "other: modified proExM (based on Gorilak et al 2021)":                   "proExM",
    "other: modified proExM (reduced expansion ~3x)":                         "proExM",
    "other: proExM-based custom protocol":                                    "proExM",
    "other: proExM-based whole-brain ExM":                                    "proExM",
    "other: proExM-based with post-expansion staining":                       "proExM",
    "other: proExM-based LSFEM (Light-Sheet Fluorescence Expansion Microscopy)": "proExM",
    "other: proExM/LSFEM (light sheet fluorescence expansion microscopy)":    "proExM",
    "other: proExM-based (modified Chen et al. 2015)":                        "proExM",
    "other: proExM-based (Gorilak et al. 2021 protocol)":                     "proExM",
    "other: proExM-based (Mosca et al. 2017 protocol)":                       "proExM",
    "other: proExM-based (MA-NHS anchoring + proteinase K)":                  "proExM",
    "other: proExM-based (as described in cited Arias Padilla/Hu lab protocols)": "proExM",
    "other: proExM-like (MA-NHS anchoring)":                                  "proExM",
    "other: proExM-like (custom protocol)":                                   "proExM",
    "other: proExM-like (custom protocol combining Chozinski 2016, Tillberg 2016, Truckenbrodt 2019)": "proExM",
    "other: proExM-like (Chen 2015 / Chozinski 2016 protocol)":               "proExM",
    "other: proExM-like (Acryloyl-X SE anchoring)":                           "proExM",
    "other: proExM-like (post-expansion labelling with heat-SDS homogenization)": "proExM",
    "other: proExM-like (19% sodium acrylate gel with heat-SDS denaturation)": "proExM",
    "other: proExM-like (protein-retention ExM with cell wall digestion step)": "proExM",
    "other: proExM + ExPath":                                                 "proExM",
    "other: modified ExM for yeast":                                          "proExM",
    "other: expansion microscopy for proteomics (proExM-based)":              "proExM",
    "other: ExM-based microproteomics (proExM-adapted)":                      "proExM",
    "other: optimized ExM combining proExM/MAP/U-ExM elements":               "proExM",
    "other: ExM (proExM-like with AMPS gel)":                                 "proExM",

    # ── ExPath ─────────────────────────────────────────────────────────────────
    "other: ExPath":                                                          "ExPath",
    "other: dExPath":                                                         "ExPath",
    "other: dExPath (decrowding expansion pathology)":                        "ExPath",
    "other: proExM-based (Bucur et al. 2020 ExPath)":                         "ExPath",
    "other: proExM on FFPE (HIF-Clear-ExM)":                                  "ExPath",  # FFPE tissue = ExPath territory

    # ── U-ExM — same protocol, different description ───────────────────────────
    "other: U-ExM":                                                           "U-ExM",
    "other: U-ExM (Ultrastructure Expansion Microscopy)":                     "U-ExM",
    "other: U-ExM (based on Gambarotto et al. 2019 and Sahabandu et al. 2019)": "U-ExM",
    "other: U-ExM (modified)":                                                "U-ExM",
    "other: U-ExM modified":                                                  "U-ExM",
    "other: U-ExM adapted":                                                   "U-ExM",
    "other: U-ExM adapted (ten-fold robust ExM, based on Damstra et al.)":    "U-ExM",
    "other: U-ExM (proExM-like, based on sodium acrylate gel with heat denaturation)": "U-ExM",
    "other: U-ExM-like (references prior Hu lab protocol)":                   "U-ExM",
    "other: U-ExM-based (proExM-like, following Padilla et al. 2024 protocol)": "U-ExM",
    "other: optimized U-ExM":                                                 "U-ExM",

    # ── ExFISH ─────────────────────────────────────────────────────────────────
    "other: ExFISH (RNA FISH + ExM)":                                         "ExFISH",
    "other: ExFISH (expansion microscopy + RNA FISH)":                        "ExFISH",
    "other: ExFISH-inspired (LabelX-based proExM)":                           "ExFISH",

    # ── Magnify ────────────────────────────────────────────────────────────────
    "other: μMagnify":                                                        "Magnify",
    "other: µExM":                                                            "Magnify",  # µExM = micro-Magnify
    "other: μExM":                                                            "Magnify",
    "other: uMagnify (microMagnify)":                                         "Magnify",

    # ── MAP ────────────────────────────────────────────────────────────────────
    "other: eMAP":                                                            "MAP",
    "other: c-MAP/U-ExM hybrid (adapted from Kong & Loncarek 2021 and Gambarotto et al. 2021)": "MAP",

    # ── TREx ───────────────────────────────────────────────────────────────────
    "other: dTREx (double TREx)":                                             "TREx",

}


def apply_fix(variant: str) -> tuple[str, bool]:
    """Return (new_value, was_changed)."""
    fixed = VARIANT_MAP.get(variant)
    if fixed:
        return fixed, True
    return variant, False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Write changes to CSV (default is dry run)")
    args = parser.parse_args()

    rows, fieldnames = [], []
    with open(CSV_FILE, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            rows.append(dict(row))

    print(f"Loaded {len(rows)} rows\n")

    changed_rows = 0
    change_summary = Counter()  # old → new counts

    for row in rows:
        old = row.get("exm_variant", "").strip()
        new, changed = apply_fix(old)
        if changed:
            row["exm_variant"] = new
            changed_rows += 1
            change_summary[f"{old}  →  {new}"] += 1

    print(f"{'DRY RUN — ' if not args.apply else ''}Changes to apply: {changed_rows} rows "
          f"({len(change_summary)} unique mappings)\n")

    # Print per-mapping summary
    for mapping, n in sorted(change_summary.items(), key=lambda x: -x[1]):
        print(f"  [{n:3d}x]  {mapping}")

    if args.apply:
        shutil.copy2(CSV_FILE, BACKUP)
        print(f"\nBackup saved → {BACKUP.name}")

        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        print(f"Written → {CSV_FILE.name}")
    else:
        print(f"\n(Dry run — add --apply to write changes)")


if __name__ == "__main__":
    main()
