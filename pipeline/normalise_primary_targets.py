#!/usr/bin/env python3
"""
Normalise label_target for primary antibodies and nanobodies in
ExM_database_curated.csv.

Three-pass normalisation:
  Pass 1 — Greek letter ASCII conversion  (lossless, always safe)
  Pass 2 — Strip contextual parentheticals (e.g. cell lines, system names)
  Pass 3 — Synonym dictionary              (curated canonical forms)

Usage:
    python normalise_primary_targets.py           # dry run — prints diff
    python normalise_primary_targets.py --apply   # write to CSV (auto-backup)
    python normalise_primary_targets.py --report  # counts only
    python normalise_primary_targets.py --show-unmapped   # show values not in dict
"""

import re, argparse, shutil
from pathlib import Path
import pandas as pd

DB = Path(__file__).parent / "ExM_database_curated.csv"

# ── Pass 1: Greek → ASCII ─────────────────────────────────────────────────────
GREEK = [
    ("α", "alpha"),  # α
    ("β", "beta"),   # β
    ("γ", "gamma"),  # γ
    ("δ", "delta"),  # δ
    ("ε", "epsilon"),# ε
]

def pass1_greek(s: str) -> str:
    for char, name in GREEK:
        # char followed by hyphen:   α-tubulin  → alpha-tubulin
        s = re.sub(re.escape(char) + r"-", name + "-", s)
        # char followed by letter/digit (no hyphen): βII → betaII, Aβ stays handled by next rule
        s = re.sub(re.escape(char) + r"(?=[A-Za-z0-9])", name, s)
        # char standalone or at end: remaining occurrences
        s = re.sub(re.escape(char), name, s)
    return s


# ── Pass 2: Strip contextual parentheticals ───────────────────────────────────
# Parentheticals that add context rather than identity — strip them.
# Keep if the content looks like a canonical abbreviation or clone name
# (all-caps, or known antibody clone patterns).

KEEP_PAREN_RE = re.compile(
    r"""
    \(
    (?:
        [A-Z][A-Z0-9\-]{1,9}   # short all-caps abbreviation: MBP, NPC, PolyE, GT335
      | H\+L                   # heavy+light chain qualifier
      | ab\d+                  # Abcam cat number
    )
    \)
    """,
    re.VERBOSE,
)

# Patterns that mark a parenthetical as "context noise" → strip
STRIP_PAREN_CONTENT = re.compile(
    r"\("
    r"(?:"
    r"[A-Z][a-z].*?cells?"   # cell-line qualifier: "HEK-293FT cells"
    r"|.*?\bcells?\b"
    r"|.*?\btissue\b"
    r"|.*?system\b"           # "SpaMo system"
    r"|secondary.*?"          # "(secondary)"
    r"|alternative.*?"
    r"|microtubules?"         # "(microtubules)"
    r"|mitochondrial.*?"
    r")"
    r"\)",
    re.IGNORECASE,
)

def pass2_strip_paren(s: str) -> str:
    # Only strip if it does NOT match a keep-pattern
    def maybe_strip(m):
        if KEEP_PAREN_RE.match(m.group(0)):
            return m.group(0)
        return ""
    s = STRIP_PAREN_CONTENT.sub(maybe_strip, s)
    return s.strip(" /,;")


# ── Pass 3: Synonym dictionary ────────────────────────────────────────────────
# Keys are case-insensitive. Values are the canonical form.
# Sorted by specificity (longer/more-specific first where ambiguous).

