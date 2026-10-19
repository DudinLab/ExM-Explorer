#!/usr/bin/env python3
"""
normalize_species.py — Normalize species names and extract cell_line column.

New columns added:
  cell_line       — canonical name of the cell line (empty if tissue/primary cells)
  species_detail  — the original parenthetical/descriptor preserved verbatim
  needs_review    — non-empty string describing what a human should check

species column is modified in-place for cell-line entries:
  e.g. "HeLa (Homo sapiens)" → "Homo sapiens"  (cell_line → "HeLa")

Usage:
    python normalize_species.py            # dry run
    python normalize_species.py --apply
"""
import argparse, csv, shutil, re
from pathlib import Path

CSV_FILE = Path(__file__).parent / "exm_database.csv"
BACKUP   = Path(__file__).parent / "exm_database_before_normalize_species.csv"

# ── Explicit map: original_species → (canonical_species, cell_line, needs_review) ──
# Entries NOT in this map keep their species unchanged and get needs_review="unmapped"
# (there should be very few of those after this list)

M = {}  # populated below for readability

def _h(orig, cl="", review=""):
    """Register: (original) → (Homo sapiens, cell_line, review)"""
    M[orig] = ("Homo sapiens", cl, review)

def _m(orig, species, cl="", review=""):
    M[orig] = (species, cl, review)

# ── Homo sapiens — HeLa variants ─────────────────────────────────────────────
_h("HeLa",                                      "HeLa")
_h("HeLa cells",                                "HeLa")
_h("HeLaP4",                                    "HeLaP4")
_h("HeLa (Homo sapiens)",                       "HeLa")
_h("HeLa (Homo sapiens cervical adenocarcinoma)","HeLa")
_h("HeLa (Kyoto)",                              "HeLa-Kyoto")
_h("HeLa (NUP43-GFP expressing)",               "HeLa")
_h("HeLa (NUP96-SNAP expressing)",               "HeLa")
_h("HeLa (SNAP-CLC-YFP expressing)",             "HeLa")
_h("HeLa (human cervical cancer cell line)",     "HeLa")
_h("HeLa (human cervical cancer cells)",         "HeLa")
_h("HeLa (human cervical cancer)",               "HeLa")
_h("HeLa (infected with Plasmodium berghei)",    "HeLa")
_h("HeLa229 (Homo sapiens)",                     "HeLa229")
_h("HeLa229 (Homo sapiens) infected with Chlamydia trachomatis", "HeLa229")
_h("HeLa229 infected with Chlamydia trachomatis","HeLa229")
_h("Homo sapiens (HeLa)",                        "HeLa")
_h("Homo sapiens (HeLa cells)",                  "HeLa")
_h("Homo sapiens (HeLa cells, ExFISH)",          "HeLa")
_h("Homo sapiens (HeLa FlipIn cells)",           "HeLa FlpIn")
_h("Homo sapiens (HeLa FlpIn cells)",            "HeLa FlpIn")
_h("Homo sapiens (HeLa S3)",                     "HeLa S3")
_h("Homo sapiens (HeLa-S3)",                     "HeLa S3")
_h("Homo sapiens (HeLa229)",                     "HeLa229")
_h("Homo sapiens HeLa",                          "HeLa")
_h("Homo sapiens HeLa-Kyoto",                    "HeLa-Kyoto")

# ── A549 ──────────────────────────────────────────────────────────────────────
_h("A549 (Homo sapiens lung adenocarcinoma)",    "A549")
_h("A549 (human lung carcinoma)",                "A549")
_h("Homo sapiens (A549)",                        "A549")
_h("Homo sapiens (A549 cell line)",              "A549")
_h("Homo sapiens (A549 cell line, PEI transfected)","A549")
_h("Homo sapiens (A549 cells)",                  "A549")
_h("Homo sapiens (A375 melanoma cells)",         "A375")
_h("Homo sapiens (A498 RFP + NK92 GFP co-culture)","A498")
_h("Homo sapiens (A498 renal carcinoma)",        "A498")

