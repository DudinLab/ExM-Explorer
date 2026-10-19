#!/usr/bin/env python3
"""
qc_check.py — Comprehensive QC pipeline for the ExM database.

9 automated checks covering data integrity, scientific validity, and metadata
accuracy. Generates a human-readable report and a CSV of all flagged items.

Usage:
    python qc_check.py              # all checks (includes CrossRef + NCBI calls)
    python qc_check.py --local      # local checks only — no network, runs instantly

Output:
    qc_report.txt    — human-readable report, one section per check
    qc_flags.csv     — machine-readable table of all flagged items for tracking
"""

import argparse
import csv
import difflib
import json
import re
import sys
import time
import urllib.request
import urllib.parse
from collections import defaultdict
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────

CSV_FILE    = Path(__file__).parent / "exm_database.csv"
REPORT_FILE = Path(__file__).parent / "qc_report.txt"
FLAGS_FILE  = Path(__file__).parent / "qc_flags.csv"
NCBI_EMAIL  = "omaya.dudin@unige.ch"   # required by NCBI Entrez policy

# ── Controlled vocabularies ────────────────────────────────────────────────────

VALID_CLADES = {
    "Alveolata", "Viridiplantae", "Stramenopiles", "Haptophyta",
    "Cryptista", "Unicellular Holozoa", "Discoba", "Rhodophyta",
    "Fungi", "Rhizaria", "Glaucophyta", "Amoebozoa",
    "Metazoa", "Archaea", "Bacteria", "Unknown",
}

CANONICAL_VARIANTS = {
    "U-ExM", "proExM", "ExPath", "ExFISH", "TREx",
    "Magnify", "cryo-ExM", "MAP", "iterative-ExM",
}

# Maps NCBI lineage node names to our 15-clade vocabulary.
# Order matters: more specific terms listed before broader ones.
LINEAGE_TO_CLADE = [
    ("Metazoa",          "Metazoa"),
    ("Fungi",            "Fungi"),
    ("Viridiplantae",    "Viridiplantae"),
    ("Alveolata",        "Alveolata"),
    ("Stramenopiles",    "Stramenopiles"),
    ("Oomycota",         "Stramenopiles"),
    ("Rhizaria",         "Rhizaria"),
    ("Discoba",          "Discoba"),
    ("Euglenozoa",       "Discoba"),        # NCBI sometimes uses Euglenozoa instead of Discoba
    ("Haptista",         "Haptophyta"),
    ("Haptophyta",       "Haptophyta"),
    ("Cryptophyceae",    "Cryptista"),
    ("Cryptista",        "Cryptista"),
    ("Choanoflagellida", "Unicellular Holozoa"),
    ("Ichthyosporea",    "Unicellular Holozoa"),
    ("Filasterea",       "Unicellular Holozoa"),
    ("Rhodophyta",       "Rhodophyta"),
    ("Glaucophyta",      "Glaucophyta"),
    ("Amoebozoa",        "Amoebozoa"),
    ("Archaea",          "Archaea"),
    ("Bacteria",         "Bacteria"),
]

# Common cell line names → their source organism, for NCBI taxonomy lookups.
# Cell line names are not in NCBI taxonomy; we resolve them to the organism first.
CELL_LINE_TO_SPECIES = {
    "hela": "Homo sapiens", "he-la": "Homo sapiens",
    "hek293": "Homo sapiens", "hek 293": "Homo sapiens", "293t": "Homo sapiens",
    "u2os": "Homo sapiens", "u-2os": "Homo sapiens",
    "rpe-1": "Homo sapiens", "rpe1": "Homo sapiens",
    "mcf-7": "Homo sapiens", "mcf7": "Homo sapiens",
    "hct116": "Homo sapiens", "a549": "Homo sapiens",
    "sh-sy5y": "Homo sapiens", "jurkat": "Homo sapiens",
    "hy926": "Homo sapiens", "beas-2b": "Homo sapiens",
    "cos-7": "Chlorocebus sabaeus", "cos7": "Chlorocebus sabaeus",
    "vero": "Chlorocebus sabaeus", "bsc-1": "Chlorocebus sabaeus",
    "cho": "Cricetulus griseus",
    "3t3": "Mus musculus", "nih 3t3": "Mus musculus", "mef": "Mus musculus",
    "pc12": "Rattus norvegicus",
    "ptk2": "Potorous tridactylus",
    "llc-pk1": "Sus scrofa",
}

