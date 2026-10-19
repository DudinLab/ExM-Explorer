#!/usr/bin/env python3
"""
fix_suppliers_v2.py — Retry supplier extraction for papers that fix_suppliers.py failed on.

Run this AFTER fix_suppliers.py finishes. It reads the current CSV, finds all
rows still showing label_supplier = "not stated", and retries with two fixes:

  Fix 1 — Robust JSON extraction:
    fix_suppliers.py only stripped markdown if the response STARTED with ```.
    But Haiku often writes preamble text ("Here is the information I found:")
    before the JSON block, making raw.startswith("```") False and causing an
    immediate json.loads failure on prose. This version searches the full
    response for any {...} block, regardless of surrounding text.

  Fix 2 — Batch large antibody lists:
    fix_suppliers.py sent all antibodies in one API call. For papers like Bai
    with 45 antibodies, the JSON output alone exceeds max_tokens=2048, producing
    a truncated and therefore invalid JSON string. This version batches > 15
    antibodies into chunks of 15, then merges the results.

  Fix 3 — Higher max_tokens:
    Raised from 2048 → 4096 to accommodate larger tables.

Run:
    $env:ANTHROPIC_API_KEY="sk-ant-..."
    python C:\\Users\\dudin\\Desktop\\ExM_Library\\fix_suppliers_v2.py
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
LOG_FILE       = Path(__file__).parent / "fix_suppliers_v2.log"
MAX_CHARS      = 60000
BATCH_SIZE     = 15     # max antibodies per API call — keeps output within max_tokens
MAX_TOKENS     = 4096   # raised from 2048
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

Return ONLY valid JSON — no markdown, no preamble, no explanation, just the JSON object:
{{"results": [
  {{
    "label_name": "exact name as given in the list above",
    "supplier": "company name | gift: [lab name] | in-house | not stated",
    "catalogue_number": "exact code as written in paper, or null"
  }}
]}}

Use "not stated" ONLY when you have searched the full text and truly cannot find any supplier information.

PAPER TEXT:
{text}"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_pdf_text(pdf_path: Path) -> str:
    try:
        doc = pymupdf.open(str(pdf_path))
        text = "".join(doc[i].get_text() for i in range(len(doc)))
        doc.close()
        return text
    except Exception as e:
        return ""


def clean_text(text: str) -> str:
    for old, new in [
        ("°", "deg"), ("µ", "u"), ("α", "alpha"), ("β", "beta"),
        ("γ", "gamma"), ("–", "-"), ("—", "-"), ("×", "x"),
        ("±", "+/-"), ("’", "'"), ("“", '"'), ("”", '"'),
    ]:
        text = text.replace(old, new)
    return text


def extract_json(raw: str) -> dict | None:
    """
    Robustly extract a JSON object from a model response.

    Strategy (most to least reliable):
      1. Direct json.loads on the full response (works when response is pure JSON)
      2. Strip a leading markdown fence (```json ... ```) and retry
      3. Search the full response for the FIRST { ... } block — handles preamble text
         like "Here is the information I found:" before the actual JSON

    Fix 1 addresses the root cause of most failures in fix_suppliers.py:
    Haiku often prefixes JSON with a prose sentence, making raw.startswith("```")
    False and json.loads immediately fail on the prose.
    """
    raw = raw.strip()

    # Attempt 1: direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Attempt 2: strip markdown fence if present anywhere in response
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Attempt 3: find the first {...} block in the response (handles preamble text)
    # Use a greedy match anchored to "results" key to avoid capturing small objects
    results_match = re.search(r'(\{"results"\s*:.*\})', raw, re.DOTALL)
    if results_match:
        try:
            return json.loads(results_match.group(1))
        except json.JSONDecodeError:
            pass

    # Attempt 4: find any {...} block
    brace_match = re.search(r'(\{.*\})', raw, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(1))
        except json.JSONDecodeError:
            pass

    return None


def call_api_batched(client, text: str, antibody_entries: list, log_f) -> dict:
    """
    Call the API in batches of BATCH_SIZE antibodies.

    Fix 2: sending all 45 antibodies in one call overflows max_tokens=2048,
    producing a truncated JSON. Batching to ≤15 per call ensures the output
    stays well within token limits.

    Returns a merged lookup: {normalized_label_name: {supplier, catalogue_number}}
    """
    lookup = {}

    for batch_start in range(0, len(antibody_entries), BATCH_SIZE):
        batch = antibody_entries[batch_start: batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(antibody_entries) + BATCH_SIZE - 1) // BATCH_SIZE

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
                raw = response.content[0].text
                result = extract_json(raw)

                if result is None:
                    log_f.write(f"  Batch {batch_num}/{total_batches} attempt {attempt+1}: "
                                f"could not extract JSON from response:\n  {raw[:200]}\n")
                    if attempt < RETRY_ATTEMPTS - 1:
                        time.sleep(RETRY_DELAY)
                    continue

                for r in result.get("results", []):
                    key = r.get("label_name", "").strip().lower()
                    if key:
                        lookup[key] = {
                            "label_supplier":        r.get("supplier", "not stated") or "not stated",
                            "label_catalogue_number": str(r.get("catalogue_number") or ""),
                        }
                break   # batch succeeded

            except Exception as e:
                log_f.write(f"  Batch {batch_num}/{total_batches} attempt {attempt+1}: "
                            f"{type(e).__name__}: {e}\n")
                if "rate" in str(e).lower():
                    time.sleep(30)
                elif attempt < RETRY_ATTEMPTS - 1:
                    time.sleep(RETRY_DELAY)

        time.sleep(0.3)  # polite delay between batches

    return lookup


# ── Main ───────────────────────────────────────────────────────────────────────

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

    # Find papers still with "not stated" suppliers
    papers_to_fix = defaultdict(list)
    for i, row in enumerate(rows):
        if (row.get("label_supplier") == "not stated"
                and row.get("label_type") in ("primary_antibody", "secondary_antibody", "nanobody")
                and row.get("label_name")):
            papers_to_fix[row["pdf_filename"]].append(i)

    print(f"Papers still with 'not stated' suppliers: {len(papers_to_fix)}")
    print(f"Total rows to fix: {sum(len(v) for v in papers_to_fix.values())}\n")

    if not papers_to_fix:
        print("Nothing to do — all suppliers already filled.")
        return

    total_fixed = 0

    with open(LOG_FILE, "w", encoding="utf-8") as log_f:
        for paper_num, (fname, row_indices) in enumerate(sorted(papers_to_fix.items()), 1):

            # De-duplicate antibody names for this paper
            seen = set()
            antibody_entries = []
            for idx in row_indices:
                name   = rows[idx].get("label_name", "").strip()
                target = rows[idx].get("label_target", "").strip()
                if name and name not in seen:
                    seen.add(name)
                    antibody_entries.append((name, target, idx))

            n_batches = (len(antibody_entries) + BATCH_SIZE - 1) // BATCH_SIZE
            batch_note = f" ({n_batches} batches)" if n_batches > 1 else ""
            print(f"[{paper_num}/{len(papers_to_fix)}] {fname} — "
                  f"{len(antibody_entries)} antibodies{batch_note}", end=" ... ", flush=True)
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

            lookup = call_api_batched(client, text, antibody_entries, log_f)

            # Update matching rows
            fixed_count = 0
            for name, target, idx in antibody_entries:
                match = lookup.get(name.lower())
                if not match:
                    # Try partial key match
                    for k, v in lookup.items():
                        if k in name.lower() or name.lower() in k:
                            match = v
                            break

                if match and match["label_supplier"] not in ("not stated", "", None):
                    rows[idx]["label_supplier"] = match["label_supplier"]
                    if match["label_catalogue_number"] and not rows[idx].get("label_catalogue_number"):
                        rows[idx]["label_catalogue_number"] = match["label_catalogue_number"]
                    fixed_count += 1
                    log_f.write(f"  FIXED: {name} -> {match['label_supplier']} "
                                f"{match['label_catalogue_number']}\n")
                else:
                    log_f.write(f"  NOT FOUND: {name}\n")

            total_fixed += fixed_count
            print(f"fixed {fixed_count}/{len(antibody_entries)}")

    # Write CSV back
    print(f"\nWriting {len(rows)} rows back to {OUTPUT_CSV.name} ...")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done. Fixed {total_fixed} supplier entries.")
    print(f"Log: {LOG_FILE}")


if __name__ == "__main__":
    main()
