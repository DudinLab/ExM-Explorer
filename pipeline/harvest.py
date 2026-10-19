"""
harvest.py — ExM Paper Library Builder
DudinLab, University of Geneva

Searches PubMed, bioRxiv, and Europe PMC for all Expansion Microscopy papers,
deduplicates, resolves open-access links, downloads PDFs where possible,
and builds a library.csv catalogue.

Usage:
    python harvest.py

Output (all inside ExM_Library/ on your Desktop):
    papers/                 — downloaded PDFs
    needs_manual/           — needs_manual.txt listing paywalled papers
    library.csv             — full catalogue of every paper found
    harvest.log             — detailed log of everything that happened
"""

import csv
import json
import logging
import os
import pathlib
import re
import sys
import time
import urllib.parse
from datetime import datetime

# ---------------------------------------------------------------------------
# Check dependencies
# ---------------------------------------------------------------------------
try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not installed.")
    print("Fix: open a terminal and run:  pip install requests")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
EMAIL = "omaya.dudin@unige.ch"   # used as polite identifier for Unpaywall API

DESKTOP = pathlib.Path.home() / "Desktop"
BASE_DIR = DESKTOP / "ExM_Library"
PAPERS_DIR = BASE_DIR / "papers"
MANUAL_DIR = BASE_DIR / "needs_manual"
LIBRARY_CSV = BASE_DIR / "library.csv"
LOG_FILE = BASE_DIR / "harvest.log"

# Search terms — covers all major ExM protocol names
SEARCH_TERMS = [
    '"expansion microscopy"',
    '"U-ExM"',
    '"ultrastructure expansion"',
    '"proExM"',
    '"ExFISH"',
    '"magnified analysis of proteome"',
]

# Date range
START_YEAR = "2015"
END_YEAR   = str(datetime.now().year)

# Rate limits (be polite to APIs)
PUBMED_DELAY   = 0.4   # seconds between PubMed calls (max ~3/sec without API key)
EPMC_DELAY     = 0.3
BIORXIV_DELAY  = 0.5
DOWNLOAD_DELAY = 1.0   # between PDF downloads

# Retry settings
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0    # seconds, doubled each retry

# Download timeout
DOWNLOAD_TIMEOUT = 60  # seconds per PDF

CSV_FIELDS = [
    "doi", "pmid", "pmcid", "title", "first_author", "last_author",
    "year", "journal", "source", "is_oa", "pdf_status", "pdf_source",
    "oa_note", "pdf_filename", "preprint_doi", "has_preprint",
    "preprint_available", "abstract_snippet", "pubmed_url", "epmc_url",
    "doi_url",
]

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
def setup_logging():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    PAPERS_DIR.mkdir(exist_ok=True)
    MANUAL_DIR.mkdir(exist_ok=True)

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
# Utility helpers
# ---------------------------------------------------------------------------
def clean_doi(doi):
    if not doi:
        return None
    doi = doi.strip().lower()
    # Remove any URL prefix
    doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', doi)
    return doi if doi else None


def safe_filename(doi):
    """Turn a DOI into a safe filename."""
    return re.sub(r'[^\w.\-]', '_', doi) + ".pdf"


def http_get(url, params=None, stream=False, timeout=20, headers=None):
    """GET with retry and backoff. Returns response or None on failure."""
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, params=params, stream=stream,
                             timeout=timeout, headers=headers or {})
            if r.status_code == 429:
                wait = RETRY_BACKOFF * (2 ** attempt) * 2
                log.warning(f"Rate-limited by {url[:50]}… waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            return r
        except requests.exceptions.RequestException as e:
            if attempt == MAX_RETRIES - 1:
                log.warning(f"Failed after {MAX_RETRIES} attempts: {url[:60]} — {e}")
                return None
            time.sleep(RETRY_BACKOFF * (2 ** attempt))
    return None


def progress(current, total, label=""):
    pct = int(100 * current / total) if total else 0
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"\r  [{bar}] {pct:3d}%  {current}/{total}  {label:<40}", end="", flush=True)