# ── Utility functions ──────────────────────────────────────────────────────────

def load_csv(path: Path):
    rows, fieldnames = [], []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            rows.append(dict(row))
    return rows, fieldnames


def papers_from_rows(rows):
    """Group rows by pdf_filename."""
    papers = defaultdict(list)
    for r in rows:
        papers[r.get("pdf_filename", "")].append(r)
    return dict(papers)


def species_set(paper_rows):
    return {r.get("species", "").strip().lower()
            for r in paper_rows if r.get("species", "").strip()}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def title_sim(t1, t2):
    return difflib.SequenceMatcher(None, t1.lower(), t2.lower()).ratio()


def safe_float(val):
    """Parse a numeric value from strings like '4x', '4–4.3x', '~4.5', '2022'.

    Uses first-number extraction rather than stripping all non-numeric chars.
    That avoids the concatenation bug where '4–4.3x' strips to '44.3':
      - '4–4.3x'                        → 4.0
      - '5x (HeLa); 5.1x (parasite)'   → 5.0  (strips parens, takes first part)
      - '~4x (in 0.001x PBS); ~2x ...'  → 4.0
      - '3.85x–4.27x'                   → 3.85
    """
    if not val:
        return None
    val = val.strip()
    # Strip parenthetical comments: "(in 0.001x PBS)", "(HeLa nuclei)"
    val = re.sub(r"\(.*?\)", "", val)
    # If compound (semicolon-separated), take first part only
    val = val.split(";")[0].strip()
    # Extract first integer or decimal found in the remaining string
    m = re.search(r"(\d+\.?\d*)", val)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            return None
    return None


def resolve_species(species):
    """Map cell line names to their source organism for NCBI lookup."""
    sp_lower = species.strip().lower()
    for cell_line, organism in CELL_LINE_TO_SPECIES.items():
        if cell_line in sp_lower:
            return organism
    return species


def ncbi_lineage_to_clade(lineage_str):
    """Convert an NCBI lineage string to our 15-clade vocabulary."""
    for ncbi_term, our_clade in LINEAGE_TO_CLADE:
        if ncbi_term in lineage_str:
            return our_clade
    return "Unknown"


# ── QC Checks ──────────────────────────────────────────────────────────────────

def check_missing_fields(papers):
    """
    CHECK 1 — Missing critical fields.

    Why: species, clade, and exm_variant are the three fields the phylogenetic
    tree and protocol comparison are built on. A paper missing all of these
    contributes nothing to the database. DOI is needed to link back to the
    source. This check flags papers where these fields are systematically empty
    across all rows — not just missing in one row due to a label-only entry.
    """
    flags = []
    for fname, rows in papers.items():
        missing = []
        if not any(r.get("species", "").strip() for r in rows):
            missing.append("species")
        if not any(r.get("clade", "").strip() for r in rows):
            missing.append("clade")
        if not any(r.get("exm_variant", "").strip() for r in rows):
            missing.append("exm_variant")
        if not rows[0].get("doi", "").strip():
            missing.append("doi")
        if missing:
            flags.append({
                "check": "missing_fields",
                "pdf_filename": fname,
                "species": "",
                "detail": "Missing: " + ", ".join(missing),
                "suggestion": "",
            })
    return flags


def check_invalid_clades(rows):
    """
    CHECK 2 — Clade values outside the controlled vocabulary.

    Why: the 15-clade vocabulary is the only valid input for the phylogenetic
    tree. Any other value — including 'uncertain: ...' prefixes that were never
    resolved — will either break the tree or create phantom branches. Every
    row must have one of the 16 valid values (15 clades + Unknown).
    """
    flags = []
    seen = set()
    for r in rows:
        clade = r.get("clade", "").strip()
        key = (r["pdf_filename"], r.get("species", ""), clade)
        if key in seen or not clade:
            continue
        seen.add(key)
        if clade not in VALID_CLADES:
            flags.append({
                "check": "invalid_clade",
                "pdf_filename": r["pdf_filename"],
                "species": r.get("species", ""),
                "detail": f"'{clade}' is not in the controlled vocabulary",
                "suggestion": "Review and assign one of the 16 valid clades",
            })
    return flags


