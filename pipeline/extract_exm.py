#!/usr/bin/env python3
"""
ExM Database Extraction Script
Processes PDFs from ExM_Library/papers/ and extracts structured data
into a single flat CSV: one row per paper × species × label.

Usage:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python3 extract_exm.py

Outputs:
    ExM_Library/exm_database.csv   — flat extraction results
    ExM_Library/extract.log        — per-file status log
    ExM_Library/failed.log         — files that failed extraction
"""

import os
import csv
import json
import time
import logging
import argparse
from pathlib import Path

try:
    import pymupdf
except ImportError:
    raise ImportError("Run: pip install pymupdf --break-system-packages")

try:
    import anthropic
except ImportError:
    raise ImportError("Run: pip install anthropic --break-system-packages")

# ── Config ──────────────────────────────────────────────────────────────────

PAPERS_DIR  = Path(__file__).parent / "papers"
OUTPUT_CSV  = Path(__file__).parent / "exm_database.csv"
LOG_FILE    = Path(__file__).parent / "extract.log"
FAILED_FILE  = Path(__file__).parent / "failed.log"
REVIEW_FILE  = Path(__file__).parent / "needs_review.log"

MODEL = "claude-sonnet-4-6"
MAX_PAGES = 999             # read entire paper
MAX_CHARS = None            # no limit — read entire paper
RETRY_ATTEMPTS = 3
RETRY_DELAY = 5             # seconds between retries

# Valid clades (controlled vocabulary)
VALID_CLADES = {
    "Alveolata", "Viridiplantae", "Stramenopiles", "Haptophyta", "Cryptista",
    "Unicellular Holozoa", "Discoba", "Rhodophyta", "Fungi", "Rhizaria",
    "Glaucophyta", "Amoebozoa", "Metazoa", "Archaea", "Bacteria", "Unknown"
}

# ── Output columns ───────────────────────────────────────────────────────────

COLUMNS = [
    # Source
    "pdf_filename",
    # Paper-level
    "doi", "title", "first_author", "last_author", "year", "journal",
    "exm_variant", "paper_type", "new_protocol",
    # Species/protocol (repeated per label row)
    "species", "clade", "sample_type",
    "fixation_reagent", "fixation_concentration", "fixation_duration",
    "fixation_temperature", "fixation_buffer",
    "anchoring_reagent", "anchoring_concentration", "anchoring_duration",
    "anchoring_temperature",
    "gel_sodium_acrylate_pct", "gel_acrylamide_pct", "gel_bis_pct",
    "gel_other_components",
    "homogenization_method",
    "expansion_factor_nominal", "expansion_factor_measured",
    "labelling_strategy", "protocol_outcome",
    # Label-level
    "label_target", "label_name", "label_type", "label_host_species",
    "label_supplier", "label_catalogue_number", "label_dilution",
    "label_fluorophore", "label_application_timing", "label_outcome",
    # Notes
    "extraction_notes",
]

# ── Extraction prompt ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a scientific data extractor specializing in Expansion Microscopy (ExM) protocols.
Extract structured data from research papers and return ONLY valid JSON, no other text."""

def build_user_prompt(text: str) -> str:
    return f"""Extract ExM (Expansion Microscopy) protocol data from this paper.

