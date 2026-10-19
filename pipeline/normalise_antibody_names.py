#!/usr/bin/env python3
"""
normalise_antibody_names.py
────────────────────────────
Comprehensive normalisation of primary antibody naming in ExM_database_curated.csv.

Tasks (in order):
  1. Fix E7 (DSHB) target: alpha-tubulin → beta-tubulin for mis-labelled rows
  2. ABCD (AA344/AA345) full normalisation:
       - Determine canonical identity from label_name + catalogue_number
       - Override label_target (AA345→alpha-tubulin, AA344→beta-tubulin, combined→alpha/beta-tubulin)
       - Normalise label_name → "AA345" / "AA344"
       - Normalise label_supplier (Geneva variants → "ABCD Antibodies")
       - Clean label_catalogue_number
  3. Clone-name label_name normalisation (DM1A, 6-11B-1, TAT-1, GT335, mAb414, 20H5, IN105, B-5-1-2)
  4. Additional label_target clean-ups (localization parentheticals, case, synonyms)
  5. Split alpha/beta-tubulin rows → two rows each
  6. Add label_category column

Usage:
    python normalise_antibody_names.py           # dry-run: summary + sample changes
    python normalise_antibody_names.py --apply   # write changes (auto-backup first)
"""

import re, argparse, shutil
from pathlib import Path
from contextlib import suppress
import pandas as pd
import numpy as np

DB = Path(__file__).parent / "ExM_database_curated.csv"

# ──────────────────────────────────────────────────────────────────────────────
# 1. ABCD IDENTITY  (AA345 = scFv-F2C = anti-ALPHA; AA344 = scFv-S11B = anti-BETA)
# ──────────────────────────────────────────────────────────────────────────────

_345_PAT = re.compile(r"AA[-\s]?345|SCF[VF][-\s]?F2C|\bF2C\b", re.I)
_344_PAT = re.compile(r"AA[-\s]?344|SCF[VF][-\s]?S11B|\bS11B\b", re.I)

def abcd_identity(label_name, cat_number):
    """Returns 'AA345' (alpha), 'AA344' (beta), 'combined', or None."""
    text = " ".join([
        str(label_name) if pd.notna(label_name) else "",
        str(cat_number) if pd.notna(cat_number) else "",
    ])
    has_345 = bool(_345_PAT.search(text))
    has_344 = bool(_344_PAT.search(text))
    if has_345 and has_344:
        return "combined"
    if has_345:
        return "AA345"
    if has_344:
        return "AA344"
    return None

def is_abcd_row(row):
    name = str(row["label_name"])    if pd.notna(row["label_name"])    else ""
    sup  = str(row["label_supplier"]) if pd.notna(row["label_supplier"]) else ""
    cat  = str(row["label_catalogue_number"]) if pd.notna(row["label_catalogue_number"]) else ""
    return bool(
        re.search(r"AA[-\s]?34[45]|scFv[-\s]?F2C|scFv[-\s]?S11B|\bF2C\b|\bS11B\b", name, re.I) or
        re.search(r"Geneva|ABCD Antibod", sup, re.I) or
        re.search(r"AA[-\s]?34[45]|scFv|F2C\b|S11B\b", cat, re.I)
    )

GENEVA_SUPPLIERS = re.compile(r"(Expasy\s+)?Geneva\s+Antibody\s+Facilit", re.I)

def clean_cat(cat, identity):
    """Normalize catalogue number for ABCD rows."""
    if not isinstance(cat, str) or cat.lower() in ("nan", "", "not stated"):
        return identity  # set to canonical if blank
    c = cat.strip()
    # Strip "ABCD_" prefix
    c = re.sub(r"^ABCD_", "", c, flags=re.I)
    # Strip " - scFv-F2C" / " - scFv-S11B" suffixes
    c = re.sub(r"\s*[-–]\s*scFv[-\s]?[FS]\w+", "", c, flags=re.I)
    # If only scFv codes remain (no AA34x), replace with canonical
    if re.fullmatch(r"scFv[-\s]?F2C", c, re.I):
        return "AA345"
    if re.fullmatch(r"scFv[-\s]?S11B", c, re.I):
        return "AA344"
    # Normalise combined catalogue forms
    if re.search(r"AA[-\s]?34[45]", c) and re.search(r"AA[-\s]?34[45]", c):
        if identity == "combined":
            return "AA345 / AA344"
    # Uppercase AA34x
    c = re.sub(r"aa[-\s]?(34[45])", lambda m: "AA" + m.group(1), c, flags=re.I)
    return c.strip()


