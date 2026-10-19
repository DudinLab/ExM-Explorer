#!/usr/bin/env python3
"""19 October 2026: merge one preprint-publication pair missed by the 9 October curation (titles differ).
Cui_bioRxiv_2022.pdf (10.1101/2022.06.19.496699) is the preprint of Park_PLOSONE_2023.pdf (10.1371/journal.pone.0291506),
confirmed by O.D. on 19 Oct 2026. As on 9 October, the preprint rows keep their extracted data and take the study
metadata (doi, title, journal, year, authors, paper type) of the published version. Edits are appended to the curation log."""
import csv, shutil, time, collections
DB = "ExM_database_curated.csv"
rows = list(csv.DictReader(open(DB, encoding="utf-8-sig"))); FIELDS = list(rows[0].keys())
assert len(rows) == 6755, f"expected the 6,755-row table, found {len(rows)} (already merged?)"
META = ["doi", "title", "journal", "year", "first_author", "last_author", "paper_type"]
A, B = "Cui_bioRxiv_2022.pdf", "Park_PLOSONE_2023.pdf"
tgt = next(r for r in rows if r["pdf_filename"] == B); tgt = {k: tgt[k] for k in META}
log = []
for r in rows:
    if r["pdf_filename"] == A:
        for k in META:
            if r[k] != tgt[k]:
                log.append(dict(pdf_filename=A, action="edit", field=k, old=r[k], new=tgt[k],
                                reason=f"preprint merged into published version {B} (O.D., 19 Oct 2026)"))
                r[k] = tgt[k]
studies = {r["doi"] or r["journal"] + r["year"] + r["first_author"] for r in rows}
print(f"rows {len(rows)} | studies {len(studies)} | log lines {len(log)}")
assert len(studies) == 381, len(studies)
stamp = time.strftime("%Y%m%d_%H%M%S")
shutil.copy(DB, f"ExM_database_curated.pre_versionmerge_{stamp}.bak.csv")
with open(DB, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
with open("curation_log_20261009.csv", "a", newline="", encoding="utf-8") as fh:
    csv.DictWriter(fh, fieldnames=["pdf_filename", "action", "field", "old", "new", "reason"]).writerows(log)
# provenance: record the pair, as for the 29 pairs of 9 October
P = list(csv.DictReader(open("paper_provenance.csv", encoding="utf-8"))); PF = list(P[0].keys())
for p in P:
    if p["pdf"] == A: p["version_pair"] = f"earlier version of {B} (confirmed)"
    if p["pdf"] == B: p["version_pair"] = f"later version of {A} (confirmed)"
with open("paper_provenance.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=PF); w.writeheader(); w.writerows(P)
print("backup:", f"ExM_database_curated.pre_versionmerge_{stamp}.bak.csv")