# ── U-2 OS / U2OS ─────────────────────────────────────────────────────────────
_h("U-2 OS",                                     "U-2 OS")
_h("U2OS",                                       "U-2 OS")
_h("U2OS (Homo sapiens osteosarcoma)",           "U-2 OS")
_h("U2OS (human osteosarcoma cell line)",        "U-2 OS")
_h("U2OS (human osteosarcoma)",                  "U-2 OS")
_h("U2OS cells (human osteosarcoma)",            "U-2 OS")
_h("Homo sapiens (U-2 OS cells)",                "U-2 OS")
_h("Homo sapiens (U-2 OS)",                      "U-2 OS")
_h("Homo sapiens (U2OS NUP96-GFP)",             "U-2 OS")
_h("Homo sapiens (U2OS Sec61β-GFP)",            "U-2 OS")
_h("Homo sapiens (U2OS cells)",                  "U-2 OS")
_h("Homo sapiens (U2OS osteosarcoma cells)",     "U-2 OS")
_h("Homo sapiens (U2OS osteosarcoma cells) — iU-ExM","U-2 OS")
_h("Homo sapiens (U2OS)",                        "U-2 OS")
_h("Homo sapiens (U2OS) — iU-ExM",              "U-2 OS")
_h("Homo sapiens (U2OS, isolated nuclei)",       "U-2 OS")
_h("Homo sapiens (U87MG glioblastoma)",          "U87MG")
_h("Homo sapiens (U251 glioma cells)",           "U251")
_h("Homo sapiens U-2 OS",                        "U-2 OS")
_h("Homo sapiens U-2 OS (NUP96-mEGFP knock-in)","U-2 OS")
_h("Homo sapiens U2OS",                          "U-2 OS")

# ── HEK293 variants ───────────────────────────────────────────────────────────
_h("HEK 293",                                    "HEK293")
_h("HEK 293T (human embryonic kidney cells)",    "HEK293T")
_h("HEK293",                                     "HEK293")
_h("HEK293 cells (human embryonic kidney)",      "HEK293")
_h("HEK293FT cells",                             "HEK293FT")
_h("HEK293T (Homo sapiens)",                     "HEK293T")
_h("Homo sapiens (HEK 293 cells)",               "HEK293")
_h("Homo sapiens (HEK 293T)",                    "HEK293T")
_h("Homo sapiens (HEK cells)",                   "HEK293",  "check: 'HEK cells' assumed HEK293")
_h("Homo sapiens (HEK-293)",                     "HEK293")
_h("Homo sapiens (HEK293 cells)",                "HEK293")
_h("Homo sapiens (HEK293-FT)",                   "HEK293FT")
_h("Homo sapiens (HEK293FT)",                    "HEK293FT")
_h("Homo sapiens (HEK293T)",                     "HEK293T")
_h("Homo sapiens HEK 293T",                      "HEK293T")