# ──────────────────────────────────────────────────────────────────────────────
# 2. CLONE NAME NORMALISATION  (label_name → canonical clone code)
# ──────────────────────────────────────────────────────────────────────────────

CLONE_PATTERNS = [
    (re.compile(r"\bDM1[Aααa]\b",  re.I), "DM1A"),
    (re.compile(r"\b6[-\s]?11B[-\s]?1\b", re.I), "6-11B-1"),
    (re.compile(r"\bTAT[-\s]?1\b",       re.I), "TAT-1"),
    (re.compile(r"\bGT335\b",            re.I), "GT335"),
    (re.compile(r"\b[Mm]a?b[-\s]?414\b", re.I), "mAb414"),
    (re.compile(r"\b20H5\b",             re.I), "20H5"),
    (re.compile(r"\bIN105\b",            re.I), "IN105"),
    (re.compile(r"\bB[-\s]?5[-\s]?1[-\s]?2\b", re.I), "B-5-1-2"),
    (re.compile(r"\bYL1/2\b",            re.I), "YL1/2"),
]

def normalize_clone_name(label_name):
    s = str(label_name) if pd.notna(label_name) else ""
    for pat, canonical in CLONE_PATTERNS:
        if pat.search(s):
            return canonical
    return label_name


# ──────────────────────────────────────────────────────────────────────────────
# 3. ADDITIONAL label_target NORMALISATION
# ──────────────────────────────────────────────────────────────────────────────

