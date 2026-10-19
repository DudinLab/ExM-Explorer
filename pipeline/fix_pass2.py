#!/usr/bin/env python3
"""
fix_pass2.py — Get labels for papers that got protocol data but no labels.

The pass 2 in retry_failed.py still overflowed for 8 papers because even the
labels-only JSON exceeded 8192 tokens. Fix: one API call PER SPECIES instead
of per paper. Each call produces a small, focused output that never overflows.

Also handles:
  - Dey_bioRxiv_2024.pdf: pass 1 failed — retry with tighter truncation (50k)
  - Mikulenková_bioRxiv_2025.pdf: filename encoding issue — found via glob

Run:
  $env:ANTHROPIC_API_KEY="sk-ant-..."
  python C:\\Users\\dudin\\Desktop\\ExM_Library\\fix_pass2.py
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

MODEL           = "claude-sonnet-4-6"
PAPERS_DIR      = Path(__file__).parent / "papers"
OUTPUT_CSV      = Path(__file__).parent / "exm_database.csv"
LOG_FILE        = Path(__file__).parent / "fix_pass2.log"
RETRY_ATTEMPTS  = 3
RETRY_DELAY     = 10

# Papers with protocol rows but no labels
PARTIAL_PAPERS = [
    "Cheng_MicrobialCell_2023.pdf",
    "Flori_bioRxiv_2025.pdf",
    "Kabatas_bioRxiv_2017.pdf",
    "Li_NatureMethods_2020.pdf",
    "Mercey_bioRxiv_2025.pdf",
    "Mercey_CellReportsMethods_2026.pdf",
    "Mikus_Cell_2025.pdf",
    "Zhao_ResearchSquare_2023.pdf",
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

LABEL_COLS = [
    "label_target", "label_name", "label_type", "label_host_species",
    "label_supplier", "label_catalogue_number", "label_dilution",
    "label_fluorophore", "label_application_timing", "label_outcome",
]

# Prompt: labels for ONE species only — keeps output small
SPECIES_LABELS_PROMPT = """Extract ALL antibodies, dyes, and labels used for {species} in this expansion microscopy paper.

Return ONLY valid JSON — no markdown, no explanation:
{{
  "labels": [
    {{
      "label_target": "protein or structure targeted e.g. alpha-tubulin",
      "label_name": "antibody clone name or product name e.g. YL1/2",
      "label_type": "one of: primary_antibody | secondary_antibody | nanobody | dye | phalloidin | lectin | tag | other",
      "label_host_species": "e.g. mouse, rabbit — or null",
      "label_supplier": "REQUIRED. Search entire text for these companies: Abcam, Sigma-Aldrich/Sigma/Merck, Thermo Fisher/Thermo Fisher Scientific/Invitrogen/Life Technologies/Molecular Probes, Proteintech, Cell Signaling Technology/CST, Santa Cruz Biotechnology, BD Biosciences, BioLegend, R&D Systems, Jackson ImmunoResearch, DSHB, Rockland, Millipore, GeneTex, Novus Biologicals, Bio-Rad, Synaptic Systems/SYSY, MBL, Bethyl. Catalogue numbers appear as: (ab5821, Abcam), (sc-48385, Santa Cruz), (#3700 Cell Signaling), Cat. No. PA5-29136. Use: company name | gift: [lab name] | in-house | not stated",
      "label_catalogue_number": "e.g. ab5821 or null",
      "label_dilution": "e.g. 1:500 or null",
      "label_fluorophore": "e.g. Alexa 488 or null",
      "label_application_timing": "one of: pre-expansion | post-expansion | null",
      "label_outcome": "one of: success | partial | fail | null"
    }}
  ]
}}

RULES:
- Include ALL labels for {species}: primary antibodies, secondary antibodies, nanobodies, DAPI, phalloidin, etc.
- label_supplier: NEVER null — always one of the 4 options
- If {species} is not mentioned or no labels are found, return {{"labels": []}}

