#!/usr/bin/env python3
"""
fix_clades.py — Correct known wrong clade assignments in exm_database.csv.

Fixes are targeted by (species, wrong_clade) → correct_clade.
Rows with a species that already has the correct clade are left untouched.

Usage:
    python fix_clades.py            # dry run
    python fix_clades.py --apply    # apply changes
"""

import argparse
import csv
import shutil
from collections import Counter
from pathlib import Path

CSV_FILE = Path(__file__).parent / "exm_database.csv"
BACKUP   = Path(__file__).parent / "exm_database_before_fix_clades.csv"

# (species_exact_match, wrong_clade) → correct_clade
# Only rows matching BOTH species AND wrong clade are changed.
CLADE_FIXES = {
    # Ichthyosporea (Unicellular Holozoa) — misassigned by extractor
    ("Chromosphaera perkinsii",   "Alveolata"):          "Unicellular Holozoa",
    ("Creolimax fragrantissima",  "Alveolata"):          "Unicellular Holozoa",
    ("Sphaeroforma arctica",      "Fungi"):              "Unicellular Holozoa",

    # Parabasalia / Metamonada — not in the 15-clade vocabulary → Unknown
    ("Trichomonas vaginalis",     "Alveolata"):          "Unknown",
    ("Tritrichomonas foetus",     "Alveolata"):          "Unknown",
    ("Tritrichomonas foetus",     "Discoba"):            "Unknown",  # also wrong

    # Diplomonada (Metamonada) — not in vocab → Unknown
    ("Giardia intestinalis",      "Discoba"):            "Unknown",
    ("Giardia lamblia",           "Discoba"):            "Unknown",

    # Oxymonadida (Metamonada) — not in vocab → Unknown
    ("Paratrimastix pyriformis",  "Discoba"):            "Unknown",

    # Nudibranch (Metazoa) — wildly misassigned to Cryptista
    ("Urgorri complanatus",       "Cryptista"):          "Metazoa",

    # Tobacco plant cell line — misassigned to Metazoa
    ("Nicotiana tabacum BY2 suspension culture cells", "Metazoa"): "Viridiplantae",

    # HSV-1 is a virus — misassigned to Bacteria
    ("Herpes simplex virus type 1 (HSV-1)", "Bacteria"): "Unknown",
}

REASONS = {
    "Chromosphaera perkinsii":   "Ichthyosporea → Unicellular Holozoa",
    "Creolimax fragrantissima":  "Ichthyosporea → Unicellular Holozoa",
    "Sphaeroforma arctica":      "Ichthyosporea → Unicellular Holozoa",
    "Trichomonas vaginalis":     "Parabasalia (Metamonada), not in 15-clade vocab → Unknown",
    "Tritrichomonas foetus":     "Parabasalia (Metamonada), not in 15-clade vocab → Unknown",
    "Giardia intestinalis":      "Metamonada (Fornicata), not Discoba → Unknown",
    "Giardia lamblia":           "Metamonada (Fornicata), not Discoba → Unknown",
    "Paratrimastix pyriformis":  "Oxymonadida (Metamonada), not Discoba → Unknown",
    "Urgorri complanatus":       "Nudibranch (Mollusca) → Metazoa",
    "Nicotiana tabacum BY2 suspension culture cells": "Plant cell line → Viridiplantae",
    "Herpes simplex virus type 1 (HSV-1)": "Virus, not Bacteria → Unknown",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows, fieldnames = [], []
    with open(CSV_FILE, encoding="utf-8-sig") as f:
        clean = (line.replace("\x00", "") for line in f)
        reader = csv.DictReader(clean)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            rows.append(dict(row))

    print(f"Loaded {len(rows)} rows\n")

    changed_rows = 0
    per_fix = Counter()

    for row in rows:
        sp    = row.get("species", "").strip()
        clade = row.get("clade", "").strip()
        key   = (sp, clade)
        if key in CLADE_FIXES:
            new_clade = CLADE_FIXES[key]
            row["clade"] = new_clade
            changed_rows += 1
            per_fix[f"{sp}  |  {clade} → {new_clade}"] += 1

    mode = "DRY RUN" if not args.apply else "APPLY"
    print(f"[{mode}]  {changed_rows} rows to fix\n")
    for desc, n in sorted(per_fix.items(), key=lambda x: -x[1]):
        reason_sp = desc.split("  |  ")[0]
        reason = REASONS.get(reason_sp, "")
        print(f"  [{n:3d} rows]  {desc}")
        if reason:
            print(f"            Reason: {reason}")

    if args.apply:
        shutil.copy2(CSV_FILE, BACKUP)
        print(f"\nBackup → {BACKUP.name}")
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"Written → {CSV_FILE.name}")
    else:
        print(f"\n(Dry run — add --apply to apply changes)")


if __name__ == "__main__":
    main()