# ── RPE-1 variants ────────────────────────────────────────────────────────────
_h("RPE1 (Homo sapiens retinal pigment epithelial)","RPE-1")
_h("hTERT RPE-1 (Homo sapiens)",                 "RPE-1 hTERT")
_h("Homo sapiens (RPE-1 cells)",                 "RPE-1")
_h("Homo sapiens (RPE-1)",                       "RPE-1")
_h("Homo sapiens (RPE-1-hTERT cells)",           "RPE-1 hTERT")
_h("Homo sapiens (RPE1 cells)",                  "RPE-1")
_h("Homo sapiens (RPE1)",                        "RPE-1")
_h("Homo sapiens (RPE1-hTERT)",                  "RPE-1 hTERT")
_h("Homo sapiens (hTERT RPE-1 TP53-/-)",         "RPE-1 hTERT p53-/-")
_h("Homo sapiens (hTERT RPE-1 cells)",           "RPE-1 hTERT")
_h("Homo sapiens (hTERT RPE-1 p53-/- cells)",    "RPE-1 hTERT p53-/-")
_h("Homo sapiens (hTERT RPE-1)",                 "RPE-1 hTERT")
_h("Homo sapiens (hTERT RPE1 cells)",            "RPE-1 hTERT")
_h("Homo sapiens (hTERT RPE1)",                  "RPE-1 hTERT")
_h("Homo sapiens (hTERT-HPNE)",                  "hTERT-HPNE")
_h("Homo sapiens (hTERT-RPE-1)",                 "RPE-1 hTERT")
_h("Homo sapiens (hTERT-RPE1)",                  "RPE-1 hTERT")
_h("Homo sapiens RPE-1",                         "RPE-1")
_h("Homo sapiens RPE-1 (retinal pigment epithelial cells)","RPE-1")
_h("Homo sapiens RPE-1 (retinal pigment epithelial)","RPE-1")
_h("Homo sapiens RPE1",                          "RPE-1")

# ── Huh7 ──────────────────────────────────────────────────────────────────────
_h("Huh7.5.1 (human hepatoma cell line)",        "Huh7.5.1")
_h("Homo sapiens (Huh7)",                        "Huh7")

# ── MCF variants ──────────────────────────────────────────────────────────────
_h("MCF-7 (Homo sapiens breast cancer)",         "MCF-7")
_h("MCF10A (human mammary epithelial cell line)","MCF-10A")
_h("MDA-MB-231 (human breast cancer cell line)", "MDA-MB-231")
_h("Homo sapiens (MCF-7 breast cancer cells)",   "MCF-7")
_h("Homo sapiens (MCF-7)",                       "MCF-7")

# ── Other established human lines ─────────────────────────────────────────────
_h("HL-60 (human promyelocytic leukemia cells)", "HL-60")
_h("HOS cells (human osteosarcoma)",             "HOS")
_h("Jurkat (human T lymphocyte cells)",          "Jurkat")
_h("Jurkat T cells (human)",                     "Jurkat")
_h("Chang (Homo sapiens conjunctival epithelial cells)","Chang")
_h("Chang cells (Homo sapiens conjunctival epithelial) infected with Neisseria gonorrhoeae","Chang")
_h("Caco-2 cells (human colorectal adenocarcinoma)","Caco-2")
_h("SH-SY5Y (Homo sapiens neuroblastoma)",       "SH-SY5Y")
_h("Human umbilical vein endothelial cells (HuVEC, Homo sapiens)","HUVEC")
_h("iD98/HR1 (EBV-positive Homo sapiens cell line)","iD98/HR1")
_h("Homo sapiens (BEAS-2B cell line)",           "BEAS-2B")
_h("Homo sapiens (CFBE41o and CFBE41o-6.2 human bronchial epithelial cells)","CFBE41o")
_h("Homo sapiens (CRL-2097 / CCD-1079Sk)",      "CRL-2097")
_h("Homo sapiens (GBM tumorsphere cell lines)",  "GBM tumorsphere")
_h("Homo sapiens (GBM#18 glioblastoma)",         "GBM#18")
_h("Homo sapiens (GES1 gastric epithelial cells)","GES1")
_h("Homo sapiens (H4 neuroglioma cells)",        "H4")
_h("Homo sapiens (HFF - human foreskin fibroblasts)","HFF")
_h("Homo sapiens (HFF host cells)",              "HFF")
_h("Homo sapiens (HFF)",                         "HFF")
_h("Homo sapiens (HFF-hTERT cells infected with HSV-1)","HFF hTERT")
_h("Homo sapiens (HNEC - human nasal epithelial cells)","HNEC")
_h("Homo sapiens (HUVEC)",                       "HUVEC")
_h("Homo sapiens (Hep3B hepatocellular carcinoma)","Hep3B")
_h("Homo sapiens (Jurkat T cells)",              "Jurkat")
_h("Homo sapiens (Jurkat T lymphocyte, clone E6.1)","Jurkat")
_h("Homo sapiens Jurkat T cells (clone E6.1)",  "Jurkat")
_h("Homo sapiens (LoVo colorectal cancer cells)","LoVo")
_h("Homo sapiens (MucilAir hTEC)",               "MucilAir")
_h("Homo sapiens (hTEC - MucilAir human tracheal epithelial cells)","MucilAir")
_h("Homo sapiens (NK cells)",                    "NK cells")
_h("Homo sapiens (RCC4 clear cell renal cell carcinoma cells)","RCC4")
_h("Homo sapiens (SA501 PDX breast cancer tissue)","SA501 PDX")
_h("Homo sapiens (UCI082014 breast cancer cell)","UCI082014")
_h("Homo sapiens (WM983b-GFP melanoma cells)",   "WM983b")
_h("Homo sapiens (hTERT BJ fibroblasts)",        "BJ hTERT")
_h("Homo sapiens SH-SY5Y neuroblastoma",         "SH-SY5Y")
_h("Homo sapiens PC3 cells",                     "PC3")
_h("Homo sapiens Caco-2 BBE",                    "Caco-2 BBE")
_h("Homo sapiens iPSC (induced pluripotent stem cells)","iPSC")
_h("Homo sapiens iPSC-derived neurons (iPSNs, C9orf72 ALS patient and WT control)","iPSC-derived neurons")