PAPER TEXT:
{text}"""

# Full two-pass prompt for Dey (pass 1 failed)
PASS1_PROMPT = """Extract structured data from this expansion microscopy paper.
Return ONLY valid JSON — no markdown, no explanation. Do NOT include labels.

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
  "extraction_notes": "One sentence max",
  "species_entries": [
    {{
      "species": "full species name",
      "clade": "one of: Alveolata | Viridiplantae | Stramenopiles | Haptophyta | Cryptista | Unicellular Holozoa | Discoba | Rhodophyta | Fungi | Rhizaria | Glaucophyta | Amoebozoa | Metazoa | Archaea | Bacteria | Unknown",
      "sample_type": "one of: cultured_cell | tissue | whole_organism | organoid | environmental | isolated_protein | other",
      "fixation_reagent": "or null", "fixation_concentration": "or null",
      "fixation_duration": "or null", "fixation_temperature": "or null", "fixation_buffer": "or null",
      "anchoring_reagent": "or null", "anchoring_concentration": "or null",
      "anchoring_duration": "or null", "anchoring_temperature": "or null",
      "gel_sodium_acrylate_pct": "or null", "gel_acrylamide_pct": "or null",
      "gel_bis_pct": "or null", "gel_other_components": "or null",
      "homogenization_method": "one of: Proteinase K | heat-SDS | both | other | null",
      "expansion_factor_nominal": "or null", "expansion_factor_measured": "or null",
      "labelling_strategy": "one of: pre-expansion | post-expansion | both | null",
      "protocol_outcome": "one of: success | partial | fail | null"
    }}
  ]
}}

