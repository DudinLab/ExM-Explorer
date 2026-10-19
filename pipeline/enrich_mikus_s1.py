"""
Enrich exm_database.csv with 189 missing species from Mikus Cell 2025 Table S1.
All are U-ExM, post-expansion labelling, formaldehyde fixation + NHS-ester anchoring.
"""
import csv, copy, re
from pathlib import Path

CSV = Path("/sessions/trusting-happy-fermat/mnt/ExM_Library/exm_database.csv")
S1  = Path("/sessions/trusting-happy-fermat/mnt/uploads/03ed1a85-c50b-4dbd-8e9e-16eb60d9bbd0-1783005589113_Table S1.xlsx")
OUT = Path("/sessions/trusting-happy-fermat/mnt/ExM_Library/exm_database.csv")

import openpyxl

# ─── Load existing DB ─────────────────────────────────────────────────────────
with open(CSV, encoding="utf-8-sig", errors="replace") as f:
    reader = csv.DictReader(f)
    FIELDNAMES = reader.fieldnames
    rows = [{k: (v or "").strip() for k, v in r.items()} for r in reader]

print(f"Loaded {len(rows)} rows, {len(FIELDNAMES)} columns")

# Template from existing Mikus rows (shared protocol params)
mikus_rows = [r for r in rows if "Mikus_Cell_2025" in r.get("pdf_filename","")]
TEMPLATE = {k: "" for k in FIELDNAMES}
TEMPLATE.update({
    "pdf_filename":              "Mikus_Cell_2025.pdf",
    "doi":                       "10.1016/j.cell.2025.09.027",
    "title":                     "Charting the landscape of cytoskeletal diversity in microbial eukaryotes",
    "first_author":              "Mikus",
    "last_author":               "Dudin",
    "year":                      "2025",
    "journal":                   "Cell",
    "exm_variant":               "U-ExM",
    "paper_type":                "application",
    "new_protocol":              "",
    "kingdom":                   "Eukaryota",
    "sample_type":               "cultured_cell",
    "fixation_reagent":          "formaldehyde",
    "fixation_concentration":    "null",
    "fixation_duration":         "null",
    "fixation_temperature":      "null",
    "fixation_buffer":           "null",
    "anchoring_reagent":         "NHS-ester",
    "anchoring_concentration":   "null",
    "anchoring_duration":        "null",
    "anchoring_temperature":     "null",
    "gel_sodium_acrylate_pct":   "null",
    "gel_acrylamide_pct":        "null",
    "gel_bis_pct":               "null",
    "gel_other_components":      "",
    "homogenization_method":     "null",
    "expansion_factor_nominal":  "null",
    "expansion_factor_measured": "",
    "labelling_strategy":        "post-expansion",
    "extraction_notes":          "Enriched from Table S1: species not visible in main figures but reported in supplementary data.",
})

# ─── Clade → supergroup mapping ───────────────────────────────────────────────
CLADE_TO_SUPERGROUP = {
    "Alveolata":           "SAR",
    "Stramenopiles":       "SAR",
    "Rhizaria":            "SAR",
    "Haptophyta":          "Haptista",
    "Cryptista":           "Cryptista",
    "Discoba":             "Excavata",
    "Viridiplantae":       "Archaeplastida",
    "Rhodophyta":          "Archaeplastida",
    "Glaucophyta":         "Archaeplastida",
    "Amoebozoa":           "Amoebozoa",
    "Metazoa":             "Opisthokonta",
    "Fungi":               "Opisthokonta",
    "Unicellular Holozoa": "Opisthokonta",
    "Bacteria":            "Bacteria",
    "Archaea":             "Archaea",
    "Unknown":             "Unknown",
}

