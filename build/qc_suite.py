#!/usr/bin/env python3
"""
qc_suite.py  -  quality controls 01, 02, 04, 05, 06 and 08 for ExM Explorer, recomputed from the database.
(QC 03 and QC 07 have their own scripts: QC/03_test_retest_v1_v2/compare_v1_v2.py and
QC/07_ncbi_clade_concordance/run_ncbi_check.py.)

Deterministic, standard library only. Writes one CSV per control into QC/<control>/ and prints the headline numbers.
Usage:  python qc_suite.py [path/to/ExM_database_curated.csv] [QC output dir]
"""
import csv, re, sys, os, collections
DB  = sys.argv[1] if len(sys.argv) > 1 else "ExM_database_curated.csv"
OUT = sys.argv[2] if len(sys.argv) > 2 else "QC"
rows = list(csv.DictReader(open(DB, encoding="utf-8-sig")))
g = lambda r, k: (r.get(k) or "").strip()
NULLS = {"", "null", "none", "n/a", "na", "not stated", "not reported", "unknown", "not specified"}
filled = lambda v: v.strip().lower() not in NULLS
def write(sub, header, data):
    if not OUT: return
    os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    with open(os.path.join(OUT, sub, data[0]), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh); w.writerow(header); w.writerows(data[1])
H = {}

# ---- QC 01 field completeness ----
CORE = ["pdf_filename", "doi", "year", "journal", "exm_variant", "species", "clade", "sample_type",
        "label_type", "label_name", "protocol_outcome"]
fc = [(k, sum(1 for r in rows if filled(r.get(k) or "")), round(100 * sum(1 for r in rows if filled(r.get(k) or "")) / len(rows), 1),
       "core" if k in CORE else "detail") for k in rows[0]]
fc.sort(key=lambda x: -x[2])
write("01_field_completeness", ["field", "rows_filled", "pct_filled", "group"], ("field_completeness.csv", fc))
H["01 min core field %"] = min(x[2] for x in fc if x[3] == "core")

# ---- primary antibodies (as in the portal: primary_antibody + nanobody) ----
P = [r for r in rows if g(r, "label_type") in ("primary_antibody", "nanobody")]
byab = collections.defaultdict(list)
for r in P:
    if g(r, "label_name"): byab[g(r, "label_name")].append(r)
H["primary antibodies"] = len(byab)

# ---- QC 02 identifier tiers (first matching tier wins) ----
CLONE = re.compile(r"\b(?=[A-Za-z0-9\-]*\d)(?=[A-Za-z0-9\-]*[A-Za-z])[A-Za-z0-9][A-Za-z0-9\-]{1,14}\b")
GENERIC = re.compile(r"^(anti[- ]?)?[a-z\-α-ω ]+$", re.I)
def tier(name, rs):
    if any(filled(g(r, "label_catalogue_number")) for r in rs): return "catalogue #"
    if CLONE.search(name) and not GENERIC.match(name): return "clone / product code"
    sup = [g(r, "label_supplier").lower() for r in rs]
    if any(s.startswith("gift") for s in sup): return "named gift lab"
    if any(filled(s) for s in sup): return "supplier / in-house"
    return "anonymous"
tc = collections.Counter(tier(n, rs) for n, rs in byab.items())
order = ["catalogue #", "clone / product code", "named gift lab", "supplier / in-house", "anonymous"]
write("02_reagent_identifier_completeness", ["identifier_tier", "n_antibodies", "pct"],
      ("identifier_tiers.csv", [(t, tc[t], round(100 * tc[t] / len(byab), 1)) for t in order]))
H["02 identifiable %"] = round(100 * (len(byab) - tc["anonymous"]) / len(byab), 1); H["02 tiers"] = dict(tc)

# ---- QC 04 cross-paper corroboration ----
multi = {n: rs for n, rs in byab.items() if len({g(r, "doi").lower() for r in rs}) >= 2}
cons = sum(1 for rs in multi.values() if len({g(r, "label_target").lower() for r in rs if g(r, "label_target")}) <= 1)
sp = collections.defaultdict(set)
for r in rows:
    if g(r, "species"): sp[g(r, "species")].add(g(r, "clade"))
spc = sum(1 for v in sp.values() if len(v) == 1)
write("04_cross_paper_corroboration", ["check", "n_multi_paper", "n_consistent", "pct"],
      ("corroboration.csv", [("primary antibody target (reagents in >=2 papers)", len(multi), cons, round(100 * cons / len(multi), 1)),
                             ("species -> clade (all species)", len(sp), spc, round(100 * spc / len(sp), 1))]))
