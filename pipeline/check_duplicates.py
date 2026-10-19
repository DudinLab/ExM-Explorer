#!/usr/bin/env python3
"""
check_duplicates.py  —  ExM Database duplicate paper resolver
Uses claude-sonnet-4-6 to evaluate potential duplicate paper pairs and
produces ExM_database_curated.csv with confirmed duplicates removed.

Run from the ExM_Library folder:
    cd C:\\Users\\dudin\\Desktop\\ExM_Library
    python check_duplicates.py

Requirements:
    pip install anthropic
    API key must be set:  $env:ANTHROPIC_API_KEY = "sk-..."  (PowerShell)
"""

import csv, json, os, re, time
from pathlib import Path

try:
    import anthropic
except ImportError:
    raise SystemExit("anthropic package not installed. Run: pip install anthropic")

# ── Paths ─────────────────────────────────────────────────────────────────────
DB          = Path("exm_database.csv")
OUT_DB      = Path("ExM_database_curated.csv")
DECISIONS   = Path("duplicate_decisions.json")   # resume-safe checkpoint
REPORT      = Path("duplicate_removal_report.txt")

# ── Config ────────────────────────────────────────────────────────────────────
MODEL       = "claude-sonnet-4-6"
MAX_TOKENS  = 300
SLEEP_SEC   = 0.4   # gentle rate-limiting between API calls

# ── Load DB ───────────────────────────────────────────────────────────────────
with open(DB, encoding="utf-8-sig", errors="replace") as f:
    reader = csv.DictReader(f)
    FIELDS = [k for k in reader.fieldnames if k]
    rows = [{k: (v or "").strip() for k, v in r.items() if k} for r in reader]

print(f"Loaded {len(rows)} rows from {DB}")

# ── Build per-paper metadata index ────────────────────────────────────────────
paper_meta = {}
for r in rows:
    fn = r.get("pdf_filename", "").strip()
    if fn and fn not in paper_meta:
        paper_meta[fn] = {
            "filename":     fn,
            "title":        r.get("title", ""),
            "doi":          r.get("doi", ""),
            "year":         r.get("year", ""),
            "journal":      r.get("journal", ""),
            "first_author": r.get("first_author", ""),
            "last_author":  r.get("last_author", ""),
        }

print(f"Unique papers in DB: {len(paper_meta)}")

# ── Extract unique pair set from possible_duplicate_of column ─────────────────
# possible_duplicate_of values can be: "A.pdf", "A.pdf | B.pdf", "n/a", blank
pairs: set[tuple[str, str]] = set()
for r in rows:
    dup_raw = (r.get("possible_duplicate_of", "") or "").strip()
    pdf = r.get("pdf_filename", "").strip()
    if not dup_raw or dup_raw in ("n/a", "null", "N/A", "unknown", ""):
        continue
    for d in re.split(r"\s*\|\s*", dup_raw):
        d = d.strip()
        if d and d != pdf:
            pairs.add(tuple(sorted([pdf, d])))

pairs_sorted = sorted(pairs)
print(f"Unique duplicate pairs to evaluate: {len(pairs_sorted)}")

# ── Sonnet prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a scientific literature curator for an expansion microscopy database.
Your task: determine whether two papers are duplicates (same scientific work published in
multiple venues, e.g. preprint + journal version).

Respond with ONLY a valid JSON object, no other text. Schema:
{
  "is_duplicate": true or false,
  "confidence": "high" | "medium" | "low",
  "keep": "<filename to keep>" or null,
  "remove": "<filename to remove>" or null,
  "reason": "<one short sentence>"
}

Decision rules (apply in order):
1. Same DOI → definitely duplicate, high confidence.
2. Same first+last author AND very similar/identical title AND year within ±1
   → duplicate, keep journal over preprint (bioRxiv/ResearchSquare/arXiv).
3. Both preprints, one clearly a version update of the other (e.g. v1/v2, "1"/"2" suffix)
   → duplicate, keep the later one.
4. Both published in different journals with similar topics but different titles
   → NOT duplicate (different papers by same group), is_duplicate=false.
