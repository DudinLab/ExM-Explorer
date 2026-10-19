#!/usr/bin/env python3
"""
ExM Database Extraction Script v2
Improvements over v1: gel %, anchoring fields, fixation_temperature (RT default
for PFA), label_dilution, catalogue numbers, expansion_factor_measured,
taxonomy disambiguation block, self-verification step.
os.fsync() after every paper prevents write truncation on Windows.

Usage:
    python extract_exm_v2.py --sample 5          # validate on 5 papers (~$0.50)
    python extract_exm_v2.py                     # full run (~$50-80)
    python extract_exm_v2.py --start 120         # resume after interruption
    python extract_exm_v2.py --only A.pdf B.pdf  # specific files only
"""

import os, csv, json, time, logging, argparse
from contextlib import suppress
from pathlib import Path

try:
    import pymupdf
except ImportError:
    raise ImportError("pip install pymupdf --break-system-packages")

try:
    import anthropic
except ImportError:
    raise ImportError("pip install anthropic --break-system-packages")

PAPERS_DIR  = Path(__file__).parent / "papers"
OUTPUT_CSV  = Path(__file__).parent / "exm_database_v2.csv"
LOG_FILE    = Path(__file__).parent / "extract_v2.log"
FAILED_FILE = Path(__file__).parent / "failed_v2.log"
REVIEW_FILE = Path(__file__).parent / "needs_review_v2.log"

MODEL          = "claude-sonnet-4-6"
MAX_TOKENS     = 16384
RETRY_ATTEMPTS = 3
RETRY_DELAY    = 5

VALID_CLADES = {
    "Alveolata","Viridiplantae","Stramenopiles","Haptophyta","Cryptista",
    "Unicellular Holozoa","Discoba","Rhodophyta","Fungi","Rhizaria",
    "Glaucophyta","Amoebozoa","Metazoa","Archaea","Bacteria","Unknown"
}

COLUMNS = [
    "pdf_filename",
    "doi","title","first_author","last_author","year","journal",
    "exm_variant","paper_type","new_protocol",
    "species","clade","sample_type",
    "fixation_reagent","fixation_concentration","fixation_duration",
    "fixation_temperature","fixation_buffer",
    "anchoring_reagent","anchoring_concentration","anchoring_duration",
    "anchoring_temperature",
    "gel_sodium_acrylate_pct","gel_acrylamide_pct","gel_bis_pct",
    "gel_other_components",
    "homogenization_method",
    "expansion_factor_nominal","expansion_factor_measured",
    "labelling_strategy","protocol_outcome",
    "label_target","label_name","label_type","label_host_species",
    "label_supplier","label_catalogue_number","label_dilution",
    "label_fluorophore","label_application_timing","label_outcome",
    "extraction_notes",
]

SYSTEM_PROMPT = (
    "You are a scientific data extractor specializing in Expansion Microscopy (ExM) protocols. "
    "Extract structured data from research papers and return ONLY valid JSON, no other text."
)