# ── Homo sapiens — tissues, organoids, primary cells (cell_line = "") ─────────
for _sp in [
    "Homo sapiens",
    "Homo sapiens (DLB patient brain tissue, cingulate gyrus)",
    "Homo sapiens (FFPE archival autopsy/biopsy)",
    "Homo sapiens (FFPE brain - hippocampus and middle frontal gyrus)",
    "Homo sapiens (FFPE brain tissue)",
    "Homo sapiens (FFPE kidney tissue)",
    "Homo sapiens (FFPE spleen tissue)",
    "Homo sapiens (FFPE tonsil)",
    "Homo sapiens (FFPE tumor tissues - spleen, kidney, intestine, brain, pancreas)",
    "Homo sapiens (bladder cancer)",
    "Homo sapiens (brain tumor biopsy)",
    "Homo sapiens (breast tissue)",
    "Homo sapiens (bronchial epithelial cells with MS2-GFP)",
    "Homo sapiens (cerebral organoid)",
    "Homo sapiens (cerebral organoids, H9 hESC-derived)",
    "Homo sapiens (clinical plasma EVs)",
    "Homo sapiens (cornea tissue)",
    "Homo sapiens (cornea)",
    "Homo sapiens (cultured human cells)",
    "Homo sapiens (hiPSC-derived brain organoids and neural rosettes)",
    "Homo sapiens (hiPSC-derived cardiomyocytes)",
    "Homo sapiens (hiPSC-derived cortical neurons)",
    "Homo sapiens (hiPSC-derived cortical organoids and neural rosettes)",
    "Homo sapiens (high-grade glioma)",
    "Homo sapiens (hippocampal epilepsy surgery specimen)",
    "Homo sapiens (human forebrain organoid)",
    "Homo sapiens (human nasal airway epithelial cells)",
    "Homo sapiens (human platelets)",
    "Homo sapiens (human primary skeletal muscle cells)",
    "Homo sapiens (human skeletal muscle cells)",
    "Homo sapiens (human skin tissue)",
    "Homo sapiens (human sperm)",
    "Homo sapiens (iPSC-derived brain organoids)",
    "Homo sapiens (iPSC-derived cortical organoids with microglia)",
    "Homo sapiens (kidney glomerulus)",
    "Homo sapiens (low-grade glioma)",
    "Homo sapiens (lung organoid)",
    "Homo sapiens (metastatic breast cancer biopsy)",
    "Homo sapiens (normal brain)",
    "Homo sapiens (patient GCP4 mutant fibroblasts)",
    "Homo sapiens (patient-derived fibroblasts, GCP4 mutant and WT control)",
    "Homo sapiens (platelets)",
    "Homo sapiens (primary breast tumor patient-derived organoid)",
    "Homo sapiens (primary neutrophils)",
    "Homo sapiens (primary pancreatic islets)",
    "Homo sapiens (retinal organoid from HS980 hESC)",
    "Homo sapiens (skeletal muscle cells)",
    "Homo sapiens (sperm cells)",
    "Homo sapiens (spleen tissue)",
    "Homo sapiens (submandibular gland organoid)",
    "Homo sapiens (surgical explant)",
]:
    _h(_sp, cl="")

