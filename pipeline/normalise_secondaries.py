#!/usr/bin/env python3
"""
Normalise secondary antibody label_target in ExM_database_curated.csv.

The label_target for secondary antibodies should always be the host IgG class
of the primary they bind, e.g. "rabbit IgG", "mouse IgG", "guinea pig IgG".
Currently many rows have a protein name there instead (model confusion), or
vague text like "secondary antibody (anti-rabbit)".

Strategy:
  1. Parse label_name (which almost always contains the full secondary name,
     e.g. "goat anti-rabbit Alexa Fluor 488") to extract:
       - target: the primary host species IgG  → label_target
       - host:   the secondary's own species   → label_host_species
  2. For rows where label_name doesn't help, try to parse the existing
     label_target.
  3. Flag rows where neither works as "uncertain: could not parse".

Usage:
    python normalise_secondaries.py           # dry run — prints changes
    python normalise_secondaries.py --apply   # write to CSV (auto-backup)
    python normalise_secondaries.py --report  # summary stats only
"""

import re, argparse, shutil
from pathlib import Path
import pandas as pd

DB = Path(__file__).parent / "ExM_database_curated.csv"

# ── Controlled vocabulary ─────────────────────────────────────────────────────
# Primary host species (what the secondary targets)
PRIMARY_HOSTS = [
    "guinea pig", "rabbit", "mouse", "rat", "chicken", "goat",
    "sheep", "donkey", "hamster", "human", "horse", "pig",
]

# Secondary producer species (goes in label_host_species)
SECONDARY_PRODUCERS = [
    "donkey", "goat", "sheep", "horse", "rabbit", "mouse",
]

IG_CLASS = {
    "chicken": "IgY",
    "default": "IgG",
}

# Typos / aliases to normalise before matching
ALIASES = {
    "guineapig":  "guinea pig",
    "guinea-pig": "guinea pig",
    "cavy":       "guinea pig",
    "chick":      "chicken",
}


def canonical_target(host: str) -> str:
    host = host.strip().lower()
    host = ALIASES.get(host, host)
    ig   = IG_CLASS.get(host, IG_CLASS["default"])
    return f"{host} {ig}"


# ── Regex helpers ─────────────────────────────────────────────────────────────
# Matches "anti-rabbit", "anti-mouse IgG", "anti guinea pig", etc.
_HOST_PAT = re.compile(
    r"anti[-\s]?(" + "|".join(PRIMARY_HOSTS) + r")",
    re.IGNORECASE,
)
# Matches "goat anti-rabbit", "donkey anti-mouse" — extracts both
_PROD_HOST_PAT = re.compile(
    r"(?P<prod>" + "|".join(SECONDARY_PRODUCERS) + r")\s+anti[-\s]?(?P<host>"
    + "|".join(PRIMARY_HOSTS) + r")",
    re.IGNORECASE,
)
# Matches bare host + IgG/IgY: "rabbit IgG", "chicken IgY", "mouse IgG (H+L)"
_BARE_PAT = re.compile(
    r"\b(" + "|".join(PRIMARY_HOSTS) + r")\s+Ig[GYMgym]",
    re.IGNORECASE,
)


def parse_secondary(label_name: str, label_target: str):
    """
    Returns (new_target, new_host_species) or (None, None) if unparseable.
    Tries label_name first, then label_target.
    """
    for text in [str(label_name), str(label_target)]:
        if not text or text.lower() in ("nan", "none", "not stated", ""):
            continue

        # 1. "goat anti-rabbit ..." pattern — extracts both producer and target
        m = _PROD_HOST_PAT.search(text)
        if m:
            return (canonical_target(m.group("host")),
                    m.group("prod").lower())

        # 2. "anti-rabbit" without explicit producer
        m = _HOST_PAT.search(text)
        if m:
            return (canonical_target(m.group(1)), None)

        # 3. "rabbit IgG" bare form
        m = _BARE_PAT.search(text)
        if m:
            return (canonical_target(m.group(1)), None)

    return (None, None)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply",  action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    df = pd.read_csv(DB, encoding="utf-8-sig", low_memory=False)
    df = df.map(lambda x: x.replace("\x00", "") if isinstance(x, str) else x)

    sec_mask = df["label_type"] == "secondary_antibody"
    sec      = df[sec_mask].copy()

    print(f"Secondary antibody rows: {len(sec)}")

    changed_target = 0
    changed_host   = 0
    unparseable    = []

    new_targets = df["label_target"].copy()
    new_hosts   = df["label_host_species"].copy()

    for idx, row in sec.iterrows():
        old_tgt  = str(row.get("label_target", ""))
        old_host = str(row.get("label_host_species", ""))
        lname    = str(row.get("label_name", ""))

        new_tgt, new_host = parse_secondary(lname, old_tgt)

        if new_tgt is None:
            unparseable.append((idx, lname, old_tgt))
            new_tgt = f"uncertain: {old_tgt}" if old_tgt not in ("nan","") else "uncertain: could not parse"

        if new_tgt != old_tgt:
            new_targets.at[idx] = new_tgt
            changed_target += 1

        if new_host and str(new_host).lower() != old_host.lower() and old_host.lower() in ("nan","","not stated"):
            new_hosts.at[idx] = new_host
            changed_host += 1

    if args.report:
        print(f"\nWould fix label_target:      {changed_target} rows")
        print(f"Would fill label_host_species: {changed_host} rows")
        print(f"Unparseable (would flag):      {len(unparseable)}")
        print("\nSample unparseable (first 20):")
        for idx, lname, tgt in unparseable[:20]:
            print(f"  name={lname!r:50s}  target={tgt!r}")
        return

    print(f"\nChanges: label_target={changed_target}, host_species filled={changed_host}, unparseable={len(unparseable)}")

    if not args.apply:
        print("\nDry run — no changes written. Run with --apply to save.")
        print("\nSample label_target changes (first 20):")
        count = 0
        for idx, row in sec.iterrows():
            old_tgt = str(row.get("label_target",""))
            nt = new_targets.at[idx]
            if nt != old_tgt:
                print(f"  {old_tgt!r:50s} → {nt!r}")
                count += 1
                if count >= 20: break
        return

    backup = DB.with_suffix(".pre_norm_sec.bak.csv")
    shutil.copy(DB, backup)
    print(f"Backup: {backup.name}")

    df["label_target"]      = new_targets
    df["label_host_species"] = new_hosts
    df.to_csv(DB, index=False, encoding="utf-8-sig")
    print(f"Saved {DB.name} — {changed_target} targets fixed, {changed_host} hosts filled")


if __name__ == "__main__":
    main()