Return a JSON object with this exact structure:
{{
  "is_exm_paper": true/false,
  "doi": "string or null",
  "title": "string",
  "first_author": "last name only",
  "last_author": "last name only",
  "year": "4-digit string or null",
  "journal": "string or null",
  "exm_variant": "one of: U-ExM | proExM | ExPath | ExFISH | TREx | Magnify | cryo-ExM | MAP | iterative-ExM | other: [name]",
  "paper_type": "one of: methods | application | protocol | review",
  "new_protocol": true/false,
  "species_entries": [
    {{
      "species": "full species name (e.g. Trypanosoma cruzi, HeLa, Arabidopsis thaliana)",
      "clade": "one of: Alveolata | Viridiplantae | Stramenopiles | Haptophyta | Cryptista | Unicellular Holozoa | Discoba | Rhodophyta | Fungi | Rhizaria | Glaucophyta | Amoebozoa | Metazoa | Archaea | Bacteria | Unknown",
      "sample_type": "one of: cultured_cell | tissue | whole_organism | organoid | environmental | isolated_protein | other",
      "fixation_reagent": "e.g. paraformaldehyde, glutaraldehyde, methanol — or null",
      "fixation_concentration": "e.g. 4% — or null",
      "fixation_duration": "e.g. 15 min — or null",
      "fixation_temperature": "e.g. RT, 37°C — or null",
      "fixation_buffer": "e.g. PBS — or null",
      "anchoring_reagent": "e.g. 4% formaldehyde + 4% acrylamide — or null",
      "anchoring_concentration": "string or null",
      "anchoring_duration": "string or null",
      "anchoring_temperature": "string or null",
      "gel_sodium_acrylate_pct": "number as string, e.g. 19 — or null",
      "gel_acrylamide_pct": "number as string, e.g. 10 — or null",
      "gel_bis_pct": "number as string, e.g. 0.1 — or null",
      "gel_other_components": "other gel additives — or null",
      "homogenization_method": "one of: Proteinase K | heat-SDS | both | other | null",
      "expansion_factor_nominal": "e.g. 4x — or null",
      "expansion_factor_measured": "e.g. 4.3x — or null",
      "labelling_strategy": "one of: pre-expansion | post-expansion | both | null",
      "protocol_outcome": "one of: success | partial | fail | null",
      "labels": [
        {{
          "label_target": "what is being detected, e.g. alpha-tubulin, DAPI, actin",
          "label_name": "product name or clone, e.g. TAT-1, Alexa 488 phalloidin",
          "label_type": "one of: primary_antibody | secondary_antibody | nanobody | dye | phalloidin | lectin | tag | other",
          "label_host_species": "e.g. mouse, rabbit — or null (for non-antibodies)",
          "label_supplier": "REQUIRED — use exactly one of: (1) company name if commercially purchased; (2) 'gift: [lab name]' if a gift/kind gift from another lab; (3) 'in-house' if generated/raised/produced in their own lab or sourced from their own prior paper; (4) 'not stated' ONLY if truly no information exists anywhere in the paper. CRITICAL: actively search the entire Methods, Materials, and Supplementary sections for supplier mentions — they appear in many formats: inline parenthetical '(ab5821, Abcam)', table columns, sentences like 'purchased from Sigma-Aldrich', 'obtained from Thermo Fisher', 'from Cell Signaling Technology (#3700)'. Common suppliers to recognise: Abcam, Sigma-Aldrich/Sigma/Merck, Thermo Fisher/Thermo Fisher Scientific/Invitrogen/Life Technologies/Molecular Probes, Proteintech, Cell Signaling Technology/CST, Santa Cruz Biotechnology, BD Biosciences, BioLegend, R&D Systems, Jackson ImmunoResearch, Developmental Studies Hybridoma Bank/DSHB, Rockland, Millipore, GeneTex, Novus Biologicals, Bio-Rad, SYSY/Synaptic Systems, MBL, Bethyl. 'not stated' should be rare — if the paper mentions a company anywhere near the antibody description, extract it.",
          "label_catalogue_number": "Catalogue/catalog number — or null if genuinely absent. These appear in many formats: 'ab5821' (Abcam style), 'sc-48385' (Santa Cruz), '#3700' or '3700S' (Cell Signaling), 'PA5-29136' (Thermo), 'T6074' or 'F7524' (Sigma), '10620-1-AP' (Proteintech). Look for alphanumeric codes in parentheses, after 'Cat.', 'Cat. No.', 'catalog number', '#', or listed in antibody tables. Extract the code exactly as written.",
          "label_dilution": "e.g. 1:200 — or null",
          "label_fluorophore": "e.g. Alexa 555, GFP — or null",
          "label_application_timing": "one of: pre-expansion | post-expansion | null",
          "label_outcome": "one of: success | partial | fail | null"
        }}
      ]
    }}
  ],
  "extraction_notes": "any important caveats, ambiguities, or things marked uncertain"
}}

RULES:
- is_exm_paper: false if this paper does not actually USE expansion microscopy (e.g. only cites it)
- clade: use your taxonomic knowledge. HeLa cells → Metazoa. S. cerevisiae → Fungi. Trypanosoma → Discoba. Unknown only if genuinely uncertain.
- If a value is not stated in the paper, use null. Do NOT guess or infer unless you prefix with "inferred: "
- If a value is uncertain, prefix with "uncertain: "
- label_supplier: NEVER leave null. Every antibody must have one of: company name | gift: [lab] | in-house | not stated
- "in-house" applies when: the paper says "generated in our lab", "raised against", "produced in-house", or cites its own prior paper as the source
- "gift: [lab name]" applies when: the paper says "kind gift from", "provided by", "generously provided by" another group
- "not stated" is the fallback when no supplier info exists and origin cannot be inferred
- Include ALL labels/antibodies/dyes mentioned, including DAPI, secondary antibodies, phalloidin, etc.
- For papers using multiple species, create one entry per species in species_entries
- protocol_outcome: success = clean signal + isotropic expansion; partial = inconsistent/weak; fail = no signal/gel failure; null = not reported

