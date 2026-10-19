#!/usr/bin/env python3
"""
normalise_dye_names.py
──────────────────────
Normalise label_name for all rows where label_type == "dye".

Groups:
  1. NHS-ester variants  → NHS-ester-[fluorophore]  (or NHS-ester for generic)
  2. Hoechst variants    → Hoechst 33342 / Hoechst 33258
  3. DAPI variants       → DAPI
  4. SYTOX/SYTO          → canonical case
  5. BODIPY              → canonical case
  6. MitoTracker         → canonical case
  7. mCLING              → canonical case
  8. Miscellaneous       → propidium iodide, DRAQ5, TO-PRO-3, R18, etc.

Usage:
    python normalise_dye_names.py           # dry-run (prints changes)
    python normalise_dye_names.py --apply   # write (auto-backup)
"""

import re, argparse, shutil, os
from contextlib import suppress
from collections import Counter
from pathlib import Path
import pandas as pd

DB = Path("/sessions/trusting-happy-fermat/mnt/ExM_Library/ExM_database_curated.csv")

# ─────────────────────────────────────────────────────────────────────────────
# 1. NHS-ester canonical map
#    All known variants → "NHS-ester-[fluorophore]"  canonical form
# ─────────────────────────────────────────────────────────────────────────────

NHS_MAP = {
    # ── Generic (no fluorophore specified) ──
    "NHS-ester":                                          "NHS-ester",
    "NHS ester":                                          "NHS-ester",
    "NHS Ester":                                          "NHS-ester",
    "NHS-ester dye":                                      "NHS-ester",
    "NHS ester dye":                                      "NHS-ester",
    "NHS ester fluorescent dye":                          "NHS-ester",
    "NHS-ester dye":                                      "NHS-ester",
    "NHS ester pan-stain":                                "NHS-ester",
    "Alexa Fluor NHS Ester":                              "NHS-ester",    # no wavelength given

    # ── AF405 ──
    "NHS Ester Alexa Fluor 405":                          "NHS-ester-AF405",
    "NHS ester Alexa Fluor 405":                          "NHS-ester-AF405",
    "NHS-Ester-Alexa Fluor 405":                          "NHS-ester-AF405",
    "NHS-Ester (Alexa Fluor 405)":                        "NHS-ester-AF405",
    "NHS-Ester AF405":                                    "NHS-ester-AF405",
    "NHS-Ester-Alexa Fluor 405":                          "NHS-ester-AF405",
    "AlexaFluor 405 NHS-Ester":                           "NHS-ester-AF405",
    "AlexaFluor 405-NHS-Ester":                           "NHS-ester-AF405",
    "Alexa-Fluor 405 NHS-ester":                          "NHS-ester-AF405",
    "Alexa Fluor 405 NHS-Ester":                          "NHS-ester-AF405",
    "NHS ester-Alexa405":                                 "NHS-ester-AF405",
    "Alexa 405 NHS Ester":                                "NHS-ester-AF405",
    "NHS-ester 405":                                      "NHS-ester-AF405",
    "NHS-ester-405":                                      "NHS-ester-AF405",
    "NHS AZ405":                                          "NHS-ester-AZ405",

    # ── AF488 ──
    "Alexa Fluor 488 NHS ester":                          "NHS-ester-AF488",
    "Alexa Fluor 488 NHS Ester (Succinimidyl Ester)":     "NHS-ester-AF488",
    "Alexa 488 NHS-ester":                                "NHS-ester-AF488",
    "Alexa 488-NHS ester":                                "NHS-ester-AF488",
    "NHS-Alexa488":                                       "NHS-ester-AF488",
    "NHS Alexa488":                                       "NHS-ester-AF488",
    "NHS-ester Alexa 488":                                "NHS-ester-AF488",
    "Alexa Fluor 488-conjugated NHS ester":               "NHS-ester-AF488",
    "NHS AZ488":                                          "NHS-ester-AZ488",

    # ── AF546 ──
    "Alexa Fluor 546 NHS ester":                          "NHS-ester-AF546",
    "NHS-AF546":                                          "NHS-ester-AF546",

    # ── AF555 ──
    "Alexa Fluor 555 NHS ester":                          "NHS-ester-AF555",
    "NHS-ester Alexa Fluor 555":                          "NHS-ester-AF555",

    # ── AF568 ──
    "Alexa 568 NHS ester":                                "NHS-ester-AF568",
    "Alexa Fluor 568 NHS-Ester":                          "NHS-ester-AF568",
    "Alexa Fluor 568 NHS-ester conjugated secondary":     "NHS-ester-AF568",

    # ── AF594 ──
    "NHS-ester-594":                                      "NHS-ester-594",    # generic 594-channel
    "NHS-ester 594":                                      "NHS-ester-594",
    "594 NHS-ester":                                      "NHS-ester-594",
    "NHS ester 594":                                      "NHS-ester-594",
    "Alexa Fluor NHS-Ester 594":                          "NHS-ester-AF594",
    "NHS-ester Alexa 594":                                "NHS-ester-AF594",
    "NHS Ester Alexa 594":                                "NHS-ester-AF594",
    "Alexa Fluor 594 NHS ester":                          "NHS-ester-AF594",
    "Alexa Fluor 594 NHS Ester":                          "NHS-ester-AF594",
    "Alexa 594 NHS-ester":                                "NHS-ester-AF594",

    # ── AF647 ──
    "NHS-ester-647":                                      "NHS-ester-647",    # generic 647-channel
    "NHS-ester Alexa Fluor 647":                          "NHS-ester-AF647",
    "NHS-Ester-Alexa Fluor 647":                          "NHS-ester-AF647",
    "NHS Ester Alexa Fluor 647":                          "NHS-ester-AF647",
    "NHS ester Alexa Fluor 647":                          "NHS-ester-AF647",
    "NHS Ester Alexa 647":                                "NHS-ester-AF647",
    "Alexa Fluor 647 carboxylic acid succinimidyl ester": "NHS-ester-AF647",
    "NHS AZ647":                                          "NHS-ester-AZ647",

    # ── ATTO425 ──
    "NHS ATTO425":                                        "NHS-ester-ATTO425",

    # ── ATTO488 ──
    "ATTO 488 NHS ester":                                 "NHS-ester-ATTO488",
    "Atto 488 NHS ester":                                 "NHS-ester-ATTO488",
    "ATTO-488 NHS-ester":                                 "NHS-ester-ATTO488",
    "NHS-ATTO-488":                                       "NHS-ester-ATTO488",
    "NHS-ATTO488":                                        "NHS-ester-ATTO488",
    "NHS-Atto488":                                        "NHS-ester-ATTO488",
    "NHS-ester-ATTO488":                                  "NHS-ester-ATTO488",
    "NHS-ester ATTO488":                                  "NHS-ester-ATTO488",
    "NHS-ester Atto488":                                  "NHS-ester-ATTO488",
    "NHS ester-ATTO488":                                  "NHS-ester-ATTO488",
    "NHS ester conjugated to ATTO488":                    "NHS-ester-ATTO488",
    "NHS ester Atto 488":                                 "NHS-ester-ATTO488",
    "ATTO 488 NHS-ester conjugated secondary":            "NHS-ester-ATTO488",

    # ── ATTO532 ──
    "NHS ester-ATTO532":                                  "NHS-ester-ATTO532",
    "NHS-ATTO-532":                                       "NHS-ester-ATTO532",
    "NHS AZ532":                                          "NHS-ester-AZ532",

    # ── ATTO565 ──
    "ATTO 565 NHS ester":                                 "NHS-ester-ATTO565",
    "NHS ester, Atto 565 conjugate":                      "NHS-ester-ATTO565",
    "NHS ester Atto 565 conjugate":                       "NHS-ester-ATTO565",
    "NHS ester-ATTO594":                                  "NHS-ester-ATTO594",  # note: below

    # ── ATTO590 ──
    "NHS-Atto590":                                        "NHS-ester-ATTO590",
    "Atto590-NHS ester":                                  "NHS-ester-ATTO590",

    # ── ATTO594 ──
    "Atto 594 NHS ester":                                 "NHS-ester-ATTO594",
    "ATTO 594 NHS ester":                                 "NHS-ester-ATTO594",
    "Atto 594 NHS-ester":                                 "NHS-ester-ATTO594",
    "NHS-Ester ATTO 594":                                 "NHS-ester-ATTO594",
    "NHS-ester-ATTO594":                                  "NHS-ester-ATTO594",
    "NHS-ester ATTO594 ":                                 "NHS-ester-ATTO594",
    "NHS-ester Atto594":                                  "NHS-ester-ATTO594",
    "Atto-NHS-594":                                       "NHS-ester-ATTO594",
    "ATTO-NHS-594":                                       "NHS-ester-ATTO594",
    "Atto-NHS ester 594":                                 "NHS-ester-ATTO594",
    "NHS Ester Atto 594":                                 "NHS-ester-ATTO594",
    "NHS ester Atto 594":                                 "NHS-ester-ATTO594",
    "NHS ester Atto 594 conjugate":                       "NHS-ester-ATTO594",
    "NHS ATTO594":                                        "NHS-ester-ATTO594",

    # ── ATTO643 ──
    "Atto-NHS-643":                                       "NHS-ester-ATTO643",
    "ATTO643-NHS":                                        "NHS-ester-ATTO643",

    # ── ATTO647N ──
    "ATTO 647N NHS ester":                                "NHS-ester-ATTO647N",
    "Atto 647N NHS ester":                                "NHS-ester-ATTO647N",
    "Atto 647N NHS Ester":                                "NHS-ester-ATTO647N",
    "ATTO TEC 647N NHS ester":                            "NHS-ester-ATTO647N",
    "Atto647N-NHS ester":                                 "NHS-ester-ATTO647N",
    "Atto-NHS-647N":                                      "NHS-ester-ATTO647N",
    "ATTO 647N NHS-ester":                                "NHS-ester-ATTO647N",
    "ATTO647N NHS ester":                                 "NHS-ester-ATTO647N",
    "NHS ATTO647N":                                       "NHS-ester-ATTO647N",

    # ── ATTO647 (ambiguous - not explicitly 647N) ──
    "ATTO 647 NHS Ester":                                 "NHS-ester-ATTO647N",  # almost certainly 647N
    "Atto 647 NHS ester":                                 "NHS-ester-ATTO647N",
    "NHS-ester ATTO647":                                  "NHS-ester-ATTO647N",
    "NHS-ester Atto647":                                  "NHS-ester-ATTO647N",
    "NHS-ester-ATTO647":                                  "NHS-ester-ATTO647N",

    # ── CF405M ──
    "NHS-CF405M":                                         "NHS-ester-CF405M",

    # ── CF555 ──
    "NHS CF 555":                                         "NHS-ester-CF555",

    # ── CF568 ──
    "NHS ester CF568":                                    "NHS-ester-CF568",
    "CF 568 NHS ester":                                   "NHS-ester-CF568",
    "CF568 NHS ester":                                    "NHS-ester-CF568",
    "CF 568 SE/TFP Ester":                                "NHS-ester-CF568",

    # ── DyLight405 ──
    "DyLight 405 NHS ester":                              "NHS-ester-DyLight405",
    "DyLight 405 NHS Ester":                              "NHS-ester-DyLight405",
    "DyLight 405 NHS-ester":                              "NHS-ester-DyLight405",
    "Dylight 405 NHS-Ester":                              "NHS-ester-DyLight405",

    # ── DyLight488 ──
    "DyLight 488 NHS ester":                              "NHS-ester-DyLight488",
    "DyLight 488 NHS Ester":                              "NHS-ester-DyLight488",
    "DyLight 488 NHS-ester":                              "NHS-ester-DyLight488",
    "DyLight NHS Ester 488":                              "NHS-ester-DyLight488",

    # ── DyLight594 ──
    "DyLight 594 NHS ester":                              "NHS-ester-DyLight594",
    "DyLight 594 NHS Ester":                              "NHS-ester-DyLight594",
    "DyLight 594 NHS-ester":                              "NHS-ester-DyLight594",

    # ── DyLight650 ──
    "NHS-Ester DyLight 650":                              "NHS-ester-DyLight650",

    # ── Cy3 / Cyanine3 ──
    "Cy3 NHS ester":                                      "NHS-ester-Cy3",
    "Cyanine3 NHS-ester":                                 "NHS-ester-Cy3",

    # ── Cy5 ──
    "Cyanine5 NHS-ester":                                 "NHS-ester-Cy5",

    # ── Sulfo-Cy3 ──
    "Sulfo-Cy3 NHS ester":                                "NHS-ester-Sulfo-Cy3",

    # ── BODIPY FL ──
    "BODIPY-FL NHS":                                      "NHS-ester-BODIPY FL",
    "NHS-Ester BODIPY FL":                                "NHS-ester-BODIPY FL",

    # ── BODIPY493/503 ──
    "NHS BODIPY493/503":                                  "NHS-ester-BODIPY493/503",

    # ── BODIPY581/591 ──
    "NHS BODIPY581/591":                                  "NHS-ester-BODIPY581/591",

    # ── BODIPY630/650 ──
    "BODIPY 630 NHS ester":                               "NHS-ester-BODIPY630/650",
    "NHS BODIPY630/650-X":                                "NHS-ester-BODIPY630/650",

    # ── STAR635P ──
    "STAR RED-NHS":                                       "NHS-ester-STAR635P",
    "NHS-STAR RED":                                       "NHS-ester-STAR635P",
    "STAR635P NHS ester":                                 "NHS-ester-STAR635P",
    "NHS-ester STAR 635P":                                "NHS-ester-STAR635P",
    "NHS-ester STAR635P":                                 "NHS-ester-STAR635P",

    # ── Fluorescein ──
    "Fluorescein NHS ester":                              "NHS-ester-fluorescein",
    "NHS-Fluorescein":                                    "NHS-ester-fluorescein",
    "NHS-Fluorescein #46409":                             "NHS-ester-fluorescein",
    "NHS-ester fluorescein":                              "NHS-ester-fluorescein",

    # ── TAMRA ──
    "TAMRA NHS ester":                                    "NHS-ester-TAMRA",
    "TAMRA NHS ester (5-Carboxy-tetramethylrhodamine N-succinimidyl ester)": "NHS-ester-TAMRA",

    # ── AZ series (AZDye) ──

    # ── MB series ──
    "NHS MB543":                                          "NHS-ester-MB543",
    "NHS MB660R":                                         "NHS-ester-MB660R",

    # ── MARS2147 ──
    "MARS2147 NHS ester":                                 "NHS-ester-MARS2147",

    # ── SeTau647 ──
    "SeTau647 NHS, K9-4149":                              "NHS-ester-SeTau647",

    # ── 550 (wavelength only) ──
    "NHS-550 ester":                                      "NHS-ester-550",

    # ── Already near-canonical forms (space/case fixes) ──
    "NHS-ester ATTO647N":                                "NHS-ester-ATTO647N",
    "NHS-ester ATTO565":                                 "NHS-ester-ATTO565",
    "NHS-ester ATTO488":                                 "NHS-ester-ATTO488",  # already canonical but include for safety
    "NHS-ester ATTO532":                                 "NHS-ester-ATTO532",
    "NHS-ester ATTO594":                                 "NHS-ester-ATTO594",
    # ── AF546 multi-choice (keep descriptive but normalize) ──
    "Alexa Fluor 546 NHS Ester or Alexa Fluor 647 NHS Ester or Atto 647N NHS Ester or Alexa 405 NHS Ester":
                                                          "NHS-ester (multiple)",
    "NHS-ester (Atto 647N or Sulfo-Cy3)":                 "NHS-ester (Atto 647N or Sulfo-Cy3)",
    "NHS-ester (Sulfo-Cy3 or Atto647N)":                  "NHS-ester (Atto 647N or Sulfo-Cy3)",

    # ── Biotin (keep, not fluorescent) ──
    "biotin NHS ester":                                   "biotin NHS ester",

    # ── AZ532 ──
    "NHS AZ532":                                          "NHS-ester-AZ532",
}