SYNONYMS = {
    # ── Tubulin family ────────────────────────────────────────────────────────
    "alpha-tubulin and beta-tubulin":   "alpha/beta-tubulin",
    "alpha-tubulin + beta-tubulin":     "alpha/beta-tubulin",
    "tubulin (alpha/beta-tubulin)":     "alpha/beta-tubulin",
    "alpha- and beta-tubulin":          "alpha/beta-tubulin",
    "tubulin / microtubules":           "alpha-tubulin",
    "tubulin (microtubules)":           "alpha-tubulin",
    "alpha-tubulin (microtubules)":     "alpha-tubulin",
    "acetylated alpha-tubulin":         "acetylated alpha-tubulin",   # canonical — keep
    "acetylated tubulin":               "acetylated alpha-tubulin",
    "beta-tubulin iv":                  "beta-tubulin IV",
    "polyglutamylated tubulin":         "polyglutamylated tubulin",
    "polyglutamylation":                "polyglutamylated tubulin",
    "glutamylated tubulin":             "polyglutamylated tubulin",
    "tyrosinated tubulin":              "tyrosinated alpha-tubulin",
    "tyrosinated alpha-tubulin":        "tyrosinated alpha-tubulin",
    "alpha-tubulin tyrosinated":        "tyrosinated alpha-tubulin",
    "detyrosinated tubulin":            "detyrosinated alpha-tubulin",
    "detyrosinated alpha-tubulin":      "detyrosinated alpha-tubulin",
    "delta2-tubulin":                   "delta2 alpha-tubulin",
    "delta 2 tubulin":                  "delta2 alpha-tubulin",
    "gamma-tubulin":                    "gamma-tubulin",

    # ── Centrin ───────────────────────────────────────────────────────────────
    "centrin":                          "centrin",
    "centrin-2":                        "centrin",
    "centrin-1":                        "centrin",
    "cetn2":                            "centrin",

    # ── Synapse proteins ──────────────────────────────────────────────────────
    "psd95":                            "PSD-95",
    "psd-95":                           "PSD-95",
    "homer":                            "Homer1",
    "homer1":                           "Homer1",
    "homer 1":                          "Homer1",
    "bassoon":                          "bassoon",
    "shank2":                           "SHANK2",
    "shank 2":                          "SHANK2",
    "synaptophysin":                    "synaptophysin",
    "synaptotagmin 1":                  "synaptotagmin-1",
    "syt1":                             "synaptotagmin-1",
    "vglut1":                           "vGLUT1",
    "vgat":                             "vGAT",

    # ── Mitochondria ──────────────────────────────────────────────────────────
    "tomm20":                           "TOM20",
    "tom20":                            "TOM20",

    # ── Actin ─────────────────────────────────────────────────────────────────
    "beta-actin":                       "actin",
    "f-actin":                          "actin",
    "g-actin":                          "actin",

    # ── Tags ──────────────────────────────────────────────────────────────────
    "flag-tag":                         "FLAG",
    "flag tag":                         "FLAG",
    "ha-tag":                           "HA",
    "ha tag":                           "HA",
    "his-tag":                          "His-tag",
    "6xhis":                            "His-tag",
    "myc-tag":                          "Myc",
    "myc tag":                          "Myc",
    "gfp":                              "GFP",
    "anti-gfp":                         "GFP",
    "mcherry":                          "mCherry",
    "rfp":                              "RFP",
    "yfp":                              "YFP",

    # ── Nuclear / NPC ─────────────────────────────────────────────────────────
    "nuclear pore complex":             "nuclear pore complex",
    "nuclear pore complex (npc)":       "nuclear pore complex",
    "npc":                              "nuclear pore complex",

    # ── Photosynthesis ────────────────────────────────────────────────────────
    "psba":                             "PsbA",
    "psba (psii)":                      "PsbA",
    "rubisco large subunit":            "RuBisCO large subunit",
    "rbcl":                             "RuBisCO large subunit",
    "rubisco large subunit (rbcl) / pyrenoid": "RuBisCO large subunit",
    "psba / d1 protein of photosystem ii": "PsbA",

    # ── Cilia / centrosome ────────────────────────────────────────────────────
    "arl13b":                           "ARL13B",
    "cep164":                           "CEP164",
    "cep290":                           "CEP290",
    "cep135":                           "CEP135",
    "cep83":                            "CEP83",
    "cep152":                           "CEP152",
    "poc5":                             "POC5",
    "poc1b":                            "POC1B",
    "sas-6":                            "SAS-6",
    "ift88":                            "IFT88",
    "ofd1":                             "OFD1",
    "odf2":                             "ODF2",
    "ninein":                           "ninein",

    # ── Case fixes for gene names ─────────────────────────────────────────────
    "lamin a/c":                        "lamin A/C",
    "lamin b1":                         "lamin B1",
    "ki-67":                            "Ki-67",
    "ki67":                             "Ki-67",
    "neun":                             "NeuN",
    "gfap":                             "GFAP",
    "map2":                             "MAP2",
    "pcm1":                             "PCM1",

    # ── Misc ──────────────────────────────────────────────────────────────────
    "betaii-spectrin":                  "betaII-spectrin",
    "beta-ii-spectrin":                 "betaII-spectrin",
    "myelin basic protein":             "MBP",
    "myelin basic protein (mbp)":       "MBP",
    "tyrosine hydroxylase":             "tyrosine hydroxylase",
}

def pass3_synonyms(s: str) -> str:
    key = s.strip().lower()
    return SYNONYMS.get(key, s)


# ── Combined normaliser ───────────────────────────────────────────────────────

def normalise(s: str) -> str:
    if not isinstance(s, str) or not s.strip():
        return s
    s = pass1_greek(s)
    s = pass2_strip_paren(s)
    s = pass3_synonyms(s)
    return s.strip()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply",        action="store_true")
    parser.add_argument("--report",       action="store_true")
    parser.add_argument("--show-unmapped",action="store_true",
                        help="Print unique values that no pass changed")
    args = parser.parse_args()

    df = pd.read_csv(DB, encoding="utf-8-sig", low_memory=False)
    df = df.map(lambda x: x.replace("\x00", "") if isinstance(x, str) else x)

    prim_mask = df["label_type"].isin(["primary_antibody", "nanobody"])
    original  = df.loc[prim_mask, "label_target"].copy()
    normed    = original.apply(lambda x: normalise(x) if isinstance(x, str) else x)

    changed   = original != normed
    n_changed = changed.sum()

    if args.report:
        print(f"Primary/nanobody rows:  {prim_mask.sum()}")
        print(f"Would change:           {n_changed}")
        return

    if args.show_unmapped:
        unchanged = original[~changed].dropna()
        print("Values unchanged by all passes (sample):")
        for v, n in unchanged.value_counts().head(40).items():
            print(f"  {n:4d}  {v!r}")
        return

    if n_changed == 0:
        print("Nothing to change.")
        return

    print(f"Changes to apply: {n_changed} rows")
    if not args.apply:
        print("\nSample (first 30):")
        shown = 0
        for idx in original[changed].index:
            print(f"  {original[idx]!r:55s} → {normed[idx]!r}")
            shown += 1
            if shown >= 30: break
        print("\nDry run. Run with --apply to save.")
        return

    backup = DB.with_suffix(".pre_norm_prim.bak.csv")
    shutil