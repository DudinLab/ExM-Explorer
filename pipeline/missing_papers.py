"""
missing_papers.py — Show what still needs downloading and regenerate browser batches
DudinLab, University of Geneva

Reads both library.csv AND library_rejected.csv, finds everything not yet
downloaded, and generates fresh browser batch HTML files.

Usage:
    python missing_papers.py
"""

import csv
import math
import pathlib
import sys
import re

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DESKTOP   = pathlib.Path.home() / "Desktop"
BASE_DIR  = DESKTOP / "ExM_Library"
BATCHES_DIR = BASE_DIR / "browser_batches"
BATCH_SIZE  = 20

# ---------------------------------------------------------------------------
def read_csv(path):
    if not path.exists():
        print(f"Not found: {path}")
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def safe_filename(doi):
    return re.sub(r"[^\w.\-]", "_", doi) + ".pdf"

# ---------------------------------------------------------------------------
# HTML generation (same style as get_papers.py)
# ---------------------------------------------------------------------------
def make_batch_html(papers, batch_num, total_batches, total_papers):
    start_n = (batch_num - 1) * BATCH_SIZE + 1
    end_n   = start_n + len(papers) - 1

    rows_html = ""
    for i, p in enumerate(papers):
        n      = start_n + i
        doi    = p.get("doi", "")
        title  = (p.get("title") or "?")
        tshort = title[:90] + ("…" if len(title) > 90 else "")
        auth   = f"{p.get('first_author','?')} … {p.get('last_author','?')}"
        jnl    = p.get("journal", "?")
        year   = p.get("year", "?")
        src    = p.get("filter_decision", p.get("source", ""))
        tag    = ""
        if "reject" in src:
            tag = '<span class="tag rej">rejected</span>'
        elif src == "keep_review":
            tag = '<span class="tag rev">no abstract</span>'

        doi_url    = f"https://doi.org/{doi}" if doi else "#"
        pubmed_url = p.get("pubmed_url", "")
        fname      = safe_filename(doi) if doi else "unknown.pdf"

        rows_html += f"""
        <tr>
          <td class="num">{n}</td>
          <td class="title">
            <a href="{doi_url}" target="_blank" title="{title}">{tshort}</a>
            {tag}
            <div class="fname">Save as: {fname}</div>
          </td>
          <td class="auth">{auth}</td>
          <td class="jnl">{jnl}<br><span class="yr">{year}</span></td>
          <td class="links">
            <a href="{doi_url}" target="_blank">DOI</a>
            {f'<a href="{pubmed_url}" target="_blank">PubMed</a>' if pubmed_url else ''}
          </td>
        </tr>"""

    prev = (f'<a href="batch_{batch_num-1:02d}.html">← Batch {batch_num-1}</a>'
            if batch_num > 1 else '<span></span>')
    nxt  = (f'<a href="batch_{batch_num+1:02d}.html">Batch {batch_num+1} →</a>'
            if batch_num < total_batches else '<span></span>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ExM Papers Batch {batch_num}/{total_batches}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        background:#f7f7f5;color:#1a1a1a;padding:2rem 1rem}}
  .wrap{{max-width:1100px;margin:0 auto}}
  h1{{color:#C0006A;font-size:20px;margin-bottom:4px}}
  .meta{{font-size:13px;color:#666;margin-bottom:1.2rem}}
  .box{{background:#fce8f1;border-left:3px solid #C0006A;padding:12px 16px;
        border-radius:4px;font-size:13px;margin-bottom:1.5rem;line-height:1.7}}
  .box code{{background:#fff;padding:1px 5px;border-radius:3px;font-size:12px}}
  table{{width:100%;border-collapse:collapse;font-size:13px;background:#fff;
         border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
  th{{text-align:left;padding:9px 12px;border-bottom:2px solid #C0006A;
      color:#C0006A;font-size:10px;text-transform:uppercase;letter-spacing:.06em}}
  td{{padding:9px 12px;border-bottom:1px solid #f0f0ec;vertical-align:top}}
  tr:last-child td{{border-bottom:none}}
  tr:hover td{{background:#fafaf8}}
  td.num{{width:36px;color:#aaa;font-size:12px;padding-top:11px}}
  td.title a{{color:#1a1a1a;text-decoration:none;font-weight:500;line-height:1.4}}
  td.title a:hover{{color:#C0006A}}
  .fname{{font-size:11px;color:#999;margin-top:3px;font-family:monospace}}
  .tag{{display:inline-block;padding:1px 7px;border-radius:100px;font-size:10px;
        font-weight:500;margin-left:6px;vertical-align:middle}}
  .tag.rej{{background:#fde8e8;color:#c0392b}}
  .tag.rev{{background:#fff8e0;color:#8a6000}}
  td.auth{{font-size:12px;color:#555;width:180px}}
  td.jnl{{font-size:12px;width:160px}}
  .yr{{color:#999}}
  td.links a{{color:#C0006A;text-decoration:none;margin-right:8px;
              font-size:12px;font-weight:500}}
  td.links a:hover{{text-decoration:underline}}
  .nav{{display:flex;justify-content:space-between;align-items:center;
        margin-top:1.5rem;font-size:14px}}
  .nav a{{color:#C0006A;text-decoration:none;font-weight:500;padding:6px 14px;
          background:#fff;border-radius:6px;border:1px solid #e8a0c0}}
  .nav a:hover{{background:#fce8f1}}
  .nav .center{{color:#666;font-size:13px}}
  .back{{margin-bottom:1rem}}
  .back a{{color:#C0006A;font-size:13px;text-decoration:none}}
</style>
</head>
<body>
<div class="wrap">
  <div class="back"><a href="index.html">← Back to index</a></div>
  <h1>ExM Paper Library — Batch {batch_num} of {total_batches}</h1>
  <div class="meta">Papers {start_n}–{end_n} of {total_papers} still to download</div>
  <div class="box">
    <strong>How to use:</strong> Click <strong>DOI</strong> → paper opens →
    UniGe access gives PDF → File → Save As using the filename in grey →
    save to <code>Desktop\\ExM_Library\\papers\\</code><br>
    Papers tagged <span style="background:#fde8e8;color:#c0392b;padding:1px 6px;
    border-radius:3px;font-size:11px">rejected</span> were filtered out as
    non-core but included here in case you want them anyway.
  </div>
  <table>
    <thead><tr><th>#</th><th>Title</th><th>Authors</th><th>Journal</th><th>Links</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  <div class="nav">{prev}<span class="center">Batch {batch_num} / {total_batches}</span>{nxt}</div>
</div>
</body>
</html>"""


def make_index_html(total_batches, total_papers, kept, rejected_count):
    batch_links = ""
    for b in range(1, total_batches + 1):
        start = (b - 1) * BATCH_SIZE + 1
        end   = min(b * BATCH_SIZE, total_papers)
        batch_links += f"""
        <a class="bl" href="batch_{b:02d}.html">
          <span class="bn">Batch {b}</span>
          <span class="br">Papers {start}–{end}</span>
        </a>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ExM Paper Library — Download Index</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        background:#f7f7f5;color:#1a1a1a;padding:2rem 1rem}}
  .wrap{{max-width:700px;margin:0 auto}}
  h1{{color:#C0006A;font-size:22px;margin-bottom:6px}}
  .meta{{font-size:13px;color:#666;margin-bottom:.8rem}}
  .stats{{display:flex;gap:12px;margin-bottom:1.5rem;flex-wrap:wrap}}
  .stat{{background:#fff;border:1px solid #e0e0dc;border-radius:8px;
         padding:10px 16px;font-size:13px}}
  .stat strong{{display:block;font-size:20px;color:#C0006A}}
  .box{{background:#fce8f1;border-left:3px solid #C0006A;padding:14px 18px;
        border-radius:4px;font-size:13px;margin-bottom:2rem;line-height:1.7}}
  .box code{{background:#fff;padding:1px 6px;border-radius:3px;font-size:12px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}}
  .bl{{display:block;background:#fff;border:1px solid #e0e0dc;border-radius:8px;
       padding:14px 16px;text-decoration:none;color:#1a1a1a;transition:border-color .15s}}
  .bl:hover{{border-color:#C0006A;box-shadow:0 2px 8px rgba(192,0,106,.1)}}
  .bn{{display:block;font-weight:600;font-size:15px;margin-bottom:3px}}
  .br{{display:block;font-size:12px;color:#888}}
</style>
</head>
<body>
<div class="wrap">
  <h1>ExM Paper Library</h1>
  <div class="meta">Papers still needing manual download</div>
  <div class="stats">
    <div class="stat"><strong>{total_papers}</strong>still to download</div>
    <div class="stat"><strong>{kept}</strong>core ExM papers</div>
    <div class="stat"><strong>{rejected_count}</strong>rejected (included anyway)</div>
    <div class="stat"><strong>{total_batches}</strong>batches of {BATCH_SIZE}</div>
  </div>
  <div class="box">
    <strong>Tip:</strong> Papers are sorted by journal — do all Nature Methods,
    all Cell, etc. in one sitting for your UniGe access.<br>
    Save each PDF to <code>Desktop\\ExM_Library\\papers\\</code> using the
    filename shown under each title.
  </div>
  <div class="grid">{batch_links}</div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("ExM Library — Missing Papers")
    print("=" * 60)

    kept_papers     = read_csv(BASE_DIR / "library.csv")
    rejected_papers = read_csv(BASE_DIR / "library_rejected.csv")
    review_papers   = read_csv(BASE_DIR / "library_needs_review.csv")

    all_papers = kept_papers + rejected_papers + review_papers
    print(f"\nLoaded: {len(kept_papers)} kept + {len(rejected_papers)} rejected "
          f"+ {len(review_papers)} needs-review = {len(all_papers)} total")

    # Find not-yet-downloaded
    missing = [p for p in all_papers if p.get("pdf_status") != "downloaded"]
    already = len(all_papers) - len(missing)

    missing_kept     = [p for p in missing if p.get("filter_decision","keep") in ("keep","keep_review","")]
    missing_rejected = [p for p in missing if "reject" in p.get("filter_decision","")]

    print(f"\nAlready downloaded:  {already}")
    print(f"Still missing:       {len(missing)}")
    print(f"  of which core:     {len(missing_kept)}")
    print(f"  of which rejected: {len(missing_rejected)}")

    if not missing:
        print("\nNothing left to download!")
        return

    # Sort by journal for efficient batch downloading
    missing.sort(key=lambda p: (p.get("journal","zzz").lower(), p.get("year","")))

    # Generate batch files
    BATCHES_DIR.mkdir(parents=True, exist_ok=True)
    total_batches = math.ceil(len(missing) / BATCH_SIZE)
    print(f"\nGenerating {total_batches} batch files → {BATCHES_DIR}")

    for b in range(total_batches):
        batch   = missing[b * BATCH_SIZE: (b+1) * BATCH_SIZE]
        bn      = b + 1
        html    = make_batch_html(batch, bn, total_batches, len(missing))
        out     = BATCHES_DIR / f"batch_{bn:02d}.html"
        out.write_text(html, encoding="utf-8")

    index_html = make_index_html(total_batches, len(missing),
                                  len(missing_kept), len(missing_rejected))
    (BATCHES_DIR / "index.html").write_text(index_html, encoding="utf-8")

    print(f"Done. Open this in your browser:")
    print(f"\n  {BATCHES_DIR / 'index.html'}\n")


if __name__ == "__main__":
    main()
