#!/usr/bin/env python3
"""
fix_suppliers.py — Fix antibody rows where label_supplier = "not stated".

For each paper with at least one "not stated" supplier, re-reads the PDF and
asks Haiku (cheap) to find supplier + catalogue number for those specific antibodies.

Uses claude-haiku-4-5-20251001 — about 10x cheaper than Sonnet.

Run AFTER retry_failed.py:
  $env:ANTHROPIC_API_KEY="sk-ant-..."
  python C:\\Users\\dudin\\Desktop\\ExM_Library\\fix_suppliers.py
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

MODEL       = "claude-haiku-4-5-20251001"
PAPERS_DIR  = Path(__file__).parent / "papers"
OUTPUT_CSV  = Path(__file__).parent / "exm_database.csv"
LOG_FILE    = Path(__file__).parent / "fix_suppliers.log"
MAX_CHARS   = 60000   # Methods section is almost always in the first 60k chars
RETRY_ATTEMPTS = 2
RETRY_DELAY    = 5

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

Return ONLY valid JSON — no markdown:
{{
  "results": [
    {{
      "label_name": "exact name as given in the list above",
      "supplier": "company name | gift: [lab name] | in-house | not stated",
      "catalogue_number": "exact code as written in paper, or null"
    }}
  ]
}}

Use "not stated" ONLY when you have searched the full text and truly cannot find any supplier information.

PAPER TEXT:
{text}"""


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


def call_api(client, prompt: str, log_f) -> dict | None:
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            return json.loads(raw)
        except json.JSONDecodeError as e:
            log_f.write(f"  JSON error attempt {attempt+1}: {e}\n")
        except Exception as e:
            log_f.write(f"  API error attempt {attempt+1}: {type(e).__name__}: {e}\n")
            if "rate" in str(e).lower():
                time.sleep(30)
        if attempt < RETRY_ATTEMPTS - 1:
            time.sleep(RETRY_DELAY)
    return None


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY first:  $env:ANTHROPIC_API_KEY='sk-ant-...'")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Read full CSV
    rows = []
    fieldnames = None
    with open(OUTPUT_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(dict(row))

    print(f"Loaded {len(rows)} rows from {OUTPUT_CSV.name}")

    # Find papers with "not stated" primary/secondary/nanobody suppliers
    papers_to_fix = defaultdict(list)   # pdf_filename -> [row indices]
    for i, row in enumerate(rows):
        if (row.get("label_supplier") == "not stated"
                and row.get("label_type") in ("primary_antibody", "secondary_antibody", "nanobody")
                and row.get("label_name")):
            papers_to_fix[row["pdf_filename"]].append(i)

    print(f"Papers with at least one 'not stated' supplier: {len(papers_to_fix)}")
    print(f"Total 'not stated' antibody rows to fix: {sum(len(v) for v in papers_to_fix.values())}\n")

    total_fixed = 0

    with open(LOG_FILE, "w", encoding="utf-8") as log_f:
        for paper_num, (fname, row_indices) in enumerate(sorted(papers_to_fix.items()), 1):

            # Build de-duplicated list of antibody names for this paper
            seen = set()
            antibody_entries = []
            for idx in row_indices:
                name   = rows[idx].get("label_name", "").strip()
                target = rows[idx].get("label_target", "").strip()
                if name and name not in seen:
                    seen.add(name)
                    antibody_entries.append((name, target, idx))

            print(f"[{paper_num}/{len(papers_to_fix)}] {fname} — {len(antibody_entries)} antibodies",
                  end=" ... ", flush=True)
            log_f.write(f"\n{'='*60}\n{fname}\n")

            pdf_path = PAPERS_DIR / fname
            if not pdf_path.exists():
                print("FILE NOT FOUND")
                log_f.write("FILE NOT FOUND\n")
                continue

            raw_text = extract_pdf_text(pdf_path)
            if len(raw_text) < 200:
                print("SKIP (scanned PDF)")
                log_f.write("SKIP: scanned\n")
                continue

            text = clean_text(raw_text[:MAX_CHARS])

            antibody_list = "\n".join(
                f"- {name}" + (f" (targets: {target})" if target else "")
                for name, target, _ in antibody_entries
            )
            log_f.write(f"Antibodies:\n{antibody_list}\n")

            result = call_api(
                client,
                SUPPLIER_PROMPT.format(antibody_list=antibody_list, text=text),
                log_f
            )

            if not result:
                print("FAILED (API/parse error)")
                continue

            # Build lookup: normalized label_name -> {supplier, catalogue_number}
            lookup = {}
            for r in result.get("results", []):
                key = r.get("label_name", "").strip().lower()
                if key:
                    lookup[key] = {
                        "label_supplier":         r.get("supplier", "not stated") or "not stated",
                        "label_catalogue_number":  str(r.get("catalogue_number") or ""),
                    }

            # Update matching rows
            fixed_count = 0
            for name, target, idx in antibody_entries:
                match = lookup.get(name.lower())
                if not match:
                    # Try partial match
                    for k, v in lookup.items():
                        if k in name.lower() or name.lower() in k:
                            match = v
                            break

                if match and match["label_supplier"] not in ("not stated", "", None):
                    old = rows[idx]["label_supplier"]
                    rows[idx]["label_supplier"] = match["label_supplier"]
                    # Only fill catalogue number if currently empty
                    if match["label_catalogue_number"] and not rows[idx].get("label_catalogue_number"):
                        rows[idx]["label_catalogue_number"] = match["label_catalogue_number"]
                    fixed_count += 1
                    log_f.write(f"  FIXED: {name} -> {match['label_supplier']} {match['label_catalogue_number']}\n")
                else:
                    log_f.write(f"  NOT FOUND: {name}\n")

            total_fixed += fixed_count
            print(f"fixed {fixed_count}/{len(antibody_entries)}")
            time.sleep(0.3)

    # Write updated CSV back
    print(f"\nWriting {len(rows)} rows back to {OUTPUT_CSV.name} ...")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done. Fixed {total_fixed} supplier entries total.")
    print(f"Detailed log: {LOG_FILE}")


if __name__ == "__main__":
    main()
