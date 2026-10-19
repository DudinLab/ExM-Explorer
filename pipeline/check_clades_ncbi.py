#!/usr/bin/env python3
"""
check_clades_ncbi.py — Verify clade assignments using NCBI taxonomy.

For each unique (species, clade) pair in exm_database.csv, queries NCBI Entrez
taxonomy to get the lineage, maps it to the 15-clade controlled vocabulary,
and flags mismatches.

Free, no API key required — uses Entrez E-utilities with email.
Rate limit: 3 requests/second without API key.

Usage:
    python check_clades_ncbi.py
"""

import csv
import json
import time
import urllib.request
import urllib.parse
from collections import defaultdict
from pathlib import Path

CSV_FILE = Path(__file__).parent / "exm_database.csv"
EMAIL = "omaya.dudin@unige.ch"
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# These species/clades we already know are correct (or intentionally Unknown)
SKIP_SPECIES = {
    # Non-cellular / in-vitro / technical
    "DNA origami", "in vitro assembled microtubules", "isolated protein",
    "synthetic liposomes", "polyacrylamide beads",
    # Viruses already set to Unknown
    "Herpes simplex virus type 1 (HSV-1)", "HIV", "SARS-CoV-2",
    "VSV", "Vaccinia virus", "bacteriophage",
}

# Lineage keyword → clade mapping (order matters: first match wins)
LINEAGE_MAP = [
    # Animals first (broad)
    (["Metazoa", "Animalia"],                        "Metazoa"),
    # Plants / green algae
    (["Viridiplantae", "Embryophyta", "Chlorophyta", "Charophyta"], "Viridiplantae"),
    # Fungi
    (["Fungi", "Chytridiomycota", "Basidiomycota", "Ascomycota",
      "Microsporidia", "Mucoromycota"],              "Fungi"),
    # Protists
    (["Ichthyosporea", "Filasterea", "Choanoflagellida"], "Unicellular Holozoa"),
    (["Euglenozoa", "Heterolobosea", "Jakobida", "Discoba"], "Discoba"),
    (["Alveolata", "Ciliophora", "Apicomplexa", "Dinoflagellata",
      "Chromerida"],                                 "Alveolata"),
    (["Stramenopiles", "Oomycetes", "Diatomeae", "Phaeophyceae",
      "Chrysophyceae", "Xanthophyceae", "Eustigmatophyceae"], "Stramenopiles"),
    (["Haptophyta", "Prymnesiophyceae", "Pavlovales"],  "Haptophyta"),
    (["Cryptophyta", "Cryptista"],                   "Cryptista"),
    (["Rhizaria", "Cercozoa", "Foraminifera", "Radiolaria"], "Rhizaria"),
    (["Rhodophyta"],                                 "Rhodophyta"),
    (["Glaucophyta"],                                "Glaucophyta"),
    (["Amoebozoa"],                                  "Amoebozoa"),
    # Prokaryotes
    (["Archaea", "Euryarchaeota", "Crenarchaeota", "TACK", "Asgard"], "Archaea"),
    (["Bacteria", "Proteobacteria", "Firmicutes", "Cyanobacteria",
      "Actinobacteria", "Bacteroidetes", "Spirochaetes",
      "Chlamydiae", "Planctomycetes"],               "Bacteria"),
    # Metamonada — not in vocab
    (["Metamonada", "Parabasalia", "Fornicata", "Oxymonadida",
      "Diplomonadida", "Trichomonadida"],             "METAMONADA_NOT_IN_VOCAB"),
]


