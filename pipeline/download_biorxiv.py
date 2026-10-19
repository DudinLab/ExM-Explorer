"""
download_biorxiv.py — Download all bioRxiv preprints in the ExM library
DudinLab, University of Geneva

Scans library.csv, library_rejected.csv, and library_needs_review.csv for
any paper with a bioRxiv DOI (10.1101/...) that hasn't been downloaded yet,
and downloads the PDF directly from biorxiv.org.

bioRxiv papers are always free — no institutional access needed.

Usage:
    python download_biorxiv.py
"""

import csv
import io
import logging
import pathlib
import re
import sys
import time

try:
    import requests
except ImportError:
    print("ERROR: run  pip install requests  first")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
EMAIL     = "omaya.dudin@unige.ch"
DESKTOP   = pathlib.Path.home() / "Desktop"
BASE_DIR  = DESKTOP / "ExM_Library"
PAPERS_DIR = BASE_DIR / "papers"
LOG_FILE  = BASE_DIR / "download_biorxiv.log"

CSV_FILES = [
    "library.csv",
    "library_rejected.csv",
    "library_needs_review.csv",
]

DELAY   = 1.0   # seconds between downloads — polite to biorxiv.org
TIMEOUT = 60

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    PAPERS_DIR.mkdir(exist_ok=True)
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
# Helpers
# ---------------------------------------------------------------------------
def safe_filename(doi):
    return re.sub(r"[^\w.\-]", "_", doi) + ".pdf"


def download_biorxiv_pdf(doi):
    """
    Try to download a bioRxiv PDF, trying v1 then v2 then v3.
    Returns (success: bool, version: str or None).
    """
    dest = PAPERS_DIR / safe_filename(doi)
    if dest.exists():
        return True, "cached"

    # Use real browser headers — bioRxiv serves HTML to bots
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/pdf,text/html,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
    })

    for v in [1, 2, 3]:
        url = f"https://www.biorxiv.org/content/{doi}v{v}.full.pdf"
        try:
            session.headers["Referer"] = f"https://www.biorxiv.org/content/{doi}v{v}"
            r = session.get(url, stream=True, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                continue
            # Read first chunk to verify it's a PDF before writing
            chunks = []
            first = True
            for chunk in r.iter_content(8192):
                if first:
                    if not chunk.startswith(b"%PDF"):
                        break   # Not a PDF — bioRxiv served HTML
                    first = False
                chunks.append(chunk)
            else:
                # Loop completed without break — it's a real PDF
                data = b"".join(chunks)
                dest.write_bytes(data)
                return True, f"v{v}"
        except Exception as e:
            log.debug(f"  {url} — {e}")
            continue

    return False, None


def read_csv_file(path):
    if not path.exists():
        return [], []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return rows, fieldnames


def write_csv_file(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def progress(current, total, label=""):
    pct = int(100 * current / total) if total else 0
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"\r  [{bar}] {pct:3d}%  {current}/{total}  {label:<50}",
          end="", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    setup()
    log.info("=" * 60)
    log.info("bioRxiv PDF Downloader — DudinLab ExM Library")
    log.info("=" * 60)

    # Load all CSV files and find bioRxiv papers not yet downloaded
    all_files = {}   # filename -> (rows, fieldnames)
    to_download = [] # list of (doi, csv_filename, row_index)

    for fname in CSV_FILES:
        path = BASE_DIR / fname
        rows, fieldnames = read_csv_file(path)
        all_files[fname] = (rows, fieldnames)

        for i, row in enumerate(rows):
            doi = row.get("doi", "")
            status = row.get("pdf_status", "")
            if doi.startswith("10.1101/") and status != "downloaded":
                to_download.append((doi, fname, i))

    if not to_download:
        log.info("No bioRxiv papers left to download.")
        return

    # Deduplicate DOIs (same paper may appear in multiple CSVs)
    seen_dois = set()
    unique = []
    for doi, fname, idx in to_download:
        if doi not in seen_dois:
            seen_dois.add(doi)
            unique.append((doi, fname, idx))

    log.info(f"Found {len(to_download)} bioRxiv entries across all files")
    log.info(f"Unique DOIs to download: {len(unique)}")
    log.info(f"Downloading to: {PAPERS_DIR}")
    log.info("")

    # Download
    results = {}  # doi -> (success, version)
    ok_count = fail_count = cached_count = 0

    for i, (doi, fname, idx) in enumerate(unique):
        progress(i, len(unique), doi)
        success, version = download_biorxiv_pdf(doi)
        results[doi] = (success, version)
        if success and version == "cached":
            cached_count += 1
        elif success:
            ok_count += 1
            log.debug(f"  ✓ {doi} ({version})")
        else:
            fail_count += 1
            log.debug(f"  ✗ {doi} — all versions failed")
        if version != "cached":
            time.sleep(DELAY)

    print()  # newline after progress bar

    # Update ALL CSV files with download results
    for fname in CSV_FILES:
        rows, fieldnames = all_files[fname]
        updated = 0
        for row in rows:
            doi = row.get("doi", "")
            if doi in results:
                success, version = results[doi]
                if success and version != "cached":
                    row["pdf_status"]   = "downloaded"
                    row["pdf_source"]   = "biorxiv_direct"
                    row["pdf_filename"] = safe_filename(doi)
                    row["oa_note"]      = f"bioRxiv preprint ({version})"
                    updated += 1
        if updated:
            write_csv_file(BASE_DIR / fname, rows, fieldnames)
            log.info(f"Updated {fname}: {updated} rows")

    # Summary
    log.info("")
    log.info("=" * 60)
    log.info(f"DONE")
    log.info(f"  Downloaded:      {ok_count}")
    log.info(f"  Already had:     {cached_count}")
    log.info(f"  Failed:          {fail_count}")
    if fail_count:
        log.info(f"  Failed DOIs (all versions tried):")
        for doi, (success, _) in results.items():
            if not success:
                log.info(f"    {doi}  →  https://doi.org/{doi}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