# Fix the ATTO565→ATTO594 collision above (NHS ester-ATTO594 was listed under 565)
NHS_MAP["NHS ester-ATTO594"] = "NHS-ester-ATTO594"

# ─────────────────────────────────────────────────────────────────────────────
# 2. Direct map for all other dye normalizations
# ─────────────────────────────────────────────────────────────────────────────

DIRECT_MAP = {
    # ── HOECHST ──
    "Hoechst":                                      "Hoechst 33342",
    "Hoechst33342":                                 "Hoechst 33342",
    "NucBlue/Hoechst 33342 (in ProLong Glass mountant)": "Hoechst 33342",
    "Hoechst33258":                                 "Hoechst 33258",
    "Hoechst BisBenzimid H 33258":                  "Hoechst 33258",

    # ── DAPI ──
    "DAPI dilactate":                               "DAPI",
    "DAPI (4',6 Diamidino 2 Phenylindole, Dilactate)": "DAPI",
    "D523 DAPI":                                    "DAPI",
    "DAPI (in Fluoromount G with DAPI)":            "DAPI",
    "DAPI (in ProLong Diamond Antifade Mountant)":  "DAPI",
    "DAPI (via DAPI Fluoromount-G)":                "DAPI",
    "ProLong Diamond Antifade Mountant with DAPI":  "DAPI",
    "Vectashield with DAPI":                        "DAPI",
    "Vectashield/DAPI":                             "DAPI",

    # ── SYTOX ──
    "Sytox Green":                                  "SYTOX Green",
    "SYTOX Green Nucleic Acid Stain":               "SYTOX Green",
    "Sytox":                                        "SYTOX",
    "SytoxTM Deep Red":                             "SYTOX Deep Red",
    "Sytox Deep Red":                               "SYTOX Deep Red",
    "SYTOX Deep Red":                               "SYTOX Deep Red",

    # ── SYTO ──
    "SYTO-17":                                      "SYTO 17",

    # ── BODIPY ceramide / variants ──
    "BODIPY-Ceramide":                              "BODIPY TR Ceramide",   # B22650 = TR
    "BODIPY-TR-Ceramide":                           "BODIPY TR Ceramide",
    "Bodipy-TR-Ceramide":                           "BODIPY TR Ceramide",
    "BodipyTR Ceramide":                            "BODIPY TR Ceramide",
    "BODIPY TR ceramide":                           "BODIPY TR Ceramide",
    "BODIPY-TM Ceramide":                           "BODIPY FL Ceramide",   # D7540 = FL; TM is typo
    "Bodipy TR":                                    "BODIPY TR Ceramide",
    "BODIPY-FL-C5-Ceramide":                        "BODIPY FL Ceramide",
    "Bodipy":                                       "BODIPY",
    "BODIPY 558/568 C12":                           "BODIPY 558/568 C12",

    # ── MitoTracker ──
    "Mitotracker":                                  "MitoTracker",
    "Mitotracker Orange CMTMRos":                   "MitoTracker Orange CMTMRos",
    "mitoTracker Red CMXRos":                       "MitoTracker Red CMXRos",

    # ── mCLING ──
    "mCling-Atto643":                               "mCLING-ATTO647N",   # ATTO643 = ATTO647N (renamed)
    "ATTO643-mCling":                               "mCLING-ATTO647N",
    "mCLING-Atto647N":                              "mCLING-ATTO647N",
    "mCLING-Atto488":                               "mCLING-ATTO488",
    "mCLING-ATTO-Alexa Fluor 647N":                 "mCLING-ATTO647N",   # confused name; cat 710 006AT1 = ATTO647N

    # ── DRAQ5 ──
    "Draq5":                                        "DRAQ5",

    # ── TO-PRO-3 ──
    "TO-PRO-3 iodide":                              "TO-PRO-3",

    # ── Propidium iodide ──
    "Propidium iodide (PI)":                        "propidium iodide",
    "Propidium iodide":                             "propidium iodide",

    # ── DiD / DiI ──
    "DiD-D dye":                                    "DiD",
    "Vybrant DiI":                                  "DiI",

    # ── CellMask ──
    "CellMask Orange Plasma Membrane Stain":        "CellMask Orange",

    # ── SYBR Safe ──
    "SybrSafe":                                     "SYBR Safe",

    # ── R18 ──
    "R18 dye":                                      "R18",
    "Octadecyl rhodamine B chloride (R18)":         "R18",
    "octadecyl rhodamine B chloride (R18)":         "R18",

    # ── FM 1-43 ──
    "FM 1-43":                                      "FM1-43",

    # ── BioTracker ──
    "BioTracker NIR694 Nuclear Dye":                "BioTracker NIR 694",

    # ── Streptavidin ──
    "Alexa Fluor 488 Streptavidin":                 "streptavidin-Alexa Fluor 488",
    "Alexa Fluor 594 streptavidin":                 "streptavidin-Alexa Fluor 594",
    "CyTM3 Streptavidin":                           "streptavidin-Cy3",
    "DyLight 405 Streptavidin":                     "streptavidin-DyLight 405",
    "streptavidin-Alexa Fluor 546 (via isHCR)":     "streptavidin-Alexa Fluor 546",

    "Atto647N-maleimide":                              "ATTO647N-maleimide",
    "MitoTracker Deep Red FM":                          "MitoTracker Deep Red",
    "BODIPY 558/568 C12":                               "BODIPY 558/568 C12",
    # ── ATTO reactive (non-NHS) — case fixes ──
    "Atto 647N maleimide":                          "ATTO647N-maleimide",
    "ATTO TEC 565 hydrazide":                       "ATTO565-hydrazide",
}