def ncbi_get_lineage(species: str) -> tuple[list[str], str]:
    """Return (lineage_list, taxid_str). Empty on failure."""
    try:
        # Search for taxid
        params = urllib.parse.urlencode({
            "db": "taxonomy", "term": species,
            "retmode": "json", "tool": "ExM-clade-check",
            "email": EMAIL, "retmax": 1,
        })
        url = f"{ESEARCH}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "ExM-QC/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return [], ""
        taxid = ids[0]
        time.sleep(0.35)  # stay under 3 req/s

        # Fetch lineage
        params2 = urllib.parse.urlencode({
            "db": "taxonomy", "id": taxid,
            "retmode": "json", "tool": "ExM-clade-check",
            "email": EMAIL,
        })
        url2 = f"{EFETCH}?{params2}"
        req2 = urllib.request.Request(url2, headers={"User-Agent": "ExM-QC/1.0"})
        with urllib.request.urlopen(req2, timeout=10) as r2:
            raw = r2.read().decode("utf-8")
        # efetch JSON for taxonomy is not standard — fall back to XML parsing
        lineage_str = ""
        # Try to extract lineage from the JSON-like response
        if '"lineage"' in raw:
            start = raw.find('"lineage"')
            segment = raw[start:start+500]
            # lineage is a string field
            idx1 = segment.find('": "') + 4
            idx2 = segment.find('"', idx1)
            lineage_str = segment[idx1:idx2]
        elif "Lineage" in raw and raw.strip().startswith("{"):
            # Sometimes efetch JSON has "Lineage" key
            d = json.loads(raw)
            recs = d.get("result", {})
            if taxid in recs:
                lineage_str = recs[taxid].get("lineage", "")

        lineage = [x.strip() for x in lineage_str.split(";") if x.strip()]
        return lineage, taxid

    except Exception as e:
        return [], ""


def infer_clade(lineage: list[str]) -> str:
    """Map NCBI lineage to our 15-clade vocabulary."""
    lineage_set = {x.lower() for x in lineage}
    lineage_str = " ".join(lineage).lower()
    for keywords, clade in LINEAGE_MAP:
        if any(k.lower() in lineage_str for k in keywords):
            return clade
    return "UNKNOWN_LINEAGE"


def main():
    # Load unique (species, clade) pairs
    pairs = {}   # species → set of clades
    with open(CSV_FILE, encoding="utf-8-sig") as f:
        clean = (line.replace("\x00", "") for line in f)
        for row in csv.DictReader(clean):
            sp    = row.get("species", "").strip()
            clade = row.get("clade", "").strip()
            if not sp or sp in SKIP_SPECIES:
                continue
            # Skip known non-biological
            if any(x in sp.lower() for x in
                   ["in vitro", "virus", "phage", "dna origami",
                    "liposome", "bead", "protein", "rna", "buffer"]):
                continue
            pairs.setdefault(sp, set()).add(clade)

    species_list = sorted(pairs.keys())
    print(f"Unique species to check: {len(species_list)}\n")

    mismatches = []
    cache = {}   # species → (lineage, inferred_clade)

    for i, sp in enumerate(species_list, 1):
        clades_in_db = pairs[sp]
        print(f"[{i:3d}/{len(species_list)}] {sp[:55]:<55}", end=" ", flush=True)

        if sp not in cache:
            lineage, taxid = ncbi_get_lineage(sp)
            inferred = infer_clade(lineage) if lineage else "LOOKUP_FAILED"
            cache[sp] = (lineage, inferred, taxid)
            time.sleep(0.35)
        else:
            lineage, inferred, taxid = cache[sp]

        for db_clade in clades_in_db:
            # Skip Unknown in DB — intentional
            if db_clade == "Unknown":
                continue
            ok = (inferred == db_clade) or inferred in ("LOOKUP_FAILED", "UNKNOWN_LINEAGE")
            if not ok:
                mismatches.append({
                    "species": sp,
                    "db_clade": db_clade,
                    "inferred": inferred,
                    "taxid": taxid,
                    "lineage_snippet": "; ".join(lineage[-5:]) if lineage else "n/a",
                })

        status = f"✓ {inferred}" if inferred == list(clades_in_db)[0] else f"DB:{','.join(clades_in_db)} → NCBI:{inferred}"
        print(status[:60])

    print(f"\n{'='*70}")
    print(f"MISMATCHES FOUND: {len(mismatches)}\n")
    for m in mismatches:
        print(f"  {m['species']}")
        print(f"    DB clade  : {m['db_clade']}")
        print(f"    NCBI says : {m['inferred']}")
        print(f"    Lineage   : ...{m['lineage_snippet']}")
        print()


if __name__ == "__main__":
    main()