PROMPT_TEMPLATE = """Extract ExM (Expansion Microscopy) protocol data from this paper.

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
      "species": "full species name or cell line name",
      "clade": "one of: Alveolata | Viridiplantae | Stramenopiles | Haptophyta | Cryptista | Unicellular Holozoa | Discoba | Rhodophyta | Fungi | Rhizaria | Glaucophyta | Amoebozoa | Metazoa | Archaea | Bacteria | Unknown",
      "sample_type": "one of: cultured_cell | tissue | whole_organism | organoid | environmental | isolated_protein | other",
      "fixation_reagent": "e.g. paraformaldehyde, glutaraldehyde, methanol — or null",
      "fixation_concentration": "e.g. 4% — or null",
      "fixation_duration": "e.g. 15 min — or null",
      "fixation_temperature": "Capture exactly as written: RT, room temperature, 4°C, 37°C, ice. If paper says at room temperature or at RT extract RT. If temperature is not mentioned and fixation uses PFA or formaldehyde, default to RT — this is the overwhelming norm in ExM. Do NOT default to RT for glutaraldehyde-only, methanol, acetone, or cryo-fixation (use null for those if not stated).",
      "fixation_buffer": "e.g. PBS, PIPES, PHEM — or null",
      "anchoring_reagent": "The anchoring step is the pre-gelation incubation crosslinking proteins to a gel-handle. In U-ExM: FA+acrylamide. In proExM: AcX. Do NOT confuse with the gelation step. null if not stated.",
      "anchoring_concentration": "Concentration of anchoring reagents, e.g. 4% FA + 4% acrylamide. null if not mentioned.",
      "anchoring_duration": "Duration of anchoring incubation, e.g. overnight, 3 h. null if not stated.",
      "anchoring_temperature": "Temperature of anchoring incubation: 4°C, RT, 37°C. RT is valid even without a number. null only if genuinely absent.",
      "gel_sodium_acrylate_pct": "Number only, no percent sign, e.g. 19. RULES: extract if stated explicitly in Methods. If paper cites external recipe without restating numbers: null, do NOT write inferred. inferred: prefix only if you derived it from indirect evidence in this paper. null is correct when recipe is not written out here.",
      "gel_acrylamide_pct": "Same rules. Typical values: 0, 0.5, 10.",
      "gel_bis_pct": "Same rules. Typical values: 0, 0.1, 0.15.",
      "gel_other_components": "Other additives e.g. TEMED, APS, DMAA — or null",
      "homogenization_method": "one of: Proteinase K | heat-SDS | both | other | null",
      "expansion_factor_nominal": "Theoretical EF from Methods or Intro, e.g. 4x. null if not stated.",
      "expansion_factor_measured": "SEARCH ENTIRE PAPER: Results text, figure captions, supplementary captions, abstract. EF is usually reported in Results or figures, not Methods. Report the primary measured value. null only if no measured value is found anywhere.",
      "labelling_strategy": "one of: pre-expansion | post-expansion | both | null",
      "protocol_outcome": "success | partial | fail | null. success=clean signal and isotropic expansion. partial=weak or inconsistent, or only some cells. fail=no signal or gel failure. null=not reported.",
      "labels": [
        {{
          "label_target": "what is detected, e.g. alpha-tubulin, DAPI, actin",
          "label_name": "product name or clone, e.g. TAT-1, Alexa 488 phalloidin",
          "label_type": "one of: primary_antibody | secondary_antibody | nanobody | dye | phalloidin | lectin | tag | other",
          "label_host_species": "e.g. mouse, rabbit — null for non-antibodies",
          "label_supplier": "REQUIRED. Options: company name | gift: [lab name] | in-house | not stated. Search full Methods and all Supplementary. INFER FROM CATALOGUE NUMBER: ABCD_ prefix means ABCD Antibodies; ab[0-9]+ means Abcam; sc- means Santa Cruz; 4-5 digit number or with S suffix means Cell Signaling Technology; PA5- or MA5- means Thermo Fisher; T or F followed by 4 digits Sigma-style means Sigma-Aldrich; 5+ digits-digits-AP means Proteintech; 04- prefix means Millipore. Also known: Agrisera, BioLegend, Jackson ImmunoResearch, DSHB, Rockland, GeneTex, Novus, Bio-Rad, Synaptic Systems, MBL, Bethyl, R&D Systems. not stated is last resort only.",
          "label_catalogue_number": "Search antibody tables, parentheticals in text, figure legend keys, product URLs. Extract code exactly as written. null only if genuinely absent after checking all locations.",
          "label_dilution": "Search antibody tables, Methods text, figure legends. Formats: 1:200, 1/1000, 2 ug/ml. null only if absent everywhere after checking.",
          "label_fluorophore": "For primary Ab with secondaries: null, fluorophore is on secondary. For direct conjugates, dyes, phalloidin: extract fluorophore name. null if not applicable or not stated.",
          "label_application_timing": "one of: pre-expansion | post-expansion | null",
          "label_outcome": "one of: success | partial | fail | null"
        }}
      ]
    }}
  ],
  "extraction_notes": "key caveats and ambiguities only — keep under 300 characters"
}}

GENERAL RULES:
- is_exm_paper false if paper only cites ExM without using it
- null if value not stated. Do not guess.
- inferred: prefix only for values derived from indirect evidence within this paper
- uncertain: prefix only when text is genuinely ambiguous
- Include ALL labels: primary Ab, secondary Ab, dyes, DAPI, phalloidin, nanobodies, lectins, FPs
- One species_entries item per species
- label_supplier never null, use not stated as fallback

TAXONOMY — resolve the genus before assigning clade:
  Metazoa: all animals, all human/mouse/rat cell lines (HeLa, U2OS, RPE1, NIH3T3, COS-7...)
  Fungi: Saccharomyces, Schizosaccharomyces, Aspergillus, Candida, Neurospora
  Unicellular Holozoa: Ichthyosporea (Sphaeroforma, Chromosphaera, Creolimax, Abeoforma, Pigoraptor), Choanoflagellates (Monosiga, Salpingoeca), Filasterea (Capsaspora, Ministeria)
  Discoba: Trypanosoma, Leishmania, Euglena, Naegleria, Giardia
  Alveolata: Ciliates (Tetrahymena, Paramecium, Podophrya, Stentor, Vorticella), Apicomplexa (Plasmodium, Toxoplasma, Cryptosporidium, Perkinsus, Babesia), Dinoflagellates (Symbiodinium, Karenia, Symbiodiniaceae)
  Stramenopiles: Diatoms (Thalassiosira, Phaeodactylum), Oomycetes (Phytophthora, Saprolegnia), Brown algae (Ectocarpus)
  Viridiplantae: all plants and green algae (Arabidopsis, Chlamydomonas, Marchantia, Zea mays)
  Rhizaria: Foraminifera, Radiolaria, Cercozoa (Bigelowiella, Plasmodiophora, Discocelia)
  Amoebozoa: Dictyostelium, Acanthamoeba, Physarum
  Bacteria or Archaea: any prokaryote
CRITICAL: perkinsii in a species name does NOT mean Perkinsozoa or Alveolata — check the genus. Chromosphaera perkinsii is Ichthyosporea which is Unicellular Holozoa.

SELF-VERIFICATION — check each point before returning JSON:
1. Each species clade: does it match the genus? Re-check any unfamiliar organism.
2. Every label with catalogue number starting ABCD_: supplier must be ABCD Antibodies.
3. Every label_supplier set to not stated: did you check the antibody table and all Supplementary sections?
4. fixation_temperature null for a PFA or formaldehyde fixation: set it to RT.
5. expansion_factor_measured null: did you check figure captions and Results text?
6. Any null in label_supplier: change to not stated.

PAPER TEXT:
{text}"""