5. Insufficient metadata to decide → is_duplicate=false, confidence=low.
When is_duplicate=false: set keep=null and remove=null.
"""

def paper_block(m: dict) -> str:
    return (
        f"  File: {m['filename']}\n"
        f"  Title: {m['title'] or '[not available]'}\n"
        f"  Authors: {m['first_author']} … {m['last_author']}\n"
        f"  Year: {m['year']}  |  Journal/Venue: {m['journal']}\n"
        f"  DOI: {m['doi'] or '[none]'}"
    )

def blank_meta(fn: str) -> dict:
    return {"filename": fn, "title": "", "doi": "", "year": "",
            "journal": "", "first_author": "", "last_author": ""}

# ── Load prior decisions (resumable) ─────────────────────────────────────────
decisions: dict = {}
if DECISIONS.exists():
    with open(DECISIONS, encoding="utf-8") as f:
        decisions = json.load(f)
    print(f"Resuming — {len(decisions)} pairs already decided, "
          f"{len(pairs_sorted)-len(decisions)} remaining")

# ── Evaluate pairs ────────────────────────────────────────────────────────────
client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from env

for a, b in pairs_sorted:
    key = f"{a}|||{b}"
    if key in decisions:
        continue

    a_meta = paper_meta.get(a, blank_meta(a))
    b_meta = paper_meta.get(b, blank_meta(b))

    user_msg = f"Paper A:\n{paper_block(a_meta)}\n\nPaper B:\n{paper_block(b_meta)}"

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()
        # strip markdown fences if model adds them
        raw = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        result = {"is_duplicate": None, "confidence": "error",
                  "reason": f"JSON parse error: {e}", "keep": None, "remove": None, "raw": raw}
    except Exception as e:
        result = {"is_duplicate": None, "confidence": "error",
                  "reason": str(e), "keep": None, "remove": None}

    decisions[key] = result

    is_dup   = result.get("is_duplicate")
    conf     = result.get("confidence", "?")
    reason   = result.get("reason", "")[:72]
    tag      = "DUP ✓" if is_dup else ("ERR" if is_dup is None else "     ")
    print(f"  [{conf:6s} {tag}] {a[:35]:<35} <-> {b[:35]:<35}  {reason}")

    # checkpoint after every pair
    with open(DECISIONS, "w", encoding="utf-8") as f:
        json.dump(decisions, f, indent=2)

    time.sleep(SLEEP_SEC)

print(f"\n✓ All {len(decisions)} pairs evaluated")

# ── Collate results ───────────────────────────────────────────────────────────
to_remove:        set[str] = set()
confirmed_pairs:  list[tuple] = []
uncertain_pairs:  list[tuple] = []
not_dup_pairs:    list[tuple] = []

for key, dec in decisions.items():
    a, b = key.split("|||")
    is_dup = dec.get("is_duplicate")
    conf   = dec.get("confidence", "error")
    reason = dec.get("reason", "")
    remove = dec.get("remove")

    if is_dup is True and conf in ("high", "medium") and remove:
        to_remove.add(remove)
        confirmed_pairs.append((a, b, remove, conf, reason))
    elif is_dup is True and conf == "low":
        uncertain_pairs.append((a, b, reason))
    elif is_dup is None or conf == "error":
        uncertain_pairs.append((a, b, reason))
    else:
        not_dup_pairs.append((a, b, reason))

# ── Print summary ─────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"CONFIRMED DUPLICATES  ({len(to_remove)} papers to remove):")
for a, b, rm, conf, reason in sorted(confirmed_pairs):
    print(f"  REMOVE [{conf}]: {rm}")
    print(f"    kept:   {a if rm == b else b}")
    print(f"    reason: {reason}")

print(f"\nUNCERTAIN ({len(uncertain_pairs)} pairs — human review needed):")
for a, b, reason in uncertain_pairs:
    print(f"  ? {a}  <->  {b}")
    print(f"    {reason}")

print(f"\nNOT DUPLICATES ({len(not_dup_pairs)} pairs — different papers, keep both):")
for a, b, reason in not_dup_pairs[:10]:   # cap output
    print(f"  ✗ {a[:45]}  <->  {b[:45]}")

# ── Write curated database ────────────────────────────────────────────────────
kept   = [r for r in rows if r.get("pdf_filename", "") not in to_remove]
n_removed_rows = len(rows) - len(kept)

with open(OUT_DB, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(kept)

print(f"\n{'='*70}")
print(f"ExM_database_curated.csv  →  {len(kept)} rows  "
      f"({n_removed_rows} rows removed from {len(to_remove)} duplicate papers)")

# ── Write human-readable report ───────────────────────────────────────────────
with open(REPORT, "w", encoding="utf-8") as f:
    f.write("ExM Database — Duplicate Removal Report\n")
    f.write("="*60 + "\n\n")
    f.write(f"Papers removed:  {len(to_remove)}\n")
    f.write(f"Rows removed:    {n_removed_rows}\n")
    f.write(f"Rows remaining:  {len(kept)}\n\n")

    f.write("REMOVED (confirmed duplicates):\n")
    for a, b, rm, conf, reason in sorted(confirmed_pairs):
        kept_fn = a if rm == b else b
        f.write(f"  REMOVE: {rm}\n")
        f.write(f"  KEEP:   {kept_fn}\n")
        f.write(f"  Conf:   {conf}  |  {reason}\n\n")

    if uncertain_pairs:
        f.write("\nUNCERTAIN (manual review needed):\n")
        for a, b, reason in uncertain_pairs:
            f.write(f"  {a}  <->  {b}\n  {reason}\n\n")

print(f"duplicate_removal_report.txt written")
print("\nDone.")