# ─── Staining → label row mapping ─────────────────────────────────────────────
LABEL_MAP = {
    # NHS esters (dyes) — fluorophore extracted from name
    "NHS594":            {"label_type":"dye",               "label_name":"NHS-ester",                      "label_target":"total protein / pan-label",  "label_fluorophore":"NHS-594",   "label_supplier":"not stated"},
    "NHS647":            {"label_type":"dye",               "label_name":"NHS-ester",                      "label_target":"total protein / pan-label",  "label_fluorophore":"NHS-647",   "label_supplier":"not stated"},
    "NHS405":            {"label_type":"dye",               "label_name":"NHS-ester",                      "label_target":"total protein / pan-label",  "label_fluorophore":"NHS-405",   "label_supplier":"not stated"},
    "NHS":               {"label_type":"dye",               "label_name":"NHS-ester",                      "label_target":"total protein / pan-label",  "label_fluorophore":"",          "label_supplier":"not stated"},
    "nhs":               {"label_type":"dye",               "label_name":"NHS-ester",                      "label_target":"total protein / pan-label",  "label_fluorophore":"",          "label_supplier":"not stated"},
    # Hoechst
    "Hoechst":           {"label_type":"dye",               "label_name":"Hoechst 33342",                  "label_target":"DNA",                        "label_fluorophore":"Hoechst",   "label_supplier":"not stated"},
    "Hoecsht":           {"label_type":"dye",               "label_name":"Hoechst 33342",                  "label_target":"DNA",                        "label_fluorophore":"Hoechst",   "label_supplier":"not stated"},
    "hoechst":           {"label_type":"dye",               "label_name":"Hoechst 33342",                  "label_target":"DNA",                        "label_fluorophore":"Hoechst",   "label_supplier":"not stated"},
    "Hoescht":           {"label_type":"dye",               "label_name":"Hoechst 33342",                  "label_target":"DNA",                        "label_fluorophore":"Hoechst",   "label_supplier":"not stated"},
    "Hoeschst":          {"label_type":"dye",               "label_name":"Hoechst 33342",                  "label_target":"DNA",                        "label_fluorophore":"Hoechst",   "label_supplier":"not stated"},
    "Hoecshet":          {"label_type":"dye",               "label_name":"Hoechst 33342",                  "label_target":"DNA",                        "label_fluorophore":"Hoechst",   "label_supplier":"not stated"},
    # Tubulin antibodies
    "Tub_E7":            {"label_type":"primary_antibody",  "label_name":"E7",                             "label_target":"alpha-tubulin",              "label_fluorophore":"",          "label_supplier":"DSHB", "label_catalogue_number":"AB_1157911"},
    "Tub_monos":         {"label_type":"primary_antibody",  "label_name":"anti-alpha/beta-tubulin",        "label_target":"alpha/beta-tubulin",         "label_fluorophore":"",          "label_supplier":"not stated"},
    "tubulin":           {"label_type":"primary_antibody",  "label_name":"anti-alpha/beta-tubulin",        "label_target":"alpha/beta-tubulin",         "label_fluorophore":"",          "label_supplier":"not stated"},
    # Centrin
    "Centrin":           {"label_type":"primary_antibody",  "label_name":"20H5",                           "label_target":"centrin",                    "label_fluorophore":"",          "label_supplier":"not stated"},
    "centrin":           {"label_type":"primary_antibody",  "label_name":"20H5",                           "label_target":"centrin",                    "label_fluorophore":"",          "label_supplier":"not stated"},
    # Actin
    "act":               {"label_type":"primary_antibody",  "label_name":"anti-actin",                     "label_target":"actin",                      "label_fluorophore":"",          "label_supplier":"not stated"},
    # NPC
    "mab414":            {"label_type":"primary_antibody",  "label_name":"mab414",                         "label_target":"nuclear pore complex (NPC)", "label_fluorophore":"",          "label_supplier":"BioLegend", "label_catalogue_number":"902901"},
    # Dyes
    "BioTracker NIR":    {"label_type":"dye",               "label_name":"BioTracker NIR 688 Lysosome Dye","label_target":"lysosomes",                  "label_fluorophore":"NIR",       "label_supplier":"not stated"},
    "BODIPY-Ceramide":   {"label_type":"dye",               "label_name":"BODIPY-Ceramide",                "label_target":"lipid membranes",            "label_fluorophore":"BODIPY",    "label_supplier":"not stated"},
}

def norm(s):
    return (s or "").strip().lower()

def parse_stainings(stain_str):
    """Parse 'Hoechst, Tub_E7, NHS594 and NHS647, Centrin, Tub_monos' into label dicts.
    Multiple panels separated by ' and ' or ';' are combined (deduplicated by label_name)."""
    if not stain_str:
        return []
    # Split panels
    panels = re.split(r'\s+and\s+|;', stain_str)
    seen_names = set()
    labels = []
    for panel in panels:
        tokens = [t.strip() for t in panel.split(",") if t.strip()]
        for token in tokens:
            info = LABEL_MAP.get(token)
            if info and info["label_name"] not in seen_names:
                seen_names.add(info["label_name"])
                labels.append(dict(info))
            elif not info and token not in ("", "null"):
                # Unknown staining — add as generic
                key = token.lower()
                if key not in seen_names:
                    seen_names.add(key)
                    labels.append({
                        "label_type": "other",
                        "label_name": token,
                        "label_target": "",
                        "label_fluorophore": "",
                        "label_supplier": "not stated",
                    })
    return labels

