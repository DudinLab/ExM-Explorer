#!/usr/bin/env python3
"""
normalise_by_reference.py
─────────────────────────
Same supplier + same catalogue number = same antibody.
Enforce a single canonical label_name and label_target within each group.

Steps:
  0. Supplier name canonicalization (Sigma→Sigma-Aldrich, etc.)
  1. Fix Soldati-Favre lab (Geneva) → ABCD Antibodies for AA344/AA345
  2. Group by (canonical supplier, cat#); pick modal label_name and label_target
  3. Apply to all rows in each group

Usage:
    python normalise_by_reference.py           # dry-run
    python normalise_by_reference.py --apply   # write (auto-backup)
"""

import re, argparse, shutil, os
from contextlib import suppress
from collections import Counter
from pathlib import Path
import pandas as pd

DB = Path("/sessions/trusting-happy-fermat/mnt/ExM_Library/ExM_database_curated.csv")

# ── 0. Supplier canonicalization ─────────────────────────────────────────────

SUPPLIER_CANON = {
    "Sigma":                               "Sigma-Aldrich",
    "Millipore Sigma":                     "Sigma-Aldrich",
    "Santa Cruz":                          "Santa Cruz Biotechnology",
    "Santa Cruz Biotech":                  "Santa Cruz Biotechnology",
    "Thermo Fisher Scientific":            "Thermo Fisher",
    "Invitrogen":                          "Thermo Fisher",
    "Life Technologies":                   "Thermo Fisher",
    "NanoTag Biotechnologies GmbH":        "NanoTag Biotechnologies",
    "Nanotag Biotechnologies":             "NanoTag Biotechnologies",
    "Adipogen":                            "AdipoGen",
    "AdipoGen Life Sciences":             "AdipoGen",
    "Chromotek":                           "ChromoTek",
    "Origene":                             "OriGene",
    "Novus":                               "Novus Biologicals",
    "Atlas antibodies":                    "Atlas Antibodies",
    "BD Pharmingen":                       "BD Biosciences",
    "Bethyl":                              "Bethyl Laboratories",
    "Enzo":                                "Enzo Life Sciences",
    "Aves":                                "Aves Labs",
    "Antibodies Inc":                      "Antibodies Inc.",
    "Antibodies Incorporated":             "Antibodies Inc.",
    "Developmental Studies Hybridoma Bank":"DSHB",
    "Torrey Pine":                         "Torrey Pines",
    "Torrey Pines Biolabs":               "Torrey Pines",
    "gift: L. Weiss":                      "gift: Louis Weiss",
    "gift: Cai Laboratory":               "gift: Cai lab",
    "gift: Cai Lab":                       "gift: Cai lab",
    "gift: G. Rogers":                     "gift: Rogers laboratory",
    "gift: Dominique Soldati Favre":       "gift: Dominique Soldati-Favre",
}

def canon_supplier(s):
    if not isinstance(s, str) or s.lower() in ("nan","not stated",""):
        return s
    return SUPPLIER_CANON.get(s.strip(), s.strip())

# ── Target pre-normalization ──────────────────────────────────────────────────

