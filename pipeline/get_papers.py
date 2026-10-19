"""
get_papers.py — ExM Paper Library: PDF Recovery Tool
DudinLab, University of Geneva

Run AFTER harvest.py. Does two things:

1. PMC RETRY — re-attempts every paper in library.csv that wasn't downloaded:
   - Papers with a PMCID but failed download → retry PMC direct
   - Papers with a PMID but no PMCID → look up PMC via elink API
   - bioRxiv preprints → retry biorxiv direct PDF
   - Everything else → try Unpaywall one more time carefully

2. BROWSER BATCHES — generates HTML files for the remaining paywalled papers
   so you can open them in your browser and save PDFs manually via your
   university access. 20 papers per batch file, sorted by journal.

Usage:
    python get_papers.py

Output:
    More PDFs in ExM_Library/papers/
    ExM_Library/browser_batches/batch_01.html, batch_02.html, ...
    ExM_Library/library.csv updated with new download statuses
"""

import csv
import logging
import math
import os
import pathlib
import re
import sys
import time
import urllib.parse
from datetime import datetime

try:
    import requests
except ImportError:
    print("ERROR: run  pip install requests  first")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config — mirrors harvest.py
# ---------------------------------------------------------------------------
EMAIL = "omaya.dudin@unige.ch"
DESKTOP = pathlib.Path.home() / "Desktop"
BASE_DIR = DESKTOP / "ExM_Library"
PAPERS_DIR = BASE_DIR / "papers"
BATCHES_DIR = BASE_DIR / "browser_batches"
LIBRARY_CSV = BASE_DIR / "library.csv"
LOG_FILE = BASE_DIR / "get_papers.log"

BATCH_SIZE = 20
DOWNLOAD_DELAY = 0.8
ELINK_DELAY = 0.4
MAX_RETRIES = 3
DOWNLOAD_TIMEOUT = 60

CSV_FIELDS = [
    "doi", "pmid", "pmcid", "title", "first_author", "last_author",
    "year", "journal", "source", "is_oa", "pdf_status", "pdf_source",
    "oa_note", "pdf_filename", "preprint_doi", "has_preprint",
    "preprint_available", "abstract_snippet", "pubmed_url", "epmc_url",
    "doi_url",
]

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    PAPERS_DIR.mkdir(exist_ok=True)
    BATCHES_DIR.mkdir(parents=True, exist_ok=True)
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
def http_get(url, params=None, stream=False, timeout=20, headers=None):
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, params=params, stream=stream,
                             timeout=timeout, headers=headers or {})
            if r.status_code == 429:
                wait = 5 * (2 ** attempt)
                log.warning(f"Rate-limited, waiting {wait}s")
                time.sleep(wait)
                continue
            return r
        except requests.exceptions.RequestException as e:
            if attempt == MAX_RETRIES - 1:
                log.debug(f"Failed: {url[:60]} — {e}")
                return None
            time.sleep(2 ** attempt)
    return None


def safe_filename(doi):
    return re.sub(r"[^\w.\-]", "_", doi) + ".pdf"


def pmc_clean(pmcid):
    """Ensure PMCID has PMC prefix."""
    if not pmcid:
        return None
    pmcid = pmcid.strip()
    return pmcid if pmcid.startswith("PMC") else "PMC" + pmcid


def download_pdf(url, dest_path):
    """Download a PDF. Returns True on success."""
    try:
        headers = {"User-Agent": f"ExM-Library/1.0 (mailto:{EMAIL})"}
        r = http_get(url, stream=True, timeout=DOWNLOAD_TIMEOUT, headers=headers)
        if r is None or r.status_code != 200:
            return False
        content_type = r.headers.get("content-type", "")
        chunks = []
        for chunk in r.iter_content(8192):
            chunks.append(chunk)
        data = b"".join(chunks)
        if not data.startswith(b"%PDF"):
            return False
        with open(dest_path, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        log.debug(f"Download error {url[:60]}: {e}")
        if pathlib.Path(dest_path).exists():
            os.remove(dest_path)
        return False


def progress(current, total, label=""):
    pct = int(100 * current / total) if total else 0
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"\r  [{bar}] {pct:3d}%  {current}/{total}  {label:<45}", end="", flush=True)


