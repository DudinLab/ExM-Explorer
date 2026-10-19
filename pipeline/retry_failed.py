#!/usr/bin/env python3
"""
retry_failed.py — Two-pass retry for the 25 papers that failed in the main run.

Why they failed: output overflow — papers with many species + antibodies generate
more JSON than fits in 8192 output tokens, causing parse failure.

Fix: split into two focused calls per paper:
  Pass 1: paper metadata + protocol details (no labels) — small output
  Pass 2: labels/antibodies only — focused output

Run:
  $env:ANTHROPIC_API_KEY="sk-ant-..."
  python C:\\Users\\dudin\\Desktop\\ExM_Library\\retry_failed.py
"""

import anthropic
import csv
import json
import os
import re
import sys
import time
import pymupdf
from pathlib import Path

MODEL = "claude-sonnet-4-6"
PAPERS_DIR  = Path(__file__).parent / "papers"
OUTPUT_CSV  = Path(__file__).parent / "exm_database.csv"
LOG_FILE    = Path(__file__).parent / "retry_failed.log"
MAX_INPUT_CHARS = 80000   # truncate very large papers (supplementary material is usually at the end)
RETRY_ATTEMPTS  = 3
RETRY_DELAY     = 10

FAILED_PAPERS = [
    "Bai_NatureCommunications_2023.pdf",
    "Bernstock_bioRxiv_2021.pdf",
    "Cheng_MicrobialCell_2023.pdf",
    "Dey_bioRxiv_2024.pdf",
    "Flori_bioRxiv_2025.pdf",
    "Guo_NatureCommunications_2025.pdf",
    "Guoa_bioRxiv_2024.pdf",
    "Kabatas_bioRxiv_2017.pdf",
    "Katrukha_CurrentBiology_2026.pdf",
    "Klimas_NatureBiotechnology_2021.pdf",
    "ksaal_bioRxiv_2022.pdf",
    "Kylies_NatureNanotechnology_2022.pdf",
    "Laporte_NatureMethods_2021.pdf",
    "Lemaitre_bioRxiv_2025.pdf",
    "Li_NatureMethods_2020.pdf",
    "Mean_CellReports_2026.pdf",
    "Mercey_bioRxiv_2025.pdf",
    "Mercey_CellReportsMethods_2026.pdf",
    "Mikulenková_bioRxiv_2025.pdf",   # ě character
    "Mikus_Cell_2025.pdf",
    "Rizzoli_ResearchSquare_2022.pdf",
    "Saal_ScientificReports_2023.pdf",
    "Shaib_bioRxiv_2022.pdf",
    "Shaib_NatureBiotechnology_2023.pdf",
    "Tillberg_NatureBiotechnology_2016.pdf",
    "Zhao_ResearchSquare_2023.pdf",
    "Zhuang_bioRxiv_2024.pdf",
]

COLUMNS = [
    "pdf_filename", "doi", "title", "first_author", "last_author",
    "year", "journal", "exm_variant", "paper_type", "new_protocol",
    "species", "clade", "sample_type",
    "fixation_reagent", "fixation_concentration", "fixation_duration",
    "fixation_temperature", "fixation_buffer",
    "anchoring_reagent", "anchoring_concentration", "anchoring_duration", "anchoring_temperature",
    "gel_sodium_acrylate_pct", "gel_acrylamide_pct", "gel_bis_pct", "gel_other_components",
    "homogenization_method",
    "expansion_factor_nominal", "expansion_factor_measured",
    "labelling_strategy", "protocol_outcome",
    "label_target", "label_name", "label_type", "label_host_species",
    "label_supplier", "label_catalogue_number", "label_dilution",
    "label_fluorophore", "label_application_timing", "label_outcome",
    "extraction_notes",
]