def map_outcome(exp_val):
    v = str(exp_val or "").strip().lower()
    if v == "yes":         return "success"
    if v == "no":          return "fail"
    if "partial" in v or "some" in v: return "partial"
    return "null"

# ─── Load S1 ──────────────────────────────────────────────────────────────────
wb = openpyxl.load_workbook(S1, read_only=True)
ws = wb['Table S1']
s1_rows = list(ws.iter_rows(values_only=True))
s1_data  = [(r[0],r[1],r[3],r[4],r[5],r[6],r[7],r[8]) for r in s1_rows[1:] if r[4]]
# cols: culture_no, class_, clade, species, expanded, stained, stainings, notes

# Species already in DB for Mikus
db_mikus_species = {norm(r["species"]) for r in mikus_rows}

# ─── Build new rows ───────────────────────────────────────────────────────────
new_rows = []
skipped = 0
added_species = set()

for culture_no, class_, clade, species, expanded, stained, stainings, notes in s1_data:
    if norm(species) in db_mikus_species:
        skipped += 1
        continue

    proto_outcome = map_outcome(expanded)
    # label_outcome: if expansion failed, label_outcome=fail; if stained=Yes→success; Partial/Some→partial
    stained_str = str(stained or "").strip().lower()
    if proto_outcome == "fail":
        lbl_outcome = "fail"
    elif stained_str == "yes":
        lbl_outcome = "success"
    elif stained_str in ("partial","some") or "partial" in stained_str or "some" in stained_str:
        lbl_outcome = "partial"
    elif stained_str == "no":
        lbl_outcome = "fail"
    else:
        lbl_outcome = "null"

    # species_detail = class
    species_detail = class_ or ""
    # culture number can go in species_detail too
    if culture_no:
        species_detail = f"{species_detail} (RCC: {culture_no})" if species_detail else f"RCC: {culture_no}"

    proto_row = copy.copy(TEMPLATE)
    proto_row["species"]         = species
    proto_row["clade"]           = clade or ""
    proto_row["kingdom"]         = "Eukaryota"
    proto_row["supergroup"]      = CLADE_TO_SUPERGROUP.get(clade, "Unknown")
    proto_row["species_detail"]  = species_detail
    proto_row["protocol_outcome"]= proto_outcome
    proto_row["extraction_notes"]= f"Added from Table S1. Outcome: expanded={expanded}, stained={stained}. {notes or ''}"

    labels = parse_stainings(stainings)
    if not labels:
        # No staining info — create one row with empty label fields
        labels = [{"label_type":"","label_name":"","label_target":"","label_fluorophore":"","label_supplier":""}]

    for lbl in labels:
        row = copy.copy(proto_row)
        row["label_type"]             = lbl.get("label_type","")
        row["label_name"]             = lbl.get("label_name","")
        row["label_target"]           = lbl.get("label_target","")
        row["label_fluorophore"]      = lbl.get("label_fluorophore","")
        row["label_supplier"]         = lbl.get("label_supplier","")
        row["label_catalogue_number"] = lbl.get("label_catalogue_number","")
        row["label_application_timing"]= "post-expansion" if proto_outcome != "fail" else ""
        row["label_outcome"]          = lbl_outcome
        new_rows.append(row)

    added_species.add(norm(species))

print(f"\nSkipped (already in DB): {skipped}")
print(f"New species added: {len(added_species)}")
print(f"New rows to add: {len(new_rows)}")

# Outcome breakdown
from collections import Counter
proto_oc = Counter(r["protocol_outcome"] for r in new_rows if r["protocol_outcome"])
print(f"Protocol outcomes: {dict(proto_oc)}")

# ─── Append to CSV ────────────────────────────────────────────────────────────
with open(OUT, "a", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
    writer.writerows(new_rows)

print(f"\n✓ Appended {len(new_rows)} rows to exm_database.csv")
print(f"New total: {len(rows) + len(new_rows)} rows")