# ── Monkey (Chlorocebus sabaeus / COS-7 / BS-C-1 / Vero) ─────────────────────
CHS = "Chlorocebus sabaeus"
for _sp, _cl in [
    ("COS-7 (Cercopithecus aethiops kidney fibroblast)",   "COS-7"),
    ("COS-7 (Cercopithecus aethiops)",                      "COS-7"),
    ("Cos-7",                                               "COS-7"),
    ("Cos-7 (Cercopithecus aethiops)",                      "COS-7"),
    ("Cercopithecus aethiops",                              ""),
    ("Cercopithecus aethiops (COS-7 monkey kidney cells)",  "COS-7"),
    ("Cercopithecus aethiops (COS-7)",                      "COS-7"),
    ("Cercopithecus aethiops (COS7 cells)",                 "COS-7"),
    ("Cercopithecus aethiops (COS7)",                       "COS-7"),
    ("Cercopithecus aethiops (Vero cells)",                 "Vero"),
    ("Cercopithecus aethiops COS7",                         "COS-7"),
    ("Chlorocebus sabaeus (BSC-1)",                         "BS-C-1"),
    ("Chlorocebus sabaeus (COS-7 cell line)",               "COS-7"),
    ("Chlorocebus sabaeus (COS-7)",                         "COS-7"),
    ("BS-C-1 (African green monkey kidney epithelial cells)","BS-C-1"),
    ("BS-C-1 (African green monkey kidney)",                "BS-C-1"),
    ("BS-C-1 (Cercopithecus aethiops kidney epithelial cells)","BS-C-1"),
    ("BS-C-1 (Cercopithecus aethiops kidney)",              "BS-C-1"),
    ("Vero (Cercopithecus aethiops kidney epithelial)",     "Vero"),
    ("Vero 76 cells (Chlorocebus sabaeus)",                 "Vero 76"),
    ("Vero cells (African green monkey kidney)",            "Vero"),
    ("Vero cells (Cercopithecus aethiops)",                 "Vero"),
]:
    M[_sp] = (CHS, _cl, "")

# ── Wrong-species errors: COS-7 listed as Homo sapiens ───────────────────────
_m("Homo sapiens (COS7 cells)",   CHS, "COS-7", "species_error: COS-7 is Chlorocebus sabaeus")
_m("Homo sapiens Cos-7",          CHS, "COS-7", "species_error: COS-7 is Chlorocebus sabaeus")

# ── Dog (Canis lupus familiaris) ──────────────────────────────────────────────
CLF = "Canis lupus familiaris"
_m("Canis lupus familiaris",                                     CLF, "")
_m("Canis lupus familiaris (dog)",                               CLF, "")
_m("Canis lupus familiaris (MDCK II cells)",                     CLF, "MDCK II")
_m("Canis lupus familiaris (MDCK cells, FTM-AQP2-MDCK)",        CLF, "MDCK")
_m("Canis lupus familiaris (MDCKII)",                            CLF, "MDCK II")
_m("MDCK (Madin-Darby Canine Kidney)",                           CLF, "MDCK")
_m("MDCK (Madin-Darby canine kidney)",                           CLF, "MDCK")
_m("Madin-Darby canine kidney (MDCK) type IIG cells",           CLF, "MDCK IIG")