PASS1_PROMPT = """Extract structured data from this expansion microscopy (ExM) paper.
Return ONLY valid JSON — no markdown, no explanation. Do NOT include labels/antibodies here.

{{
  "is_exm_paper": true,
  "doi": "...",
  "title": "...",
  "first_author": "surname only",
  "last_author": "surname only",
  "year": 2024,
  "journal": "...",
  "exm_variant": "one of: U-ExM | proExM | ExPath | ExFISH | TREx | Magnify | cryo-ExM | MAP | iterative-ExM | other: [name]",
  "paper_type": "one of: methods | application | protocol",
  "new_protocol": true,
  "extraction_notes": "One sentence max — key caveats only",
  "species_entries": [
    {{
      "species": "full species name e.g. Trypanosoma brucei",
      "clade": "one of: Alveolata | Viridiplantae | Stramenopiles | Haptophyta | Cryptista | Unicellular Holozoa | Discoba | Rhodophyta | Fungi | Rhizaria | Glaucophyta | Amoebozoa | Metazoa | Archaea | Bacteria | Unknown",
      "sample_type": "one of: cultured_cell | tissue | whole_organism | organoid | environmental | isolated_protein | other",
      "fixation_reagent": "e.g. paraformaldehyde or null",
      "fixation_concentration": "e.g. 4% or null",
      "fixation_duration": "e.g. 10 min or null",
      "fixation_temperature": "e.g. RT or null",
      "fixation_buffer": "e.g. PBS or null",
      "anchoring_reagent": "e.g. NHS-ester or null",
      "anchoring_concentration": "or null",
      "anchoring_duration": "or null",
      "anchoring_temperature": "or null",
      "gel_sodium_acrylate_pct": "or null",
      "gel_acrylamide_pct": "or null",
      "gel_bis_pct": "or null",
      "gel_other_components": "or null",
      "homogenization_method": "one of: Proteinase K | heat-SDS | both | other | null",
      "expansion_factor_nominal": "e.g. 4x or null",
      "expansion_factor_measured": "or null",
      "labelling_strategy": "one of: pre-expansion | post-expansion | both | null",
      "protocol_outcome": "one of: success | partial | fail | null"
    }}
  ]
}}

RULES:
- is_exm_paper: false if paper only cites ExM, does not actually use it
- Use null for missing values. Prefix uncertain values with "uncertain: ", inferred with "inferred: "
- Be concise. One species entry per species studied.
- Do NOT include a "labels" array — that comes in a separate pass.

PAPER TEXT:
{text}"""

