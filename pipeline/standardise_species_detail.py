#!/usr/bin/env python3
"""
Standardise species_detail column in ExM_database_curated.csv
No API calls — purely rule-based normalisation.

Usage:
    python3 standardise_species_detail.py              # dry run (prints changes, no write)
    python3 standardise_species_detail.py --apply      # write updated CSV
    python3 standardise_species_detail.py --report     # just print summary stats

Output (when --apply):
    ExM_database_curated.csv  — updated in-place (backup written to ExM_database_curated.bak.csv)
"""

import argparse
import shutil
from pathlib import Path
import pandas as pd

DB = Path(__file__).parent / "ExM_database_curated.csv"

# ── Normalisation map ────────────────────────────────────────────────────────
# Key   = raw value (case-insensitive match after stripping whitespace)
# Value = canonical form
#
# Grouped by cell line. Add new entries at the bottom.
NORM = {
    # U2OS
    "u2os"                              : "U2OS",
    "u2os cells"                        : "U2OS",
    "u2os osteosarcoma cells"           : "U2OS",
    "u2-os"                             : "U2OS",
    "u2os cell line"                    : "U2OS",

    # RPE1 / hTERT-RPE1
    "rpe1"                              : "hTERT-RPE1",
    "rpe-1"                             : "hTERT-RPE1",
    "rpe1 cells"                        : "hTERT-RPE1",
    "htert-rpe1"                        : "hTERT-RPE1",
    "htert rpe-1"                       : "hTERT-RPE1",
    "htert rpe-1 tp53-/-"               : "hTERT-RPE1 TP53-/-",
    "htert rpe1"                        : "hTERT-RPE1",
    "htert rpe1 cells"                  : "hTERT-RPE1",

    # HeLa
    "hela"                              : "HeLa",
    "hela cells"                        : "HeLa",
    "hela cell line"                    : "HeLa",
    "hela s3"                           : "HeLa S3",

    # MEF
    "mef"                               : "MEF",
    "mefs"                              : "MEF",
    "mouse embryonic fibroblasts"       : "MEF",
    "mouse embryonic fibroblast"        : "MEF",
    "primary mef"                       : "MEF",

    # COS-7
    "cos-7"                             : "COS-7",
    "cos7"                              : "COS-7",
    "cos 7"                             : "COS-7",

    # Cercopithecus aethiops / Vero / CV1
    "cercopithecus aethiops"            : "Cercopithecus aethiops (Vero)",
    "vero"                              : "Cercopithecus aethiops (Vero)",
    "vero cells"                        : "Cercopithecus aethiops (Vero)",
    "vero e6"                           : "Cercopithecus aethiops (Vero E6)",
    "cv1"                               : "Cercopithecus aethiops (CV-1)",
    "cv-1"                              : "Cercopithecus aethiops (CV-1)",

    # NRK
    "nrk49f"                            : "NRK-49F",
    "nrk49f cell line"                  : "NRK-49F",
    "nrk-49f"                           : "NRK-49F",
    "nrk"                               : "NRK-49F",

    # Neurons (primary)
    "primary hippocampal neurons"       : "primary hippocampal neurons",
    "hippocampal neurons"               : "primary hippocampal neurons",
    "rat hippocampal neurons"           : "primary hippocampal neurons",
    "mouse hippocampal neurons"         : "primary hippocampal neurons",
    "primary cortical neurons"          : "primary cortical neurons",
    "cortical neurons"                  : "primary cortical neurons",

    # Organoids
    "ipsc-derived brain organoids"      : "iPSC-derived brain organoids",
    "ipsc brain organoids"              : "iPSC-derived brain organoids",
    "cerebral organoids"                : "iPSC-derived brain organoids",

    # Homo sapiens (host species, not a cell line)
    "homo sapiens"                      : "Homo sapiens",
    "human"                             : "Homo sapiens",
    "human cervical cancer cell line"   : "HeLa",   # almost always HeLa in ExM context

    # Tissue
    "ffpe tonsil"                       : "FFPE tonsil",
    "ffpe brain - hippocampus and middle frontal gyrus" : "FFPE brain (hippocampus/mPFC)",
    "ffpe brain"                        : "FFPE brain",

    # Dog
    "dog"                               : "Canis lupus familiaris",
    "canis lupus familiaris"            : "Canis lupus familiaris",
}


def normalise(val: str) -> str:
    """Return normalised value, or original if no match found."""
    if not isinstance(val, str):
        return val
    stripped = val.strip()
    key = stripped.lower()
    return NORM.get(key, stripped)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply",  action="store_true", help="Write changes to CSV")
    parser.add_argument("--report", action="store_true", help="Summary stats only")
    args = parser.parse_args()

    df = pd.read_csv(DB, encoding="utf-8-sig", low_memory=False)
    df = df.map(lambda x: x.replace('\x00', '') if isinstance(x, str) else x)

    if "species_detail" not in df.columns:
        print("Column 'species_detail' not found in database. Nothing to do.")
        return

    original = df["species_detail"].copy()
    normalised = df["species_detail"].apply(normalise)

    changed = original != normalised
    n_changed = changed.sum()

    if args.report:
        print(f"Total rows: {len(df)}")
        print(f"Non-empty species_detail: {original.notna().sum()}")
        print(f"Rows that would be changed: {n_changed}")
        print("\nTop 30 values after normalisation:")
        print(normalised.value_counts().head(30).to_string())
        return

    if n_changed == 0:
        print("No changes needed — all values already normalised.")
        return

    print(f"Changes to apply ({n_changed} rows):")
    for old, new in (original[changed].value_counts().items()):
        norm = normalise(old)
        print(f"  {old!r:55s} → {norm!r}")

    if args.apply:
        backup = DB.with_suffix(".bak.csv")
        shutil.copy(DB, backup)
        print(f"\nBackup written to: {backup.name}")
        df["species_detail"] = normalised
        df.to_csv(DB, index=False, encoding="utf-8-sig")
        print(f"Updated {DB.name} ({n_changed} cells changed)")
    else:
        print("\nDry run — no changes written. Run with --apply to save.")


if __name__ == "__main__":
    main()