EXTRA_TARGET_MAP = {
    # Tubulin localization / context parentheticals
    "tubulin (alpha)":                               "alpha-tubulin",
    "tubulin (beta)":                                "beta-tubulin",
    "tubulin (alpha and beta)":                      "alpha/beta-tubulin",
    "tubulin (aa344)":                               "beta-tubulin",
    "tubulin (aa345)":                               "alpha-tubulin",
    "tubulin (microtubules)":                        "alpha-tubulin",
    "tubulin / microtubules":                        "alpha-tubulin",
    "tubulin (alpha/beta-tubulin)":                  "alpha/beta-tubulin",
    "alpha-tubulin (microtubules)":                  "alpha-tubulin",
    "alpha-tubulin (basal body and pro-basal body)": "alpha-tubulin",
    "alpha-tubulin (post-expansion)":                "alpha-tubulin",
    "alpha-tubulin (distortion analysis)":           "alpha-tubulin",
    "alpha-tubulin (ifa unexpanded)":                "alpha-tubulin",
    "alpha-tubulin acetylated":                      "acetylated alpha-tubulin",
    "acetylated-tubulin":                            "acetylated alpha-tubulin",
    "alpha-tubulin (tyrosinated)":                   "tyrosinated alpha-tubulin",
    # Polyglutamylation variants
    "glutamylation":                                 "polyglutamylated tubulin",
    "glutamylated tubulin (gt335)":                  "polyglutamylated tubulin",
    "polyglutamylated tubulin (gt335)":              "polyglutamylated tubulin",
    "polyglutamylated-tubulin (pglu-tubulin)":       "polyglutamylated tubulin",
    "polyglutamylated tubulin (centrioles)":         "polyglutamylated tubulin",
    "polyglutamylated tubulin (unexpanded centrioles)": "polyglutamylated tubulin",
    "polyglutamylation (polye)":                     "polyglutamylated tubulin",
    "polyglutamylation (spmts)":                     "polyglutamylated tubulin",
    "polyglutamylation (monoE/gt335)":               "polyglutamylated tubulin",
    "polyglutamate chain tubulin":                   "polyglutamylated tubulin",
    "polyglutamate chain tubulin":                   "polyglutamylated tubulin",
    "gt335 (glutamylated tubulin)":                  "polyglutamylated tubulin",
    "alpha-tubulin / beta-tubulin (polyglutamate chain, polye)": "polyglutamylated tubulin",
    # Centrin variants
    "centrin":                           "centrin",   # canonical (case-insensitive lookup)
    "centrin-2":                         "centrin",
    "centrin-1":                         "centrin",
    "centrin1":                          "centrin",
    "centrin 1":                         "centrin",
    "centrin 2":                         "centrin",
    "centrin (cdc31p)":                  "centrin",
    "centrin (outer centriolar plaque)": "centrin",
    "centrin 1 (distal lumen of centrioles)": "centrin",
    "hscentrin2":                        "centrin",
    # TOM20 variants
    "tom20 (outer mitochondrial membrane)":  "TOM20",
    "tomm20 (outer mitochondrial membrane)": "TOM20",
    "tomm20 (mitochondria)":                 "TOM20",
    "tom20 (mitochondria)":                  "TOM20",
    # NPC variants
    "nuclear pore complex (fg-nucleoporins)":       "nuclear pore complex",
    "nuclear pore complex (npc)":                   "nuclear pore complex",
    "nup153 (nuclear pore complex)":                "NUP153",
    "nup98 (nuclear pores)":                        "NUP98",
    # Case / abbreviation fixes
    "arl13b":                            "ARL13B",
    "cep164":                            "CEP164",
    "bassoon (presynaptic marker)":      "bassoon",
    "gfap (glial fibrillary acidic protein)": "GFAP",
    "gfap (astrocyte marker)":           "GFAP",
    "parvalbumin (pv)":                  "parvalbumin",
    "rootletin (crocc)":                 "rootletin",
    "alpha-synuclein (asyn)":            "alpha-synuclein",
    "ha epitope tag":                    "HA",
    "c-myc tag":                         "Myc",
    "flag-tag (on spamo)":               "FLAG",
    "vimentin":                          "vimentin",
    "rhodopsin":                         "rhodopsin",
    "gephyrin":                          "gephyrin",
    "shank3":                            "SHANK3",
    "gfp / megfp":                       "GFP",
    "gfp (mtck-gfp)":                   "GFP",
    "nup96-megfp (gfp)":                "GFP",
    "megfp (nup96-megfp)":              "GFP",
    "tyrosine hydroxylase (th)":         "tyrosine hydroxylase",
    "ryr2 (ryanodine receptor 2)":       "RyR2",
    "synaptic vesicle protein 2 (sv2)":  "SV2",
    "fibrillarin (nucleolar fibrillar regions)": "fibrillarin",
    "sf3a66 (nuclear speckles)":         "SF3A66",
    "peroxiredoxin 3 (prx3)":            "Peroxiredoxin 3",
    "tfam (direct conjugate)":           "TFAM",
    "tubulin (alpha/beta-tubulin)":      "alpha/beta-tubulin",
    "tubulin (aa344)":                   "beta-tubulin",
    "tubulin (aa345)":                   "alpha-tubulin",
}

def extra_target_norm(s):
    if not isinstance(s, str) or not s.strip():
        return s
    key = s.strip().lower()
    # Check exact match first, then lower-cased
    if s.strip() in EXTRA_TARGET_MAP:
        return EXTRA_TARGET_MAP[s.strip()]
    if key in EXTRA_TARGET_MAP:
        return EXTRA_TARGET_MAP[key]
    return s


# ──────────────────────────────────────────────────────────────────────────────
# 4. LABEL_CATEGORY
# ──────────────────────────────────────────────────────────────────────────────