def check_exm_variants(papers):
    """
    CHECK 3 — Non-canonical ExM variant names.

    Why: the model sometimes outputs overly descriptive names like
    'other: proExM (Chen et al. 2015 original ExM)' instead of 'proExM', or
    'other: PS-ExM (Pre-gelation Staining ExM)' vs 'other: PS-ExM
    (pre-gelation staining expansion microscopy)' — the same variant with
    inconsistent capitalisation. These need collapsing for filtering to work.
    This check surfaces all non-canonical values and suggests mappings where
    it can detect the canonical form inside the string.
    """
    flags = []
    seen_variants = set()
    for fname, rows in papers.items():
        variant = rows[0].get("exm_variant", "").strip()
        if not variant or variant in CANONICAL_VARIANTS or variant in seen_variants:
            continue
        seen_variants.add(variant)
        suggestion = next(
            (c for c in CANONICAL_VARIANTS if c.lower() in variant.lower()), ""
        )
        flags.append({
            "check": "non_canonical_variant",
            "pdf_filename": fname,
            "species": "",
            "detail": f"Variant: '{variant}'",
            "suggestion": suggestion or "Review manually",
        })
    return flags


def check_duplicates(papers):
    """
    CHECK 4 — Potential duplicate papers.

    Why: papers are often first posted as bioRxiv preprints and later published
    in a journal, but duplicates can also be bioRxiv vs bioRxiv (two versions)
    or journal vs journal (rare but real). Including both inflates every count
    in the database. We cannot rely on DOI comparison — DOIs are always
    different — so we use two complementary signals:

      (a) Title similarity > 0.85 via SequenceMatcher: even papers that are
          revised significantly between preprint and publication retain > 85%
          of their title text.
      (b) Same first + last author AND species Jaccard similarity > 0.60 AND
          year difference ≤ 3: a different study by the same authors testing
          the same species in the same year is extremely unlikely.

    Either signal alone triggers a flag. Human confirmation is always needed
    before deletion — the script never removes data.
    """
    flags = []
    fnames = list(papers.keys())
    for i in range(len(fnames)):
        for j in range(i + 1, len(fnames)):
            a, b = fnames[i], fnames[j]
            ar, br = papers[a], papers[b]

            a_title = (ar[0].get("title") or "").strip()
            b_title = (br[0].get("title") or "").strip()
            a_first = (ar[0].get("first_author") or "").lower().strip()
            b_first = (br[0].get("first_author") or "").lower().strip()
            a_last  = (ar[0].get("last_author") or "").lower().strip()
            b_last  = (br[0].get("last_author") or "").lower().strip()
            a_year  = safe_float(ar[0].get("year") or "0") or 0
            b_year  = safe_float(br[0].get("year") or "0") or 0
            a_sp    = species_set(ar)
            b_sp    = species_set(br)

            t_sim_val  = title_sim(a_title, b_title) if a_title and b_title else 0
            sp_jac     = jaccard(a_sp, b_sp)
            same_auth  = a_first == b_first and a_last == b_last and bool(a_first)
            yr_close   = abs(a_year - b_year) <= 3

            if t_sim_val >= 0.85 or (same_auth and yr_close and sp_jac >= 0.60):
                flags.append({
                    "check": "duplicate",
                    "pdf_filename": a,
                    "species": "",
                    "detail": (
                        f"Possible duplicate of: {b} | "
                        f"title_sim={t_sim_val:.2f} "
                        f"species_jaccard={sp_jac:.2f} "
                        f"same_authors={same_auth} "
                        f"year_diff={abs(a_year - b_year):.0f}"
                    ),
                    "suggestion": f"Compare with {b} and keep journal version",
                })
    return flags