# ── Rat (Rattus norvegicus) ───────────────────────────────────────────────────
RN = "Rattus norvegicus"
_m("INS-1E (Insulinoma 1E rat beta cell line)",                  RN, "INS-1E")
_m("INS-1E rat insulinoma cells",                                RN, "INS-1E")
_m("Rattus norvegicus (NRK49F cell line)",                       RN, "NRK49F")
_m("Rattus norvegicus (Sprague Dawley)",                         RN, "")
_m("Rattus norvegicus (Sprague-Dawley primary cortical neurons)",RN, "")
_m("Rattus norvegicus (Sprague-Dawley rat)",                     RN, "")
_m("Rattus norvegicus (Wistar rat)",                             RN, "")
_m("Rattus norvegicus (Wistar-Hannover rat OPCs)",               RN, "")
_m("Rattus norvegicus (brain slices, cerebellum)",               RN, "")
_m("Rattus norvegicus (cardiomyocyte)",                          RN, "")
_m("Rattus norvegicus (dorsal root ganglia primary cells)",      RN, "")
_m("Rattus norvegicus (embryonic hippocampal neurons)",          RN, "")
_m("Rattus norvegicus (embryonic rat hippocampal neurons)",      RN, "")
_m("Rattus norvegicus (hippocampal neuron)",                     RN, "")
_m("Rattus norvegicus (hippocampal neurons)",                    RN, "")
_m("Rattus norvegicus (hippocampal neurons, DIV 18-21)",         RN, "")
_m("Rattus norvegicus (neonatal Wistar rat)",                    RN, "")
_m("Rattus norvegicus (primary hippocampal neurons)",            RN, "")
_m("Rattus norvegicus (primary hippocampal neurons, host cells)",RN, "")
_m("Rattus norvegicus (primary osteoblasts)",                    RN, "")
_m("Rattus norvegicus (rat liver tissue)",                       RN, "")
_m("Rattus norvegicus (rat)",                                    RN, "")
_m("Rattus norvegicus",                                          RN, "")

# ── Mouse (Mus musculus) — cell lines ────────────────────────────────────────
MM = "Mus musculus"
_m("NIH 3T3 mouse fibroblast",                                   MM, "NIH 3T3")
_m("NIH-3T3 (Mus musculus)",                                     MM, "NIH 3T3")
_m("RAW264.7 (Mus musculus macrophage)",                         MM, "RAW264.7")
_m("Mus musculus (NIH/3T3)",                                     MM, "NIH 3T3")
_m("Mus musculus (Neuro-2A)",                                    MM, "Neuro-2A")
_m("Mus musculus Neuro-2a",                                      MM, "Neuro-2A")
_m("Mus musculus (MIN6 cell line)",                              MM, "MIN6")
_m("Mus musculus MPEK-BL6 (mouse primary epidermal keratinocytes)",MM,"MPEK-BL6")
_m("Mus musculus MPEK-BL6 keratinocytes",                        MM, "MPEK-BL6")
_m("Mus musculus (C2C12 myoblasts)",                             MM, "C2C12")
_m("Mus musculus (mCCD cells, mouse cortical collecting duct)",  MM, "mCCD")
_m("Mus musculus embryonic fibroblast (MEF)",                    MM, "MEF")
_m("Mus musculus embryonic fibroblast (MEF) — primary cilia",    MM, "MEF")
_m("Mus musculus (MEFs on micropatterned lines)",                 MM, "MEF")
_m("Mus musculus (immortalized mouse embryonic fibroblasts, MEF)",MM,"MEF")
_m("Mus musculus (immortalized mouse embryonic fibroblasts, MEF, RPTP α+/+ background)",MM,"MEF")
_m("Mus musculus (primary mouse embryonic fibroblasts)",         MM, "MEF")
_m("Mus musculus (mouse embryonic fibroblasts, MEFs)",           MM, "MEF")