EXACT_CATEGORY = {
    # Fluorescent protein tags
    "GFP": "fluorescent_protein_tag",
    "mCherry": "fluorescent_protein_tag",
    "RFP": "fluorescent_protein_tag",
    "YFP": "fluorescent_protein_tag",
    "CFP": "fluorescent_protein_tag",
    "BFP": "fluorescent_protein_tag",
    "tdTomato": "fluorescent_protein_tag",
    "GFP/YFP": "fluorescent_protein_tag",
    # Epitope tags
    "HA": "epitope_tag",
    "Myc": "epitope_tag",
    "His-tag": "epitope_tag",
    "FLAG": "epitope_tag",
    "V5": "epitope_tag",
    "MBP": "epitope_tag",
    # Nuclear envelope
    "nuclear pore complex": "nuclear_envelope",
    "lamin A/C": "nuclear_envelope",
    "lamin B1": "nuclear_envelope",
    # Synaptic
    "PSD-95": "synaptic",
    "Homer1": "synaptic",
    "bassoon": "synaptic",
    "synaptophysin": "synaptic",
    "synaptotagmin-1": "synaptic",
    "vGLUT1": "synaptic",
    "vGAT": "synaptic",
    "SHANK2": "synaptic",
    "SHANK3": "synaptic",
    "gephyrin": "synaptic",
    # Mitochondria
    "TOM20": "mitochondria",
    # Photosynthesis
    "PsbA": "photosynthesis",
    "RuBisCO large subunit": "photosynthesis",
    # Neuron markers
    "NeuN": "neuron_marker",
    "GFAP": "neuron_marker",
    "MAP2": "neuron_marker",
    "tyrosine hydroxylase": "neuron_marker",
    "NF-L": "neuron_marker",
    # Cytoskeleton
    "centrin": "cytoskeleton",
    "actin": "cytoskeleton",
    "alpha-tubulin": "cytoskeleton",
    "beta-tubulin": "cytoskeleton",
    "gamma-tubulin": "cytoskeleton",
    "acetylated alpha-tubulin": "cytoskeleton",
    "tyrosinated alpha-tubulin": "cytoskeleton",
    "detyrosinated alpha-tubulin": "cytoskeleton",
    "polyglutamylated tubulin": "cytoskeleton",
    "alpha/beta-tubulin": "cytoskeleton",
    "betaII-spectrin": "cytoskeleton",
    "vimentin": "cytoskeleton",
    "delta2 alpha-tubulin": "cytoskeleton",
}

CATEGORY_RULES = [
    ("cytoskeleton", [
        "tubulin", "actin", "centrin", "spectrin", "cofilin", "filamin",
        "myosin", "septin", "anillin", "kinesin", "dynein", "arp2", "arp3",
        "cortactin", "fascin", "tropomyosin", "rootletin", "vimentin",
        "desmin", "keratin", "neurofilament",
    ]),
    ("fluorescent_protein_tag", [
        "gfp", "mcherry", "rfp", "yfp", "cfp", "bfp", "egfp", "meos",
        "mturquoise", "tdtomato", "dendra", "mkate", "mneongreen", "mtagrfp",
        "mruby", "mscarlet", "mvenus", "moxberry", "mneptune",
    ]),
    ("epitope_tag", [
        "flag", "snap-tag", "clip-tag", "suntag", "halo", "alfa tag",
        "strep-tag",
    ]),
    ("nuclear_envelope", [
        "lamin", "nuclear pore", "nucleoporin", "nup", "sun1", "sun2", "emerin",
        "man1",
    ]),
    ("chromatin", [
        "histone", "h3k", "ki-67", "ki67", "pcna", "cenpa", "cenpb", "hp1",
        "h2a", "h2b", "chromatin", "dna", "cenp-", "smc",
    ]),
    ("synaptic", [
        "psd-95", "psd95", "homer", "bassoon", "synaptophysin", "synaptotagmin",
        "vglut", "vgat", "shank", "gephyrin", "piccolo", "liprin",
        "munc18", "rab3a", "synapsin", "neurexin", "neuroligin",
    ]),
    ("mitochondria", [
        "tom20", "vdac", "cox-iv", "cox iv", "tim23", "tomm", "mthsp70",
        "mtco", "atp5", "tfam", "opa1",
    ]),
    ("photosynthesis", [
        "psba", "rubisco", "rbcl", "chloroplast", "photosystem", "psii", "psi",
        "lhcb", "cab",
    ]),
    ("neuron_marker", [
        "neun", "map2", "gfap", "nefl", "tyrosine hydroxylase", "neurofascin",
        "choline acetyltransferase", "parvalbumin", "alpha-synuclein",
        "somatostatin", "neuropeptide",
    ]),
    ("cilia_centrosome", [
        "arl13b", "cep1", "cep2", "cep3", "cep4", "cep5", "cep6", "cep7",
        "cep8", "cep9", "ift", "sas-6", "poc5", "poc1", "odf2", "ofd1",
        "ninein", "sdccag8", "pericentrin", "pericentriolar", "pcm1",
        "rootletin", "dnai", "dnah", "rpgr", "cdc20b", "haus",
    ]),
]