def check_species_names(rows):
    """
    CHECK 5 — Species name standardisation.

    Why: abbreviated names like 'T. brucei' and 'Trypanosoma brucei' will be
    treated as two distinct species in the tree, creating phantom leaf nodes.
    We flag:
      (a) Abbreviated genus ('T. brucei' — dot after first letter)
      (b) Names starting with lowercase (PDF parsing artifact)
      (c) Pairs of names that look like the same species written differently
          (same species epithet + same genus initial + string similarity > 0.75)
    """
    flags = []
    seen = set()
    species_to_paper = {}

    for r in rows:
        sp = r.get("species", "").strip()
        if not sp or sp in seen:
            continue
        seen.add(sp)
        species_to_paper[sp] = r.get("pdf_filename", "")

        issues = []
        if re.match(r"^[A-Za-z]\.\s+\w", sp):
            issues.append("abbreviated genus (e.g. 'T. brucei') — spell out in full")
        if sp and sp[0].islower():
            issues.append("starts with lowercase — likely parsing artifact")
        if issues:
            flags.append({
                "check": "species_name",
                "pdf_filename": species_to_paper[sp],
                "species": sp,
                "detail": "; ".join(issues),
                "suggestion": "",
            })

    # Pairwise: detect abbreviated vs full-name pairs of the same species.
    # We strip parenthetical qualifiers (cell line, tissue, strain) before comparing.
    # 'Homo sapiens (HeLa)' and 'Homo sapiens (HEK)' share the base 'Homo sapiens'
    # — they are intentionally different rows, not duplicates. Skip those pairs.
    sp_list = list(species_to_paper.keys())
    for i in range(len(sp_list)):
        for j in range(i + 1, len(sp_list)):
            sa, sb = sp_list[i], sp_list[j]
            # Strip trailing parenthetical qualifiers for comparison
            import re as _re
            ba = _re.sub(r'\s*\(.*\)\s*$', '', sa).strip()
            bb = _re.sub(r'\s*\(.*\)\s*$', '', sb).strip()
            # Same base organism = intentionally different cell lines, not a dup
            if ba.lower() == bb.lower():
                continue
            wa = ba.lower().split()
            wb = bb.lower().split()
            if (len(wa) >= 2 and len(wb) >= 2
                    and wa[-1] == wb[-1]           # same species epithet
                    and wa[0][0] == wb[0][0]       # same genus initial
                    and title_sim(ba, bb) > 0.75): # compare base names
                flags.append({
                    "check": "species_name",
                    "pdf_filename": species_to_paper[sa],
                    "species": sa,
                    "detail": f"Possible same species as '{sb}' — standardise to one form",
                    "suggestion": sb if len(sb) > len(sa) else sa,
                })
    return flags


def check_expansion_factors(rows):
    """
    CHECK 6 — Expansion factor sanity.

    Why: standard ExM protocols expand tissue between 2x and 10x (some
    iterative protocols reach up to 20x). Values outside 1.5–25x are almost
    certainly parsing errors — common mistakes include '400%' instead of '4x',
    or a resolution value ('4.5 nm') being misread as an expansion factor.
    These junk values would corrupt any quantitative analysis of expansion.
    """
    flags = []
    seen = set()
    for r in rows:
        for field in ("expansion_factor_nominal", "expansion_factor_measured"):
            val = r.get(field, "").strip()
            if not val or val.lower().startswith(("null", "uncertain", "inferred", "n/a")):
                continue
            key = (r["pdf_filename"], r.get("species", ""), field, val)
            if key in seen:
                continue
            seen.add(key)
            num = safe_float(val)
            if num is None:
                flags.append({
                    "check": "expansion_factor",
                    "pdf_filename": r["pdf_filename"],
                    "species": r.get("species", ""),
                    "detail": f"{field} = '{val}' — could not parse as a number",
                    "suggestion": "Check source PDF for actual expansion factor",
                })
            elif num > 25:
                flags.append({
                    "check": "expansion_factor",
                    "pdf_filename": r["pdf_filename"],
                    "species": r.get("species", ""),
                    "detail": f"{field} = {num} (above expected maximum 25x)",
                    "suggestion": "Check source PDF — likely a parsing error",
                })
            elif num < 1.5 and r.get("clade", "") not in ("Bacteria", "Archaea"):
                # Bacteria/Archaea with rigid cell walls legitimately expand less
                flags.append({
                    "check": "expansion_factor",
                    "pdf_filename": r["pdf_filename"],
                    "species": r.get("species", ""),
                    "detail": f"{field} = {num} (outside expected range 1.5–25x)",
                    "suggestion": "Check source PDF — likely a parsing error",
                })
    return flags


