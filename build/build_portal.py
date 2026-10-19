#!/usr/bin/env python3
"""
build_portal.py  —  ExAME Portal build script (DudinLab / Dey Lab)
-------------------------------------------------------------------
Deterministic, model-free. Regenerates the interactive web resource
(index.html) from the curated database.

Inputs  : ExM_database_curated.csv   (the final ExM database, 43 fields)
          portal_template.html       (single-file app shell; /*DATA*/ marker +
                                       __BUILD_DATE__ version stamp)
Output  : index.html                 (self-contained, deployable to any static host)

Aggregates the one-row-per-(species x label x paper) table into five lookup
structures embedded verbatim as JavaScript constants:
  SPECIES  one record per species
  ABP      primary antibodies + nanobodies, grouped by label_name
  ABS      secondary / detection antibodies, grouped by label_name
  DYE      all non-antibody labels (dyes, stains, phalloidin, lectins, tags)
  PAPERS   one record per paper (DOI), with what each contributed

Reagent records (ABP/ABS/DYE) also carry protocol-compatibility tallies:
  hmg  { homogenization_method : [total_uses, successes] }   (Proteinase K / heat-SDS / other)
  vmg  { ExM_variant           : [total_uses, successes] }
so users can ask "which antibody actually worked under heat-SDS vs Proteinase K".

Standard library only.  Usage:  python build_portal.py
"""
import csv, json, os, datetime
from collections import OrderedDict, Counter

CSV_IN   = "../data/ExM_database_curated.csv"
TEMPLATE = "portal_template.html"
HTML_OUT = "../portal/index.html"
OVERVIEW_JSON = "overview_data.json"   # reviewed, precomputed landing-figure data (8 figures)

def g(r, k): return (r.get(k) or "").strip()

def vnorm(v):
    v = v.strip()
    return v.split(":", 1)[1].strip() if v.startswith("other:") else v

def homset(h):
    """Normalise homogenization_method into canonical, filterable buckets."""
    h = h.strip().lower()
    if h == "both": return ["Proteinase K", "heat-SDS"]
    if "proteinase" in h: return ["Proteinase K"]
    if "sds" in h or "heat" in h: return ["heat-SDS"]
    if h: return ["other"]
    return []

def most_common(vals):
    vals = [v for v in vals if v]
    return Counter(vals).most_common(1)[0][0] if vals else ""

