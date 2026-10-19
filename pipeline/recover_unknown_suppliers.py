#!/usr/bin/env python3
r"""
recover_unknown_suppliers.py  —  targeted, non-destructive supplier recovery.

Re-reads the source PDFs to recover supplier / catalogue number ONLY for the
~155 primary antibodies that currently have no identifier at all (no catalogue
number, no clone/product code in the name, no gift lab, no supplier).

Why a dedicated script (not fix_suppliers_full.py):
  * It reads/writes the CURRENT file  ExM_database_curated.csv  (not the old
    exm_database.csv).
  * It ONLY touches the anonymous rows. Every already-curated supplier
    (Sigma-Aldrich, etc., set by normalise_by_reference.py) is left untouched.
  * It fills a field only when it is currently blank / "not stated" — so it can
    never overwrite good data, and re-running it is safe.
  * It writes a timestamped backup and a review CSV of every change it made.

Model: claude-haiku-4-5  (same as the original supplier pass).

RUN (Windows PowerShell):
    pip install anthropic pymupdf
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    cd C:\Users\dudin\Desktop\ExM_Library
    python recover_unknown_suppliers.py
"""
import anthropic, csv, json, os, re, sys, time, shutil, datetime
import pymupdf
from collections import defaultdict
from pathlib import Path

HERE       = Path(__file__).parent
CSV_FILE   = HERE / "ExM_database_curated.csv"
PAPERS_DIR = HERE / "papers"
LOG_FILE   = HERE / "recover_unknown_suppliers.log"
REVIEW_CSV = HERE / "recover_unknown_suppliers_review.csv"
MODEL      = "claude-haiku-4-5-20251001"
MAX_CHARS, BATCH_SIZE, MAX_TOKENS = 60000, 15, 4096
RETRY_ATTEMPTS, RETRY_DELAY = 3, 10

BLANK = {"", "not stated", "na", "n/a", "none", "-", "unknown", "unspecified",
         "not specified", "not reported"}

def real(x): return x.strip() and x.strip().lower() not in BLANK
def is_gift(s): return s.strip().lower().startswith("gift")

def has_clone(name):
    for tok in re.split(r"[\s,()]+", name):
        if len(tok) < 2:
            continue
        if (re.search(r"\d", tok) and re.search(r"[A-Za-z]", tok)
                and tok.lower() not in ("igg1", "igg2", "igg2b", "h+l", "igg",
                                        "488", "594", "647", "405", "555", "568")):
            return True
    return bool(re.search(r"\bclone\b", name, re.I))

def is_unknown(row):
    """A primary/nanobody antibody with NO identifier of any kind."""
    if row.get("label_type") not in ("primary_antibody", "nanobody"):
        return False
    name = (row.get("label_name") or "").strip()
    if not name:
        return False
    if real(row.get("label_catalogue_number") or ""): return False
    if is_gift(row.get("label_supplier") or ""):       return False
    if real(row.get("label_supplier") or ""):          return False
    if has_clone(name):                                return False
    return True

SUPPLIER_PROMPT = """You are extracting antibody supplier and catalogue number information from a scientific paper.

Find the supplier and catalogue number for EACH of the following antibodies/labels.
Search thoroughly: Methods, Materials, Supplementary methods, antibody tables, figure legends.

Antibodies to find:
{antibody_list}

SEARCH PATTERNS — suppliers appear in many formats:
- Inline parenthetical: "anti-tubulin (ab5821, Abcam)" -> supplier=Abcam, cat=ab5821
- After company name: "Cell Signaling Technology (#3700)" -> supplier=Cell Signaling Technology, cat=3700
- In sentences: "purchased from Sigma-Aldrich (Cat. No. T6074)"
- In tables with separate columns for supplier and catalogue number
- After "obtained from", "provided by", "purchased from", "from"

KNOWN COMPANIES (recognise all name variants):
Abcam | Sigma-Aldrich/Sigma/Merck | Thermo Fisher Scientific/Thermo Fisher/Invitrogen/Life Technologies/Molecular Probes |
Proteintech | Cell Signaling Technology/CST | Santa Cruz Biotechnology/Santa Cruz | BD Biosciences/BD |
BioLegend | R&D Systems | Jackson ImmunoResearch | DSHB/Developmental Studies Hybridoma Bank |
Rockland | Millipore/EMD Millipore | GeneTex | Novus Biologicals/Novus | Bio-Rad |
Synaptic Systems/SYSY | MBL | Bethyl | Fitzgerald | ChromoTek | NanoTag | Enzo |
Cayman Chemical | Vector Laboratories | Alexa Fluor (if Invitrogen/Thermo branding)

Return ONLY the JSON object below - no markdown fences, no preamble, no explanation:
{{"results": [
  {{
    "label_name": "exact name as given in the list above",
    "supplier": "company name | gift: [lab name] | in-house | not stated",
    "catalogue_number": "exact code as written in paper, or null"
  }}
]}}

Use "not stated" ONLY when you have searched the full text and truly cannot find supplier information.

PAPER TEXT:
{text}"""

