#!/usr/bin/env python3
"""
normalise_species_names.py
──────────────────────────
Standardise the `species` column across all rows.

Key normalizations:
  • U2OS / U-2 OS / "Homo sapiens U2OS" variants → "U2OS"
  • HeLa variants → "HeLa"  (HeLa229, HeLa Kyoto, HeLa S3 kept distinct)
  • hTERT-RPE1 variants → "hTERT-RPE1"
  • HEK293 / HEK293T / HEK293FT variants → canonical
  • COS-7, BS-C-1, NIH-3T3, MEF, Jurkat, HUVEC, HFF, etc.
  • Giardia lamblia → Giardia intestinalis  (synonym; intestinalis is valid name)
  • Common descriptors stripped: "(zebrafish)", "(dog)", "(bovine)", etc.
  • iPSC terminology standardised (iPSC → hiPSC for human lines)

Usage:
    python normalise_species_names.py           # dry-run
    python normalise_species_names.py --apply   # write (auto-backup)
"""

import re, argparse, shutil, os
from contextlib import suppress
from pathlib import Path
import pandas as pd

DB = Path("/sessions/trusting-happy-fermat/mnt/ExM_Library/ExM_database_curated.csv")

# ─────────────────────────────────────────────────────────────────────────────
# DIRECT MAP  —  exact-match replacements  (old → new)
# ─────────────────────────────────────────────────────────────────────────────