# ---------------------------------------------------------------------------
# Step 1 — look up missing PMCIDs via elink
# ---------------------------------------------------------------------------
def lookup_pmcids(papers):
    """For papers with PMID but no PMCID, query PMC elink."""
    need_lookup = [p for p in papers
                   if p.get("pmid") and not p.get("pmcid")
                   and p.get("pdf_status") in ("paywalled", "download_failed", "oa_landing_only")]

    log.info(f"Looking up PMC IDs for {len(need_lookup)} papers via elink...")
    found = 0

    for i, paper in enumerate(need_lookup):
        progress(i, len(need_lookup), paper.get("title", "")[:40])
        pmid = paper["pmid"]
        r = http_get(f"{PUBMED_BASE}/elink.fcgi", params={
            "dbfrom": "pubmed", "db": "pmc",
            "id": pmid, "retmode": "json",
        })
        if r and r.status_code == 200:
            try:
                data = r.json()
                linksets = data.get("linksets", [])
                for ls in linksets:
                    for link in ls.get("linksetdbs", []):
                        if link.get("dbto") == "pmc" and link.get("links"):
                            pmcid = "PMC" + str(link["links"][0])
                            paper["pmcid"] = pmcid
                            paper["is_oa"] = "yes"
                            found += 1
                            log.debug(f"Found PMC: {pmid} → {pmcid}")
                            break
            except Exception:
                pass
        time.sleep(ELINK_DELAY)

    print()
    log.info(f"Found {found} new PMC IDs")
    return found


# ---------------------------------------------------------------------------
# Step 2 — retry downloads
# ---------------------------------------------------------------------------
def retry_downloads(papers):
    """Attempt download for all papers not yet successfully downloaded."""
    to_retry = [p for p in papers if p.get("pdf_status") != "downloaded"]
    log.info(f"Retrying downloads for {len(to_retry)} papers...")

    stats = {"downloaded": 0, "still_failed": 0}

    for i, paper in enumerate(to_retry):
        progress(i, len(to_retry), paper.get("title", "")[:40])

        doi = paper.get("doi", "")
        if not doi:
            stats["still_failed"] += 1
            continue

        fname = safe_filename(doi)
        dest = PAPERS_DIR / fname

        if dest.exists():
            paper["pdf_status"] = "downloaded"
            paper["pdf_filename"] = fname
            stats["downloaded"] += 1
            continue

        downloaded = False

        # --- Priority 1: PMCID direct ---
        pmcid = pmc_clean(paper.get("pmcid", ""))
        if pmcid:
            url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
            if download_pdf(url, dest):
                paper["pdf_status"] = "downloaded"
                paper["pdf_filename"] = fname
                paper["pdf_source"] = "pmc"
                paper["oa_note"] = f"PMC open access ({pmcid})"
                stats["downloaded"] += 1
                downloaded = True
                log.debug(f"PMC download OK: {pmcid}")

        # --- Priority 2: bioRxiv direct ---
        if not downloaded and "10.1101" in doi:
            # Try v1, v2, v3
            for ver in ["v1", "v2", "v3"]:
                url = f"https://www.biorxiv.org/content/{doi}{ver}.full.pdf"
                if download_pdf(url, dest):
                    paper["pdf_status"] = "downloaded"
                    paper["pdf_filename"] = fname
                    paper["pdf_source"] = f"biorxiv_{ver}"
                    paper["oa_note"] = f"bioRxiv preprint ({ver})"
                    stats["downloaded"] += 1
                    downloaded = True
                    break

        # --- Priority 3: preprint fallback ---
        if not downloaded and paper.get("preprint_doi"):
            pdoi = paper["preprint_doi"]
            if "10.1101" in pdoi:
                for ver in ["v1", "v2"]:
                    url = f"https://www.biorxiv.org/content/{pdoi}{ver}.full.pdf"
                    if download_pdf(url, dest):
                        paper["pdf_status"] = "downloaded"
                        paper["pdf_filename"] = fname
                        paper["pdf_source"] = "biorxiv_preprint_fallback"
                        paper["oa_note"] = f"bioRxiv preprint of published paper ({ver})"
                        stats["downloaded"] += 1
                        downloaded = True
                        break

        # --- Priority 4: Unpaywall careful retry ---
        if not downloaded and doi and "10.1101" not in doi:
            r = http_get(
                f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi, safe='')}",
                params={"email": EMAIL}, timeout=15,
            )
            if r and r.status_code == 200:
                try:
                    data = r.json()
                    # Try all OA locations, not just the best one
                    locations = data.get("oa_locations", [])
                    for loc in locations:
                        pdf_url = loc.get("url_for_pdf")
                        if pdf_url and download_pdf(pdf_url, dest):
                            paper["pdf_status"] = "downloaded"
                            paper["pdf_filename"] = fname
                            paper["pdf_source"] = "unpaywall"
                            paper["oa_note"] = f"OA via {loc.get('host_type','?')} ({loc.get('version','?')})"
                            stats["downloaded"] += 1
                            downloaded = True
                            break
                except Exception:
                    pass
            time.sleep(0.3)

        if not downloaded:
            paper["pdf_status"] = "paywalled"
            stats["still_failed"] += 1

        time.sleep(DOWNLOAD_DELAY)

    print()
    return stats