TARGET_PREPROCESS = {
    "alpha-tubulin (total)":                 "alpha-tubulin",
    "alpha-tubulin (n-terminus)":            "alpha-tubulin",
    "alpha-tubulin (distortion analysis)":   "alpha-tubulin",
    "alpha-tubulin (ifa unexpanded)":        "alpha-tubulin",
    "alpha-tubulin (basal body and pro-basal body)": "alpha-tubulin",
    "beta-tubulin (figs. 4 and 5)":          "beta-tubulin",
    "alpha-tubulin i and alpha-tubulin ii":  "alpha-tubulin",
    "alpha/beta-tubulin":                    "alpha/beta-tubulin",
    "tubulin (alpha)":                       "alpha-tubulin",
    "tubulin (beta)":                        "beta-tubulin",
    "gfp/egfp":                              "GFP",
    "gfp/eyfp":                              "GFP",
    "gfp/yfp":                               "GFP",
    "gfp / fluorescent proteins":            "GFP",
    "gfp / megfp":                           "GFP",
    "ha tag (sun1-ha, allc1-ha)":            "HA",
    "ha tag (sas4, delta-tubulin, epsilon-tubulin, pf16, eb1)": "HA",
    "ha-tag (ccdc146)":                      "HA",
    "opa1::ha / drp1::ha":                   "HA",
    "ha tag (non-exm control)":              "HA",
    "ha epitope tag":                        "HA",
    "flag tag (tedc1-halotag-3xflag)":       "FLAG",
    "flag-tag on spamo":                     "FLAG",
    "flag-tag (spamo amplification)":        "FLAG",
    "centrin (clone 20h5)":                  "centrin",
    "centrin1":                              "centrin",
    "centrin 1":                             "centrin",
    "centrin 2":                             "centrin",
    "centrin (cdc31p)":                      "centrin",
    "centrin 1 (distal lumen of centrioles)":"centrin",
    "sass6":                                 "SAS-6",
    "hssas-6":                               "SAS-6",
    "homer1 (postsynaptic marker)":          "Homer1",
    "homer (postsynaptic)":                  "Homer1",
    "synaptophysin 1":                       "synaptophysin",
    "synaptophysin 1 (syp1)":               "synaptophysin",
    "synaptophysin1 (syp1)":                "synaptophysin",
    "bassoon (presynaptic marker)":          "bassoon",
    "cenpj (cpap)":                          "CPAP",
    "clathrin-coated pits":                  "clathrin heavy chain",
    "clathrin heavy chain (clathrin-coated pits)": "clathrin heavy chain",
    "clathrin heavy chain (clta)":           "clathrin heavy chain",
    "psba (photosystem ii d1 subunit / thylakoids)": "PsbA",
    "polyglutamylated tubulin (polye, b-tubule marker)": "polyglutamylated tubulin",
    "polyglutamate chain (polye)":           "polyglutamylated tubulin",
    "polyglutamate chain on alpha- and beta-tubulin": "polyglutamylated tubulin",
    "polyglutamate chain tubulin":           "polyglutamylated tubulin",
    "tom20 (outer mitochondrial membrane)":  "TOM20",
    "tomm20 (outer mitochondrial membrane)": "TOM20",
    "tomm20 (mitochondria)":                 "TOM20",
    "tom20 (mitochondria)":                  "TOM20",
    "nup96/nup98":                           "NUP98-NUP96",
    "nup205 (nuclear pore complex)":         "NUP205",
    "nup153 (nuclear pore complex)":         "NUP153",
    "gfap (glial fibrillary acidic protein)":"GFAP",
    "gfap (astrocyte marker)":               "GFAP",
    "alpha-synuclein (asyn)":                "alpha-synuclein",
    "rootletin (crocc)":                     "rootletin",
    "chlamydial heat shock protein 60 (chsp60)": "chlamydial HSP60",
    "glutamylated tubulin (gt335)":          "polyglutamylated tubulin",
    "polyglutamylated tubulin (gt335)":      "polyglutamylated tubulin",
    "acetylated-tubulin":                    "acetylated alpha-tubulin",
    "acetylated alpha-tubulin, clone 6-11b-1": "acetylated alpha-tubulin",
}

GFP_PAT = re.compile(r"^GFP\s*[\(/]", re.I)
HA_PAT  = re.compile(r"^HA\s*[\(\-/]|^HA\s+tag|^HA\s+epitope", re.I)

def preprocess_target(t):
    if not isinstance(t, str): return t
    key = t.strip().lower()
    if key in TARGET_PREPROCESS:  return TARGET_PREPROCESS[key]
    if t.strip() in TARGET_PREPROCESS: return TARGET_PREPROCESS[t.strip()]
    if GFP_PAT.match(t.strip()): return "GFP"
    if HA_PAT.match(t.strip()):  return "HA"
    return t.strip()

# ── Canonical selection ───────────────────────────────────────────────────────

GENERIC_TARGETS = {"tubulin", "nan", "not stated", ""}

def best_target(targets):
    preprocessed = [preprocess_target(t) for t in targets if isinstance(t, str)]
    valid   = [t for t in preprocessed if t.lower() not in GENERIC_TARGETS]
    if not valid:
        return None
    return Counter(valid).most_common(1)[0][0]

CANONICAL_CLONE_NAMES = {
    "DM1A","6-11B-1","TAT-1","GT335","mAb414","20H5","IN105",
    "B-5-1-2","YL1/2","GTU-88","EP1332Y","E7","3F10","T14",
}

