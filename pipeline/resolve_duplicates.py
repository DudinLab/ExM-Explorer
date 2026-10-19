#!/usr/bin/env python3
"""
resolve_duplicates.py — Classify the 166 duplicate-flagged paper pairs using CrossRef.

Reads qc_flags.csv (check = duplicate), queries CrossRef for both DOIs in each pair,
and outputs resolved_duplicates.csv with a verdict for each pair.

No Anthropic API needed — CrossRef is free.

Verdicts
────────
  keep_journal   — confirmed preprint + journal pair; DELETE the preprint row
  keep_both      — probably distinct papers despite high title similarity; KEEP both
  review         — CrossRef returned conflicting or missing data; check manually

Output: resolved_duplicates.csv
  Columns: file_a, file_b, doi_a, doi_b, type_a, type_b,
           crossref_title_a, crossref_title_b, verdict, reason

Usage:
    python resolve_duplicates.py
"""

import csv
import json
import time
import urllib.request
import urllib.parse
import re
import difflib
from pathlib import Path
from collections import defaultdict

QC_FLAGS = Path(__file__).parent / "qc_flags.csv"
CSV_FILE = Path(__file__).parent / "exm_database.csv"
OUTPUT   = Path(__file__).parent / "resolved_duplicates.csv"

CROSSREF_URL = "https://api.crossref.org/works/{doi}?mailto=omaya.dudin@unige.ch"

# These container-title/institution strings mark a preprint server
PREPRINT_MARKERS = {
    "biorxiv", "medrxiv", "research square", "researchsquare",
    "preprint", "ssrn", "chemrxiv", "authorea",
}


# ── CrossRef helpers ────────────────────────────────────────────────────────────

def crossref_lookup(doi: str) -> dict | None:
    if not doi or doi.strip() in ("", "null", "N/A"):
        return None
    doi = doi.strip()
    url = CROSSREF_URL.format(doi=urllib.parse.quote(doi, safe="/"))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ExM-QC/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("message", {})
    except Exception:
        return None


def work_type(cr: dict) -> str:
    """Return 'preprint', 'journal', or 'unknown'."""
    if not cr:
        return "unknown"

    wtype = cr.get("type", "")

    # Explicit preprint type
    if wtype in ("posted-content",):
        return "preprint"

    # Check institution/group names
    for inst in cr.get("institution", []):
        name = inst.get("name", "").lower()
        if any(m in name for m in PREPRINT_MARKERS):
            return "preprint"

    # Check container-title
    for ct in cr.get("container-title", []):
        if any(m in ct.lower() for m in PREPRINT_MARKERS):
            return "preprint"

    if wtype == "journal-article":
        return "journal"

    # Fallback: look at publisher
    publisher = cr.get("publisher", "").lower()
    if any(m in publisher for m in PREPRINT_MARKERS):
        return "preprint"

    return "unknown"


def cr_title(cr: dict) -> str:
    titles = cr.get("title", [])
    return titles[0] if titles else ""