def check_label_consistency(papers):
    """
    CHECK 7 — Label completeness and consistency.

    Two sub-checks:
      (a) Secondary antibody without a primary: a secondary antibody amplifies
          a primary — having one without the other is almost always a missed
          extraction, not a deliberate protocol choice.
      (b) No labels at all: papers where every row has an empty label_name.
          These may be chemistry-based ExM (no antibodies by design) or failed
          label extractions. Human review needed to distinguish the two.
    """
    flags = []
    for fname, rows in papers.items():
        by_species = defaultdict(list)
        for r in rows:
            sp = r.get("species", "")
            if sp:
                by_species[sp].append(r)

        for sp, sp_rows in by_species.items():
            has_primary   = any(r.get("label_type") == "primary_antibody"  for r in sp_rows)
            has_secondary = any(r.get("label_type") == "secondary_antibody" for r in sp_rows)
            if has_secondary and not has_primary:
                flags.append({
                    "check": "label_consistency",
                    "pdf_filename": fname,
                    "species": sp,
                    "detail": "Secondary antibody present but no primary — primary likely missed",
                    "suggestion": "Check source PDF for primary antibody details",
                })

        if not any(r.get("label_name", "").strip() for r in rows):
            flags.append({
                "check": "no_labels",
                "pdf_filename": fname,
                "species": "",
                "detail": "No antibodies or labels extracted for this paper",
                "suggestion": "Check if chemistry-based ExM (no antibodies by design) or missing extraction",
            })
    return flags