def best_name(names):
    valid = [n for n in names if isinstance(n, str) and n.lower() not in ("nan","not stated","")]
    if not valid: return None
    # Prefer canonical clone codes
    clones = [n for n in valid if n in CANONICAL_CLONE_NAMES]
    if clones: return Counter(clones).most_common(1)[0][0]
    return Counter(valid).most_common(1)[0][0]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    df = pd.read_csv(DB, encoding="utf-8-sig", low_memory=False)
    df = df.map(lambda x: x.replace("\x00", "") if isinstance(x, str) else x)

    prim_mask = df["label_type"].isin(["primary_antibody", "nanobody"])

    # Step 0: Canonicalize supplier names (all rows, not just primaries)
    sup_changes = 0
    for idx in df.index:
        old = df.at[idx, "label_supplier"]
        new = canon_supplier(old)
        if isinstance(old, str) and new != old:
            df.at[idx, "label_supplier"] = new
            sup_changes += 1
    print(f"Step 0 — Supplier canonicalization: {sup_changes} rows")

    # Step 1: Soldati-Favre (Geneva) → ABCD for AA344/AA345
    sf_mask = (
        df["label_supplier"].str.contains(r"Soldati.Favre lab \(Geneva", na=False, regex=True) &
        df["label_name"].isin(["AA344","AA345"])
    )
    df.loc[sf_mask, "label_supplier"] = "ABCD Antibodies"
    print(f"Step 1 — Soldati-Favre → ABCD: {sf_mask.sum()} rows")

    # Step 2: Group by (supplier, cat#) → enforce canonical name + target
    has_ref = (
        prim_mask &
        df["label_supplier"].notna() &
        ~df["label_supplier"].str.lower().isin(["nan","not stated",""]) &
        df["label_catalogue_number"].notna() &
        ~df["label_catalogue_number"].astype(str).str.lower().isin(["nan","not stated",""])
    )

    ref_df = df[has_ref].copy()
    groups = ref_df.groupby(["label_supplier","label_catalogue_number"], sort=False)

    name_fixes = target_fixes = 0
    conflict_groups = 0

    for (sup, cat), grp in groups:
        cn = best_name(grp["label_name"].tolist())
        ct = best_target(grp["label_target"].tolist())

        # Hard override: YL1/2 always → tyrosinated alpha-tubulin
        if cat in ("MA1-80017", "MAB1864"):
            ct = "tyrosinated alpha-tubulin"

        n_names   = grp["label_name"].nunique()
        n_targets = grp["label_target"].apply(preprocess_target).nunique()

        has_conflict = n_names > 1 or n_targets > 1
        if not has_conflict:
            continue
        conflict_groups += 1

        print(f"\n  [{sup}] / [{cat}]  ({len(grp)} rows)")
        if n_names > 1:
            nc = Counter(n for n in grp["label_name"] if isinstance(n, str))
            print(f"    names   ({n_names} variants) → {cn!r}")
            for nm, c in nc.most_common():
                print(f"            {c:3d}×  {nm!r}{'  ◀' if nm==cn else ''}")
        if n_targets > 1:
            tc = Counter(preprocess_target(t) for t in grp["label_target"] if isinstance(t, str))
            print(f"    targets ({n_targets} variants) → {ct!r}")
            for tg, c in tc.most_common():
                print(f"            {c:3d}×  {tg!r}{'  ◀' if tg==ct else ''}")

        for idx in grp.index:
            old_name   = df.at[idx, "label_name"]
            old_target = df.at[idx, "label_target"]
            if cn and str(old_name) != cn:
                df.at[idx, "label_name"] = cn
                name_fixes += 1
            if ct:
                processed = preprocess_target(old_target)
                final_tgt = ct
                if str(old_target) != final_tgt:
                    df.at[idx, "label_target"] = final_tgt
                    target_fixes += 1

    print(f"\nStep 2 — Group normalisation: {conflict_groups} conflict groups")
    print(f"         label_name fixes:   {name_fixes}")
    print(f"         label_target fixes: {target_fixes}")
    print(f"         Total rows: {len(df)}")

    if not args.apply:
        print("\nDry run — no changes written. Run with --apply to save.")
        return

    backup = DB.with_suffix(".pre_ref_norm.bak.csv")
    shutil.copy(DB, backup)
    print(f"\nBackup: {backup.name}")

    with open(DB, "w", encoding="utf-8-sig", newline="") as f:
        df.to_csv(f, index=False)
        with suppress(OSError):
            os.fsync(f.fileno())
    print(f"Saved {DB.name}")

if __name__ == "__main__":
    main()