# ── Mouse — tissue / in vivo (cell_line = "") ─────────────────────────────────
for _sp in [
    "Mus musculus",
    "Mus musculus (5xFAD Alzheimer's disease model)",
    "Mus musculus (C57BL/6 mouse brain)",
    "Mus musculus (C57BL/6 mouse)",
    "Mus musculus (C57BL/6 primary hippocampal neurons)",
    "Mus musculus (C57BL/6)",
    "Mus musculus (C57BL/6, adult brain tissue)",
    "Mus musculus (C57BL/6J mouse brain)",
    "Mus musculus (C57BL/6J)",
    "Mus musculus (C57BL/6J, brain sections — striatum)",
    "Mus musculus (C57BL/6J, mouse embryo)",
    "Mus musculus (C57BL6/N)",
    "Mus musculus (C57Bl/6 mouse tail skin)",
    "Mus musculus (C57Bl/6 newborn mouse tail skin)",
    "Mus musculus (C57Bl/6J)",
    "Mus musculus (C57Bl/6j)",
    "Mus musculus (E6.5-7.0 embryo)",
    "Mus musculus (GFAP-EGFP)",
    "Mus musculus (R26R-Mito-EGFP / mito-GFP transgenic)",
    "Mus musculus (Thy1-EGFP transgenic)",
    "Mus musculus (Thy1-EGFP, perfusion-fixed adult brain section)",
    "Mus musculus (Thy1-GFP C57BL/6)",
    "Mus musculus (Thy1-YFP brain, HCR-ExFISH)",
    "Mus musculus (Thy1-YFP brain, post-expansion staining)",
    "Mus musculus (Thy1-YFP mouse)",
    "Mus musculus (Thy1-YFP transgenic)",
    "Mus musculus (Thy1-YFP)",
    "Mus musculus (Thy1-YFP-H brain)",
    "Mus musculus (Thy1-YFP-H mouse)",
    "Mus musculus (Thy1-YFP-H transgenic)",
    "Mus musculus (athymic nude, U87MG xenograft)",
    "Mus musculus (bone marrow-derived macrophages)",
    "Mus musculus (brain sections, ExPath protocol for synapsin-1)",
    "Mus musculus (brain sections, striatum)",
    "Mus musculus (brain tissue — cortex and hippocampus)",
    "Mus musculus (brain tissue)",
    "Mus musculus (brain tissue, Thy1-YFP)",
    "Mus musculus (brain tissue, striatum)",
    "Mus musculus (brain, hippocampus, visual cortex)",
    "Mus musculus (cerebellar granule neurons)",
    "Mus musculus (cerebellar slice)",
    "Mus musculus (cerebellum)",
    "Mus musculus (ependymal cells)",
    "Mus musculus (erythrocytes)",
    "Mus musculus (fosTRAP2-tdTomato)",
    "Mus musculus (hippocampal neurons)",
    "Mus musculus (hippocampal neurons, cultured)",
    "Mus musculus (hippocampal slice)",
    "Mus musculus (hippocampal slice, 15 µm, fresh-frozen)",
    "Mus musculus (hippocampal slice, 50 µm, Thy1-YFP, transcardial perfusion)",
    "Mus musculus (hippocampus, Thy1-YFP, 50 µm, targeted ExSeq)",
    "Mus musculus (human WT aSyn transgenic mouse brain)",
    "Mus musculus (intestinal epithelium, in vivo tissue)",
    "Mus musculus (kidney tissue)",
    "Mus musculus (mouse brain cortex)",
    "Mus musculus (mouse brain slice)",
    "Mus musculus (mouse brain slices, C57BL/6J)",
    "Mus musculus (mouse brain tissue)",
    "Mus musculus (mouse brain tissue, Thy1-YFP)",
    "Mus musculus (mouse brain)",
    "Mus musculus (mouse hippocampal neurons)",
    "Mus musculus (mouse platelets)",
    "Mus musculus (mouse sperm)",
    "Mus musculus (mouse tracheal epithelial cells, MTEC)",
    "Mus musculus (organotypic hippocampal slice culture)",
    "Mus musculus (paraldehyde-preserved brain, lipid retention)",
    "Mus musculus (photoreceptor cells, retina)",
    "Mus musculus (primary hepatocytes)",
    "Mus musculus (primary hippocampal and cortical neurons)",
    "Mus musculus (primary hippocampal neurons)",
    "Mus musculus (primary hippocampal neurons, CD1 embryos)",
    "Mus musculus (primary hippocampal neurons, Swiss Webster)",
    "Mus musculus (primary pancreatic islets)",
    "Mus musculus (retina cryosection, non-expansion)",
    "Mus musculus (retina photoreceptors)",
    "Mus musculus (retina)",
    "Mus musculus (spinal cord injury model - ICR)",
    "Mus musculus (spinal cord injury, Tissue-MAP / original MAP)",
    "Mus musculus (tracheal epithelial cells)",
    "Mus musculus (tracheal tissue)",
    "Mus musculus (vGLUT1venus knock-in mouse forebrain synaptosomes)",
    "Mus musculus (visual cortex, Thy1-YFP, 50 µm, targeted ExSeq)",
    "Mus musculus Neuro-2a",
    "Mus musculus brain tissue (Thy1-YFP)",
    "Mus musculus embryonic stem cells",
    "Mus musculus embryonic stem cells (mESC)",
]:
    M.setdefault(_sp, (MM, "", ""))