PASS2_PROMPT = """Extract ALL antibodies, dyes, and labels from this expansion microscopy paper.
Return ONLY valid JSON — no markdown, no explanation.

The paper studies these species: {species_list}

{{
  "species_entries": [
    {{
      "species": "must exactly match one of the species listed above",
      "labels": [
        {{
          "label_target": "protein or structure targeted e.g. alpha-tubulin",
          "label_name": "antibody clone name or product name e.g. YL1/2 or Alexa Fluor 488",
          "label_type": "one of: primary_antibody | secondary_antibody | nanobody | dye | phalloidin | lectin | tag | other",
          "label_host_species": "e.g. mouse, rabbit — or null for non-antibodies",
          "label_supplier": "REQUIRED. Search entire text. Company name (e.g. Abcam, Sigma-Aldrich, Thermo Fisher, Invitrogen, Life Technologies, Molecular Probes, Proteintech, Cell Signaling Technology, CST, Santa Cruz Biotechnology, BD Biosciences, BioLegend, R&D Systems, Jackson ImmunoResearch, DSHB, Rockland, Millipore, GeneTex, Novus, Bio-Rad, Synaptic Systems, SYSY, MBL, Bethyl) | gift: [lab name] | in-house | not stated. Look for patterns: (ab5821, Abcam), (sc-48385, Santa Cruz), (#3700 Cell Signaling), Cat. No. PA5-29136, purchased from Sigma. Use not stated ONLY if truly absent.",
          "label_catalogue_number": "alphanumeric code e.g. ab5821 or sc-48385 or null",
          "label_dilution": "e.g. 1:500 or null",
          "label_fluorophore": "e.g. Alexa 488 or null",
          "label_application_timing": "one of: pre-expansion | post-expansion | null",
          "label_outcome": "one of: success | partial | fail | null"
        }}
      ]
    }}
  ]
}}

RULES:
- Include ALL labels: primary antibodies, secondary antibodies, nanobodies, dyes (DAPI etc.), phalloidin, lectins
- If a label is used across all species, include it under each species
- label_supplier: NEVER null — always one of the 4 options
- Match each entry to the correct species

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
        ("±", "+/-"), ("≥", ">="), ("≤", "<="),
        ("’", "'"), ("“", '"'), ("”", '"'),
    ]:
        text = text.replace(old, new)
    return text


def call_api(client, prompt: str, label: str, log_f) -> dict | None:
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            return json.loads(raw)
        except json.JSONDecodeError as e:
            log_f.write(f"  [{label}] attempt {attempt+1}: JSON parse error — {e}\n")
        except Exception as e:
            log_f.write(f"  [{label}] attempt {attempt+1}: API error — {type(e).__name__}: {e}\n")
            if "rate" in str(e).lower():
                time.sleep(60)
        if attempt < RETRY_ATTEMPTS - 1:
            time.sleep(RETRY_DELAY)
    return None


def build_rows(fname: str, pass1: dict, pass2: dict) -> list[dict]:
    """Merge pass1 (protocol) and pass2 (labels) into flat CSV rows."""
    paper_fields = {
        "pdf_filename": fname,
        "doi":          str(pass1.get("doi") or ""),
        "title":        str(pass1.get("title") or ""),
        "first_author": str(pass1.get("first_author") or ""),
        "last_author":  str(pass1.get("last_author") or ""),
        "year":         str(pass1.get("year") or ""),
        "journal":      str(pass1.get("journal") or ""),
        "exm_variant":  str(pass1.get("exm_variant") or ""),
        "paper_type":   str(pass1.get("paper_type") or ""),
        "new_protocol": str(pass1.get("new_protocol") or ""),
        "extraction_notes": str(pass1.get("extraction_notes") or ""),
    }

    # Build lookup: lowercase species name -> labels list (from pass2)
    labels_lookup = {}
    for se in pass2.get("species_entries", []):
        key = se.get("species", "").strip().lower()
        labels_lookup[key] = se.get("labels", [])

    rows = []
    for sp_entry in pass1.get("species_entries", []):
        sp_name = str(sp_entry.get("species") or "")
        protocol_fields = {
            "species":                   sp_name,
            "clade":                     str(sp_entry.get("clade") or ""),
            "sample_type":               str(sp_entry.get("sample_type") or ""),
            "fixation_reagent":          str(sp_entry.get("fixation_reagent") or ""),
            "fixation_concentration":    str(sp_entry.get("fixation_concentration") or ""),
            "fixation_duration":         str(sp_entry.get("fixation_duration") or ""),
            "fixation_temperature":      str(sp_entry.get("fixation_temperature") or ""),
            "fixation_buffer":           str(sp_entry.get("fixation_buffer") or ""),
            "anchoring_reagent":         str(sp_entry.get("anchoring_reagent") or ""),
            "anchoring_concentration":   str(sp_entry.get("anchoring_concentration") or ""),
            "anchoring_duration":        str(sp_entry.get("anchoring_duration") or ""),
            "anchoring_temperature":     str(sp_entry.get("anchoring_temperature") or ""),
            "gel_sodium_acrylate_pct":   str(sp_entry.get("gel_sodium_acrylate_pct") or ""),
            "gel_acrylamide_pct":        str(sp_entry.get("gel_acrylamide_pct") or ""),
            "gel_bis_pct":               str(sp_entry.get("gel_bis_pct") or ""),
            "gel_other_components":      str(sp_entry.get("gel_other_components") or ""),
            "homogenization_method":     str(sp_entry.get("homogenization_method") or ""),
            "expansion_factor_nominal":  str(sp_entry.get("expansion_factor_nominal") or ""),
            "expansion_factor_measured": str(sp_entry.get("expansion_factor_measured") or ""),
            "labelling_strategy":        str(sp_entry.get("labelling_strategy") or ""),
            "protocol_outcome":          str(sp_entry.get("protocol_outcome") or ""),
        }

        # Find labels for this species
        labels = labels_lookup.get(sp_name.strip().lower(), [])
        # Fallback: if only one species in pass2, use its labels
        if not labels and len(labels_lookup) == 1:
            labels = list(labels_lookup.values())[0]

        if labels:
            for lbl in labels:
                row = {**paper_fields, **protocol_fields}
                row.update({
                    "label_target":           str(lbl.get("label_target") or ""),
                    "label_name":             str(lbl.get("label_name") or ""),
                    "label_type":             str(lbl.get("label_type") or ""),
                    "label_host_species":     str(lbl.get("label_host_species") or ""),
                    "label_supplier":         str(lbl.get("label_supplier") or "not stated"),
                    "label_catalogue_number": str(lbl.get("label_catalogue_number") or ""),
                    "label_dilution":         str(lbl.get("label_dilution") or ""),
                    "label_fluorophore":      str(lbl.get("label_fluorophore") or ""),
                    "label_application_timing": str(lbl.get("label_application_timing") or ""),
                    "label_outcome":          str(lbl.get("label_outcome") or ""),
                })
                rows.append(row)
        else:
            # Write protocol row without labels
            row = {**paper_fields, **protocol_fields}
            for col in ["label_target", "label_name", "label_type", "label_host_species",
                        "label_supplier", "label_catalogue_number", "label_dilution",
                        "label_fluorophore", "label_application_timing", "label_outcome"]:
                row[col] = ""
            rows.append(row)

    return rows


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY first:  $env:ANTHROPIC_API_KEY='sk-ant-...'")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    total_rows = 0
    still_failed = []

    print(f"Retrying {len(FAILED_PAPERS)} failed papers (two-pass approach)")
    print(f"Output: {OUTPUT_CSV}\n")

    with open(LOG_FILE, "w", encoding="utf-8") as log_f, \
         open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig") as csvfile:

        writer = csv.DictWriter(csvfile, fieldnames=COLUMNS, extrasaction="ignore")

        for i, fname in enumerate(FAILED_PAPERS, 1):
            pdf_path = PAPERS_DIR / fname
            if not pdf_path.exists():
                # Try alternate encoding for special characters
                matches = list(PAPERS_DIR.glob(fname[:20] + "*.pdf"))
                if matches:
                    pdf_path = matches[0]
                    fname = pdf_path.name
                else:
                    print(f"[{i}/{len(FAILED_PAPERS)}] {fname} ... FILE NOT FOUND")
                    log_f.write(f"NOT FOUND\t{fname}\n")
                    still_failed.append(fname)
                    continue

            print(f"[{i}/{len(FAILED_PAPERS)}] {fname}", end=" ... ", flush=True)
            log_f.write(f"\n{'='*60}\n{fname}\n")

            raw_text = extract_pdf_text(pdf_path)
            if len(raw_text) < 200:
                print("SKIP (scanned — no text)")
                log_f.write("SKIP: scanned PDF\n")
                still_failed.append(fname)
                continue

            text = clean_text(raw_text[:MAX_INPUT_CHARS])
            if len(raw_text) > MAX_INPUT_CHARS:
                log_f.write(f"NOTE: truncated {len(raw_text)} -> {MAX_INPUT_CHARS} chars\n")

            # PASS 1 — metadata + protocol (no labels)
            pass1 = call_api(client, PASS1_PROMPT.format(text=text), "Pass1", log_f)
            if not pass1:
                print("FAILED (pass 1 parse error)")
                log_f.write("FAILED: pass 1\n")
                still_failed.append(fname)
                continue

            if not pass1.get("is_exm_paper", True):
                print("SKIP (not ExM)")
                log_f.write("SKIP: not ExM\n")
                continue

            species_list = [se.get("species", "") for se in pass1.get("species_entries", []) if se.get("species")]
            if not species_list:
                print("SKIP (no species in pass 1)")
                log_f.write("SKIP: no species\n")
                continue

            time.sleep(0.5)

            # PASS 2 — labels only
            pass2 = call_api(
                client,
                PASS2_PROMPT.format(species_list=", ".join(species_list), text=text),
                "Pass2",
                log_f
            )
            if not pass2:
                print("PARTIAL (pass 2 failed — writing protocol rows only)")
                log_f.write("WARNING: pass 2 failed\n")
                pass2 = {"species_entries": []}

            rows = build_rows(fname, pass1, pass2)
            for row in rows:
                writer.writerow(row)
            csvfile.flush()
            total_rows += len(rows)
            print(f"OK ({len(rows)} rows)")
            log_f.write(f"OK: {len(rows)} rows\n")

            time.sleep(0.5)

    print(f"\nDone. {total_rows} rows added to exm_database.csv")
    if still_failed:
        print(f"Still failed ({len(still_failed)}): {still_failed}")
    print(f"Detailed log: {LOG_FILE}")


if __name__ == "__main__":
    main()
