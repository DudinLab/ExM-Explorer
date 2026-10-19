"""
filter_library.py — ExM Paper Library Filter
DudinLab, University of Geneva

Reads library.csv and filters down to papers that:
  1. Actually perform Expansion Microscopy (not just cite or review it)
  2. Use antibodies as part of the protocol

Papers you already downloaded (pdf_status = downloaded) are always kept.
Papers with no abstract are kept but flagged for manual review.
Everything else is scored on title + abstract and either kept or rejected.

Outputs:
  library.csv             — REPLACED with filtered version (kept papers only)
  library_rejected.csv    — rejected papers (audit trail, never deleted)
  library_review.csv      — no-abstract papers needing manual check

Usage:
    python filter_library.py
"""

import csv
import logging
import pathlib
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DESKTOP = pathlib.Path.home() / "Desktop"
BASE_DIR = DESKTOP / "ExM_Library"
LIBRARY_CSV     = BASE_DIR / "library.csv"
REJECTED_CSV    = BASE_DIR / "library_rejected.csv"
REVIEW_CSV      = BASE_DIR / "library_needs_review.csv"
LOG_FILE        = BASE_DIR / "filter.log"

SCORE_THRESHOLD = 3   # keep if score >= this

# ---------------------------------------------------------------------------
# Scoring vocabulary
# ---------------------------------------------------------------------------
EXPANSION_TERMS = [
    "expansion microscopy", "u-exm", "proexm", "expath", "exfish",
    "trex", "magnify", "cryo-exm", "ultrastructure expansion",
    "magnified analysis", "expansion factor", "acrylamide gel",
    "gelation", "sodium acrylate", "expanded gel", "gel expansion",
    "post-expansion", "pre-expansion", "expansion protocol",
    "isotropic expansion", "hydrogel expansion", "physical expansion",
]

ANTIBODY_TERMS = [
    "antibod", "immunostain", "immunofluoresc",
    "primary antibod", "secondary antibod",
    "anti-tubulin", "anti-actin", "anti-gfp", "anti-ha",
    "alexa fluor", "nhs-ester", "nanobod", "immunolabel",
    "monoclonal", "polyclonal", "epitope",
]

DOING_EXPERIMENT_TERMS = [
    "fixed", "fixation", "formaldehyde", "paraformaldehyde", "pfa",
    "staining", "labelling", "labeling", "immunostain",
    "anchoring", "acryloyl", "gelation", "denaturation",
    "proteinase k", "digestion",
]

REVIEW_TERMS = [
    "we review", "this review", "review of", "review article",
    "perspective", "commentary", "overview of", "prospects for",
    "advances in", "progress in", "introduction to", "tutorial",
    "do-it-yourself", "spinning disk confocal", "spinning-disk",
    "light sheet", "light-sheet microscopy",
    "cryo-electron", "cryo-em", "cryo-et",
    "single molecule localization", "smfish", "seqfish", "merfish",
    "super-resolution review",
]