# ---------------------------------------------------------------------------
# Step 3 — generate browser batch HTML files
# ---------------------------------------------------------------------------
def generate_browser_batches(papers):
    """Generate paginated HTML files for manual download via browser."""
    paywalled = [p for p in papers
                 if p.get("pdf_status") in ("paywalled", "download_failed", "oa_landing_only")]

    if not paywalled:
        log.info("No paywalled papers — no batch files needed.")
        return

    # Sort by journal then year — groups institutional access efficiently
    paywalled.sort(key=lambda p: (p.get("journal", "zzz").lower(), p.get("year", "")))

    total_batches = math.ceil(len(paywalled) / BATCH_SIZE)
    log.info(f"Generating {total_batches} browser batch files for {len(paywalled)} paywalled papers...")

    for b in range(total_batches):
        batch = paywalled[b * BATCH_SIZE: (b + 1) * BATCH_SIZE]
        batch_num = b + 1
        html = make_batch_html(batch, batch_num, total_batches, len(paywalled))
        out_path = BATCHES_DIR / f"batch_{batch_num:02d}.html"
        out_path.write_text(html, encoding="utf-8")

    # Write an index file
    index_html = make_index_html(total_batches, len(paywalled))
    (BATCHES_DIR / "index.html").write_text(index_html, encoding="utf-8")

    log.info(f"Browser batches written to: {BATCHES_DIR}")
    log.info(f"Open {BATCHES_DIR / 'index.html'} in your browser to start")


