#!/usr/bin/env python3
"""
flag_duplicates.py — Add a 'possible_duplicate_of' column to exm_database.csv.

For each keep_journal pair in resolved_duplicates.csv:
  - preprint/journal  → flag the preprint rows
  - journal/preprint  → flag the preprint rows
  - preprint/preprint → flag BOTH (can't confirm which is canonical without manual check)

The flag value is the filename of the likely canonical paper, e.g.:
  "Alonso_ParasitologyResearch_2022.pdf"

Rows for non-duplicated papers get an empty string in this column.

When making figures: filter to rows where possible_duplicate_of == ""

Usage:
    python flag_duplicates.py
"""

import csv
import shutil
from collections import defaultdict
from pathlib import Path

CSV_FILE   = Path(__file__).parent / "exm_database.csv"
DUPES_FILE = Path(__file__).parent / "resolved_duplicates.csv"
BACKUP     = Path(__file__).parent / "exm_database_before_flag_duplicates.csv"
NEW_COL    = "possible_duplicate_of"


def main():
    # Read duplicate verdicts
    dupes = list(csv.DictReader(open(DUPES_FILE, encoding="utf-8-sig")))
    keep_journal = [d for d in dupes if d["verdict"] == "keep_journal"]
    print(f"keep_journal pairs: {len(keep_journal)}")

    # Build flag map: filename → canonical_filename (the one to keep)
    # flag_map[file_to_flag] = canonical_file
    flag_map = defaultdict(set)

    for d in keep_journal:
        fa, fb  = d["file_a"], d["file_b"]
        ta, tb  = d["type_a"], d["type_b"]

        if ta == "preprint" and tb == "journal":
            flag_map[fa].add(fb)          # flag the preprint
        elif ta == "journal" and tb == "preprint":
            flag_map[fb].add(fa)          # flag the preprint
        elif ta == "preprint" and tb == "preprint":
            flag_map[fa].add(fb)          # flag both — can't be sure which is better
            flag_map[fb].add(fa)

    print(f"Papers to flag: {len(flag_map)}")
    for fname, dupes_of in sorted(flag_map.items()):
        print(f"  {fname}  →  {' | '.join(sorted(dupes_of))}")

    # Load CSV
    rows, fieldnames = [], []
    with open(CSV_FILE, encoding="utf-8-sig") as f:
        # Strip NUL bytes that can appear after interrupted writes
        clean = (line.replace("\x00", "") for line in f)
        reader = csv.DictReader(clean)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            rows.append(dict(row))

    # Add column if not present
    if NEW_COL not in fieldnames:
        fieldnames.append(NEW_COL)

    # Apply flags
    flagged_rows = 0
    for row in rows:
        fname = row.get("pdf_filename", "")
        if fname in flag_map:
            row[NEW_COL] = " | ".join(sorted(flag_map[fname]))
            flagged_rows += 1
        elif NEW_COL not in row:
            row[NEW_COL] = ""

    print(f"\nFlagged {flagged_rows} rows across {len(flag_map)} papers")

    # Backup and write
    shutil.copy2(CSV_FILE, BACKUP)
    print(f"Backup → {BACKUP.name}")

    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Written → {CSV_FILE.name}")
    print(f"\nTo exclude duplicates in analysis: filter rows where {NEW_COL} == \"\"")


if __name__ == "__main__":
    main()