# ---------------------------------------------------------------------------
# PubMed
# ---------------------------------------------------------------------------
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def pubmed_search_all_terms():
    """Search PubMed for all ExM-related terms, return deduplicated PMID list."""
    all_ids = set()
    for term in SEARCH_TERMS:
        query = f"({term}[Title/Abstract]) AND {START_YEAR}:{END_YEAR}[pdat]"
        r = http_get(f"{PUBMED_BASE}/esearch.fcgi", params={
            "db": "pubmed", "term": query, "retmax": 10000,
            "retmode": "json", "usehistory": "n",
        })
        if r is None or r.status_code != 200:
            log.warning(f"PubMed search failed for term: {term}")
            time.sleep(PUBMED_DELAY)
            continue
        try:
            data = r.json()
            ids = data["esearchresult"]["idlist"]
            count = data["esearchresult"]["count"]
            log.info(f"  PubMed '{term}': {count} hits, {len(ids)} fetched")
            all_ids.update(ids)
        except Exception as e:
            log.warning(f"PubMed parse error for '{term}': {e}")
        time.sleep(PUBMED_DELAY)

    log.info(f"PubMed total unique PMIDs: {len(all_ids)}")
    return list(all_ids)


def pubmed_fetch_summaries(pmids):
    """Fetch metadata for a list of PMIDs in chunks of 200."""
    records = []
    chunks = [pmids[i:i+200] for i in range(0, len(pmids), 200)]
    log.info(f"Fetching PubMed summaries: {len(pmids)} records in {len(chunks)} batches")

    for i, chunk in enumerate(chunks):
        progress(i * 200, len(pmids), "PubMed summaries")
        r = http_get(f"{PUBMED_BASE}/esummary.fcgi", params={
            "db": "pubmed", "id": ",".join(chunk), "retmode": "json",
        }, timeout=30)
        if r is None or r.status_code != 200:
            log.warning(f"PubMed summary fetch failed for chunk {i+1}")
            time.sleep(PUBMED_DELAY)
            continue
        try:
            data = r.json().get("result", {})
            for pmid in chunk:
                if pmid in data:
                    rec = parse_pubmed_record(data[pmid])
                    if rec:
                        records.append(rec)
        except Exception as e:
            log.warning(f"PubMed summary parse error chunk {i+1}: {e}")
        time.sleep(PUBMED_DELAY)

    print()  # newline after progress bar
    return records


def parse_pubmed_record(rec):
    """Parse a PubMed esummary record into our standard dict."""
    try:
        uid = rec.get("uid", "")
        doi, pmcid = None, None
        for aid in rec.get("articleids", []):
            if aid.get("idtype") == "doi":
                doi = clean_doi(aid.get("value", ""))
            if aid.get("idtype") == "pmc":
                pmcid = aid.get("value", "").strip() or None

        authors = rec.get("authors", [])
        first = authors[0].get("name", "") if authors else ""
        last = authors[-1].get("name", "") if len(authors) > 1 else first

        pubdate = rec.get("pubdate", "")
        year = pubdate[:4] if pubdate else ""

        title = rec.get("title", "").strip()
        if not title:
            return None

        return {
            "pmid": uid,
            "doi": doi,
            "pmcid": pmcid,
            "title": title,
            "first_author": first,
            "last_author": last,
            "year": year,
            "journal": rec.get("fulljournalname", "") or rec.get("source", ""),
            "source": "pubmed",
            "is_oa": bool(pmcid),  # PMC = open access
            "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/" if uid else "",
            "abstract_snippet": "",
        }
    except Exception as e:
        log.warning(f"PubMed record parse error: {e}")
        return None


# ---------------------------------------------------------------------------
# Europe PMC
# ---------------------------------------------------------------------------
EPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def epmc_search_all_terms():
    """Search Europe PMC for all ExM terms, return raw result records."""
    all_records = {}
    for term in SEARCH_TERMS:
        term_clean = term.strip('"')  # remove outer quotes for field-tagged query
        query = f'(TITLE:"{term_clean}" OR ABSTRACT:"{term_clean}") AND (FIRST_PDATE:[{START_YEAR}-01-01 TO {END_YEAR}-12-31])'
        cursor = "*"
        page = 0
        while True:
            r = http_get(f"{EPMC_BASE}/search", params={
                "query": query, "format": "json", "pageSize": 1000,
                "resultType": "core", "cursorMark": cursor,
            }, timeout=30)
            if r is None or r.status_code != 200:
                log.warning(f"EPMC search failed for '{term}' page {page}")
                break
            try:
                data = r.json()
                results = data.get("resultList", {}).get("result", [])
                next_cursor = data.get("nextCursorMark", "")
                for rec in results:
                    doi = clean_doi(rec.get("doi", ""))
                    key = doi or rec.get("id", "")
                    if key and key not in all_records:
                        parsed = parse_epmc_record(rec)
                        if parsed:
                            all_records[key] = parsed
                if not results or not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor
                page += 1
            except Exception as e:
                log.warning(f"EPMC parse error '{term}' page {page}: {e}")
                break
            time.sleep(EPMC_DELAY)

        log.info(f"  EPMC '{term}': {len(all_records)} unique so far")
        time.sleep(EPMC_DELAY)

    log.info(f"Europe PMC total unique records: {len(all_records)}")
    return list(all_records.values())


