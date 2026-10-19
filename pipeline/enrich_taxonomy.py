#!/usr/bin/env python3
"""
enrich_taxonomy.py — Add kingdom + supergroup columns to exm_database.csv.

Full path: kingdom → supergroup → clade (existing)

Usage:
    python enrich_taxonomy.py            # dry run (prints stats)
    python enrich_taxonomy.py --apply
"""
import argparse, csv, shutil
from pathlib import Path

CSV_FILE = Path(__file__).parent / "exm_database.csv"
BACKUP   = Path(__file__).parent / "exm_database_before_enrich_taxonomy.csv"

# clade → (supergroup, kingdom)
CLADE_TAX = {
    # Opisthokonta
    "Metazoa":            ("Opisthokonta", "Eukaryota"),
    "Fungi":              ("Opisthokonta", "Eukaryota"),
    "Unicellular Holozoa":("Opisthokonta", "Eukaryota"),
    # Archaeplastida
    "Viridiplantae":      ("Archaeplastida", "Eukaryota"),
    "Rhodophyta":         ("Archaeplastida", "Eukaryota"),
    "Glaucophyta":        ("Archaeplastida", "Eukaryota"),
    # SAR
    "Alveolata":          ("SAR",           "Eukaryota"),
    "Stramenopiles":      ("SAR",           "Eukaryota"),
    "Rhizaria":           ("SAR",           "Eukaryota"),
    # TSAR orphans (placement still debated)
    "Haptophyta":         ("Haptista",      "Eukaryota"),
    "Cryptista":          ("Cryptista",     "Eukaryota"),
    # Excavata
    "Discoba":            ("Excavata",      "Eukaryota"),
    # Amoebozoa
    "Amoebozoa":          ("Amoebozoa",     "Eukaryota"),
    # Prokaryotes
    "Bacteria":           ("Bacteria",      "Bacteria"),
    "Archaea":            ("Archaea",       "Archaea"),
    # Unknown — will be overridden per-species for known cases
    "Unknown":            ("Unknown",       "Unknown"),
}

# Per-species overrides (for entries currently in Unknown)
SPECIES_TAX_OVERRIDE = {
    # Metamonada (Excavata, but not in 15-clade vocab → clade=Unknown)
    "Giardia intestinalis":      ("Excavata",        "Eukaryota"),
    "Giardia lamblia":           ("Excavata",        "Eukaryota"),
    "Trichomonas vaginalis":     ("Excavata",        "Eukaryota"),
    "Tritrichomonas foetus":     ("Excavata",        "Eukaryota"),
    "Paratrimastix pyriformis":  ("Excavata",        "Eukaryota"),
    # Viruses
    "Herpes simplex virus type 1 (HSV-1)": ("Duplodnaviria", "Virus"),
    "Human immunodeficiency virus (HIV)":  ("Riboviria",     "Virus"),
    "SARS-CoV-2":                          ("Riboviria",     "Virus"),
    "Vesicular stomatitis virus (VSV)":    ("Riboviria",     "Virus"),
    # Synthetic / in vitro
    "DNA origami (synthetic nanostructure)":              ("Synthetic", "Non-biological"),
    "DNA origami nanoruler (synthetic)":                  ("Synthetic", "Non-biological"),
    "in vitro assembled microtubules (bovine/porcine tubulin)": ("Synthetic", "Non-biological"),
    "isolated peptide (synthetic)":                       ("Synthetic", "Non-biological"),
    "isolated protein":                                   ("Synthetic", "Non-biological"),
    "isolated protein (various)":                         ("Synthetic", "Non-biological"),
    "synthetic peptides in ExM hydrogel":                 ("Synthetic", "Non-biological"),
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows, fieldnames = [], []
    with open(CSV_FILE, encoding="utf-8-sig") as f:
        clean = (line.replace("\x00", "") for line in f)
        reader = csv.DictReader(clean)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            rows.append(dict(row))

    # Insert kingdom + supergroup right after clade
    clade_idx = fieldnames.index("clade")
    for col in ("supergroup", "kingdom"):
        if col not in fieldnames:
            fieldnames.insert(clade_idx + 1, col)

    from collections import Counter
    sg_counts = Counter()

    for row in rows:
        clade   = row.get("clade", "").strip()
        species = row.get("species", "").strip()

        # Check per-species override first
        if species in SPECIES_TAX_OVERRIDE:
            sg, kg = SPECIES_TAX_OVERRIDE[species]
        else:
            sg, kg = CLADE_TAX.get(clade, ("Unknown", "Unknown"))

        row["supergroup"] = sg
        row["kingdom"]    = kg
        sg_counts[f"{kg} / {sg}"] += 1

    mode = "DRY RUN" if not args.apply else "APPLY"
    print(f"[{mode}]  {len(rows)} rows\n")
    print(f"{'KINGDOM / SUPERGROUP':<45}  ROWS")
    print("-"*55)
    for key, n in sorted(sg_counts.items(), key=lambda x: -x[1]):
        print(f"  {key:<43}  {n:5d}")

    if args.apply:
        shutil.copy2(CSV_FILE, BACKUP)
        print(f"\nBackup → {BACKUP.name}")
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"Written → {CSV_FILE.name}")
    else:
        print("\n(add --apply to write)")

if __name__ == "__main__":
    main()
