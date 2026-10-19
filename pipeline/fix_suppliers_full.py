#!/usr/bin/env python3
"""
fix_suppliers_full.py — Full supplier extraction pass for all papers with antibodies.

Processes every paper in the database that has at least one primary antibody,
secondary antibody, or nanobody row — regardless of current supplier value.
This is a clean full run combining the original fix_suppliers.py logic with
two critical bug fixes:

  Fix 1 — Robust JSON extraction:
    The original script only stripped markdown if the response STARTED with ```.
    Haiku often prefixes JSON with a prose sentence ("Here is what I found:"),
    making that check fail and json.loads blow up on plain text.
    This version searches the full response for any valid JSON object.

  Fix 2 — Batched antibody lists:
    Papers with many antibodies (e.g. 45) overflow max_tokens=2048 and produce
    a truncated JSON string that cannot be parsed. This version sends at most
    15 antibodies per API call and merges the results.

Run:
    $env:ANTHROPIC_API_KEY="sk-ant-..."
    python C:\\Users\\dudin\\Desktop\\ExM_Library\\fix_suppliers_full.py
"""

import anthropic
import csv
import json
import os
import re
import sys
import time
import pymupdf
from collections import defaultdict
from pathlib import Path

MODEL          = "claude-haiku-4-5-20251001"
PAPERS_DIR     = Path(__file__).parent / "papers"
OUTPUT_CSV     = Path(__file__).parent / "exm_database.csv"
LOG_FILE       = Path(__file__).parent / "fix_suppliers_full.log"
MAX_CHARS      = 60000
BATCH_SIZE     = 15      # antibodies per API call
MAX_TOKENS     = 4096
RETRY_ATTEMPTS = 3
RETRY_DELAY    = 10