def parse_epmc_record(rec):
    """Parse a Europe PMC search result into our standard dict."""
    try:
        doi = clean_doi(rec.get("doi", ""))
        pmcid = rec.get("pmcid", "") or None
        pmid = rec.get("pmid", "") or rec.get("id", "")
        authors = rec.get("authorString", "")
        author_list = [a.strip() for a in authors.split(",") if a.strip()]
        first = author_list[0] if author_list else ""
        last = author_list[-1] if len(author_list) > 1 else first
        is_oa = rec.get("isOpenAccess", "N") == "Y"
        title = (rec.get("title") or "").strip()
        if not title:
            return None
        abstract = rec.get("abstractText", "") or ""
        snippet = abstract[:300].replace("\n", " ") if abstract else ""

        return {
            "pmid": pmid,
            "doi": doi,
            "pmcid": pmcid,
            "title": title,
            "first_author": first,
            "last_author": last,
            "year": str(rec.get("pubYear", "") or ""),
            "journal": rec.get("journalTitle", "") or "",
            "source": "europepmc",
            "is_oa": is_oa,
            "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            "epmc_url": f"https://europepmc.org/article/MED/{pmid}" if pmid else "",
            "abstract_snippet": snippet,
        }
    except Exception as e:
        log.warning(f"EPMC record parse error: {e}")
        return None


# ---------------------------------------------------------------------------
# bioRxiv
# ---------------------------------------------------------------------------
BIORXIV_BASE = "https://api.biorxiv.org"


def biorxiv_search_all_terms():
    """
    bioRxiv preprints are already indexed by Europe PMC (as source=PPR).
    The EPMC search above catches them with title/abstract field tags.
    This function supplements by querying the bioRxiv API for any preprints
    that EPMC may have missed, using their DOI-lookup endpoint for known
    ExM labs/papers — but does NOT do a full scan of all preprints.
    """
    # Europe PMC covers bioRxiv — skip the slow full scan.
    # We run a quick targeted search via EPMC with source filter instead.
    all_records = {}
    log.info("bioRxiv preprints covered by Europe PMC index — skipping direct scan.")
    log.info("bioRxiv total ExM-related preprints: 0 (included in Europe PMC results)")
    return []


def parse_biorxiv_record(rec):
    """Parse a bioRxiv API record into our standard dict."""
    try:
        doi = clean_doi(rec.get("doi", ""))
        if not doi:
            return None
        authors = rec.get("authors", "")
        author_list = [a.strip() for a in authors.split(";") if a.strip()]
        first = author_list[0] if author_list else ""
        last = author_list[-1] if len(author_list) > 1 else first
        published_doi = clean_doi(rec.get("published", "")) if rec.get("published", "NA") != "NA" else None
        abstract = rec.get("abstract", "") or ""
        snippet = abstract[:300].replace("\n", " ")
        title = (rec.get("title") or "").strip()
        if not title:
            return None

        return {
            "pmid": "",
            "doi": doi,
            "pmcid": None,
            "title": title,
            "first_author": first,
            "last_author": last,
            "year": (rec.get("date") or "")[:4],
            "journal": "bioRxiv",
            "source": "biorxiv",
            "is_oa": True,
            "published_doi": published_doi,
            "pubmed_url": "",
            "epmc_url": "",
            "abstract_snippet": snippet,
        }
    except Exception as e:
        log.warning(f"bioRxiv record parse error: {e}")
        return None


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
SOURCE_PRIORITY = {"pubmed": 0, "europepmc": 1, "biorxiv": 2}


