#!/usr/bin/env python3
"""
normalise_species_resolution.py  —  FIRST-PASS species resolver (review only).

Resolves each raw `species` string in ExM_database_curated.csv to a canonical
biological species, so clade/coverage counts reflect real species rather than
cell lines, strains and tissue descriptions.

Does NOT modify the database. Writes:
  species_resolution_review.csv  (raw -> resolved, per row-string, with method/confidence)
  species_resolution_summary.csv (raw vs resolved distinct-species count per clade)

Rules: strip parentheticals; map known cell lines to source organism; drop
non-biological entries; take Genus+epithet; flag 'Genus sp.' and inferred ones.
Everything flagged 'review' needs a human eye (per project data-integrity rules).
"""
import csv, re
from collections import defaultdict
HERE_CSV="../data/ExM_database_curated.csv"
HS,MM,RN='Homo sapiens','Mus musculus','Rattus norvegicus'
CELLMAP={ # cell line / abbrev -> source organism
 'hela':HS,'hek293':HS,'u2os':HS,'u251':HS,'u87':HS,'a549':HS,'a375':HS,'a498':HS,'mcf':HS,'mda-mb':HS,
 'sh-sy5y':HS,'jurkat':HS,'huh7':HS,'hep3b':HS,'hl-60':HS,'hos':HS,'huvec':HS,'hff':HS,'htert':HS,'pc3':HS,
 'rcc4':HS,'sw480':HS,'lovo':HS,'caco':HS,'beas':HS,'bv173':HS,'chang':HS,'nk-92':HS,'cfbe':HS,'ges1':HS,
 'mm.1s':HS,'wm983':HS,'uci0':HS,'hpne':HS,'rpe1':HS,'nup':HS,'gbm#':HS,'h4':HS,'id98':HS,'mucilair':HS,
 'c2c12':MM,'neuro-2a':MM,'nih-3t3':MM,'raw264':MM,'min6':MM,'mpek':MM,'mtec':MM,'mesc':MM,
 'ins-1e':RN,'nrk49f':RN,
 'cos-7':'Chlorocebus aethiops','vero':'Chlorocebus aethiops','bs-c-1':'Chlorocebus aethiops',
 'cho':'Cricetulus griseus','bhk':'Mesocricetus auratus','mdck':'Canis lupus familiaris',
 'nlfk':'Felis catus','feline':'Felis catus','ptk2':'Potorous tridactylus','s2 cell':'Drosophila melanogaster',
 'u87mg':HS,'sa501':HS,'pdx':HS,'nup96':HS,'nup43':HS,'hgadfn':HS,'snap-clc':HS,'snap-cel':HS,
}
NONBIO=['in vitro','isolated protein','dna origami','liposome',' bead','synthetic','polyacrylamide','recombinant',
        'microtubule','buffer only','sars-cov','viral particle','virion','bacteriophage']
# curated overrides (verified via web search) that must beat the cell-line heuristics
SPECIAL={'neospora':'Neospora caninum'}
def resolve(raw):
    s=raw.strip(); low=s.lower()
    for nb in NONBIO:
        if nb in low: return ('',' excluded: non-biological','exclude')
    for k,v in SPECIAL.items():
        if k in low: return (v,'curated override','ok')
    # cell-line / abbreviation mapping. Long codes (>=4) match as a prefix at a token boundary
    # (so 'hek293' catches HEK293T); short codes match as a whole token (so 'cho' misses triCHOmonas).
    for k,v in CELLMAP.items():
        pat=(r'(?<![a-z0-9])'+re.escape(k)) if len(k)>=4 else (r'(?<![a-z0-9])'+re.escape(k)+r'(?![a-z0-9])')
        if re.search(pat, low):
            return (v,'cell line/abbrev -> source organism','infer')
    # strip parentheticals and bracketed annotations
    base=re.sub(r'\s*\([^)]*\)','',s)
    base=re.sub(r'\s*\[[^\]]*\]','',base).strip()
    if 'human' in base.lower(): return (HS,'contains "human" -> Homo sapiens','infer')
    toks=base.split()
    if not toks: return ('',' empty after strip','review')
    genus=toks[0]
    # Genus sp. / undescribed
    if len(toks)>=2 and re.match(r'^(sp\.?|cf\.?|aff\.?)',toks[1],re.I):
        return (genus+' sp.','genus-level / undescribed','review')
    if len(toks)==1:
        return (genus+' sp.','genus only','review')
    epi=toks[1].strip('.,')
    # epithet should be lowercase alphabetic-ish
    if re.match(r'^[a-z\-]+$',epi):
        return (genus+' '+epi,'binomial','ok')
    # otherwise genus-level
    return (genus+' sp.','non-standard epithet -> genus','review')

def main():
    rows=list(csv.DictReader(open(HERE_CSV,encoding='utf-8-sig')))
    g=lambda r,k:(r.get(k) or '').strip()
    seen={}  # raw -> (resolved,method,conf)
    raw_by_clade=defaultdict(set); res_by_clade=defaultdict(set)
    for r in rows:
        sp=g(r,'species'); cl=g(r,'clade') or 'Unknown'
        if not sp: continue
        if sp not in seen: seen[sp]=resolve(sp)
        res,method,conf=seen[sp]
        raw_by_clade[cl].add(sp)
        if res: res_by_clade[cl].add(res)
    # review CSV (one row per distinct raw string)
    with open('species_resolution_review.csv','w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f); w.writerow(['raw_species','resolved_species','genus','method','confidence'])
        for raw in sorted(seen):
            res,method,conf=seen[raw]
            w.writerow([raw,res,res.split()[0] if res else '',method,conf])
    # summary CSV
    clades=sorted(set(list(raw_by_clade)+list(res_by_clade)),key=lambda c:-len(raw_by_clade[c]))
    with open('species_resolution_summary.csv','w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f); w.writerow(['clade','raw_strings','resolved_species','shrinkage'])
        tr=ts=0
        for c in clades:
            rr=len(raw_by_clade[c]); rs=len(res_by_clade[c]); tr+=rr; ts+=rs
            w.writerow([c,rr,rs,rr-rs])
        w.writerow(['TOTAL',tr,ts,tr-ts])
    # console
    print('%-24s %8s %10s'%('clade','raw','resolved'))
    for c in clades:
        print('%-24s %8d %10d'%(c,len(raw_by_clade[c]),len(res_by_clade[c])))
    tot_raw=len(set().union(*raw_by_clade.values())); tot_res=len(set().union(*res_by_clade.values()))
    print('-'*46); print('%-24s %8d %10d  (distinct across all clades)'%('TOTAL',tot_raw,tot_res))
    nconf=defaultdict(int)
    for raw in seen: nconf[seen[raw][2]]+=1
    print('confidence of resolutions:',dict(nconf))
if __name__=='__main__': main()