SUPPLIER_PROMPT = """You are extracting antibody supplier and catalogue number information from a scientific paper.

Find the supplier and catalogue number for EACH of the following antibodies/labels.
Search thoroughly: Methods, Materials, Supplementary methods, antibody tables, figure legends.

Antibodies to find:
{antibody_list}

SEARCH PATTERNS — suppliers appear in many formats:
- Inline parenthetical: "anti-tubulin (ab5821, Abcam)" → supplier=Abcam, cat=ab5821
- After company name: "Cell Signaling Technology (#3700)" → supplier=Cell Signaling Technology, cat=3700
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

CATALOGUE NUMBER FORMATS:
ab#### (Abcam) | sc-#### (Santa Cruz) | ##### or ####S (Cell Signaling) |
PA#-##### (Thermo) | T#### or F#### (Sigma) | ####-#-## (Proteintech) |
A-##### or A##### (Invitrogen/Molecular Probes) | any alphanumeric code near a company name

Return ONLY the JSON object below — no markdown fences, no preamble, no explanation:
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_pdf_text(pdf_path: Path) -> str:
    try:
        doc = pymupdf.open(str(pdf_path))
        text = "".join(doc[i].get_text() for i in range(len(doc)))
        doc.close()
        return text
    except Exception:
        return ""


def clean_text(text: str) -> str:
    for old, new in [
        ("°", "deg"), ("µ", "u"), ("α", "alpha"), ("β", "beta"),
        ("γ", "gamma"), ("–", "-"), ("—", "-"), ("×", "x"),
        ("±", "+/-"), ("'", "'"), (""", '"'), (""", '"'),
    ]:
        text = text.replace(old, new)
    return text


def extract_json(raw: str) -> dict | None:
    """
    Extract a JSON object from the model response regardless of surrounding text.

    Tries four strategies in order:
      1. Direct parse (response is pure JSON)
      2. Strip a ```json ... ``` fence
      3. Find {"results": ...} anywhere in the response (handles preamble prose)
      4. Find any {...} block as a last resort
    """
    raw = raw.strip()

    # 1. Direct
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2. Markdown fence
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 3. "results" key anywhere in response
    m = re.search(r'(\{"results"\s*:.*\})', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 4. Any {...} block
    m = re.search(r'(\{.*\})', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    return None


def call_api_batched(client, text: str, antibody_entries: list, log_f) -> dict:
    """
    Send antibodies in batches of BATCH_SIZE. Merge all results into one lookup.
    Returns {normalised_label_name: {label_supplier, label_catalogue_number}}.
    """
    lookup = {}
    total_batches = (len(antibody_entries) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_i, batch_start in enumerate(range(0, len(antibody_entries), BATCH_SIZE), 1):
        batch = antibody_entries[batch_start: batch_start + BATCH_SIZE]

        antibody_list = "\n".join(
            f"- {name}" + (f" (targets: {target})" if target else "")
            for name, target, _ in batch
        )
        prompt = SUPPLIER_PROMPT.format(antibody_list=antibody_list, text=text)

        for attempt in range(RETRY_ATTEMPTS):
            try:
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    messages=[{"role": "user", "content": prompt}]
                )
                raw  = response.content[0].text
                data = extract_json(raw)

                if data is None:
                    log_f.write(f"  batch {batch_i}/{total_batches} attempt {attempt+1}: "
                                f"no JSON found in: {raw[:200]}\n")
                    if attempt < RETRY_ATTEMPTS - 1:
                        time.sleep(RETRY_DELAY)
                    continue

                for r in data.get("results", []):
                    key = r.get("label_name", "").strip().lower()
                    if key:
                        lookup[key] = {
                            "label_supplier":         r.get("supplier", "not stated") or "not stated",
                            "label_catalogue_number": str(r.get("catalogue_number") or ""),
                        }
                break  # success

            except Exception as e:
                log_f.write(f"  batch {batch_i}/{total_batches} attempt {attempt+1}: "
                            f"{type(e).__name__}: {e}\n")
                if "rate" in str(e).lower():
                    time.sleep(30)
                elif attempt < RETRY_ATTEMPTS - 1:
                    time.sleep(RETRY_DELAY)

        time.sleep(0.3)

    return lookup


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: $env:ANTHROPIC_API_KEY not set"); sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Load CSV
    rows, fieldnames = [], None
    with open(OUTPUT_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(dict(row))
    print(f"Loaded {len(rows)} rows from {OUTPUT_CSV.name}")

    # Group by paper — collect ALL antibody rows (not just "not stated")
    papers_with_antibodies = defaultdict(list)
    for i, row in enumerate(rows):
        if (row.get("label_type") in ("primary_antibody", "secondary_antibody", "nanobody")
                and row.get("label_name", "").strip()):
            papers_with_antibodies[row["pdf_filename"]].append(i)

    print(f"Papers with antibody rows: {len(papers_with_antibodies)}")
    print(f"Total antibody rows:       {sum(len(v) for v in papers_with_antibodies.values())}\n")

    total_updated = 0

    with open(LOG_FILE, "w", encoding="utf-8") as log_f:
        for paper_num, (fname, row_indices) in enumerate(sorted(papers_with_antibodies.items()), 1):

            # De-duplicate antibody names
            seen, antibody_entries = set(), []
            for idx in row_indices:
                name   = rows[idx].get("label_name", "").strip()
                target = rows[idx].get("label_target", "").strip()
                if name and name not in seen:
                    seen.add(name)
                    antibody_entries.append((name, target, idx))

            n_batches   = (len(antibody_entries) + BATCH_SIZE - 1) // BATCH_SIZE
            batch_note  = f" ({n_batches} batches)" if n_batches > 1 else ""
            print(f"[{paper_num}/{len(papers_with_antibodies)}] {fname} — "
                  f"{len(antibody_entries)} antibodies{batch_note}", end=" ... ", flush=True)
            log_f.write(f"\n{'='*60}\n{fname}\n")

            pdf_path = PAPERS_DIR / fname
            if not pdf_path.exists():
                print("FILE NOT FOUND"); log_f.write("FILE NOT FOUND\n"); continue

            raw_text = extract_pdf_text(pdf_path)
            if len(raw_text) < 200:
                print("SKIP (scanned)"); log_f.write("SKIP: scanned\n"); continue

            text   = clean_text(raw_text[:MAX_CHARS])
            lookup = call_api_batched(client, text, antibody_entries, log_f)

            # Apply results to ALL rows for this paper (not just index rows)
            updated = 0
            for name, target, idx in antibody_entries:
                match = lookup.get(name.lower())
                if not match:
                    for k, v in lookup.items():
                        if k in name.lower() or name.lower() in k:
                            match = v; break

                if match:
                    rows[idx]["label_supplier"] = match["label_supplier"]
                    if match["label_catalogue_number"]:
                        rows[idx]["label_catalogue_number"] = match["label_catalogue_number"]
                    updated += 1
                    log_f.write(f"  SET: {name} -> {match['label_supplier']} "
                                f"{match['label_catalogue_number']}\n")
                else:
                    log_f.write(f"  NO RESULT: {name}\n")

            total_updated += updated
            print(f"updated {updated}/{len(antibody_entries)}")

    # Write CSV
    print(f"\nWriting {len(rows)} rows to {OUTPUT_CSV.name} ...")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done. Updated {total_updated} antibody rows total.")
    print(f"Log: {LOG_FILE}")


if __name__ == "__main__":
    main()