def title_sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    # Build DOI lookup from main CSV
    doi_map = {}
    with open(CSV_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            fname = row.get("pdf_filename", "")
            if fname and fname not in doi_map:
                doi_map[fname] = row.get("doi", "").strip()

    # Load duplicate flags
    # detail format: "Possible duplicate of: FILE_B | title_sim=1.00 ..."
    # pdf_filename column = file_a
    pairs = []
    seen = set()
    with open(QC_FLAGS, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("check") != "duplicate":
                continue
            file_a = row.get("pdf_filename", "").strip()
            detail = row.get("detail", "")
            m = re.match(r"Possible duplicate of:\s+(.+?)\s+\|", detail)
            if not m:
                continue
            file_b = m.group(1).strip()

            # Deduplicate pairs (A↔B and B↔A are the same)
            key = tuple(sorted([file_a, file_b]))
            if key in seen:
                continue
            seen.add(key)

            pairs.append({
                "file_a": file_a,
                "file_b": file_b,
                "doi_a":  doi_map.get(file_a, ""),
                "doi_b":  doi_map.get(file_b, ""),
                "original_detail": detail,
            })

    print(f"Loaded {len(pairs)} duplicate pairs to resolve\n")

    out_rows = []
    cache = {}  # doi → crossref result

    for i, pair in enumerate(pairs, 1):
        file_a, file_b = pair["file_a"], pair["file_b"]
        doi_a,  doi_b  = pair["doi_a"],  pair["doi_b"]

        print(f"[{i:3d}/{len(pairs)}] {file_a}  ↔  {file_b}", end=" ... ", flush=True)

        # CrossRef lookups (cached)
        if doi_a not in cache:
            cache[doi_a] = crossref_lookup(doi_a)
            time.sleep(0.2)
        if doi_b not in cache:
            cache[doi_b] = crossref_lookup(doi_b)
            time.sleep(0.2)

        cr_a = cache[doi_a]
        cr_b = cache[doi_b]

        type_a = work_type(cr_a)
        type_b = work_type(cr_b)
        title_a = cr_title(cr_a) if cr_a else ""
        title_b = cr_title(cr_b) if cr_b else ""
        sim = title_sim(title_a, title_b) if (title_a and title_b) else None

        # ── Verdict logic ──────────────────────────────────────────────────────
        verdict = "review"
        reason  = ""

        types = {type_a, type_b}

        if "preprint" in types and "journal" in types:
            # Classic preprint + journal pair
            if sim is None or sim >= 0.80:
                verdict = "keep_journal"
                preprint_file = file_a if type_a == "preprint" else file_b
                reason = f"Preprint+journal pair (CrossRef types: {type_a}/{type_b}). Delete: {preprint_file}"
            else:
                verdict = "review"
                reason = f"Types suggest preprint+journal but CrossRef titles differ (sim={sim:.2f})"

        elif types == {"preprint", "preprint"}:
            # Two preprints — likely same work on different servers (bioRxiv + ResearchSquare)
            if sim is None or sim >= 0.85:
                verdict = "keep_journal"  # keep neither is unusual; flag for manual pick
                reason = f"Two preprints of same work. Keep whichever has more data; delete the other."
            else:
                verdict = "review"
                sim_str = f"{sim:.2f}" if sim is not None else "n/a"
                reason = f"Two preprints but titles differ (sim={sim_str})"

        elif types == {"journal", "journal"}:
            # Two journal papers — might be genuinely distinct or same paper in two journals
            if sim is not None and sim >= 0.90:
                verdict = "review"
                reason = f"Both journal papers with very similar titles (sim={sim:.2f}) — possible duplicate publication"
            else:
                verdict = "keep_both"
                sim_str = f"{sim:.2f}" if sim is not None else "n/a"
                reason = f"Both journal papers, titles differ enough (sim={sim_str}) — likely distinct"

        elif "unknown" in types:
            verdict = "review"
            reason = f"CrossRef returned type 'unknown' for one or both DOIs ({type_a}/{type_b})"
            if not doi_a or not doi_b:
                reason += " — missing DOI"

        else:
            verdict = "review"
            reason = f"Unexpected type combination: {type_a}/{type_b}"

        print(f"{verdict}  ({type_a}/{type_b})")

        out_rows.append({
            "file_a":           file_a,
            "file_b":           file_b,
            "doi_a":            doi_a,
            "doi_b":            doi_b,
            "type_a":           type_a,
            "type_b":           type_b,
            "crossref_title_a": title_a,
            "crossref_title_b": title_b,
            "title_similarity": f"{sim:.3f}" if sim is not None else "",
            "verdict":          verdict,
            "reason":           reason,
        })

    # Write output
    fieldnames = ["file_a","file_b","doi_a","doi_b","type_a","type_b",
                  "crossref_title_a","crossref_title_b","title_similarity",
                  "verdict","reason"]

    with open(OUTPUT, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    # Summary
    from collections import Counter
    verdicts = Counter(r["verdict"] for r in out_rows)
    print(f"\nDone. Results → {OUTPUT.name}")
    print(f"  keep_journal : {verdicts['keep_journal']:3d}  (delete the preprint from these pairs)")
    print(f"  keep_both    : {verdicts['keep_both']:3d}  (distinct papers, no action needed)")
    print(f"  review       : {verdicts['review']:3d}  (manual check required)")


if __name__ == "__main__":
    main()