def build_species(rows):
    import build_overview2 as _ov2
    resolve = _ov2.nsr.resolve
    species = OrderedDict()
    for r in rows:
        raw = g(r, "species")
        if not raw:
            continue
        rres, meth, _ = resolve(raw)
        if rres: key = rres                                   # resolved species (HeLa, HEK293... -> Homo sapiens)
        elif "exclud" in meth: continue                       # DNA origami, isolated proteins, viruses: not a species
        else: key = raw                                       # genuinely unresolved -> keep raw
        s = species.setdefault(key, {
            "sp": key, "clades": Counter(), "raws": set(),
            "variants": set(), "samples": set(),
            "papers": OrderedDict(), "protocols": [], "labels": [],
            "pout": {"success": 0, "partial": 0, "fail": 0}})
        s["raws"].add(raw)
        s["clades"][g(r, "clade") or "Unknown"] += 1
        v = vnorm(g(r, "exm_variant"))
        if v: s["variants"].add(v)
        st = g(r, "sample_type")
        if st: s["samples"].add(st)
        po = g(r, "protocol_outcome")
        if po in s["pout"]: s["pout"][po] += 1
        doi = g(r, "doi"); key = doi or (g(r, "journal") + g(r, "year"))
        if key and key not in s["papers"]:
            s["papers"][key] = {"jr": g(r, "journal"), "yr": g(r, "year"), "doi": doi,
                                "fa": g(r, "first_author"), "ti": g(r, "title")}
        ln = g(r, "label_name")
        if ln:
            s["labels"].append({
                "target": g(r, "label_target"), "name": ln, "type": g(r, "label_type"),
                "host": g(r, "label_host_species"), "sup": g(r, "label_supplier"),
                "cat": g(r, "label_catalogue_number"), "dil": g(r, "label_dilution"),
                "fl": g(r, "label_fluorophore"), "tm": g(r, "label_application_timing"),
                "out": g(r, "label_outcome"), "cat_g": g(r, "label_category"), "variant": v})
        s["protocols"].append({
            "variant": v, "sample": st, "fix": g(r, "fixation_reagent"),
            "fixc": g(r, "fixation_concentration"), "fixd": g(r, "fixation_duration"),
            "anch": g(r, "anchoring_reagent"), "sa": g(r, "gel_sodium_acrylate_pct"),
            "aa": g(r, "gel_acrylamide_pct"), "bis": g(r, "gel_bis_pct"),
            "homog": g(r, "homogenization_method"), "efn": g(r, "expansion_factor_nominal"),
            "efm": g(r, "expansion_factor_measured"), "lab": g(r, "labelling_strategy"),
            "out": po, "_pk": key})
    out = []
    for sp, s in species.items():
        # One protocol record per distinct reported recipe (every field shown on the card), with the
        # papers that reported exactly that recipe ("pp": indices into the species' paper list).
        pkeys = list(s["papers"].keys())
        seen = OrderedDict()
        for p in s["protocols"]:
            pk_ = p.pop("_pk")
            sig = tuple(p[k] for k in ("variant", "sample", "fix", "fixc", "fixd", "anch", "sa", "aa", "bis",
                                       "homog", "efn", "efm", "lab", "out"))
            q = seen.setdefault(sig, dict(p, pp=[]))
            if pk_ in s["papers"] and pkeys.index(pk_) not in q["pp"]:
                q["pp"].append(pkeys.index(pk_))
        protos = sorted(seen.values(), key=lambda q: -len(q["pp"]))   # stable: most widely used recipe first
        seenl = set(); labs = []
        for l in s["labels"]:
            sig = (l["name"], l["target"], l["cat"])
            if sig in seenl: continue
            seenl.add(sig); labs.append(l)
        res = ("success" if s["pout"]["success"] else "partial" if s["pout"]["partial"]
               else "fail" if s["pout"]["fail"] else "")
        out.append({
            "sp": sp, "clade": s["clades"].most_common(1)[0][0], "var": sorted(s["variants"]),
            "smp": sorted(s["samples"]), "res": res, "pout": s["pout"],
            "np": len(s["papers"]), "nl": len(labs),
            "nraw": len(s["raws"]), "raw": sorted(s["raws"]),
            "papers": list(s["papers"].values()), "protos": protos, "labels": labs})
    out.sort(key=lambda x: (-(x["np"] * 10 + x["nl"]), x["sp"]))
    return out

def aggregate(subset, keep_target):
    groups = OrderedDict()
    for r in subset:
        name = g(r, "label_name")
        if not name:
            continue
        grp = groups.setdefault(name, {"rows": [], "species": OrderedDict(),
            "clades": OrderedDict(), "papers": OrderedDict(), "outcomes": set(),
            "hmg": OrderedDict(), "vmg": OrderedDict()})
        grp["rows"].append(r)
        if g(r, "species"): grp["species"][g(r, "species")] = 1
        if g(r, "clade"):   grp["clades"][g(r, "clade")] = 1
        doi = g(r, "doi"); pk = doi or (g(r, "journal") + g(r, "year"))
        if pk and pk not in grp["papers"]:
            grp["papers"][pk] = {"jr": g(r, "journal"), "yr": g(r, "year"), "doi": doi}
        succ = 1 if g(r, "label_outcome") == "success" else 0
        if g(r, "label_outcome"): grp["outcomes"].add(g(r, "label_outcome"))
        for m in homset(g(r, "homogenization_method")):
            t = grp["hmg"].setdefault(m, [0, 0]); t[0] += 1; t[1] += succ
        v = vnorm(g(r, "exm_variant"))
        if v:
            t = grp["vmg"].setdefault(v, [0, 0]); t[0] += 1; t[1] += succ
    out = []
    for name, grp in groups.items():
        rws = grp["rows"]
        d = {"name": name, "type": most_common([g(r, "label_type") for r in rws]),
             "host": most_common([g(r, "label_host_species") for r in rws]),
             "sup": most_common([g(r, "label_supplier") for r in rws]),
             "cat": most_common([g(r, "label_catalogue_number") for r in rws]),
             "fl": most_common([g(r, "label_fluorophore") for r in rws]),
             "cat_g": most_common([g(r, "label_category") for r in rws]),
             "sppl": "; ".join(grp["species"]), "cll": "; ".join(grp["clades"]),
             "n": len(grp["species"]), "papers": list(grp["papers"].values()),
             "out": "; ".join(sorted(grp["outcomes"])),
             "hmg": dict(grp["hmg"]), "vmg": dict(grp["vmg"])}
        if keep_target:
            d["target"] = most_common([g(r, "label_target") for r in rws])
            # every target / category the antibody was reported with (used by the Overview figure clicks)
            d["tgts"] = sorted({g(r, "label_target") for r in rws if g(r, "label_target")})
            d["cgs"] = sorted({(g(r, "label_category") or "other").replace("_", " ") for r in rws})
        out.append(d)
    out.sort(key=lambda x: -x["n"])
    return out

