#!/usr/bin/env python3
"""
run_ncbi_check.py — QC 07: clade concordance vs NCBI Taxonomy (current database).

Self-contained version of check_clades_ncbi.py that reads the CURRENT file
(ExM_database_curated.csv), queries NCBI Entrez for every species, maps the
lineage to the 15-clade vocabulary, and writes two outputs INTO THIS FOLDER:
    concordance_summary.txt   — the headline concordance % and counts
    clade_mismatches.csv      — every species where DB clade != NCBI clade

No API key needed — free NCBI E-utilities (just internet + an email).
Takes ~5-8 min. Run from anywhere:

    python QC\07_ncbi_clade_concordance\run_ncbi_check.py
"""
import csv, json, time, urllib.request, urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
CSV_FILE = HERE.parents[1] / "data" / "ExM_database_curated.csv"   # ExM_Library/ExM_database_curated.csv
EMAIL = "omaya.dudin@unige.ch"
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

LINEAGE_MAP = [
    (["Metazoa", "Animalia"], "Metazoa"),
    (["Viridiplantae", "Embryophyta", "Chlorophyta", "Charophyta"], "Viridiplantae"),
    (["Fungi", "Chytridiomycota", "Basidiomycota", "Ascomycota", "Microsporidia", "Mucoromycota"], "Fungi"),
    (["Ichthyosporea", "Filasterea", "Choanoflagellida"], "Unicellular Holozoa"),
    (["Euglenozoa", "Heterolobosea", "Jakobida", "Discoba"], "Discoba"),
    (["Alveolata", "Ciliophora", "Apicomplexa", "Dinoflagellata", "Chromerida"], "Alveolata"),
    (["Stramenopiles", "Oomycetes", "Diatomeae", "Phaeophyceae", "Chrysophyceae", "Xanthophyceae", "Eustigmatophyceae"], "Stramenopiles"),
    (["Haptophyta", "Prymnesiophyceae", "Pavlovales"], "Haptophyta"),
    (["Cryptophyta", "Cryptista"], "Cryptista"),
    (["Rhizaria", "Cercozoa", "Foraminifera", "Radiolaria"], "Rhizaria"),
    (["Rhodophyta"], "Rhodophyta"),
    (["Glaucophyta"], "Glaucophyta"),
    (["Amoebozoa"], "Amoebozoa"),
    (["Archaea", "Euryarchaeota", "Crenarchaeota", "TACK", "Asgard"], "Archaea"),
    (["Bacteria", "Proteobacteria", "Firmicutes", "Cyanobacteria", "Actinobacteria", "Bacteroidetes", "Spirochaetes", "Chlamydiae", "Planctomycetes"], "Bacteria"),
    (["Metamonada", "Parabasalia", "Fornicata", "Oxymonadida", "Diplomonadida", "Trichomonadida"], "METAMONADA_NOT_IN_VOCAB"),
]
SKIP = ["in vitro", "virus", "phage", "dna origami", "liposome", "bead", "protein", "rna", "buffer"]

def get_lineage(species):
    try:
        p = urllib.parse.urlencode({"db":"taxonomy","term":species,"retmode":"json","tool":"ExM-QC","email":EMAIL,"retmax":1})
        req = urllib.request.Request(f"{ESEARCH}?{p}", headers={"User-Agent":"ExM-QC/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r: data = json.loads(r.read())
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids: return []
        taxid = ids[0]; time.sleep(0.35)
        # efetch for db=taxonomy returns XML (retmode=json is ignored). Parse <Lineage>.
        p2 = urllib.parse.urlencode({"db":"taxonomy","id":taxid,"tool":"ExM-QC","email":EMAIL})
        req2 = urllib.request.Request(f"{EFETCH}?{p2}", headers={"User-Agent":"ExM-QC/1.0"})
        with urllib.request.urlopen(req2, timeout=10) as r2: raw = r2.read().decode("utf-8", "replace")
        import re as _re
        m = _re.search(r"<Lineage>(.*?)</Lineage>", raw, _re.S)
        lin = m.group(1) if m else ""
        if not lin:  # fall back to LineageEx <ScientificName> nodes
            lin = "; ".join(_re.findall(r"<ScientificName>(.*?)</ScientificName>", raw))
        return [x.strip() for x in lin.split(";") if x.strip()]
    except Exception:
        return []

def infer(lineage):
    s = " ".join(lineage).lower()
    for kws, clade in LINEAGE_MAP:
        if any(k.lower() in s for k in kws): return clade
    return "UNKNOWN_LINEAGE"

def main():
    pairs = {}
    with open(CSV_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(l.replace("\x00","") for l in f):
            sp = (row.get("species") or "").strip(); cl = (row.get("clade") or "").strip()
            if not sp or any(x in sp.lower() for x in SKIP): continue
            pairs.setdefault(sp, set()).add(cl)
    species = sorted(pairs)
    print(f"Querying NCBI for {len(species)} species (~{len(species)*0.7/60:.0f} min)...\n")
    checkable = matched = failed = 0; mism = []
    for i, sp in enumerate(species, 1):
        lin = get_lineage(sp); inf = infer(lin) if lin else "LOOKUP_FAILED"
        time.sleep(0.35)
        for db in pairs[sp]:
            if db == "Unknown": continue
            if inf in ("LOOKUP_FAILED", "UNKNOWN_LINEAGE", "METAMONADA_NOT_IN_VOCAB"):
                failed += 1; continue
            checkable += 1
            if inf == db: matched += 1
            else: mism.append({"species": sp, "db_clade": db, "ncbi_clade": inf, "lineage_tail": "; ".join(lin[-4:])})
        if i % 25 == 0: print(f"  {i}/{len(species)} done")
    pct = 100*matched/checkable if checkable else 0
    with open(HERE/"concordance_summary.txt","w",encoding="utf-8") as f:
        f.write(f"NCBI clade concordance (QC 07)\n{'='*40}\n")
        f.write(f"Species queried:        {len(species)}\n")
        f.write(f"Clade assignments checkable against NCBI: {checkable}\n")
        f.write(f"Matched NCBI:           {matched}\n")
        f.write(f"Mismatches:             {len(mism)}\n")
        f.write(f"Not resolvable (no taxid / not in vocab): {failed}\n\n")
        f.write(f"CONCORDANCE: {pct:.1f}%\n")
    with open(HERE/"clade_mismatches.csv","w",newline="",encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["species","db_clade","ncbi_clade","lineage_tail"]); w.writeheader(); w.writerows(mism)
    print(f"\nDONE. Concordance: {pct:.1f}%  ({matched}/{checkable}).  {len(mism)} mismatches.")
    print(f"Wrote concordance_summary.txt and clade_mismatches.csv in {HERE.name}/")

if __name__ == "__main__":
    main()