# ── Other model organisms / cell lines ───────────────────────────────────────
_m("Norden Laboratory Feline Kidney (NLFK) cells",              "Felis catus",          "NLFK")
_m("Potorous tridactylus (PtK2)",                               "Potorous tridactylus", "PtK2")
_m("Drosophila melanogaster S2 cells",                          "Drosophila melanogaster","S2")
_m("Cricetulus griseus (CHO)",                                  "Cricetulus griseus",   "CHO")
_m("Bos taurus (bovine)",                                       "Bos taurus",           "")
_m("Callithrix jacchus",                                        "Callithrix jacchus",   "")
_m("Callithrix jacchus (common marmoset)",                      "Callithrix jacchus",   "")
_m("Canis lupus familiaris",                                    "Canis lupus familiaris","")
_m("Canis lupus familiaris (dog)",                              "Canis lupus familiaris","")

# ── Drosophila melanogaster tissue entries ────────────────────────────────────
for _sp, _cl in [
    ("Drosophila melanogaster",                    ""),
    ("Drosophila melanogaster (embryos)",           ""),
    ("Drosophila melanogaster (ovaries)",           ""),
    ("Drosophila melanogaster (testes/spermatids)", ""),
]:
    M[_sp] = ("Drosophila melanogaster", _cl, "")


def extract_species_detail(orig: str) -> str:
    """Pull out parenthetical content from species string."""
    m = re.search(r'\((.+)\)$', orig.strip())
    return m.group(1) if m else ""


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

    # Insert new columns right after 'species'
    sp_idx = fieldnames.index("species")
    for col in ("needs_review", "species_detail", "cell_line"):
        if col not in fieldnames:
            fieldnames.insert(sp_idx + 1, col)

    changed = 0

    for row in rows:
        orig = row.get("species", "").strip()

        if orig in M:
            new_sp, cl, review = M[orig]
            row["cell_line"]     = cl
            row["species_detail"]= extract_species_detail(orig)
            row["needs_review"]  = review
            if new_sp != orig:
                row["species"] = new_sp
                changed += 1
        else:
            # Not in map — keep species + cell_line unchanged, no flag
            row.setdefault("cell_line", "")
            row.setdefault("species_detail", extract_species_detail(orig))
            row.setdefault("needs_review", "")

    mode = "DRY RUN" if not args.apply else "APPLY"
    print(f"[{mode}]  {changed} species values rewritten")

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