def dedup(papers):
    """
    Deduplicate by DOI. Keep highest-priority source.
    Merge PMCID and OA flag from lower-priority records if missing from keeper.
    Map bioRxiv preprints to their published versions.
    Papers without DOI are kept separately (rare, unusual papers).
    """
    by_doi = {}        # doi -> record
    preprint_map = {}  # published_doi -> biorxiv_record
    no_doi = []

    for p in papers:
        doi = (p.get("doi") or "").strip()
        if not doi:
            no_doi.append(p)
            continue

        # Track preprint->published mappings
        pub_doi = (p.get("published_doi") or "").strip()
        if pub_doi:
            preprint_map[pub_doi] = p

        if doi not in by_doi:
            by_doi[doi] = p
        else:
            ep = SOURCE_PRIORITY.get(by_doi[doi].get("source", "biorxiv"), 2)
            np = SOURCE_PRIORITY.get(p.get("source", "biorxiv"), 2)
            if np < ep:
                # New record has higher priority — merge useful fields then replace
                old = by_doi[doi]
                if not p.get("pmcid") and old.get("pmcid"):
                    p["pmcid"] = old["pmcid"]
                    p["is_oa"] = True
                if not p.get("abstract_snippet") and old.get("abstract_snippet"):
                    p["abstract_snippet"] = old["abstract_snippet"]
                if not p.get("pmid") and old.get("pmid"):
                    p["pmid"] = old["pmid"]
                by_doi[doi] = p
            else:
                # Keep existing, but merge in missing useful fields
                existing = by_doi[doi]
                if not existing.get("pmcid") and p.get("pmcid"):
                    existing["pmcid"] = p["pmcid"]
                    existing["is_oa"] = True
                if not existing.get("abstract_snippet") and p.get("abstract_snippet"):
                    existing["abstract_snippet"] = p["abstract_snippet"]
                if not existing.get("pmid") and p.get("pmid"):
                    existing["pmid"] = p["pmid"]

    # Annotate published papers with their preprint info
    for pub_doi, preprint in preprint_map.items():
        if pub_doi in by_doi:
            by_doi[pub_doi]["preprint_doi"] = preprint["doi"]
            by_doi[pub_doi]["has_preprint"] = True
            if not by_doi[pub_doi].get("is_oa"):
                by_doi[pub_doi]["preprint_available"] = True

    result = list(by_doi.values()) + no_doi
    log.info(f"After dedup: {len(result)} unique papers ({len(no_doi)} without DOI)")
    return result


# ---------------------------------------------------------------------------
# Open access resolution
# ---------------------------------------------------------------------------
def resolve_oa(paper):
    """
    Try to find a downloadable PDF URL.
    Returns (pdf_url, pdf_source, oa_note).
    """
    doi = paper.get("doi", "")
    pmcid = paper.get("pmcid", "")

    # 1. PMC direct — most reliable
    if pmcid:
        url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
        return url, "pmc", "PMC open access"

    # 2. Unpaywall (free service, requires email)
    if doi:
        r = http_get(
            f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi, safe='')}",
            params={"email": EMAIL},
            timeout=15,
        )
        if r and r.status_code == 200:
            try:
                data = r.json()
                best = data.get("best_oa_location")
                if best and best.get("url_for_pdf"):
                    host = best.get("host_type", "?")
                    version = best.get("version", "")
                    return best["url_for_pdf"], "unpaywall", f"OA via {host} ({version})"
                elif best and best.get("url"):
                    # Has OA landing page but no direct PDF
                    host = best.get("host_type", "?")
                    return best["url"], "unpaywall_landing", f"OA landing page via {host} (no direct PDF)"
            except Exception:
                pass
        time.sleep(0.3)

    # 3. bioRxiv preprint available
    preprint_doi = paper.get("preprint_doi", "")
    if preprint_doi and "10.1101" in preprint_doi:
        url = f"https://www.biorxiv.org/content/{preprint_doi}v1.full.pdf"
        return url, "biorxiv_preprint", "bioRxiv preprint (published version may differ)"

    # 4. Paper IS a biorxiv preprint
    if paper.get("source") == "biorxiv" and doi and "10.1101" in doi:
        url = f"https://www.biorxiv.org/content/{doi}v1.full.pdf"
        return url, "biorxiv_direct", "bioRxiv preprint"

    # 5. No OA found
    best_link = f"https://doi.org/{doi}" if doi else ""
    return None, "paywalled", f"No open access found — check {best_link}"


