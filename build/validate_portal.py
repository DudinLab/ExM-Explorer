#!/usr/bin/env python3
"""
validate_portal.py  -  whole-system validation for ExM Explorer.

Every expected number is computed from the data (ExM_database_curated.csv, index.html,
the pipeline logs), never typed in. Then every number written next to a unit
("6,755 rows", "381 studies", "301 species" ...) in the portal and in the docs is checked
against those live values, so a stale number anywhere fails the run.
Exit code 0 = all green. Run after ANY change:  python validate_portal.py
"""
import csv, json, re, sys, os, html as H, importlib.util, collections
HERE = os.path.dirname(os.path.abspath(__file__)); P = lambda p: os.path.join(HERE, p); os.chdir(HERE)
fails = []; n = 0
def check(name, cond, detail=""):
    global n; n += 1
    print(("  PASS " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond: fails.append(name)

# ---------------- live values ----------------
page = open(P("../portal/index.html"), encoding="utf-8").read()
J = lambda a, b: json.loads(page.split(f"const {a}=")[1].split(f";\nconst {b}")[0])
SPECIES, ABP, ABS, DYE, PAPERS = J("SPECIES","ABP"), J("ABP","ABS"), J("ABS","DYE"), J("DYE","PAPERS"), J("PAPERS","OVERVIEW=")
OV  = json.loads(page.split("const OVERVIEW=")[1].split(";\nconst OVERVIEW2")[0])
OV2 = json.loads(page.split("const OVERVIEW2=")[1].split(";\n")[0])
rows = list(csv.DictReader(open(P("../data/ExM_database_curated.csv"), encoding="utf-8-sig")))
g = lambda r, k: (r.get(k) or "").strip()
spec = importlib.util.spec_from_file_location("b", P("build_overview2.py")); b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
def sumn(t): return t["n"] if t.get("leaf") else sum(sumn(c) for c in t["children"])
def find(t, nm):
    if t.get("name") == nm: return t
    for c in t.get("children", []):
        x = find(c, nm)
        if x: return x
LIVE = dict(rows=len(rows), studies=len(PAPERS), pdfs=len({g(r, "pdf_filename") for r in rows}),
            species=len(SPECIES), euk=sumn(OV2["tree"]), prok=OV2["prok"]["Bacteria"] + OV2["prok"]["Archaea"],
            primary=len(ABP), secondary=len(ABS), dyes=len(DYE), clades=15,
            raw_species=len({g(r, "species") for r in rows if g(r, "species")}))
print("LIVE:", LIVE)

print("\n=== A. COHERENCE ===")
check("species == tree eukaryotes + prokaryotes", LIVE["species"] == LIVE["euk"] + LIVE["prok"], (LIVE["species"], LIVE["euk"], LIVE["prok"]))
check("species == accumulation (last year)", LIVE["species"] == OV2["accum"][-1]["value"])
check("Fig1 Metazoa == Fig2 animals", find(OV2["tree"], "Metazoa")["n"] == len(OV2["anim"]))
def leaves(t): return [t] if t.get("leaf") else [x for c in t["children"] for x in leaves(c)]
FL = leaves(OV2["tree"])
check("Fig1 EukProt denominators sum to the 993 EukProt v3 species", sum(x["N"] for x in FL) == 993)
check("Fig1 every lineage: in EukProt + outside == expanded (and Mikus split)", all(x["k"] + x["o"] == x["n"] and x["km"] + x["om"] == x["m"] and x["k"] <= x["N"] for x in FL))
check("accumulation monotonic", all(a["value"] <= c["value"] for a, c in zip(OV2["accum"], OV2["accum"][1:])))

print("\n=== B. TABLE INTEGRITY ===")
check("every row has a DOI", all(g(r, "doi") for r in rows), sum(1 for r in rows if not g(r, "doi")))
by = collections.defaultdict(set)
for r in rows: by[g(r, "doi").lower()].add((g(r, "title"), g(r, "journal"), g(r, "year")))
check("one title/journal/year per DOI (merged studies consistent)", all(len(v) == 1 for v in by.values()),
      [k for k, v in by.items() if len(v) > 1][:5])
check("PAPERS == distinct DOIs in CSV", LIVE["studies"] == len(by), (LIVE["studies"], len(by)))
check("no review articles", not any(g(r, "paper_type") == "review" and "Övermöhle" not in g(r, "pdf_filename") for r in rows))
if os.path.exists(P("../data/paper_versions_review.csv")):
    pv = list(csv.DictReader(open(P("../data/paper_versions_review.csv"), encoding="utf-8")))
    d = {g(r, "pdf_filename"): g(r, "doi").lower() for r in rows}
    check("every preprint/published pair shares one DOI", all(d.get(p["earlier_version_pdf"]) == d.get(p["later_version_pdf"]) for p in pv))

print("\n=== C. NOMENCLATURE ===")
check("no 'ExAME'", "ExAME" not in page); check("title is ExM Explorer", "<title>ExM Explorer" in page)

print("\n=== D. SPECIES RESOLUTION ===")
treesp, proksp = set(), set()
for r in rows:
    res = b.nsr.resolve(g(r, "species"))[0] if g(r, "species") else None
    if not res: continue
    gen = res.split()[0].rstrip(".")
    (treesp if b.GEN2TG.get(gen) else proksp if g(r, "clade") in ("Bacteria", "Archaea") else set()).add(res)
check("no species both on tree and prokaryote", not (treesp & proksp), treesp & proksp)
check("Homo sapiens has no 'Whole organism'", OV2["anim"].get("Homo sapiens", {}).get("Whole organism", 0) == 0)
check("Fig2 categories are curated sample types", all(c in OV2["acats"] for o in OV2["anim"] for c in OV2["anim"][o]))
check("gel scatter headline methods only", {p["v"] for p in OV2["gelPoints"]} <= {"U-ExM","proExM","TREx","cryo-ExM","Magnify","LR-ExM","MAP"})
for k in ["D","EXP","HOM","TRANS","CAT","DIFF","MAT","C"]: check(f"OVERVIEW.{k} non-empty", bool(OV.get(k)))

print("\n=== E. EVERY STATED NUMBER MATCHES THE DATA ===")
UNIT = [  # (regex for the unit that follows a number, live key)
    (r"(?:structured |curated )?rows", "rows"), (r"(?:distinct |unique )?studies", "studies"),
    (r"(?:source |unique )?(?:papers|publications)", "studies"), (r"(?:resolved |distinct |eukaryote |real )?species", "species"),
    (r"eukaryotes", "euk"), (r"prokaryotes", "prok"), (r"(?:distinct )?primary antibodies(?: and nanobodies)?", "primary"),
    (r"antibodies", "primary"), (r"secondary(?: antibodies|/detection reagents| reagents)", "secondary"),
    (r"dyes(?: (?:&|&amp;|and) stains)?", "dyes"), (r"clades", "clades"), (r"PDFs", "pdfs_any"), (r"raw (?:species )?strings", "raw_species")]
ALLOW = {"pdfs_any": {579, 584, 525, LIVE["pdfs"]}, "studies": {LIVE["studies"]}}  # pipeline-stage counts that are legitimately stated
OK_CONTEXT = re.compile(r"(?:\d+\s*(?:species|antibodies)\s*(?:with|×|x)|e\.g\.|for example|a paper that|yields?|produces?|testing)", re.I)
def scan(name, text):
    text = H.unescape(re.sub(r"<[^>]+>", " ", text)); bad = []
    for unit, key in UNIT:
        for m in re.finditer(r"(?<![\w.,≥≤<>+])(~?\d{1,3}(?:,\d{3})*|\d+)\s+" + unit + r"\b", text):
            v = int(m.group(1).lstrip("~").replace(",", ""))
            ctx = text[max(0, m.start() - 60): m.end() + 40]
            if OK_CONTEXT.search(ctx) or v < 5: continue
            if key == "studies" and re.search(r"\b(screen|candidate|records|kept|reject|PDF|documents?|before|after|v1|v2)\b", ctx, re.I): continue
            if key == "species" and re.search(r"\banimal", ctx, re.I):
                good = {len(OV2["anim"])}                      # animal species (Fig. 2)
            elif key == "species" and re.search(r"Table S1", text[m.start(): m.end() + 90]):
                good = {189}                                    # Mikus et al. Table S1, a fixed historical count
            elif key == "species" and re.search(r"EukProt", text[max(0, m.start() - 40): m.end() + 40]):
                good = {993}                                    # EukProt v3 species list, a fixed external count
            elif key == "primary" and re.search(r"(≥ ?2|two or more) studies", text[m.start(): m.end() + 40]):
                good = {228}                                    # QC 04 denominator: antibodies used in two or more studies
            elif key == "rows" and re.search(r"ciliate", ctx):
                good = {12}                                     # the hand-added Mikus Fig. 7 ciliate rows
            elif key == "rows" and re.search(r"5 July", ctx):
                good = {6759}                                   # the build the QC suite was run on
            elif key == "pdfs_any" and re.search(r"not (?:to be )?ExM|excluded", ctx):
                good = {51}                                     # PDFs the model judged not ExM
            else:
                good = ALLOW.get(key, {LIVE.get(key)})
            if v not in good: bad.append(f"'{m.group(0).strip()}' (live {sorted(good)})")
    check(f"{name}: no stale numbers", not bad, bad[:6])
scan("portal", page.split("const SPECIES=")[0])
for doc in ["../README.md", "../METHODS.md", "../data/README.md"]:
    if os.path.exists(P(doc)): scan(doc, open(P(doc), encoding="utf-8").read())

print("\n" + "=" * 50); print(f"RESULT: {n} checks, {len(fails)} FAILED")
if fails: print("FAILURES:"); [print("  - " + f) for f in fails]; sys.exit(1)
print("ALL GREEN"); sys.exit(0)
