#!/usr/bin/env python3
"""
curate_20261009.py  -  curation decisions taken on 9 October 2026 (O.D.) (see PROVENANCE.md, section 5).

1. Merge 29 preprint/published pairs (paper_versions_review.csv, all confirmed by O.D.).
   Rule: keep every row; the earlier version's rows take the later version's
   doi / title / journal / year / first_author / last_author / paper_type, so the study
   counts once wherever papers are keyed by DOI. pdf_filename is left unchanged so each
   row still traces to the PDF it was extracted from.
2. Drop two review articles (Q5, Q6).
3. Restore metadata recorded in the search results (library.csv) but lost or wrong in the table.

Backs up the CSV first and writes curation_log_20261009.csv (one line per changed or removed row).
Run once:  python curate_20261009.py
"""
import csv, os, shutil, time, collections
os.chdir(os.path.dirname(os.path.abspath(__file__)))
DB = "ExM_database_curated.csv"
rows = list(csv.DictReader(open(DB, encoding="utf-8-sig")))
FIELDS = list(rows[0].keys())
assert len(rows) == 6771, f"expected the 6,771-row table, found {len(rows)} (already curated?)"

META = ["doi", "title", "journal", "year", "first_author", "last_author", "paper_type"]
DROP = {"Laporte_MedecineSciences_2023.pdf": "Q5 review article (O.D., 9 Oct 2026)",
        "Sena_JournalofMicroscopy_2025.pdf": "Q6 review article (O.D., 9 Oct 2026)"}
FIX = {   # pdf -> {field: value}, each value taken from library.csv
    "Taddei_JAMANeurology_2023.pdf": {"doi": "10.1001/jamaneurol.2023.3530"},
    "Wen_ACSNano_2015.pdf": {"doi": "10.1021/acsnano.3c07510", "journal": "ACS Nano"},
    "Michels1_MethodsinMolecularBiology_2026.pdf": {"doi": "10.1007/978-1-0716-5146-9_13",
                                                     "title": "Expansion Microscopy in Euglenozoa"},
    "Petreaca_MethodsinMolecularBiology_2025.pdf": {"doi": "10.1007/978-1-0716-4168-2_4"},
}
log = []
def setf(r, k, v, why):
    if r.get(k, "") != v:
        log.append(dict(pdf_filename=r["pdf_filename"], action="edit", field=k, old=r.get(k, ""), new=v, reason=why))
        r[k] = v

# 3. metadata fixes first, so the merge copies corrected values
for r in rows:
    for k, v in FIX.get(r["pdf_filename"], {}).items():
        setf(r, k, v, "restored from search record (library.csv)")

# 1. merge version pairs
pairs = list(csv.DictReader(open("paper_versions_review.csv", encoding="utf-8")))
assert len(pairs) == 29
first = {}
for r in rows: first.setdefault(r["pdf_filename"], r)
for p in pairs:
    a, b = p["earlier_version_pdf"], p["later_version_pdf"]
    assert a in first and b in first, (a, b)
    tgt = {k: first[b][k] for k in META}
    for r in rows:
        if r["pdf_filename"] == a:
            for k in META: setf(r, k, tgt[k], f"preprint merged into published version {b}")

# 2. drop reviews
kept = []
for r in rows:
    if r["pdf_filename"] in DROP:
        log.append(dict(pdf_filename=r["pdf_filename"], action="remove row", field="", old=r["label_name"],
                        new="", reason=DROP[r["pdf_filename"]]))
    else: kept.append(r)

# checks before writing
dois = collections.defaultdict(set)
for r in kept: dois[(r["doi"] or r["journal"] + r["year"] + r["first_author"])].add(r["pdf_filename"])
nstud = len(dois)
print(f"rows {len(rows)} -> {len(kept)} | source PDFs {len(first)} -> {len({r['pdf_filename'] for r in kept})} | studies (by DOI) {nstud}")
assert len(kept) == 6771 - sum(1 for r in rows if r["pdf_filename"] in DROP)
assert nstud == 413 - 29 - 2, nstud
assert all(r["doi"] for r in kept), "every study now has a DOI"

stamp = time.strftime("%Y%m%d_%H%M%S")
shutil.copy(DB, f"ExM_database_curated.pre_versionmerge_{stamp}.bak.csv")
with open(DB, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader(); w.writerows(kept)
with open("curation_log_20261009.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["pdf_filename", "action", "field", "old", "new", "reason"]); w.writeheader(); w.writerows(log)
print(f"backup: ExM_database_curated.pre_versionmerge_{stamp}.bak.csv | log lines: {len(log)}")