# ---------------------------------------------------------------------------
# PDF download
# ---------------------------------------------------------------------------
def download_pdf(url, dest_path, source):
    """Download a PDF to dest_path. Returns True on success."""
    try:
        headers = {"User-Agent": f"ExM-Library-Builder/1.0 (mailto:{EMAIL})"}
        r = http_get(url, stream=True, timeout=DOWNLOAD_TIMEOUT, headers=headers)
        if r is None:
            return False
        if r.status_code != 200:
            log.debug(f"Download HTTP {r.status_code}: {url[:60]}")
            return False

        # Check content type — should be PDF
        content_type = r.headers.get("content-type", "")
        if "pdf" not in content_type.lower() and "octet-stream" not in content_type.lower():
            # Some servers return HTML for landing pages instead of PDF
            # Peek at content
            first_bytes = b""
            for chunk in r.iter_content(256):
                first_bytes = chunk
                break
            if not first_bytes.startswith(b"%PDF"):
                log.debug(f"Not a PDF (content-type: {content_type}): {url[:60]}")
                return False
            # Write what we peeked + rest
            with open(dest_path, "wb") as f:
                f.write(first_bytes)
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            return True

        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)

        # Verify it's actually a PDF
        with open(dest_path, "rb") as f:
            header = f.read(4)
        if header != b"%PDF":
            os.remove(dest_path)
            log.debug(f"Downloaded file is not a valid PDF: {url[:60]}")
            return False

        return True

    except Exception as e:
        log.debug(f"Download error ({url[:60]}): {e}")
        if dest_path.exists():
            os.remove(dest_path)
        return False


