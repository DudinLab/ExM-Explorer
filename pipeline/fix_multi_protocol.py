#!/usr/bin/env python3
"""
fix_multi_protocol.py — Standardise multi-protocol 'other:' entries.

Entries where a paper used two or more protocols get renamed to:
  other: multi-protocol (X, Y, Z)

Named protocols that happen to combine elements (CATS, GelMap) get their
parenthetical description stripped to a clean name.

Usage:
    python fix_multi_protocol.py            # dry run
    python fix_multi_protocol.py --apply
"""
import argparse, csv, shutil
from pathlib import Path

CSV_FILE = Path(__file__).parent / "exm_database.csv"
BACKUP   = Path(__file__).parent / "exm_database_before_fix_multi_protocol.csv"

VARIANT_MAP = {
    # ── Multi-protocol papers → standardised format ──────────────────────────
    "other: ExM and U-ExM":
        "other: multi-protocol (proExM, U-ExM)",
    "other: U-ExM and proExM":
        "other: multi-protocol (proExM, U-ExM)",
    "other: proExM and U-ExM":
        "other: multi-protocol (proExM, U-ExM)",
    "other: both proExM and U-ExM":
        "other: multi-protocol (proExM, U-ExM)",
    "other: U-ExM and iU-ExM":
        "other: multi-protocol (U-ExM, iterative-ExM)",
    "other: MAP / proExM (protein-retention ExM)":
        "other: multi-protocol (MAP, proExM)",
    "other: hybrid proExM/Magnify":
        "other: multi-protocol (Magnify, proExM)",
    "other: proExM/ExFISH hybrid":
        "other: multi-protocol (ExFISH, proExM)",
    "other: 10x ExM / proExM / TREx":
        "other: multi-protocol (proExM, TREx)",
    "other: 10x ExM (X10/TREx-derived) and proExM (4x)":
        "other: multi-protocol (proExM, TREx)",
    "other: X10 ExM / ONE microscopy / U-ExM":
        "other: multi-protocol (ONE microscopy, U-ExM, X10 ExM)",
    "other: proExM (4x) and X10 ExM (10x)":
        "other: multi-protocol (proExM, X10 ExM)",
    "other: proExM + TREx with TRITON linkers":
        "other: multi-protocol (proExM, TREx)",
    "other: proExM + TREx (TRITON linker optimization)":
        "other: multi-protocol (proExM, TREx)",

    # ── Named protocols — strip parenthetical description ────────────────────
    "other: GelMap (applied across TREx, proExM, MAP, iterative pan-ExM)":
        "other: GelMap",
    "other: CATS (proExM and MAP variants)":
        "other: CATS",
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

    from collections import Counter
    changes = Counter()
    changed_rows = 0

    for row in rows:
        old = row.get("exm_variant", "").strip()
        new = VARIANT_MAP.get(old)
        if new:
            row["exm_variant"] = new
            changes[f"{old}  →  {new}"] += 1
            changed_rows += 1

    mode = "DRY RUN" if not args.apply else "APPLY"
    print(f"[{mode}]  {changed_rows} rows updated ({len(changes)} unique mappings)\n")
    for mapping, n in sorted(changes.items(), key=lambda x: -x[1]):
        print(f"  [{n:3d}]  {mapping}")

    if args.apply:
        shutil.copy2(CSV_FILE, BACKUP)
        print(f"\nBackup → {BACKUP.name}")
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"Written → {CSV_FILE.name}")
    else:
        print("\n(add --apply to write)")


if __name__ == "__main__":
    main()