REVIEW_JOURNALS = [
    "nature reviews", "annual review", "trends in cell",
    "trends in biochem", "current opinion", "essays in biochem",
    "seminars in cell", "chemical reviews", "chemical society reviews",
    "wiley interdisciplinary", "biological reviews",
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_paper(title, abstract, journal):
    """
    Score a paper on how likely it is to be a genuine ExM+antibody paper.
    Returns (score, list_of_reasons).
    """
    t = (title or "").lower()
    a = (abstract or "").lower()
    j = (journal or "").lower()
    full = t + " " + a

    score = 0
    reasons = []

    # ExM in title — strong signal
    if any(term in t for term in EXPANSION_TERMS):
        score += 2
        reasons.append("ExM in title")

    # ExM in abstract — moderate signal
    if any(term in a for term in EXPANSION_TERMS):
        score += 1
        reasons.append("ExM in abstract")

    # Antibody usage — required signal
    if any(term in full for term in ANTIBODY_TERMS):
        score += 2
        reasons.append("antibody mention")

    # Actually doing the experiment (fixation, staining, etc.)
    if any(term in a for term in DOING_EXPERIMENT_TERMS):
        score += 1
        reasons.append("experimental terms")

    # Review / wrong method — strong negative
    review_hits = [term for term in REVIEW_TERMS if term in full]
    if review_hits:
        score -= 3
        reasons.append(f"review/wrong-method term: '{review_hits[0]}'")

    # Review journal — additional negative
    journal_hits = [rj for rj in REVIEW_JOURNALS if rj in j]
    if journal_hits:
        score -= 2
        reasons.append(f"review journal: '{journal_hits[0]}'")

    return score, reasons


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    setup_logging()
    log.info("=" * 60)
    log.info("ExM Library Filter — DudinLab")
    log.info(f"Input:  {LIBRARY_CSV}")
    log.info("=" * 60)

    if not LIBRARY_CSV.exists():
        log.error("library.csv not found. Run harvest.py first.")
        sys.exit(1)

    with open(LIBRARY_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        papers = list(reader)

    log.info(f"Loaded {len(papers)} papers")

    # Add filter columns to fieldnames
    extra_fields = ["filter_score", "filter_decision", "filter_reason"]
    out_fields = list(fieldnames) + [f for f in extra_fields if f not in fieldnames]

    keep, rejected, needs_review = [], [], []

    for p in papers:
        title    = p.get("title", "")
        abstract = p.get("abstract_snippet", "")
        journal  = p.get("journal", "")
        doi      = p.get("doi", "")
        status   = p.get("pdf_status", "")

        # Always keep papers already downloaded
        if status == "downloaded":
            p["filter_score"]    = "kept"
            p["filter_decision"] = "keep"
            p["filter_reason"]   = "already downloaded"
            keep.append(p)
            continue

        # No abstract — keep but flag
        if not abstract.strip():
            p["filter_score"]    = "n/a"
            p["filter_decision"] = "keep_review"
            p["filter_reason"]   = "no abstract — needs manual check"
            needs_review.append(p)
            continue

        # Score it
        score, reasons = score_paper(title, abstract, journal)
        reason_str = "; ".join(reasons)
        p["filter_score"]  = str(score)
        p["filter_reason"] = reason_str

        if score >= SCORE_THRESHOLD:
            p["filter_decision"] = "keep"
            keep.append(p)
        else:
            if score < 0:
                p["filter_decision"] = "reject_review"
            else:
                p["filter_decision"] = "reject_weak"
            rejected.append(p)

    total_kept     = len(keep) + len(needs_review)
    total_rejected = len(rejected)

    log.info(f"\nResults:")
    log.info(f"  Keep (downloaded):        {sum(1 for p in keep if p['filter_reason']=='already downloaded')}")
    log.info(f"  Keep (scored >= {SCORE_THRESHOLD}):       {sum(1 for p in keep if p['filter_decision']=='keep' and p['filter_reason']!='already downloaded')}")
    log.info(f"  Keep (no abstract/check): {len(needs_review)}")
    log.info(f"  Reject (reviews):         {sum(1 for p in rejected if p['filter_decision']=='reject_review')}")
    log.info(f"  Reject (weak signal):     {sum(1 for p in rejected if p['filter_decision']=='reject_weak')}")
    log.info(f"  ─────────────────────────────")
    log.info(f"  Total kept:               {total_kept}")
    log.info(f"  Total rejected:           {total_rejected}")
    log.info(f"  Reduction:                {len(papers)} → {total_kept} ({100*total_rejected//len(papers)}% removed)")

    # Confirm before overwriting
    print(f"\n  {len(papers)} papers → {total_kept} kept, {total_rejected} rejected")
    answer = input("  Overwrite library.csv with filtered version? [y/n]: ").strip().lower()
    if answer != "y":
        log.info("Aborted — no files changed.")
        return

    # Write filtered library.csv
    kept_all = keep + needs_review
    kept_all.sort(key=lambda p: (p.get("year", ""), p.get("first_author", "")))
    with open(LIBRARY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept_all)
    log.info(f"Wrote library.csv: {len(kept_all)} papers")

    # Write rejected CSV (audit trail)
    rejected.sort(key=lambda p: p.get("filter_decision", ""))
    with open(REJECTED_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rejected)
    log.info(f"Wrote library_rejected.csv: {len(rejected)} papers")

    # Write needs-review CSV
    if needs_review:
        with open(REVIEW_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(needs_review)
        log.info(f"Wrote library_needs_review.csv: {len(needs_review)} papers")

    log.info("\nDone.")
    log.info(f"  Open library_rejected.csv to audit what was removed.")
    if needs_review:
        log.info(f"  Open library_needs_review.csv to manually check {len(needs_review)} papers.")


if __name__ == "__main__":
    main()
