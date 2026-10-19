#!/usr/bin/env python3
"""
compare_v1_v2.py  -  QC 03: test-retest agreement between the two independent extraction passes.

v1 = the first full extraction (v1_table.csv.gz, shipped in this folder, 8,757 rows).
v2 = the released database. Rows are aligned by (source PDF, species, label name); for every aligned
row we report how often the two passes recorded the same value. Writes agreement.csv here.
Usage:  python compare_v1_v2.py [path/to/ExM_database_curated.csv]
"""
import csv, gzip, io, sys
from pathlib import Path
HERE = Path(__file__).parent
DB = sys.argv[1] if len(sys.argv) > 1 else str(HERE.parents[1] / "data" / "ExM_database_curated.csv")
g = lambda r, k: (r.get(k) or "").strip().lower()
key = lambda r: (g(r, "pdf_filename"), g(r, "species"), g(r, "label_name"))
v1 = {key(r): r for r in csv.DictReader(io.TextIOWrapper(gzip.open(HERE / "v1_table.csv.gz"), encoding="utf-8-sig"))}
v2 = {key(r): r for r in csv.DictReader(open(DB, encoding="utf-8-sig"))}
common = set(v1) & set(v2)
FIELDS = [("clade", "clade"), ("protocol_outcome", "protocol outcome"), ("label_outcome", "label outcome"),
          ("exm_variant", "ExM variant"), ("label_target", "antibody target (raw text)")]
out = []
for f, lab in FIELDS:
    a = sum(1 for k in common if g(v1[k], f) == g(v2[k], f))
    out.append((lab, round(100 * a / len(common), 1)))
with open(HERE / "agreement.csv", "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.writer(fh); w.writerow(["field", "agreement_pct"]); w.writerows(out)
    w.writerow(["aligned rows", len(common)])
print(f"aligned rows {len(common):,} (v1 {len(v1):,}, v2 {len(v2):,})")
for lab, p in out: print(f"  {lab:28} {p}%")