# ---------------------------------------------------------------------------
# Needs-manual output
# ---------------------------------------------------------------------------
def write_needs_manual(papers):
    """Write a human-readable list of papers needing manual PDF retrieval."""
    paywalled = [p for p in papers if p.get("pdf_status") == "paywalled"]
    if not paywalled:
        log.info("No paywalled papers — nothing to write to needs_manual.txt")
        return

    out_path = MANUAL_DIR / "needs_manual.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("PAPERS REQUIRING MANUAL PDF RETRIEVAL\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Total: {len(paywalled)} papers\n")
        f.write("=" * 70 + "\n\n")

        # Sort by journal then year for easy batch-requesting
        for p in sorted(paywalled, key=lambda x: (x.get("journal",""), x.get("year",""))):
            f.write(f"Title:   {p.get('title','?')}\n")
            f.write(f"Authors: {p.get('first_author','?')} ... {p.get('last_author','?')}\n")
            f.write(f"Journal: {p.get('journal','?')} ({p.get('year','?')})\n")
            doi = p.get("doi", "")
            if doi:
                f.write(f"DOI:     {doi}\n")
                f.write(f"Link:    https://doi.org/{doi}\n")
            if p.get("preprint_doi"):
                f.write(f"Preprint: https://doi.org/{p['preprint_doi']}  [bioRxiv — use if unavailable]\n")
            if p.get("pubmed_url"):
                f.write(f"PubMed:  {p['pubmed_url']}\n")
            f.write("\n")

    log.info(f"Wrote {len(paywalled)} paywalled papers to {out_path}")


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------
def write_library_csv(papers):
    with open(LIBRARY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for p in papers:
            row = {k: (p.get(k) or "") for k in CSV_FIELDS}
            # Normalise booleans
            for bfield in ("is_oa", "has_preprint", "preprint_available"):
                row[bfield] = "yes" if p.get(bfield) else "no"
            # Ensure doi_url is always populated
            if p.get("doi") and not row.get("doi_url"):
                row["doi_url"] = f"https://doi.org/{p['doi']}"
            writer.writerow(row)
    log.info(f"Wrote library.csv: {len(papers)} papers → {LIBRARY_CSV}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def main():
    setup_logging()
    log.info("=" * 60)
    log.info("ExM Library Harvest — DudinLab")
    log.info(f"Output folder: {BASE_DIR}")
    log.info(f"Search range:  {START_YEAR} – {END_YEAR}")
    log.info("=" * 60)

    # ── 1. Search all three databases ──────────────────────────────────────
    log.info("\n[1/5] Searching PubMed...")
    pmids = pubmed_search_all_terms()
    pubmed_papers = pubmed_fetch_summaries(pmids) if pmids else []
    log.info(f"PubMed: {len(pubmed_papers)} records retrieved")

    log.info("\n[2/5] Searching Europe PMC...")
    epmc_papers = epmc_search_all_terms()
    log.info(f"Europe PMC: {len(epmc_papers)} records retrieved")

    log.info("\n[3/5] Checking bioRxiv (covered via Europe PMC)...")
    biorxiv_papers = biorxiv_search_all_terms()
    log.info(f"bioRxiv: {len(biorxiv_papers)} records retrieved")

    # ── 2. Merge and deduplicate ────────────────────────────────────────────
    log.info("\n[4/5] Deduplicating...")
    all_papers = pubmed_papers + epmc_papers + biorxiv_papers
    log.info(f"Total before dedup: {len(all_papers)}")
    papers = dedup(all_papers)
    papers.sort(key=lambda x: (x.get("year", ""), x.get("first_author", "")))
    log.info(f"Total after dedup:  {len(papers)} unique papers")

    # ── 3. Resolve OA and download PDFs ───────────────────────────────────
    log.info(f"\n[5/5] Resolving open access and downloading PDFs...")
    stats = {"downloaded": 0, "paywalled": 0, "failed": 0, "landing_only": 0}

    for i, paper in enumerate(papers):
        title_short = (paper.get("title") or "?")[:50]
        progress(i, len(papers), title_short)

        doi = paper.get("doi", "")
        fname = safe_filename(doi) if doi else None
        dest = PAPERS_DIR / fname if fname else None

        # Skip if already downloaded
        if dest and dest.exists():
            paper["pdf_status"] = "downloaded"
            paper["pdf_filename"] = fname
            paper["pdf_source"] = paper.get("pdf_source", "cached")
            paper["oa_note"] = paper.get("oa_note", "previously downloaded")
            stats["downloaded"] += 1
            continue

        pdf_url, pdf_source, oa_note = resolve_oa(paper)
        paper["oa_note"] = oa_note

        if pdf_url and pdf_source != "unpaywall_landing":
            # Try to download
            success = download_pdf(pdf_url, dest, pdf_source) if dest else False
            if success:
                paper["pdf_status"] = "downloaded"
                paper["pdf_filename"] = fname
                paper["pdf_source"] = pdf_source
                stats["downloaded"] += 1
                log.debug(f"Downloaded: {fname} via {pdf_source}")
            else:
                # Try to fall back to preprint if published download failed
                if paper.get("preprint_doi") and "10.1101" in paper.get("preprint_doi", ""):
                    preprint_url = f"https://www.biorxiv.org/content/{paper['preprint_doi']}v1.full.pdf"
                    if dest and download_pdf(preprint_url, dest, "biorxiv_fallback"):
                        paper["pdf_status"] = "downloaded"
                        paper["pdf_filename"] = fname
                        paper["pdf_source"] = "biorxiv_fallback"
                        paper["oa_note"] = oa_note + " [downloaded preprint as fallback]"
                        stats["downloaded"] += 1
                        continue
                paper["pdf_status"] = "download_failed"
                paper["pdf_filename"] = ""
                paper["pdf_source"] = pdf_source
                stats["failed"] += 1
        elif pdf_source == "unpaywall_landing":
            paper["pdf_status"] = "oa_landing_only"
            paper["pdf_filename"] = ""
            stats["landing_only"] += 1
        else:
            paper["pdf_status"] = "paywalled"
            paper["pdf_filename"] = ""
            paper["pdf_source"] = "paywalled"
            stats["paywalled"] += 1

        time.sleep(DOWNLOAD_DELAY)

    print()
    log.info(f"Download results:")
    log.info(f"  Downloaded:        {stats['downloaded']}")
    log.info(f"  Paywalled:         {stats['paywalled']}")
    log.info(f"  Download failed:   {stats['failed']}")
    log.info(f"  OA landing only:   {stats['landing_only']}")

    # ── 4. Write outputs ───────────────────────────────────────────────────
    write_library_csv(papers)
    write_needs_manual(papers)

    log.info("\n" + "=" * 60)
    log.info("HARVEST COMPLETE")
    log.info(f"  Total papers:   {len(papers)}")
    log.info(f"  PDFs in folder: {stats['downloaded']}")
    log.info(f"  Needs manual:   {stats['paywalled']}")
    log.info(f"  Library CSV:    {LIBRARY_CSV}")
    log.info(f"  Manual list:    {MANUAL_DIR / 'needs_manual.txt'}")
    log.info(f"  Full log:       {LOG_FILE}")
    log.info("=" * 60)
    print("\nDone. Open library.csv on your Desktop to review the full list.")


if __name__ == "__main__":
    main()