def make_batch_html(papers, batch_num, total_batches, total_papers):
    start_n = (batch_num - 1) * BATCH_SIZE + 1
    end_n = start_n + len(papers) - 1

    rows_html = ""
    for i, p in enumerate(papers):
        n = start_n + i
        doi = p.get("doi", "")
        title = (p.get("title") or "?")
        title_short = title[:90] + ("…" if len(title) > 90 else "")
        authors = f"{p.get('first_author','?')} … {p.get('last_author','?')}"
        journal = p.get("journal", "?")
        year = p.get("year", "?")
        doi_url = f"https://doi.org/{doi}" if doi else "#"
        pubmed_url = p.get("pubmed_url", "")
        fname = safe_filename(doi) if doi else "unknown.pdf"

        rows_html += f"""
        <tr>
          <td class="num">{n}</td>
          <td class="title">
            <a href="{doi_url}" target="_blank" title="{title}">{title_short}</a>
            <div class="fname">Save as: {fname}</div>
          </td>
          <td class="auth">{authors}</td>
          <td class="jnl">{journal}<br><span class="yr">{year}</span></td>
          <td class="links">
            <a href="{doi_url}" target="_blank">DOI</a>
            {f'<a href="{pubmed_url}" target="_blank">PubMed</a>' if pubmed_url else ''}
          </td>
        </tr>"""

    prev_link = (f'<a href="batch_{batch_num-1:02d}.html">← Batch {batch_num-1}</a>'
                 if batch_num > 1 else '<span></span>')
    next_link = (f'<a href="batch_{batch_num+1:02d}.html">Batch {batch_num+1} →</a>'
                 if batch_num < total_batches else '<span></span>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ExM Papers Batch {batch_num}/{total_batches}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f7f7f5; color: #1a1a1a; padding: 2rem 1rem; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ color: #C0006A; font-size: 20px; margin-bottom: 4px; }}
  .meta {{ font-size: 13px; color: #666; margin-bottom: 1.2rem; }}
  .box {{ background: #fce8f1; border-left: 3px solid #C0006A; padding: 12px 16px;
          border-radius: 4px; font-size: 13px; margin-bottom: 1.5rem; line-height: 1.7; }}
  .box code {{ background: #fff; padding: 1px 5px; border-radius: 3px; font-size: 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px;
           background: #fff; border-radius: 8px; overflow: hidden;
           box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  th {{ text-align: left; padding: 9px 12px; border-bottom: 2px solid #C0006A;
        color: #C0006A; font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; }}
  td {{ padding: 9px 12px; border-bottom: 1px solid #f0f0ec; vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #fafaf8; }}
  td.num {{ width: 36px; color: #aaa; font-size: 12px; padding-top: 11px; }}
  td.title a {{ color: #1a1a1a; text-decoration: none; font-weight: 500; line-height: 1.4; }}
  td.title a:hover {{ color: #C0006A; }}
  .fname {{ font-size: 11px; color: #999; margin-top: 3px; font-family: monospace; }}
  td.auth {{ font-size: 12px; color: #555; width: 180px; }}
  td.jnl {{ font-size: 12px; width: 160px; }}
  .yr {{ color: #999; }}
  td.links a {{ color: #C0006A; text-decoration: none; margin-right: 8px;
                font-size: 12px; font-weight: 500; }}
  td.links a:hover {{ text-decoration: underline; }}
  .nav {{ display: flex; justify-content: space-between; align-items: center;
          margin-top: 1.5rem; font-size: 14px; }}
  .nav a {{ color: #C0006A; text-decoration: none; font-weight: 500; padding: 6px 14px;
            background: #fff; border-radius: 6px; border: 1px solid #e8a0c0; }}
  .nav a:hover {{ background: #fce8f1; }}
  .nav .center {{ color: #666; font-size: 13px; }}
  .back {{ margin-bottom: 1rem; }}
  .back a {{ color: #C0006A; font-size: 13px; text-decoration: none; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="back"><a href="index.html">← Back to index</a></div>
  <h1>ExM Paper Library — Batch {batch_num} of {total_batches}</h1>
  <div class="meta">Papers {start_n}–{end_n} of {total_papers} needing manual download</div>
  <div class="box">
    <strong>How to use:</strong> Click each <strong>DOI</strong> link →
    paper opens in browser → your UniGe access should give the PDF →
    File → Save As → use the filename shown in grey below the title →
    save to <code>Desktop\\ExM_Library\\papers\\</code>
  </div>
  <table>
    <thead>
      <tr><th>#</th><th>Title</th><th>Authors</th><th>Journal</th><th>Links</th></tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
  <div class="nav">
    {prev_link}
    <span class="center">Batch {batch_num} / {total_batches}</span>
    {next_link}
  </div>
</div>
</body>
</html>"""


def make_index_html(total_batches, total_papers):
    batch_links = ""
    for b in range(1, total_batches + 1):
        start = (b - 1) * BATCH_SIZE + 1
        end = min(b * BATCH_SIZE, total_papers)
        batch_links += f"""
        <a class="batch-link" href="batch_{b:02d}.html">
          <span class="bn">Batch {b}</span>
          <span class="br">Papers {start}–{end}</span>
        </a>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ExM Paper Library — Manual Download Index</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f7f7f5; color: #1a1a1a; padding: 2rem 1rem; }}
  .wrap {{ max-width: 700px; margin: 0 auto; }}
  h1 {{ color: #C0006A; font-size: 22px; margin-bottom: 6px; }}
  .meta {{ font-size: 13px; color: #666; margin-bottom: 1.5rem; }}
  .box {{ background: #fce8f1; border-left: 3px solid #C0006A; padding: 14px 18px;
          border-radius: 4px; font-size: 13px; margin-bottom: 2rem; line-height: 1.7; }}
  .box code {{ background: #fff; padding: 1px 6px; border-radius: 3px; font-size: 12px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }}
  .batch-link {{ display: block; background: #fff; border: 1px solid #e0e0dc;
                 border-radius: 8px; padding: 14px 16px; text-decoration: none;
                 color: #1a1a1a; transition: border-color 0.15s, box-shadow 0.15s; }}
  .batch-link:hover {{ border-color: #C0006A; box-shadow: 0 2px 8px rgba(192,0,106,0.1); }}
  .bn {{ display: block; font-weight: 600; font-size: 15px; margin-bottom: 3px; }}
  .br {{ display: block; font-size: 12px; color: #888; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>ExM Paper Library</h1>
  <div class="meta">{total_papers} papers to download manually · {total_batches} batches of {BATCH_SIZE}</div>
  <div class="box">
    <strong>Instructions:</strong> Open each batch, click DOI links one by one,
    save PDFs using the filename shown, move to
    <code>Desktop\\ExM_Library\\papers\\</code><br><br>
    <strong>Tip:</strong> Papers are sorted by journal — do all Nature Methods,
    all Cell, etc. in one sitting to make the most of your institutional access.
  </div>
  <div class="grid">{batch_links}</div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# CSV read / write
# ---------------------------------------------------------------------------
def read_library():
    if not LIBRARY_CSV.exists():
        log.error(f"library.csv not found at {LIBRARY_CSV}")
        log.error("Run harvest.py first.")
        sys.exit(1)
    with open(LIBRARY_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_library(papers):
    with open(LIBRARY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(papers)
    log.info(f"library.csv updated: {len(papers)} papers")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    setup_logging()
    log.info("=" * 60)
    log.info("ExM Library — PDF Recovery")
    log.info(f"Library: {LIBRARY_CSV}")
    log.info("=" * 60)

    papers = read_library()
    total = len(papers)
    already = sum(1 for p in papers if p.get("pdf_status") == "downloaded")
    log.info(f"Loaded {total} papers ({already} already downloaded, {total - already} to retry)")

    # Step 1 — find new PMCIDs
    log.info("\n[1/3] Looking up missing PMC IDs...")
    new_pmcids = lookup_pmcids(papers)

    # Step 2 — retry all downloads
    log.info("\n[2/3] Retrying downloads...")
    stats = retry_downloads(papers)

    # Save updated CSV
    write_library(papers)

    downloaded_total = sum(1 for p in papers if p.get("pdf_status") == "downloaded")
    paywalled_total = sum(1 for p in papers if p.get("pdf_status") == "paywalled")

    log.info(f"\nDownload results:")
    log.info(f"  Newly downloaded:  {stats['downloaded']}")
    log.info(f"  Total downloaded:  {downloaded_total}")
    log.info(f"  Still paywalled:   {paywalled_total}")

    # Step 3 — browser batches for the rest
    log.info("\n[3/3] Generating browser batch files...")
    generate_browser_batches(papers)

    log.info("\n" + "=" * 60)
    log.info("DONE")
    log.info(f"  New PMC IDs found:  {new_pmcids}")
    log.info(f"  New PDFs:           {stats['downloaded']}")
    log.info(f"  Total PDFs:         {downloaded_total}")
    log.info(f"  Browser batches:    {BATCHES_DIR}")
    log.info(f"  Open this to start: {BATCHES_DIR / 'index.html'}")
    log.info("=" * 60)
    print(f"\nOpen  {BATCHES_DIR / 'index.html'}  in your browser to download the rest.")


if __name__ == "__main__":
    main()