def check_metadata_crossref(papers):
    """
    CHECK 8 — Metadata verification via CrossRef API (free, no API key needed).

    Why: paper titles and journal names extracted from PDFs are sometimes
    garbled — encoding issues, running headers mixed into the title, or
    abbreviated journal names. CrossRef is the authoritative source for
    published metadata. We compare our title against CrossRef and flag
    similarity < 0.70 (substantial mismatch) and year differences.

    Rate limit: 1 call/second (CrossRef polite pool). Runtime: ~1s per paper.
    Papers without DOIs or with uncertain DOIs are skipped.
    """
    flags = []
    for fname, rows in papers.items():
        doi = (rows[0].get("doi") or "").strip()
        if not doi or doi.startswith(("uncertain", "inferred", "null")):
            flags.append({
                "check": "crossref",
                "pdf_filename": fname,
                "species": "",
                "detail": "No valid DOI — cannot verify metadata",
                "suggestion": "Search CrossRef manually: https://search.crossref.org/",
            })
            continue

        time.sleep(1.05)
        try:
            doi_enc = urllib.parse.quote(doi, safe="")
            url = f"https://api.crossref.org/works/{doi_enc}"
            req = urllib.request.Request(
                url, headers={"User-Agent": f"ExMDatabase/1.0 (mailto:{NCBI_EMAIL})"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            if data.get("status") != "OK":
                raise ValueError("non-OK status")

            msg      = data["message"]
            cr_title = (msg.get("title") or [""])[0]
            cr_year  = ""
            for date_key in ("published-print", "published-online", "created"):
                dp = msg.get(date_key, {}).get("date-parts", [[]])
                if dp and dp[0]:
                    cr_year = str(dp[0][0])
                    break

            our_title = (rows[0].get("title") or "").strip()
            our_year  = str(rows[0].get("year") or "").strip()

            if our_title and cr_title:
                sim = title_sim(our_title, cr_title)
                if sim < 0.70:
                    flags.append({
                        "check": "crossref",
                        "pdf_filename": fname,
                        "species": "",
                        "detail": f"Title mismatch (similarity={sim:.2f}): ours='{our_title[:70]}' | CrossRef='{cr_title[:70]}'",
                        "suggestion": cr_title,
                    })

            if our_year and cr_year and our_year != cr_year:
                flags.append({
                    "check": "crossref",
                    "pdf_filename": fname,
                    "species": "",
                    "detail": f"Year mismatch: ours={our_year} | CrossRef={cr_year}",
                    "suggestion": cr_year,
                })

        except Exception as e:
            flags.append({
                "check": "crossref",
                "pdf_filename": fname,
                "species": "",
                "detail": f"DOI lookup failed for {doi}: {e}",
                "suggestion": "",
            })
    return flags


def check_clades_ncbi(rows):
    """
    CHECK 9 — Clade verification via NCBI taxonomy (free, no API key needed).

    Why: the model assigned clades using its training knowledge, which can be
    wrong for unusual or recently reclassified species. NCBI taxonomy is the
    authoritative source. We query each unique (species, clade) pair, derive
    the expected clade from the NCBI lineage string, and flag mismatches.

    Cell lines (HeLa, HEK293, etc.) are resolved to their source organism
    before querying — cell lines have no taxonomy entry of their own.
    Species not found in NCBI are flagged as unverifiable (not errors).

    Rate limit: 3 calls per species (search + fetch) with 0.35s sleep each
    = ~1s per species. With ~200 unique species: ~3 minutes.
    """
    try:
        from Bio import Entrez
        Entrez.email = NCBI_EMAIL
    except ImportError:
        return [{
            "check": "ncbi_clade", "pdf_filename": "SETUP",
            "species": "", "suggestion": "",
            "detail": "biopython not installed — run: pip install biopython --break-system-packages",
        }]

    flags = []
    seen = {}
    for r in rows:
        sp    = r.get("species", "").strip()
        clade = r.get("clade", "").strip()
        if sp and clade and (sp, clade) not in seen:
            seen[(sp, clade)] = r.get("pdf_filename", "")

    for (sp, our_clade), fname in seen.items():
        if our_clade.startswith("uncertain") or our_clade == "Unknown":
            continue

        query_sp = resolve_species(sp)
        lineage = None

        try:
            from Bio import Entrez
            handle = Entrez.esearch(db="taxonomy", term=f'"{query_sp}"[Scientific Name]')
            record = Entrez.read(handle); handle.close()
            time.sleep(0.35)

            if not record.get("IdList"):
                handle = Entrez.esearch(db="taxonomy", term=query_sp)
                record = Entrez.read(handle); handle.close()
                time.sleep(0.35)

            if record.get("IdList"):
                taxid = record["IdList"][0]
                handle = Entrez.efetch(db="taxonomy", id=taxid, rettype="xml")
                records = Entrez.read(handle); handle.close()
                time.sleep(0.35)
                if records:
                    lineage = records[0].get("Lineage", "")
        except Exception:
            pass

        if lineage is None:
            flags.append({
                "check": "ncbi_clade",
                "pdf_filename": fname,
                "species": sp,
                "detail": f"Not found in NCBI taxonomy — '{our_clade}' assigned by model, verify manually",
                "suggestion": "",
            })
        else:
            ncbi_result = ncbi_lineage_to_clade(lineage)
            if ncbi_result != our_clade:
                flags.append({
                    "check": "ncbi_clade",
                    "pdf_filename": fname,
                    "species": sp,
                    "detail": f"Clade mismatch: ours='{our_clade}' | NCBI lineage suggests '{ncbi_result}' (lineage: {lineage[:80]}...)",
                    "suggestion": ncbi_result,
                })

    return flags


# ── Report ──────────────────────────────────────────────────────────────────────

CHECK_TITLES = {
    "missing_fields":        "CHECK 1 — Missing critical fields",
    "invalid_clade":         "CHECK 2 — Invalid / out-of-vocabulary clade values",
    "non_canonical_variant": "CHECK 3 — Non-canonical ExM variant names",
    "duplicate":             "CHECK 4 — Potential duplicate papers",
    "species_name":          "CHECK 5 — Species name standardisation",
    "expansion_factor":      "CHECK 6 — Expansion factor out of expected range",
    "label_consistency":     "CHECK 7a — Secondary antibody without primary",
    "no_labels":             "CHECK 7b — Papers with no labels extracted",
    "crossref":              "CHECK 8 — Metadata mismatch vs CrossRef",
    "ncbi_clade":            "CHECK 9 — Clade mismatch vs NCBI taxonomy",
}


def write_report(all_flags, papers, rows, local_mode):
    by_check = defaultdict(list)
    for f in all_flags:
        by_check[f["check"]].append(f)

    with open(REPORT_FILE, "w", encoding="utf-8") as rpt:
        rpt.write("=" * 70 + "\n")
        rpt.write("ExM DATABASE — QC REPORT\n")
        rpt.write("=" * 70 + "\n\n")
        rpt.write(f"CSV: {CSV_FILE.name}\n")
        rpt.write(f"Rows: {len(rows)}   Papers: {len(papers)}\n")
        rpt.write(f"Network checks: {'SKIPPED (--local)' if local_mode else 'included'}\n")
        rpt.write(f"Total flags: {len(all_flags)}\n\n")

        rpt.write("SUMMARY\n" + "-" * 40 + "\n")
        for check, title in CHECK_TITLES.items():
            n = len(by_check.get(check, []))
            if local_mode and check in ("crossref", "ncbi_clade"):
                rpt.write(f"  {title[:45]:<45}  SKIPPED\n")
            else:
                rpt.write(f"  {title[:45]:<45}  {n:>4} flags\n")
        rpt.write("\n")

        for check, title in CHECK_TITLES.items():
            flags = by_check.get(check, [])
            if local_mode and check in ("crossref", "ncbi_clade"):
                continue
            rpt.write(f"\n{title}\n{'─' * 60}\n")
            if not flags:
                rpt.write("  ✓ No issues found\n")
                continue
            for f in flags:
                rpt.write(f"  {f.get('pdf_filename', '')}\n")
                rpt.write(f"    Issue:  {f.get('detail', '')}\n")
                if f.get("suggestion"):
                    rpt.write(f"    Fix:    {f.get('suggestion', '')}\n")
                if f.get("species"):
                    rpt.write(f"    Species: {f.get('species', '')}\n")


def write_flags_csv(all_flags):
    fields = ["check", "pdf_filename", "species", "detail", "suggestion"]
    with open(FLAGS_FILE, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows({k: flag.get(k, "") for k in fields} for flag in all_flags)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="QC pipeline for ExM database")
    parser.add_argument("--local", action="store_true",
                        help="Skip network checks (CrossRef + NCBI) — instant run")
    args = parser.parse_args()

    if not CSV_FILE.exists():
        print(f"ERROR: {CSV_FILE} not found"); sys.exit(1)

    print(f"Loading {CSV_FILE.name} ...")
    rows, _ = load_csv(CSV_FILE)
    papers  = papers_from_rows(rows)
    print(f"  {len(rows)} rows | {len(papers)} papers\n")

    all_flags = []

    steps = [
        ("Check 1: Missing critical fields",       lambda: check_missing_fields(papers)),
        ("Check 2: Invalid clade values",           lambda: check_invalid_clades(rows)),
        ("Check 3: Non-canonical ExM variants",     lambda: check_exm_variants(papers)),
        ("Check 4: Duplicate detection",            lambda: check_duplicates(papers)),
        ("Check 5: Species name standardisation",   lambda: check_species_names(rows)),
        ("Check 6: Expansion factor sanity",        lambda: check_expansion_factors(rows)),
        ("Check 7: Label consistency",              lambda: check_label_consistency(papers)),
    ]

    for label, fn in steps:
        print(label + " ...")
        all_flags += fn()

    if not args.local:
        print("Check 8: CrossRef metadata (~1s per paper — may take several minutes) ...")
        all_flags += check_metadata_crossref(papers)
        print("Check 9: NCBI taxonomy clade verification (~1s per unique species) ...")
        all_flags += check_clades_ncbi(rows)
    else:
        print("Checks 8 & 9: SKIPPED (--local flag)")

    print(f"\nTotal flags: {len(all_flags)}")
    write_report(all_flags, papers, rows, args.local)
    write_flags_csv(all_flags)
    print(f"Report: {REPORT_FILE}")
    print(f"Flags:  {FLAGS_FILE}")
    print("\nDone.")


if __name__ == "__main__":
    main()