def build_user_prompt(text):
    return PROMPT_TEMPLATE.format(text=text)


def extract_pdf_text(pdf_path):
    doc = pymupdf.open(str(pdf_path))
    text = "".join(doc[i].get_text() for i in range(len(doc)))
    doc.close()
    return text


def extract_with_claude(client, text):
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = client.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_prompt(text)}]
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logging.warning(f"JSON parse (attempt {attempt+1}): {e}")
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
        except anthropic.RateLimitError:
            logging.warning(f"Rate limit, waiting 60s (attempt {attempt+1})")
            time.sleep(60)
        except Exception as e:
            logging.warning(f"API error (attempt {attempt+1}): {e}")
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    raise RuntimeError(f"All {RETRY_ATTEMPTS} attempts failed")


def count_issues(rows):
    issues = []
    n_unc = sum(
        1 for r in rows for v in r.values()
        if isinstance(v, str) and (v.startswith("uncertain:") or v.startswith("inferred:"))
    )
    if n_unc >= 5:
        issues.append(f"{n_unc} uncertain/inferred fields")
    if all(not r.get("label_name") for r in rows):
        issues.append("no labels extracted")
    if all(not r.get("fixation_reagent") for r in rows):
        issues.append("no protocol details")
    n_null_sup = sum(
        1 for r in rows
        if r.get("label_type") in ("primary_antibody","secondary_antibody","nanobody")
        and not r.get("label_supplier")
    )
    if n_null_sup:
        issues.append(f"{n_null_sup} antibodies with null supplier")
    return issues