def build_papers(rows):
    def key(r): return g(r, "doi") or (g(r, "journal") + g(r, "year") + g(r, "first_author"))
    P = OrderedDict()
    for r in rows:
        k = key(r)
        if not k:
            continue
        p = P.setdefault(k, {"id": k, "doi": g(r, "doi"), "title": g(r, "title"),
            "fa": g(r, "first_author"), "la": g(r, "last_author"),
            "jr": g(r, "journal"), "yr": g(r, "year"),
            "variants": OrderedDict(), "ptypes": [], "newp": False,
            "species": OrderedDict(), "clades": OrderedDict(), "labels": OrderedDict(),
            "pout": {"success": 0, "partial": 0, "fail": 0}})
        v = vnorm(g(r, "exm_variant"))
        if v: p["variants"][v] = 1
        pt = g(r, "paper_type")
        if pt: p["ptypes"].append(pt)
        if g(r, "new_protocol").lower() == "true": p["newp"] = True
        sp = g(r, "species"); cl = g(r, "clade") or "Unknown"
        if sp and sp not in p["species"]: p["species"][sp] = cl
        if sp: p["clades"][cl] = 1
        po = g(r, "protocol_outcome")
        if po in p["pout"]: p["pout"][po] += 1
        ln = g(r, "label_name")
        if ln and ln not in p["labels"]:
            p["labels"][ln] = {"name": ln, "target": g(r, "label_target"), "type": g(r, "label_type")}
    out = []
    for k, p in P.items():
        species = [{"sp": sp, "clade": cl} for sp, cl in p["species"].items()]
        out.append({"id": p["id"], "doi": p["doi"], "title": p["title"], "fa": p["fa"], "la": p["la"],
            "jr": p["jr"], "yr": p["yr"], "variants": list(p["variants"].keys()),
            "ptype": most_common(p["ptypes"]), "newp": p["newp"],
            "species": species, "clades": list(p["clades"].keys()),
            "nsp": len(species), "nlab": len(p["labels"]), "labels": list(p["labels"].values()),
            "pout": p["pout"]})
    out.sort(key=lambda x: (-(x["nsp"] * 100 + x["nlab"]), x["fa"]))
    return out

# ---- Release metadata: the only place to edit when the GitHub repo and Zenodo DOI exist ----
RELEASE = {"authors": "Mikus F, Llanos Fuentes PL, Juárez Núñez KA, Beltrame D, Dey G, Dudin O", "version": "1.0", "date": "2026-10-21", "date_long": "21 October 2026",
           "repo_url": "https://github.com/DudinLab/ExM-Explorer",
           "data_doi": "10.5281/zenodo.23439354"}      # Zenodo DOI of the v1.0 deposit, e.g. "10.5281/zenodo.xxxxxxx"