SPECIES_MAP = {

    # ══════════════════════════════════════════════════════════════════════════
    # U2OS  (all non-modified variants → "U2OS")
    # ══════════════════════════════════════════════════════════════════════════
    "U2OS (human osteosarcoma cell line)":                          "U2OS",
    "U2OS (human osteosarcoma)":                                    "U2OS",
    "U-2 OS (human osteosarcoma cell line)":                        "U2OS",
    "U-2 OS (human osteosarcoma)":                                  "U2OS",
    "Homo sapiens U2OS":                                            "U2OS",
    "Homo sapiens U-2 OS":                                          "U2OS",
    "Homo sapiens U2-OS (HTB-96)":                                  "U2OS",
    "Homo sapiens U2OS (bone osteosarcoma cell line)":              "U2OS",
    "Homo sapiens U2OS (cryo-fixed, ER imaging)":                   "U2OS",
    "Homo sapiens (U2OS)":                                          "U2OS",
    "Homo sapiens (U2OS cells)":                                    "U2OS",
    # NUP96-mEGFP variants (CRISPR knock-in, distinct line)
    "U-2 OS (human osteosarcoma, NUP96-mEGFP knock-in)":           "U2OS (NUP96-mEGFP)",
    "Homo sapiens U-2 OS (NUP96-mEGFP knock-in)":                  "U2OS (NUP96-mEGFP)",
    "Homo sapiens U2OS (U-2 OS-CRISPR-NUP96-mEGFP clone #195)":    "U2OS (NUP96-mEGFP)",
    "Homo sapiens U2OS NUP96-GFP":                                  "U2OS (NUP96-GFP)",

    # ══════════════════════════════════════════════════════════════════════════
    # HeLa  (plain variants → "HeLa"; subclones kept)
    # ══════════════════════════════════════════════════════════════════════════
    "HeLa (CCL-2)":                                                 "HeLa",
    "HeLa (CRM-CCL-2)":                                             "HeLa",
    "HeLa (Homo sapiens)":                                          "HeLa",
    "HeLa (human cervical adenocarcinoma)":                         "HeLa",
    "HeLa (human cervical cancer cell line)":                       "HeLa",
    "HeLa (human cervical carcinoma cell line)":                    "HeLa",
    "HeLa (human cervical carcinoma cells)":                        "HeLa",
    "HeLa (human cervical carcinoma)":                              "HeLa",
    "HeLa cells":                                                   "HeLa",
    "Homo sapiens HeLa":                                            "HeLa",
    "Homo sapiens (HeLa)":                                          "HeLa",
    "HeLa (human) infected with Plasmodium berghei ANKA":           "HeLa (P. berghei ANKA infected)",
    "HeLa FlipIn (human cervical cancer cell line)":                "HeLa FlipIn",
    "Homo sapiens (HeLa-S3)":                                       "HeLa S3",
    # HeLa229 subclone (CCL-2.1 — distinct from CCL-2)
    "HeLa229 (CCL-2.1)":                                            "HeLa229",
    "HeLa229 (human cervical carcinoma)":                           "HeLa229",
    "Homo sapiens HeLa229":                                         "HeLa229",

    # ══════════════════════════════════════════════════════════════════════════
    # hTERT-RPE1  (all variants → "hTERT-RPE1"; TP53-/- kept distinct)
    # ══════════════════════════════════════════════════════════════════════════
    "hTERT RPE-1":                                                  "hTERT-RPE1",
    "hTERT RPE-1 (human retinal pigment epithelial cell line)":     "hTERT-RPE1",
    "hTERT RPE1":                                                   "hTERT-RPE1",
    "hTERT RPE1 (human retinal pigment epithelial cell line)":      "hTERT-RPE1",
    "Homo sapiens RPE-1":                                           "hTERT-RPE1",
    "Homo sapiens RPE-1 (hTERT-immortalized retinal pigment epithelial-1)": "hTERT-RPE1",
    "Homo sapiens RPE1":                                            "hTERT-RPE1",
    "Homo sapiens RPE1 (hTERT-RPE1)":                              "hTERT-RPE1",
    "Homo sapiens hTERT RPE-1":                                     "hTERT-RPE1",
    "Homo sapiens hTERT-RPE-1":                                     "hTERT-RPE1",
    "Homo sapiens hTERT-RPE1":                                      "hTERT-RPE1",
    "Homo sapiens hTERT RPE1":                                      "hTERT-RPE1",
    "RPE-1 (human retinal pigment epithelial cells)":               "hTERT-RPE1",
    "RPE-1-hTERT (human immortalized retinal pigmented epithelial cells)": "hTERT-RPE1",
    "RPE1":                                                         "hTERT-RPE1",
    "RPE1 (human retinal pigment epithelial cell line)":            "hTERT-RPE1",
    "RPE1 (human retinal pigment epithelial cells)":                "hTERT-RPE1",
    "RPE1 (human retinal pigment epithelium cell line)":            "hTERT-RPE1",
    "RPE1 (human retinal pigment epithelial)":                      "hTERT-RPE1",
    "RPE1-hTERT":                                                   "hTERT-RPE1",
    "Homo sapiens hTERT-HPNE":                                      "hTERT-HPNE",
    # TP53 knockout variant
    "Homo sapiens RPE-1 (hTERT RPE-1 TP53-/-)":                    "hTERT-RPE1 (TP53-/-)",
    "Homo sapiens RPE-1 p53-":                                      "hTERT-RPE1 (TP53-/-)",
    "Homo sapiens hTERT-RPE1":                                      "hTERT-RPE1",

    # ══════════════════════════════════════════════════════════════════════════
    # HEK293  (base / T / FT variants)
    # ══════════════════════════════════════════════════════════════════════════
    "HEK 293":                                                      "HEK293",
    "HEK 293 (Human Embryonic Kidney 293)":                         "HEK293",
    "HEK 293 (human embryonic kidney cell line)":                   "HEK293",
    "HEK 293 (human embryonic kidney cells)":                       "HEK293",
    "HEK-293 (Human Embryonic Kidney 293)":                         "HEK293",
    "HEK293 cells (human embryonic kidney)":                        "HEK293",
    "Homo sapiens HEK293":                                          "HEK293",
    # T variant
    "HEK 293T":                                                     "HEK293T",
    # FT variant
    "HEK293-FT (human embryonic kidney cells)":                     "HEK293FT",
    "Homo sapiens HEK-293FT":                                       "HEK293FT",
    "Homo sapiens HEK293FT":                                        "HEK293FT",

    # ══════════════════════════════════════════════════════════════════════════
    # COS-7
    # ══════════════════════════════════════════════════════════════════════════
    "COS-7 (African green monkey kidney fibroblast-like)":          "COS-7",
    "COS-7 (African green monkey kidney)":                          "COS-7",
    "COS-7 (Cercopithecus aethiops kidney)":                        "COS-7",
    "Cercopithecus aethiops (COS7 cells)":                          "COS-7",
    "Cercopithecus aethiops COS-7":                                 "COS-7",
    "Homo sapiens COS-7":                                           "COS-7",

    # ══════════════════════════════════════════════════════════════════════════
    # BS-C-1  (African green monkey kidney)
    # ══════════════════════════════════════════════════════════════════════════
    "BS-C-1 (African green monkey kidney epithelial cell line)":    "BS-C-1",
    "BS-C-1 (African green monkey kidney epithelial cells)":        "BS-C-1",
    "BS-C-1 (African green monkey kidney epithelial)":              "BS-C-1",
    "BSC-1 (African green monkey kidney)":                          "BS-C-1",

    # ══════════════════════════════════════════════════════════════════════════
    # Vero
    # ══════════════════════════════════════════════════════════════════════════
    "Vero cells":                                                   "Vero",
    "Vero cells (ATCC CCL-81)":                                     "Vero",
    "Vero (Cercopithecus aethiops kidney epithelial)":              "Vero",
    "Vero 76 cells (African green monkey, Chlorocebus sabaeus)":    "Vero 76",

    # ══════════════════════════════════════════════════════════════════════════
    # MDCK
    # ══════════════════════════════════════════════════════════════════════════
    "Madin-Darby Canine Kidney type II cells (MDCKII)":             "MDCKII",
    "MDCK II (Madin-Darby canine kidney)":                          "MDCKII",
    "MDCK II (Madin-Darby Canine Kidney, canine cell line)":        "MDCKII",

    # ══════════════════════════════════════════════════════════════════════════
    # NIH-3T3
    # ══════════════════════════════════════════════════════════════════════════
    "NIH 3T3":                                                      "NIH-3T3",
    "NIH-3T3 (mouse fibroblast cell line)":                         "NIH-3T3",

    # ══════════════════════════════════════════════════════════════════════════
    # MEF (mouse embryonic fibroblasts)
    # ══════════════════════════════════════════════════════════════════════════
    "Mouse embryonic fibroblast (MEF)":                             "Mus musculus (MEF)",
    "Mouse embryonic fibroblasts (MEFs)":                           "Mus musculus (MEF)",
    "Mus musculus embryonic fibroblast (MEF)":                      "Mus musculus (MEF)",
    "Mus musculus embryonic fibroblasts (MEF)":                     "Mus musculus (MEF)",
    "Mus musculus (primary mouse embryonic fibroblasts)":           "Mus musculus (MEF)",
    "wild-type mouse embryonic fibroblasts (MEF, ATCC CRL-2991)":  "Mus musculus (MEF)",

    # ══════════════════════════════════════════════════════════════════════════
    # Jurkat
    # ══════════════════════════════════════════════════════════════════════════
    "Jurkat (human T-cell leukemia cell line)":                     "Jurkat",
    "Jurkat Clone E6-1 (human T lymphoblast)":                      "Jurkat Clone E6-1",
    "Jurkat T cells (clone E6-1, human T lymphocyte cells)":        "Jurkat Clone E6-1",
    "Homo sapiens Jurkat T cells (clone E6.1)":                     "Jurkat Clone E6-1",
    "Homo sapiens (Jurkat T-cells, clone E6.1)":                    "Jurkat Clone E6-1",

    # ══════════════════════════════════════════════════════════════════════════
    # HUVEC
    # ══════════════════════════════════════════════════════════════════════════
    "HUVEC (Human Umbilical Vein Endothelial Cells)":               "HUVEC",
    "Homo sapiens (HUVEC)":                                         "HUVEC",
    "Human umbilical vein endothelial cells (HuVEC)":               "HUVEC",
    "Human Umbilical Vein Endothelial Cells (HUVEC)":               "HUVEC",

    # ══════════════════════════════════════════════════════════════════════════
    # HFF  (human foreskin fibroblast)
    # ══════════════════════════════════════════════════════════════════════════
    "Human foreskin fibroblast (HFF)":                              "HFF",
    "Human foreskin fibroblasts (HFF)":                             "HFF",
    "Homo sapiens (HFF — human foreskin fibroblast)":               "HFF",
    "Homo sapiens (HFF, ATCC CCL-171)":                             "HFF",
    "HFF-hTERT (human foreskin fibroblast hTERT)":                  "HFF-hTERT",
    "HFF hTERT (human foreskin fibroblast hTERT)":                  "HFF-hTERT",

    # ══════════════════════════════════════════════════════════════════════════
    # A549
    # ══════════════════════════════════════════════════════════════════════════
    "A549 (human alveolar carcinoma cell line)":                    "A549",
    "Homo sapiens A549":                                            "A549",
    "Homo sapiens (A549)":                                          "A549",

    # ══════════════════════════════════════════════════════════════════════════
    # MCF cell lines
    # ══════════════════════════════════════════════════════════════════════════
    "MCF-10A (immortalized breast epithelial cell line)":           "MCF-10A",
    "MCF10A":                                                       "MCF-10A",
    "MCF-7 (breast cancer cell line)":                              "MCF-7",
    "MCF-7 (human breast cancer cell line)":                        "MCF-7",

    # ══════════════════════════════════════════════════════════════════════════
    # MDA-MB
    # ══════════════════════════════════════════════════════════════════════════
    "MDA-MB-231 (breast cancer cell line)":                         "MDA-MB-231",
    "MDA-MB-468 (breast cancer cell line)":                         "MDA-MB-468",

    # ══════════════════════════════════════════════════════════════════════════
    # Other human cell lines
    # ══════════════════════════════════════════════════════════════════════════
    "A375 (human melanoma cell line)":                              "A375",
    "A498 renal carcinoma (human cell line)":                       "A498",
    "Homo sapiens SH-SY5Y":                                         "SH-SY5Y",
    "Homo sapiens PC3 cells":                                       "PC3",
    "BV173 (human B cell precursor leukemia)":                      "BV173",
    "H4 (Human neuroglioma)":                                       "H4",
    "LoVo (human colorectal cancer cell line)":                     "LoVo",
    "RCC4 (human clear cell renal cell carcinoma cell line)":       "RCC4",
    "U251 (human glioblastoma cell line)":                          "U251",
    "WM983b (human metastatic melanoma cell line)":                 "WM983b",
    "MM.1S (human multiple myeloma)":                               "MM.1S",
    "Chang cells (human conjunctival epithelial)":                  "Chang cells",
    "Neuro-2A (mouse neuroblastoma)":                               "Neuro-2a",

    # ══════════════════════════════════════════════════════════════════════════
    # Rodent cell lines
    # ══════════════════════════════════════════════════════════════════════════
    "Chinese hamster ovary (CHO)":                                  "CHO",
    "Baby hamster kidney (BHK) fibroblasts":                        "BHK",
    "Cricetulus griseus BHK (Baby Hamster Kidney fibroblasts)":     "BHK",
    "MIN6 (Mus musculus insulinoma cell line)":                      "MIN6",

    # ══════════════════════════════════════════════════════════════════════════
    # Homo sapiens tissue / sample descriptors (normalize format only)
    # ══════════════════════════════════════════════════════════════════════════
    "Homo sapiens (human tonsil FFPE tissue)":                      "Homo sapiens (FFPE tonsil tissue)",
    "Homo sapiens HNEC (human nasal epithelial cells)":             "Homo sapiens (Human Nasal Epithelial Cells)",
    "Homo sapiens (bronchial basal stem-cell-derived lung organoids)": "Homo sapiens (bronchial basal stem cell-derived lung organoids)",
    "Homo sapiens (CSF samples from PD patients and controls)":     "Homo sapiens (cerebrospinal fluid — Parkinson disease patients and controls)",
    "Homo sapiens platelets":                                       "Homo sapiens (platelets)",
    "Homo sapiens primary skeletal muscle cells":                   "Homo sapiens (primary skeletal muscle cells)",
    "Homo sapiens (human) - FFPE tissue (kidney, brain, spleen)":  "Homo sapiens (FFPE tissue)",
    "Homo sapiens (human) - lung organoid":                         "Homo sapiens (lung organoid)",

    # iPSC: standardise format and iPSC→hiPSC for human lines
    "Homo sapiens iPSC-derived brain organoids":                    "Homo sapiens (hiPSC-derived brain organoids)",
    "Homo sapiens iPSC-derived cortical organoids":                 "Homo sapiens (hiPSC-derived cortical organoids)",
    "Homo sapiens hiPSC-derived cardiomyocytes":                    "Homo sapiens (hiPSC-derived cardiomyocytes)",
    "Homo sapiens glutamatergic neurons (iPSC-derived)":            "Homo sapiens (hiPSC-derived glutamatergic neurons)",
    "human iPSC (induced pluripotent stem cells)":                  "Homo sapiens (hiPSC)",
    "human iPSC-derived neurons (C9orf72 ALS and WT control)":      "Homo sapiens (hiPSC-derived neurons, C9orf72 ALS/WT)",
    "human induced pluripotent stem cell-derived cortical neurons (hiPSC-neurons)": "Homo sapiens (hiPSC-derived cortical neurons)",

    # ══════════════════════════════════════════════════════════════════════════
    # Model organisms — strip common-name parentheticals
    # ══════════════════════════════════════════════════════════════════════════
    "Danio rerio (zebrafish)":                                      "Danio rerio",
    "Danio rerio (zebrafish) — Dent's fixation":               "Danio rerio",
    "Callithrix jacchus (common marmoset)":                         "Callithrix jacchus",
    "Macaca mulatta (rhesus macaque)":                              "Macaca mulatta",
    "Canis lupus familiaris (dog)":                                 "Canis lupus familiaris",
    "Bos taurus (bovine)":                                          "Bos taurus",
    "Sus scrofa (porcine)":                                         "Sus scrofa",
    "Sus scrofa domesticus (domestic pig)":                         "Sus scrofa",
    "Sus scrofa (primary porcine brain endothelial cells)":         "Sus scrofa (primary brain endothelial cells)",
    "Rattus norvegicus (rat)":                                      "Rattus norvegicus",
    "Rattus norvegicus domestica (primary hippocampal neurons)":    "Rattus norvegicus (primary hippocampal neurons)",
    "Rattus norvegicus hippocampal neurons (cultured)":             "Rattus norvegicus (cultured hippocampal neurons)",
    "Drosophila melanogaster ovary":                                "Drosophila melanogaster (ovary)",

    # ══════════════════════════════════════════════════════════════════════════
    # Taxonomy: valid name corrections
    # ══════════════════════════════════════════════════════════════════════════
    # Giardia lamblia = Giardia intestinalis (intestinalis is the valid name)
    "Giardia lamblia":                                              "Giardia intestinalis",
}