def extract_pdf_text(p):
    try:
        doc = pymupdf.open(str(p))
        t = "".join(doc[i].get_text() for i in range(len(doc)))
        doc.close(); return t
    except Exception:
        return ""

def clean_text(t):
    for a, b in [("°","deg"),("µ","u"),("α","alpha"),("β","beta"),("γ","gamma"),
                 ("–","-"),("—","-"),("×","x"),("±","+/-")]:
        t = t.replace(a, b)
    return t

def extract_json(raw):
    raw = raw.strip()
    for pat in (None, r"```(?:json)?\s*(\{.*?\})\s*```", r'(\{"results"\s*:.*\})', r'(\{.*\})'):
        try:
            return json.loads(raw if pat is None else re.search(pat, raw, re.DOTALL).group(1))
        except Exception:
            continue
    return None

def call_api(client, text, names, log_f):
    lookup = {}
    for start in range(0, len(names), BATCH_SIZE):
        batch = names[start:start + BATCH_SIZE]
        prompt = SUPPLIER_PROMPT.format(antibody_list="\n".join("- " + n for n in batch), text=text)
        for attempt in range(RETRY_ATTEMPTS):
            try:
                resp = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS,
                                               messages=[{"role": "user", "content": prompt}])
                data = extract_json(resp.content[0].text)
                if data is None:
                    if attempt < RETRY_ATTEMPTS - 1: time.sleep(RETRY_DELAY)
                    continue
                for r in data.get("results", []):
                    k = (r.get("label_name") or "").strip().lower()
                    if k:
                        lookup[k] = {"sup": (r.get("supplier") or "not stated"),
                                     "cat": str(r.get("catalogue_number") or "")}
                break
            except Exception as e:
                log_f.write(f"    api error: {type(e).__name__}: {e}\n")
                time.sleep(30 if "rate" in str(e).lower() else RETRY_DELAY)
        time.sleep(0.3)
    return lookup

def main():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("ERROR: ANTHROPIC_API_KEY is not set. In PowerShell:  $env:ANTHROPIC_API_KEY=\"sk-ant-...\"")
        sys.exit(1)
    client = anthropic.Anthropic(api_key=key)

    with open(CSV_FILE, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f); fields = reader.fieldnames
        rows = [dict(r) for r in reader]

    targets = [i for i, r in enumerate(rows) if is_unknown(r)]
    by_paper = defaultdict(list)
    for i in targets:
        by_paper[rows[i]["pdf_filename"]].append(i)
    print(f"Loaded {len(rows)} rows. Anonymous antibody rows to recover: {len(targets)} "
          f"across {len(by_paper)} papers.\n")
    if not targets:
        print("Nothing to do — no anonymous antibodies found."); return

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = CSV_FILE.with_suffix(f".pre_recover_{stamp}.bak.csv")
    shutil.copy2(CSV_FILE, backup)
    print(f"Backup written: {backup.name}\n")

    changes = []
    with open(LOG_FILE, "w", encoding="utf-8") as log_f:
        for n, (fname, idxs) in enumerate(sorted(by_paper.items()), 1):
            names = sorted({rows[i]["label_name"].strip() for i in idxs})
            print(f"[{n}/{len(by_paper)}] {fname} — {len(names)} antibodies ...", end=" ", flush=True)
            pdf = PAPERS_DIR / fname
            if not pdf.exists():
                print("PDF NOT FOUND"); log_f.write(f"{fname}: PDF NOT FOUND\n"); continue
            text = clean_text(extract_pdf_text(pdf)[:MAX_CHARS])
            if len(text) < 200:
                print("skip (scanned)"); continue
            lookup = call_api(client, text, names, log_f)
            filled = 0
            for i in idxs:
                nm = rows[i]["label_name"].strip()
                m = lookup.get(nm.lower())
                if not m:
                    for k, v in lookup.items():
                        if k in nm.lower() or nm.lower() in k:
                            m = v; break
                if not m: continue
                new_sup, new_cat = m["sup"].strip(), m["cat"].strip()
                # only fill blanks, only with real values
                if real(new_sup) and not real(rows[i].get("label_supplier") or ""):
                    changes.append({"pdf_filename": fname, "label_name": nm,
                                    "old_supplier": rows[i].get("label_supplier", ""),
                                    "new_supplier": new_sup, "new_catalogue": new_cat})
                    rows[i]["label_supplier"] = new_sup
                    if new_cat and not real(rows[i].get("label_catalogue_number") or ""):
                        rows[i]["label_catalogue_number"] = new_cat
                    filled += 1
            print(f"filled {filled}/{len(names)}")

    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    with open(REVIEW_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["pdf_filename", "label_name", "old_supplier",
                                          "new_supplier", "new_catalogue"])
        w.writeheader(); w.writerows(changes)

    print(f"\nDone. Recovered a supplier for {len(changes)} rows.")
    print(f"Review the changes in:  {REVIEW_CSV.name}")
    print(f"Backup (to restore if needed):  {backup.name}")

if __name__ == "__main__":
    main()