PAPER TEXT:
{text}"""


def find_pdf(fname: str) -> Path | None:
    """Find PDF by exact name, then by glob (handles encoding variants)."""
    exact = PAPERS_DIR / fname
    if exact.exists():
        return exact
    # Try glob with first 10 chars (safe even with special characters)
    stem = fname[:10]
    matches = list(PAPERS_DIR.glob(stem + "*.pdf"))
    if matches:
        return matches[0]
    return None


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
        ("±", "+/-"), ("'", "'"), ("“", '"'), ("”", '"'),
    ]:
        text = text.replace(old, new)
    return text


def call_api(client, prompt: str, label: str, log_f) -> dict | None:
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,   # per-species output is small — 4096 is plenty
                messages=[{"role": "user", "content": prompt}]
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            return json.loads(raw)
        except json.JSONDecodeError as e:
            log_f.write(f"  [{label}] attempt {attempt+1}: JSON parse — {e}\n")
        except Exception as e:
            log_f.write(f"  [{label}] attempt {attempt+1}: API error — {type(e).__name__}: {e}\n")
            if "rate" in str(e).lower():
                time.sleep(60)
        if attempt < RETRY_ATTEMPTS - 1:
            time.sleep(RETRY_DELAY)
    return None


def get_labels_for_species(client, species: str, text: str, log_f) -> list[dict]:
    """One API call for one species — small, focused, never overflows."""
    result = call_api(
        client,
        SPECIES_LABELS_PROMPT.format(species=species, text=text),
        f"labels/{species[:30]}",
        log_f
    )
    if result:
        return result.get("labels", [])
    return []


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY first")
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

    print(f"Loaded {len(rows)} rows from CSV\n")

    new_rows = []   # rows to append at the end
    modified = 0

    with open(LOG_FILE, "w", encoding="utf-8") as log_f:

        # ── PARTIAL PAPERS: fill in missing labels ─────────────────────────
        for paper_num, fname in enumerate(PARTIAL_PAPERS, 1):
            print(f"[{paper_num}/{len(PARTIAL_PAPERS)}] {fname}", end=" ... ", flush=True)
            log_f.write(f"\n{'='*60}\n{fname}\n")

            pdf_path = find_pdf(fname)
            if not pdf_path:
                print("FILE NOT FOUND")
                log_f.write("FILE NOT FOUND\n")
                continue

            raw_text = extract_pdf_text(pdf_path)
            if len(raw_text) < 200:
                print("SKIP (scanned)")
                continue
            text = clean_text(raw_text[:80000])

            # Find existing protocol rows for this paper (label_name is empty)
            paper_rows = [(i, r) for i, r in enumerate(rows)
                          if r.get("pdf_filename") == fname and not r.get("label_name")]

            if not paper_rows:
                print("no protocol rows found in CSV")
                continue

            # Group by species
            species_to_row_idx = {}
            for i, r in paper_rows:
                sp = r.get("species", "")
                if sp and sp not in species_to_row_idx:
                    species_to_row_idx[sp] = i   # index of first protocol row for this species

            labels_added = 0
            for species, base_idx in species_to_row_idx.items():
                log_f.write(f"  Species: {species}\n")
                labels = get_labels_for_species(client, species, text, log_f)
                time.sleep(0.3)

                if not labels:
                    log_f.write(f"    No labels found\n")
                    continue

                # Fill first label into the existing protocol row
                base_row = rows[base_idx]
                lbl = labels[0]
                for col in LABEL_COLS:
                    key = col.replace("label_", "label_")
                    val = lbl.get(col) or lbl.get(col.replace("label_", ""))
                    base_row[col] = str(val or "")
                # Ensure supplier is never empty
                if not base_row.get("label_supplier"):
                    base_row["label_supplier"] = "not stated"
                modified += 1
                labels_added += 1

                # Add additional labels as new rows (copying protocol fields)
                for lbl in labels[1:]:
                    new_row = {k: base_row[k] for k in COLUMNS if k not in LABEL_COLS}
                    for col in LABEL_COLS:
                        val = lbl.get(col)
                        new_row[col] = str(val or "")
                    if not new_row.get("label_supplier"):
                        new_row["label_supplier"] = "not stated"
                    new_rows.append(new_row)
                    labels_added += 1

                log_f.write(f"    Added {len(labels)} labels\n")

            print(f"OK ({labels_added} labels added across {len(species_to_row_idx)} species)")

        # ── DEY: full two-pass with aggressive truncation ──────────────────
        print(f"\n[Special] Dey_bioRxiv_2024.pdf (pass 1 retry, 50k truncation)", end=" ... ", flush=True)
        log_f.write(f"\n{'='*60}\nDey_bioRxiv_2024.pdf (special)\n")

        dey_path = find_pdf("Dey_bioRxiv_2024.pdf")
        if dey_path:
            raw_text = extract_pdf_text(dey_path)
            text = clean_text(raw_text[:50000])   # more aggressive truncation

            pass1 = call_api(client, PASS1_PROMPT.format(text=text), "Dey-Pass1", log_f)
            if pass1 and pass1.get("is_exm_paper", True):
                paper_fields = {
                    "pdf_filename": "Dey_bioRxiv_2024.pdf",
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
                dey_rows_added = 0
                for sp_entry in pass1.get("species_entries", []):
                    sp = sp_entry.get("species", "")
                    protocol_fields = {
                        "species": sp,
                        "clade": str(sp_entry.get("clade") or ""),
                        "sample_type": str(sp_entry.get("sample_type") or ""),
                        "fixation_reagent": str(sp_entry.get("fixation_reagent") or ""),
                        "fixation_concentration": str(sp_entry.get("fixation_concentration") or ""),
                        "fixation_duration": str(sp_entry.get("fixation_duration") or ""),
                        "fixation_temperature": str(sp_entry.get("fixation_temperature") or ""),
                        "fixation_buffer": str(sp_entry.get("fixation_buffer") or ""),
                        "anchoring_reagent": str(sp_entry.get("anchoring_reagent") or ""),
                        "anchoring_concentration": str(sp_entry.get("anchoring_concentration") or ""),
                        "anchoring_duration": str(sp_entry.get("anchoring_duration") or ""),
                        "anchoring_temperature": str(sp_entry.get("anchoring_temperature") or ""),
                        "gel_sodium_acrylate_pct": str(sp_entry.get("gel_sodium_acrylate_pct") or ""),
                        "gel_acrylamide_pct": str(sp_entry.get("gel_acrylamide_pct") or ""),
                        "gel_bis_pct": str(sp_entry.get("gel_bis_pct") or ""),
                        "gel_other_components": str(sp_entry.get("gel_other_components") or ""),
                        "homogenization_method": str(sp_entry.get("homogenization_method") or ""),
                        "expansion_factor_nominal": str(sp_entry.get("expansion_factor_nominal") or ""),
                        "expansion_factor_measured": str(sp_entry.get("expansion_factor_measured") or ""),
                        "labelling_strategy": str(sp_entry.get("labelling_strategy") or ""),
                        "protocol_outcome": str(sp_entry.get("protocol_outcome") or ""),
                    }
                    labels = get_labels_for_species(client, sp, text, log_f)
                    time.sleep(0.3)
                    if labels:
                        for lbl in labels:
                            row = {**paper_fields, **protocol_fields}
                            for col in LABEL_COLS:
                                row[col] = str(lbl.get(col) or "")
                            if not row.get("label_supplier"):
                                row["label_supplier"] = "not stated"
                            new_rows.append(row)
                            dey_rows_added += 1
                    else:
                        row = {**paper_fields, **protocol_fields}
                        for col in LABEL_COLS:
                            row[col] = ""
                        new_rows.append(row)
                        dey_rows_added += 1
                print(f"OK ({dey_rows_added} rows)")
            else:
                print("FAILED (pass 1 still failing — skip)")
        else:
            print("FILE NOT FOUND")

        # ── MIKULENKOVÁ: filename encoding — find via glob ─────────────────
        print(f"\n[Special] Mikulenková_bioRxiv_2025.pdf", end=" ... ", flush=True)
        log_f.write(f"\n{'='*60}\nMikulenková_bioRxiv_2025.pdf\n")

        mikul_path = find_pdf("Mikulenková_bioRxiv_2025.pdf")
        if not mikul_path:
            # Try broader glob
            matches = list(PAPERS_DIR.glob("Mikul*.pdf"))
            if matches:
                mikul_path = matches[0]

        if mikul_path:
            fname_actual = mikul_path.name
            log_f.write(f"Found as: {fname_actual}\n")
            raw_text = extract_pdf_text(mikul_path)
            text = clean_text(raw_text[:80000])

            if len(raw_text) < 200:
                print("SKIP (scanned)")
            else:
                pass1 = call_api(client, PASS1_PROMPT.format(text=text), "Mikul-Pass1", log_f)
                if pass1 and pass1.get("is_exm_paper", True):
                    paper_fields = {
                        "pdf_filename": fname_actual,
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
                    mikul_rows = 0
                    for sp_entry in pass1.get("species_entries", []):
                        sp = sp_entry.get("species", "")
                        protocol_fields = {
                            "species": sp,
                            "clade": str(sp_entry.get("clade") or ""),
                            "sample_type": str(sp_entry.get("sample_type") or ""),
                            "fixation_reagent": str(sp_entry.get("fixation_reagent") or ""),
                            "fixation_concentration": str(sp_entry.get("fixation_concentration") or ""),
                            "fixation_duration": str(sp_entry.get("fixation_duration") or ""),
                            "fixation_temperature": str(sp_entry.get("fixation_temperature") or ""),
                            "fixation_buffer": str(sp_entry.get("fixation_buffer") or ""),
                            "anchoring_reagent": str(sp_entry.get("anchoring_reagent") or ""),
                            "anchoring_concentration": str(sp_entry.get("anchoring_concentration") or ""),
                            "anchoring_duration": str(sp_entry.get("anchoring_duration") or ""),
                            "anchoring_temperature": str(sp_entry.get("anchoring_temperature") or ""),
                            "gel_sodium_acrylate_pct": str(sp_entry.get("gel_sodium_acrylate_pct") or ""),
                            "gel_acrylamide_pct": str(sp_entry.get("gel_acrylamide_pct") or ""),
                            "gel_bis_pct": str(sp_entry.get("gel_bis_pct") or ""),
                            "gel_other_components": str(sp_entry.get("gel_other_components") or ""),
                            "homogenization_method": str(sp_entry.get("homogenization_method") or ""),
                            "expansion_factor_nominal": str(sp_entry.get("expansion_factor_nominal") or ""),
                            "expansion_factor_measured": str(sp_entry.get("expansion_factor_measured") or ""),
                            "labelling_strategy": str(sp_entry.get("labelling_strategy") or ""),
                            "protocol_outcome": str(sp_entry.get("protocol_outcome") or ""),
                        }
                        labels = get_labels_for_species(client, sp, text, log_f)
                        time.sleep(0.3)
                        if labels:
                            for lbl in labels:
                                row = {**paper_fields, **protocol_fields}
                                for col in LABEL_COLS:
                                    row[col] = str(lbl.get(col) or "")
                                if not row.get("label_supplier"):
                                    row["label_supplier"] = "not stated"
                                new_rows.append(row)
                                mikul_rows += 1
                        else:
                            row = {**paper_fields, **protocol_fields}
                            for col in LABEL_COLS:
                                row[col] = ""
                            new_rows.append(row)
                            mikul_rows += 1
                    print(f"OK ({mikul_rows} rows)")
                else:
                    print("FAILED or not ExM")
        else:
            print("FILE NOT FOUND — rename manually and re-run")

    # ── Write updated CSV ──────────────────────────────────────────────────
    all_rows = rows + new_rows
    print(f"\nWriting {len(all_rows)} rows to CSV ({modified} modified, {len(new_rows)} new) ...")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Done. Log: {LOG_FILE}")


if __name__ == "__main__":
    main()