H["04 antibody target"] = f"{cons}/{len(multi)} = {100*cons/len(multi):.1f}%"; H["04 species->clade"] = f"{spc}/{len(sp)}"

# ---- QC 05 controlled vocabulary ----
CLADES = {"Alveolata", "Viridiplantae", "Stramenopiles", "Haptophyta", "Cryptista", "Unicellular Holozoa", "Discoba",
          "Rhodophyta", "Fungi", "Rhizaria", "Glaucophyta", "Amoebozoa", "Metazoa", "Archaea", "Bacteria", "Unknown"}
VAR = {"U-ExM", "proExM", "ExPath", "ExFISH", "TREx", "Magnify", "cryo-ExM", "MAP", "iterative-ExM"}
cin = sum(1 for r in rows if g(r, "clade") in CLADES); unk = sum(1 for r in rows if g(r, "clade") == "Unknown")
vcan = sum(1 for r in rows if g(r, "exm_variant") in VAR); voth = sum(1 for r in rows if g(r, "exm_variant").startswith("other:"))
oin = sum(1 for r in rows if g(r, "protocol_outcome") in ("success", "partial", "fail", ""))
write("05_controlled_vocabulary", ["field", "in_controlled_vocab_pct", "note"], ("vocab_conformance.csv", [
    ("clade", round(100 * cin / len(rows), 1), f"{unk} rows = Unknown ({100*unk/len(rows):.1f}%)"),
    ("exm_variant (canonical)", round(100 * vcan / len(rows), 1), f'{voth} rows = novel "other:" protocols ({100*voth/len(rows):.1f}%); well-formed {100*(vcan+voth)/len(rows):.1f}%'),
    ("protocol_outcome", round(100 * oin / len(rows), 1), "success/partial/fail/null only")]))
H["05 clade in-vocab %"] = round(100 * cin / len(rows), 1); H["05 Unknown rows"] = unk
H["05 variant canonical/other %"] = (round(100 * vcan / len(rows), 1), round(100 * voth / len(rows), 1)); H["05 outcome %"] = round(100 * oin / len(rows), 1)

# ---- QC 06 catalogue-number syntax ----
FAM = [("Abcam ab####", r"^ab\d+"), ("Santa Cruz sc-####", r"^sc-\d+"), ("Proteintech ####-#-ig/ap", r"^\d{4,6}-\d-(ig|ap)"),
       ("Thermo/Invitrogen PA/MA/A#", r"^(pa\d?|ma\d?|a)-?\d"), ("CST ####/####s", r"^\d{3,5}s?$"),
       ("Sigma letter+digits", r"^[a-z]{1,2}\d{3,5}$"), ("DSHB/clone code", r"^[a-z0-9]{1,6}([-.][a-z0-9]+)*$")]
cats = {g(r, "label_catalogue_number") for r in rows if g(r, "label_type") in ("primary_antibody", "nanobody", "secondary_antibody")
        and filled(g(r, "label_catalogue_number"))}
def fam(c):
    c = c.lower().replace(" ", "").replace("#", "").replace("cat.", "").replace("cat", "")
    for name, rx in FAM:
        if re.match(rx, c): return name
    return "other plausible code" if re.match(r"^[a-z0-9][a-z0-9\-./_]{2,30}$", c) and re.search(r"\d", c) else "unrecognized"
fcnt = collections.Counter(fam(c) for c in cats)
write("06_catalogue_format_validity", ["format_class", "n_distinct_catalogue_numbers"], ("catalogue_format.csv", fcnt.most_common()))
H["06 catalogue numbers"] = len(cats); H["06 well-formed %"] = round(100 * (len(cats) - fcnt["unrecognized"]) / len(cats), 1)

# ---- QC 08 abstention ----
unc = sum(1 for r in rows for v in r.values() if (v or "").strip().lower().startswith("uncertain:"))
inf = sum(1 for r in rows for v in r.values() if (v or "").strip().lower().startswith("inferred:"))
nr = [(f"null rate: {k}", f"{100*sum(1 for r in rows if not filled(r.get(k) or ''))/len(rows):.1f}%") for k in
      ["fixation_temperature", "anchoring_duration", "gel_bis_pct", "expansion_factor_measured", "label_dilution", "label_catalogue_number"]]
write("08_honest_abstention", ["metric", "value"], ("abstention.csv", [("uncertain: flagged cells", unc), ("inferred: flagged cells", inf)] + nr))
H["08 uncertain/inferred"] = (unc, inf)

print(f"{DB}: {len(rows)} rows")
for k, v in H.items(): print(f"  {k}: {v}")