def build_rows(pdf_filename, data):
    if not data.get("is_exm_paper", True):
        return []

    paper = {
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
        clade = sp.get("clade", "Unknown")
        if clade not in VALID_CLADES:
            clade = f"uncertain: {clade}"

        proto = {
            "species":                   sp.get("species"),
            "clade":                     clade,
            "sample_type":               sp.get("sample_type"),
            "fixation_reagent":          sp.get("fixation_reagent"),
            "fixation_concentration":    sp.get("fixation_concentration"),
            "fixation_duration":         sp.get("fixation_duration"),
            "fixation_temperature":      sp.get("fixation_temperature"),
            "fixation_buffer":           sp.get("fixation_buffer"),
            "anchoring_reagent":         sp.get("anchoring_reagent"),
            "anchoring_concentration":   sp.get("anchoring_concentration"),
            "anchoring_duration":        sp.get("anchoring_duration"),
            "anchoring_temperature":     sp.get("anchoring_temperature"),
            "gel_sodium_acrylate_pct":   sp.get("gel_sodium_acrylate_pct"),
            "gel_acrylamide_pct":        sp.get("gel_acrylamide_pct"),
            "gel_bis_pct":               sp.get("gel_bis_pct"),
            "gel_other_components":      sp.get("gel_other_components"),
            "homogenization_method":     sp.get("homogenization_method"),
            "expansion_factor_nominal":  sp.get("expansion_factor_nominal"),
            "expansion_factor_measured": sp.get("expansion_factor_measured"),
            "labelling_strategy":        sp.get("labelling_strategy"),
            "protocol_outcome":          sp.get("protocol_outcome"),
            "extraction_notes":          data.get("extraction_notes"),
        }

        labels = sp.get("labels", [])
        if not labels:
            rows.append({**paper, **proto,
                         "label_target": None, "label_name": None,
                         "label_type": None, "label_host_species": None,
                         "label_supplier": None, "label_catalogue_number": None,
                         "label_dilution": None, "label_fluorophore": None,
                         "label_application_timing": None, "label_outcome": None})
        else:
            for lb in labels:
                rows.append({**paper, **proto,
                             "label_target":            lb.get("label_target"),
                             "label_name":              lb.get("label_name"),
                             "label_type":              lb.get("label_type"),
                             "label_host_species":      lb.get("label_host_species"),
                             "label_supplier":          lb.get("label_supplier"),
                             "label_catalogue_number":  lb.get("label_catalogue_number"),
                             "label_dilution":          lb.get("label_dilution"),
                             "label_fluorophore":       lb.get("label_fluorophore"),
                             "label_application_timing": lb.get("label_application_timing"),
                             "label_outcome":           lb.get("label_outcome")})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start",     type=int, default=0)
    parser.add_argument("--limit",     type=int, default=None)
    parser.add_argument("--sample",    type=int, default=None)
    parser.add_argument("--only",      nargs="+", default=None)
    parser.add_argument("--from-file", type=str, default=None,
                        help="Text file with one PDF filename per line")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("Set ANTHROPIC_API_KEY first.\n"
                         "  PowerShell: $env:ANTHROPIC_API_KEY = 'sk-ant-...'")

    logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    logging.info(f"=== Run started (model={MODEL}) ===")

    client = anthropic.Anthropic(api_key=api_key)

    if args.from_file:
        names = Path(args.from_file).read_text(encoding="utf-8").splitlines()
        names = [n.strip() for n in names if n.strip()]
        pdfs = [PAPERS_DIR / n for n in names if (PAPERS_DIR / n).exists()]
        missing = [n for n in names if not (PAPERS_DIR / n).exists()]
        if missing:
            print(f"WARNING not found: {missing}")
    elif args.only:
        pdfs = [PAPERS_DIR / f for f in args.only if (PAPERS_DIR / f).exists()]
        missing = [f for f in args.only if not (PAPERS_DIR / f).exists()]
        if missing:
            print(f"WARNING not found: {missing}")
    else:
        pdfs = sorted(PAPERS_DIR.glob("*.pdf"))
        if args.sample:
            pdfs = pdfs[:args.sample]
        elif args.limit:
            pdfs = pdfs[args.start:args.start + args.limit]
        else:
            pdfs = pdfs[args.start:]

    print(f"Model: {MODEL}")
    print(f"Processing {len(pdfs)} PDFs -> {OUTPUT_CSV}")

    processed = set()
    if OUTPUT_CSV.exists():
        try:
            with open(OUTPUT_CSV, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    processed.add(row.get("pdf_filename", ""))
            print(f"Already processed: {len(processed)} -- skipping")
        except Exception:
            pass

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
                    print("SKIP (no extractable text)")
                    logging.warning(f"SKIP {fname}: {len(text)} chars")
                    with open(FAILED_FILE, "a") as ff:
                        ff.write(f"NO_TEXT\t{fname}\n")
                    continue

                data = extract_with_claude(client, text)
                rows = build_rows(fname, data)

                if not data.get("is_exm_paper", True):
                    print("SKIP (not ExM)")
                    logging.info(f"SKIP {fname}: not ExM")
                    with open(REVIEW_FILE, "a") as rf:
                        rf.write(f"{fname}\tnot-ExM per model\n")
                    continue

                for row in rows:
                    writer.writerow(row)
                csvfile.flush()
                with suppress(OSError):
                    os.fsync(csvfile.fileno())

                total_rows += len(rows)
                issues = count_issues(rows)
                flag = (" ! " + "; ".join(issues)) if issues else ""
                if issues:
                    with open(REVIEW_FILE, "a") as rf:
                        rf.write(f"{fname}\t{'; '.join(issues)}\n")

                print(f"OK ({len(rows)} rows){flag}")
                logging.info(f"OK {fname}: {len(rows)} rows{flag}")

            except Exception as e:
                print(f"FAILED: {e}")
                logging.error(f"FAILED {fname}: {e}")
                with open(FAILED_FILE, "a") as ff:
                    ff.write(f"ERROR\t{fname}\t{e}\n")
                failed.append(fname)

    print(f"\n=== Done: {total_rows} rows written, {len(failed)} failed ===")
    if failed:
        print(f"Failed papers logged in: {FAILED_FILE}")
    logging.info(f"=== Run complete: {total_rows} rows, {len(failed)} failures ===")


if __name__ == "__main__":
    main()