# ─────────────────────────────────────────────────────────────────────────────
# Apply
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    df = pd.read_csv(DB, encoding="utf-8-sig", low_memory=False)
    df = df.map(lambda x: x.replace("\x00", "") if isinstance(x, str) else x)

    changes = []
    for idx in df.index:
        old = df.at[idx, "species"]
        if not isinstance(old, str):
            continue
        new = SPECIES_MAP.get(old.strip())
        if new is None or new == old:
            continue
        changes.append((idx, old, new))
        df.at[idx, "species"] = new

    # Summary grouped by (old → new)
    from collections import Counter
    by_pair = Counter((old, new) for _, old, new in changes)
    print(f"Total rows changed: {len(changes)}")
    print(f"Unique mappings applied: {len(by_pair)}\n")
    for (old, new), cnt in sorted(by_pair.items(), key=lambda x: x[0][1]):
        print(f"  {cnt:4d}×  {old!r}")
        print(f"        → {new!r}")

    # Species counts after
    print(f"\nUnique species before: {len(set(SPECIES_MAP.keys()) | set(df['species'].dropna()))}")
    after_unique = df["species"].nunique()
    print(f"Unique species after:  {after_unique}")

    if not args.apply:
        print("\nDry run — pass --apply to save.")
        return

    backup = DB.with_suffix(".pre_species_norm.bak.csv")
    shutil.copy(DB, backup)
    print(f"\nBackup: {backup.name}")
    with open(DB, "w", encoding="utf-8-sig", newline="") as f:
        df.to_csv(f, index=False)
        with suppress(OSError):
            os.fsync(f.fileno())
    print(f"Saved {DB.name}  ({len(df)} rows)")

if __name__ == "__main__":
    main()