PAPER TEXT:
{text}"""

# ── PDF text extraction ──────────────────────────────────────────────────────

def extract_pdf_text(pdf_path: Path) -> str:
    """Extract full text from all pages of the PDF."""
    doc = pymupdf.open(str(pdf_path))
    text = "".join(doc[i].get_text() for i in range(len(doc)))
    doc.close()
    return text

# ── Claude API call ──────────────────────────────────────────────────────────

def extract_with_claude(client: anthropic.Anthropic, text: str) -> dict:
    """Call Claude API and parse JSON response."""
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_prompt(text)}]
            )
            raw = response.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logging.warning(f"JSON parse error (attempt {attempt+1}): {e}")
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
        except anthropic.RateLimitError:
            logging.warning(f"Rate limit hit, waiting 60s (attempt {attempt+1})")
            time.sleep(60)
        except Exception as e:
            logging.warning(f"API error (attempt {attempt+1}): {e}")
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    raise RuntimeError(f"All {RETRY_ATTEMPTS} attempts failed")

# ── Row builder ──────────────────────────────────────────────────────────────

def count_issues(rows: list[dict]) -> list[str]:
    """Return list of problem descriptions for the needs_review log."""
    issues = []
    uncertain_fields = sum(
        1 for r in rows for v in r.values()
        if isinstance(v, str) and (v.startswith("uncertain:") or v.startswith("inferred:"))
    )
    if uncertain_fields >= 5:
        issues.append(f"{uncertain_fields} uncertain/inferred fields")

    no_labels = all(not r.get("label_name") for r in rows)
    if no_labels:
        issues.append("no antibodies/labels extracted")

    no_protocol = all(not r.get("fixation_reagent") for r in rows)
    if no_protocol:
        issues.append("no protocol details extracted")

    invalid_clades = [r["clade"] for r in rows if r.get("clade", "").startswith("uncertain:")]
    if invalid_clades:
        issues.append(f"invalid clade: {invalid_clades[0]}")

    null_suppliers = sum(1 for r in rows if r.get("label_type") in
                         ("primary_antibody","secondary_antibody","nanobody")
                         and not r.get("label_supplier"))
    if null_suppliers:
        issues.append(f"{null_suppliers} antibodies with no supplier")

    return issues


def build_rows(pdf_filename: str, data: dict) -> list[dict]:
    """Convert extracted JSON into flat CSV rows (one per species × label)."""
    if not data.get("is_exm_paper", True):
        return []  # skip non-ExM papers

    paper_fields = {
        "pdf_filename": pdf_filename,
        "doi":          data.get("doi"),
        "title":        data.get("title"),
        "first_author": data.get("first_author"),
        "last_author":  data.get("last_author"),
        "year":         data.get("year"),
        "journal":      data.get("journal"),
        "exm_variant":  data.get("exm_variant"),
        "paper_type":   data.get("paper_type"),
        "new_protocol": data.get("new_protocol"),
    }

    rows = []
    for sp in data.get("species_entries", []):
        # Validate clade
        clade = sp.get("clade", "Unknown")
        if clade not in VALID_CLADES:
            clade = f"uncertain: {clade}"

        protocol_fields = {
            "species":                  sp.get("species"),
            "clade":                    clade,
            "sample_type":              sp.get("sample_type"),
            "fixation_reagent":         sp.get("fixation_reagent"),
            "fixation_concentration":   sp.get("fixation_concentration"),
            "fixation_duration":        sp.get("fixation_duration"),
            "fixation_temperature":     sp.get("fixation_temperature"),
            "fixation_buffer":          sp.get("fixation_buffer"),
            "anchoring_reagent":        sp.get("anchoring_reagent"),
            "anchoring_concentration":  sp.get("anchoring_concentration"),
            "anchoring_duration":       sp.get("anchoring_duration"),
            "anchoring_temperature":    sp.get("anchoring_temperature"),
            "gel_sodium_acrylate_pct":  sp.get("gel_sodium_acrylate_pct"),
            "gel_acrylamide_pct":       sp.get("gel_acrylamide_pct"),
            "gel_bis_pct":              sp.get("gel_bis_pct"),
            "gel_other_components":     sp.get("gel_other_components"),
            "homogenization_method":    sp.get("homogenization_method"),
            "expansion_factor_nominal": sp.get("expansion_factor_nominal"),
            "expansion_factor_measured":sp.get("expansion_factor_measured"),
            "labelling_strategy":       sp.get("labelling_strategy"),
            "protocol_outcome":         sp.get("protocol_outcome"),
            "extraction_notes":         data.get("extraction_notes"),
        }

        labels = sp.get("labels", [])
        if not labels:
            # Paper has no labels listed — still write a row
            row = {**paper_fields, **protocol_fields,
                   "label_target": None, "label_name": None,
                   "label_type": None, "label_host_species": None,
                   "label_supplier": None, "label_catalogue_number": None,
                   "label_dilution": None, "label_fluorophore": None,
                   "label_application_timing": None, "label_outcome": None}
            rows.append(row)
        else:
            for label in labels:
                row = {**paper_fields, **protocol_fields,
                       "label_target":           label.get("label_target"),
                       "label_name":             label.get("label_name"),
                       "label_type":             label.get("label_type"),
                       "label_host_species":     label.get("label_host_species"),
                       "label_supplier":         label.get("label_supplier"),
                       "label_catalogue_number": label.get("label_catalogue_number"),
                       "label_dilution":         label.get("label_dilution"),
                       "label_fluorophore":      label.get("label_fluorophore"),
                       "label_application_timing": label.get("label_application_timing"),
                       "label_outcome":          label.get("label_outcome")}
                rows.append(row)
    return rows

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Extract ExM data from PDFs")
    parser.add_argument("--start", type=int, default=0, help="Start at PDF index (for resuming)")
    parser.add_argument("--limit", type=int, default=None, help="Process only N papers")
    parser.add_argument("--sample", type=int, default=None, help="Process N sample papers and exit")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("Set ANTHROPIC_API_KEY environment variable first")

    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.info("=== Extraction run started ===")

    client = anthropic.Anthropic(api_key=api_key)

    pdfs = sorted(PAPERS_DIR.glob("*.pdf"))
    if args.sample:
        pdfs = pdfs[:args.sample]
    elif args.limit:
        pdfs = pdfs[args.start : args.start + args.limit]
    else:
        pdfs = pdfs[args.start:]

    print(f"Processing {len(pdfs)} PDFs → {OUTPUT_CSV}")

    # Check which files already processed (for resuming)
    processed = set()
    if OUTPUT_CSV.exists():
        with open(OUTPUT_CSV, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                processed.add(row.get("pdf_filename", ""))
        print(f"Already processed: {len(processed)} files — skipping")

    write_header = not OUTPUT_CSV.exists() or len(processed) == 0

    failed = []
    total_rows = 0

    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()

        for i, pdf_path in enumerate(pdfs):
            fname = pdf_path.name
            if fname in processed:
                continue

            print(f"[{i+1}/{len(pdfs)}] {fname} ...", end=" ", flush=True)

            try:
                text = extract_pdf_text(pdf_path)
                if len(text) < 200:
                    print("SKIP (no text — likely scanned)")
                    logging.warning(f"SKIP {fname}: insufficient text ({len(text)} chars)")
                    with open(FAILED_FILE, "a", encoding="utf-8") as ff:
                        ff.write(f"NO_TEXT\t{fname}\n")
                    continue

                data = extract_with_claude(client, text)
                rows = build_rows(fname, data)

                if not data.get("is_exm_paper", True):
                    print("SKIP (not ExM — logged for review)")
                    logging.info(f"SKIP {fname}: not ExM paper")
                    with open(REVIEW_FILE, "a", encoding="utf-8") as rf:
                        rf.write(f"{fname}\tmarked not-ExM by model — verify manually\n")
                    continue

                writer.writerows(rows)
                csvfile.flush()
                total_rows += len(rows)

                issues = count_issues(rows)
                if issues:
                    flag = " ⚠ " + "; ".join(issues)
                    with open(REVIEW_FILE, "a", encoding="utf-8") as rf:
                        rf.write(f"{fname}\t{'; '.join(issues)}\n")
                else:
                    flag = ""

                print(f"OK ({len(rows)} rows){flag}")
                logging.info(f"OK {fname}: {len(rows)} rows written{flag}")

            except Exception as e:
                print(f"FAILED: {e}")
                logging.error(f"FAILED {fname}: {e}")
                with open(FAILED_FILE, "a", encoding="utf-8") as ff:
                    ff.write(f"ERROR\t{fname}\t{e}\n")
                failed.append(fname)

            # Brief pause to avoid rate limits
            time.sleep(0.5)

    print(f"\n{'='*50}")
    print(f"Done. {total_rows} rows written to {OUTPUT_CSV}")
    print(f"Failed: {len(failed)} files — see {FAILED_FILE}")
    if failed:
        for f in failed:
            print(f"  {f}")

if __name__ == "__main__":
    main()