# Merge NHS_MAP into DIRECT_MAP (NHS entries take precedence)
FULL_MAP = {**DIRECT_MAP, **NHS_MAP}

# ─────────────────────────────────────────────────────────────────────────────
# 3. Apply
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    df = pd.read_csv(DB, encoding="utf-8-sig", low_memory=False)
    df = df.map(lambda x: x.replace("\x00", "") if isinstance(x, str) else x)

    dye_mask = df["label_type"] == "dye"
    dye_idx  = df[dye_mask].index

    changes = []
    for idx in dye_idx:
        old = df.at[idx, "label_name"]
        if not isinstance(old, str):
            continue
        stripped = old.strip()
        new = FULL_MAP.get(stripped)
        if new is None:
            continue   # not in map; leave unchanged
        if new != old:
            changes.append((idx, old, new))
            df.at[idx, "label_name"] = new

    # Summary
    print(f"Dye rows total: {dye_mask.sum()}")
    print(f"Changes:        {len(changes)}\n")

    # Group by (old → new) for report
    by_pair = {}
    for _, old, new in changes:
        key = (old, new)
        by_pair[key] = by_pair.get(key, 0) + 1
    for (old, new), cnt in sorted(by_pair.items(), key=lambda x: x[0][1]):
        arrow = "→" if old != new else "="
        print(f"  {cnt:3d}×  {old!r}  {arrow}  {new!r}")

    # Check for names we didn't map (informational)
    remaining = df.loc[dye_idx, "label_name"]
    after_vc  = remaining.value_counts()
    unmapped  = [n for n in after_vc.index
                 if isinstance(n, str) and n not in set(FULL_MAP.values())
                 and n not in set(FULL_MAP.keys())]
    if unmapped:
        print(f"\nNames NOT in map (kept as-is) — {len(unmapped)} unique:")
        for n in sorted(unmapped, key=lambda x: x.lower()):
            print(f"         {after_vc[n]:3d}×  {n!r}")

    if not args.apply:
        print("\nDry run — pass --apply to save.")
        return

    backup = DB.with_suffix(".pre_dye_norm.bak.csv")
    shutil.copy(DB, backup)
    print(f"\nBackup: {backup.name}")

    with open(DB, "w", encoding="utf-8-sig", newline="") as f:
        df.to_csv(f, index=False)
        with suppress(OSError):
            os.fsync(f.fileno())
    print(f"Saved {DB.name}  ({len(df)} rows)")

if __name__ == "__main__":
    main()