def categorize(target):
    if not isinstance(target, str):
        return "other"
    if target in EXACT_CATEGORY:
        return EXACT_CATEGORY[target]
    t = target.lower()
    for cat, keywords in CATEGORY_RULES:
        if any(k in t for k in keywords):
            return cat
    # Short exact matches that could collide with other patterns
    if t in ("ha", "myc", "v5", "gst", "mbp", "flag"):
        return "epitope_tag"
    if t in ("gfp", "rfp", "yfp", "cfp", "bfp", "egfp"):
        return "fluorescent_protein_tag"
    return "other"


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Write changes to CSV (auto-backup first)")
    args = parser.parse_args()

    df = pd.read_csv(DB, encoding="utf-8-sig", low_memory=False)
    df = df.map(lambda x: x.replace("\x00", "") if isinstance(x, str) else x)

    prim_mask = df["label_type"].isin(["primary_antibody", "nanobody"])
    original  = df.copy()

    changes_log = []

    # ── Step 1: Fix E7 (DSHB) alpha→beta ─────────────────────────────────────
    e7_wrong = (
        prim_mask &
        df["label_name"].str.fullmatch(r"E7", na=False) &
        (df["label_target"] == "alpha-tubulin")
    )
    n_e7 = e7_wrong.sum()
    df.loc[e7_wrong, "label_target"] = "beta-tubulin"
    changes_log.append(f"Step 1 — E7 target fix: {n_e7} rows alpha-tubulin → beta-tubulin")

    # ── Step 2: ABCD normalisation ────────────────────────────────────────────
    abcd_mask = df.apply(lambda r: prim_mask[r.name] and is_abcd_row(r), axis=1)
    n_abcd = abcd_mask.sum()

    target_fixes = name_fixes = supplier_fixes = cat_fixes = 0

    for idx in df.index[abcd_mask]:
        row = df.loc[idx]
        identity = abcd_identity(row["label_name"], row["label_catalogue_number"])
        if identity is None:
            continue  # can't determine; skip target/name changes

        # Canonical target
        new_target = {
            "AA345":    "alpha-tubulin",
            "AA344":    "beta-tubulin",
            "combined": "alpha/beta-tubulin",
        }[identity]

        if str(row["label_target"]) != new_target:
            df.at[idx, "label_target"] = new_target
            target_fixes += 1

        # Canonical label_name
        new_name = {
            "AA345":    "AA345",
            "AA344":    "AA344",
            "combined": "AA345 / AA344",
        }[identity]
        if str(row["label_name"]).strip() != new_name:
            df.at[idx, "label_name"] = new_name
            name_fixes += 1

        # Supplier: Geneva → ABCD Antibodies
        sup = str(row["label_supplier"]) if pd.notna(row["label_supplier"]) else ""
        if GENEVA_SUPPLIERS.search(sup):
            df.at[idx, "label_supplier"] = "ABCD Antibodies"
            supplier_fixes += 1

        # Catalogue number
        old_cat = row["label_catalogue_number"]
        new_cat = clean_cat(old_cat, new_name)
        if str(old_cat) != str(new_cat):
            df.at[idx, "label_catalogue_number"] = new_cat
            cat_fixes += 1

    changes_log.append(
        f"Step 2 — ABCD normalisation: {n_abcd} rows detected, "
        f"{target_fixes} target fixes, {name_fixes} name fixes, "
        f"{supplier_fixes} supplier fixes, {cat_fixes} cat# fixes"
    )

    # ── Step 3: Clone name normalisation ─────────────────────────────────────
    prim_rows = df.index[prim_mask]
    # Exclude ABCD rows already normalised
    abcd_idx_set = set(df.index[abcd_mask])
    clone_fixes = 0
    for idx in prim_rows:
        if idx in abcd_idx_set:
            continue
        old_name = df.at[idx, "label_name"]
        new_name = normalize_clone_name(old_name)
        if new_name != old_name:
            df.at[idx, "label_name"] = new_name
            clone_fixes += 1
    changes_log.append(f"Step 3 — Clone name normalisation: {clone_fixes} label_name fixes")

    # ── Step 4: Extra label_target normalisation ──────────────────────────────
    target_extra = 0
    for idx in prim_rows:
        old_tgt = df.at[idx, "label_target"]
        new_tgt = extra_target_norm(old_tgt)
        if new_tgt != old_tgt:
            df.at[idx, "label_target"] = new_tgt
            target_extra += 1
    changes_log.append(f"Step 4 — Extra label_target normalisation: {target_extra} fixes")

    # ── Step 5: Split alpha/beta-tubulin rows ─────────────────────────────────
    split_mask = (
        prim_mask &
        (df["label_target"] == "alpha/beta-tubulin")
    )
    split_idx = list(df.index[split_mask])
    n_to_split = len(split_idx)
    changes_log.append(f"Step 5 — Split alpha/beta-tubulin: {n_to_split} rows → {n_to_split * 2} rows")

    if n_to_split > 0:
        keep_rows = df[~split_mask].copy()

        new_rows = []
        for idx in split_idx:
            row = df.loc[idx]
            # Determine if this is an ABCD combined row
            is_abcd_combined = idx in abcd_idx_set
            # Also detect rows we just normalised as combined
            if not is_abcd_combined:
                ident = abcd_identity(row["label_name"], row["label_catalogue_number"])
                is_abcd_combined = (ident == "combined")

            row_alpha = row.copy()
            row_beta  = row.copy()

            if is_abcd_combined:
                row_alpha["label_name"]            = "AA345"
                row_alpha["label_target"]          = "alpha-tubulin"
                row_alpha["label_catalogue_number"] = "AA345"
                row_beta["label_name"]             = "AA344"
                row_beta["label_target"]           = "beta-tubulin"
                row_beta["label_catalogue_number"] = "AA344"
            else:
                row_alpha["label_target"] = "alpha-tubulin"
                row_beta["label_target"]  = "beta-tubulin"

            new_rows.append(row_alpha)
            new_rows.append(row_beta)

        split_df = pd.DataFrame(new_rows)
        df = pd.concat([keep_rows, split_df], ignore_index=True)

        # Re-derive prim_mask after concat
        prim_mask = df["label_type"].isin(["primary_antibody", "nanobody"])

    # ── Step 6: Add label_category ────────────────────────────────────────────
    df["label_category"] = df["label_target"].apply(categorize)
    cat_counts = df.loc[prim_mask, "label_category"].value_counts()
    changes_log.append(
        f"Step 6 — label_category added. Distribution (primaries):\n" +
        "\n".join(f"           {cat}: {cnt}" for cat, cnt in cat_counts.items())
    )

    # ── Print summary ─────────────────────────────────────────────────────────
    print(f"\nTotal rows: {len(original)} → {len(df)} (delta = {len(df) - len(original)})")
    for line in changes_log:
        print(f"  {line}")

    if not args.apply:
        print("\nDry run — no changes saved. Run with --apply to write.")
        return

    # ── Save ──────────────────────────────────────────────────────────────────
    backup = DB.with_suffix(".pre_ab_norm.bak.csv")
    shutil.copy(DB, backup)
    print(f"\nBackup saved: {backup.name}")

    import os
    with open(DB, "w", encoding="utf-8-sig", newline="") as f:
        df.to_csv(f, index=False)
        with suppress(OSError):
            os.fsync(f.fileno())

    print(f"Saved {DB.name} ({len(df)} rows)")


if __name__ == "__main__":
    main()