def main():
    rows = list(csv.DictReader(open(CSV_IN, encoding="utf-8-sig")))
    SPECIES = build_species(rows)
    ABP = aggregate([r for r in rows if g(r, "label_type") in ("primary_antibody", "nanobody")], True)
    ABS = aggregate([r for r in rows if g(r, "label_type") == "secondary_antibody"], False)
    DYE = aggregate([r for r in rows if g(r, "label_type") in
                     ("dye", "phalloidin", "lectin", "tag", "other", "")], True)
    PAPERS = build_papers(rows)

    import build_overview2
    OVERVIEW = build_overview2.build_infographic()   # Infographic figures, computed live (was a static JSON of 19 Sep 2026)
    OVERVIEW2 = build_overview2.build()   # Fig 1 (EukProt tree) + Fig 2 (animals), computed from current CSV

    # UniEuk taxonomy overlay for SEARCH ONLY (from the Fig 1 genus map; the clade field is left untouched).
    _path = {}
    def _walk(n, anc):
        p = anc + [n["name"]]
        if n.get("leaf"): _path[n["name"]] = p
        else:
            for c in n["children"]: _walk(c, p)
    _walk(OVERVIEW2["tree"], [])
    def _lineage(spname):
        res, _, _ = build_overview2.nsr.resolve(spname)
        if not res: return ""
        tg = build_overview2.GEN2TG.get(res.split()[0].rstrip("."))
        return " > ".join(_path[tg]) if tg in _path else ""
    for s in SPECIES:
        s["lin"] = _lineage(s["sp"])
    # Publications search: each study also matches its species (raw entries, resolved organism, clade, lineage)
    for p in PAPERS:
        terms = []
        for x in p.get("species", []):
            raw = x["sp"]; res = build_overview2.nsr.resolve(raw)[0] or ""
            terms += [raw, res, x.get("clade", ""), _lineage(res) if res else ""]
        p["stx"] = " ".join(t for t in dict.fromkeys(terms) if t)

    tpl = open(TEMPLATE, encoding="utf-8").read()
    assert "/*DATA*/" in tpl, "template marker /*DATA*/ not found"
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    data = "const SPECIES=%s;\nconst ABP=%s;\nconst ABS=%s;\nconst DYE=%s;\nconst PAPERS=%s;\nconst OVERVIEW=%s;\nconst OVERVIEW2=%s;" % (
        j(SPECIES), j(ABP), j(ABS), j(DYE), j(PAPERS), j(OVERVIEW), j(OVERVIEW2))
    html = tpl.replace("/*DATA*/", data)
    html = html.replace("__BUILD_DATE__", RELEASE["date"])
    for k, v in (("__VERSION__", RELEASE["version"]), ("__RELEASE_DATE_LONG__", RELEASE["date_long"]),
                 ("__REPO_URL__", RELEASE["repo_url"]), ("__AUTHORS__", RELEASE["authors"]), ("__DATA_DOI__", RELEASE["data_doi"])):
        html = html.replace(k, v)
    LIVE = {"{{ROWS}}": len(rows), "{{STUDIES}}": len(PAPERS), "{{SPECIES}}": len(SPECIES), "{{PRIMARY}}": len(ABP),
            "{{SECONDARY}}": len(ABS), "{{DYES}}": len(DYE), "{{ANIMALS}}": len(OVERVIEW2["anim"])}
    for k, v in LIVE.items(): html = html.replace(k, "{:,}".format(v))
    assert "{{" not in html.split("const SPECIES=")[0], "unfilled placeholder in template"
    assert html.count("</script>") == 1 and html.count("</html>") == 1
    open(HTML_OUT, "w", encoding="utf-8").write(html)
    print("Wrote %s  (%.2f MB)  version %s (%s)" % (
        HTML_OUT, os.path.getsize(HTML_OUT) / 1024 / 1024, RELEASE["version"], RELEASE["date"]))
    print("  species=%d  primary_ab=%d  secondary_ab=%d  dyes=%d  papers=%d  overview_figs=%d" %
          (len(SPECIES), len(ABP), len(ABS), len(DYE), len(PAPERS), len(OVERVIEW)))

if __name__ == "__main__":
    main()
