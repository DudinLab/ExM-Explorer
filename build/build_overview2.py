#!/usr/bin/env python3
"""Build overview2.json for the portal: EukProt/UniEuk species tree (Fig 1) + animals-by-sample-type (Fig 2).
Reads the curated CSV (now including the Mikus environmental ciliates). No per-species lists (Fig 1 has no panel in the portal)."""
import csv,re,json,importlib.util
from collections import defaultdict
spec=importlib.util.spec_from_file_location("nsr","normalise_species_resolution.py")
nsr=importlib.util.module_from_spec(spec); spec.loader.exec_module(nsr)
g=lambda r,k:(r.get(k) or '').strip()
rows=list(csv.DictReader(open('../data/ExM_database_curated.csv',encoding='utf-8-sig')))

TG={
 'Metazoa':['Homo','Human','Mus','Rattus','Danio','Danionella','Xenopus','Gallus','Bos','Sus','Canis','Felis','Macaca','Callithrix','Mesocricetus','Cricetulus','Chlorocebus','Drosophila','Anopheles','Apis','Plodia','Caenorhabditis','Ascaris','Schmidtea','Astyanax','Lampetra','Pleurodeles','Potorous','HGADFN167','PDX-HCI-002','SA501','SNAP-CLC-YFP','Primary'],
 'Ichthyosporea':['Amoebidium','Chromosphaera','Creolimax','Sphaeroforma'],'Pluriformea':['Corallochytrium'],
 'Ascomycota':['Aspergillus','Candida','Fusarium','Nakaseomyces','Saccharomyces','Schizosaccharomyces'],'Basidiomycota':['Cryptococcus','Ustilago'],'Chytridiomycota':['Rhizoclosmatium'],
 'Tubulinea':['Amoeba'],'Discosea':['Acanthamoeba'],'Evosea':['Dictyostelium','Incendiamoeba'],
 'Chlorophyta':['Ankistrodesmus','Chlamydomonas','Chlorella','Chloroparvula','Chloropicon','Crucigenia','Desmodesmus','Dunaliella','Ettlia','Haematococcus','Hazenia','Mamiella','Mantoniella','Micractinium','Microglena','Nephrocytium','Nephroselmis','Oltmannsiellopsis','Pandorina','Pediastrum','Prasinococcus','Pterosperma','Pyramimonas','Pyramimosas','Scenedesmus','Tetradesmus','Tetraselmis','Volvox'],
 'Streptophyta':['Arabidopsis','Closterium','Cosmarium','Hordeum','Nicotiana','Spinacia','Spirogyra','Zea'],'Rhodophyta':['Neorhodella','Porphyridium'],'Glaucophyta':['Cyanophora'],
 'Diatomea':['Chaetoceros','Conticribra','Coscinodiscus','Cylindrotheca','Cymatosiraceae','Epithemia','Minidiscus','Odontella','Opephora','Phaeodactylum','Pleurosigma','Rhizosolenia','Shionodiscus','Thalassiosira'],
 'Raphidophyceae':['Chattonella','Fibrocapsa','Haramonas','Heterosigma','Olisthodiscus'],
 'other Ochrophyta':['Ankylochrysis','Nematochrysis','Polypodochrysis','Andersenia','Melkoniania','Aureoumbra','Pelagococcus','Pelagomonadales','Florenciella','Pseudochattonella','Xanthonema','Schizocladia'],'Labyrinthulomycetes':['Aurantochytrium'],
 'Dinoflagellata':['Alexandrium','Amphidinium','Ansanella','Azadinium','Biecheleriopsis','Brandtodinium','Coolia','Dinophyceae','Fukuyoa','Glenodinium','Gymnodinium','Heterocapsa','Karenia','Karlodinium','Lingulodinium','Margalefidinium','Ostreopsis','Oxyrrhis','Pelagodinium','Pentapharsodinium','Prorocentrum','Protoceratium','Protodinium','Pyrocystis','Suessiales','Symbiodinium','Takayama','Thoracosphaera','Palmerina'],
 'Apicomplexa':['Babesia','Cryptosporidium','Lecudina','Neospora','Plasmodium','Sarcocystis','Toxoplasma'],'Colpodellida':['Chromera','Vitrella'],
 'Ciliophora':['Paramecium','Podophrya','Tetrahymena','Euplotes','Lacrymaria','Vorticella','Pseudourostyla'],
 'Cercozoa':['Gymnochlora','Discocelia'],
 'Prymnesiophyceae':['Calcidiscus','Ceratolithus','Chrysochromulina','Chrysotila','Coccolithus','Dicrateria','Emiliania','Exanthemachrysis','Helicosphaera','Isochrysis','Oolithotus','Phaeocystis','Prymnesium','Rebecca','Ruttnera','Tisochrysis','Umbilicosphaera'],'Pavlovophyceae':['Diacronema','Pavlomulina','Pavlova'],
 'Cryptophyceae':['Chroomonas','Cryptomonas','Cryptophyceae','Goniomonas','Plagioselmis','Proteomonas','Rhinomonas','Rhodomonas','Urgorri'],
 'Euglenida':['Colacium','Euglena','Eutreptiella'],'Kinetoplastea':['Leishmania','Trypanosoma'],'Fornicata':['Giardia'],'Preaxostyla':['Paratrimastix'],'Parabasalia':['Trichomonas','Tritrichomonas']}
TG['Dinoflagellata'].append('Ross'); TG['Chlorophyta'].append('Dolischomastix'); TG['other Ochrophyta'].append('Guanchochroma'); TG['Prymnesiophyceae'].append('Scyphosphaera')
EXCL=set(['Acetobacter','Acidaminococcus','Bacillus','Bacteroides','Bifidobacterium','Citrobacter','Clostridium','Enterococcus','Escherichia','Fusobacterium','Lactobacillus','Limosilactobacillus','Mycobacterium','Nanosynbacter','Neisseria','Parabacteroides','Pseudomonas','Salmonella','Schaalia','Serratia','Simkania','Staphylococcus','Streptococcus','Herpes','Vesicular','SARS-CoV-2','Candidatus'])
GEN2TG={ge:tg for tg,gs in TG.items() for ge in gs}

# ---- Figure 1 denominator: EukProt v3 (Richter et al. 2022), species assigned to lineages by their UniEuk taxonomy ----
EUKPROT='../data/EukProt_included_data_sets.v03.2021_11_22.txt'
EUKPROT_MD5='f8599a2db3c95ff322e7dd9cb50fbde7'
TREE=('Eukaryota',[
 ('Amorphea',[
   ('Obazoa',[
     ('Opisthokonta',[
       ('Holozoa',['Metazoa','Choanoflagellata','Filasterea','Ichthyosporea','Pluriformea']),
       ('Holomycota (Fungi)',['Ascomycota','Basidiomycota','Chytridiomycota','Mucoromycota','Microsporidia','other Fungi','Nucleariidae'])]),
     'Apusomonadida','Breviatea']),
   ('Amoebozoa',['Tubulinea','Discosea','Evosea'])]),
 ('Diaphoretickes',[
   ('Archaeplastida',['Chlorophyta','Streptophyta','Rhodophyta','Rhodelphidia','Glaucophyta']),
   ('TSAR',[
     ('Stramenopiles',['Diatomea','Raphidophyceae','other Ochrophyta','Phaeophyceae','Labyrinthulomycetes','Oomycota','other Stramenopiles']),
     ('Alveolata',['Dinoflagellata','Apicomplexa','Ciliophora','Colpodellida','Perkinsea','other Alveolata']),
     ('Rhizaria',['Cercozoa','Endomyxa','Foraminifera','Radiolaria']),
     'Telonemia']),
   ('Haptista',['Prymnesiophyceae','Pavlovophyceae','Centroplasthelida']),
   ('Cryptista',['Cryptophyceae','Katablepharidia','Palpitomonas'])]),
 ('Excavata',[
   ('Discoba',['Euglenida','Kinetoplastea','Diplonemea','Symbiontida','Heterolobosea','Jakobida','Tsukubamonadida']),
   ('Metamonada',['Fornicata','Preaxostyla','Parabasalia','Anaeramoebidae','Barthelona'])]),
 ('Other lineages',['Hemimastigophora','Picozoa','CRuMs','Malawimonadida','Ancyromonadida','Ancoracysta','Provora'])])
def _leaves(t): return [t] if isinstance(t,str) else [x for c in t[1] for x in _leaves(c)]
LEAVES=_leaves(TREE)
def eukprot_lineage(r,LS=set(LEAVES)):
    """UniEuk taxonomy of one EukProt v3 species -> Figure 1 lineage"""
    t1,t2,sg=r['Taxogroup1_UniEuk'],r['Taxogroup2_UniEuk'],r['Supergroup_UniEuk']
    if sg=='Preaxostyla': return 'Preaxostyla'
    if t1=='Palmophyllophyceae': return 'Chlorophyta'
    if t1=='Colpodellida': return 'Colpodellida'
    if t1=='Fungi': return t2 if t2 in LS else 'other Fungi'
    if t1=='Ochrophyta': return {'Diatomeae':'Diatomea','Raphidophyceae':'Raphidophyceae','Phaeophyceae':'Phaeophyceae'}.get(t2,'other Ochrophyta')
    if t2=='Labyrinthulomycetes': return 'Labyrinthulomycetes'
    if t2=='Peronosporomycetes': return 'Oomycota'
    if t1 in LS: return t1
    if sg=='Stramenopiles': return 'other Stramenopiles'
    if sg=='Rhodophyta': return 'Rhodophyta'
    if t1=='Pavlovales': return 'Pavlovophyceae'
    if t1 in ('Cryptomonadales','Goniomonas'): return 'Cryptophyceae'
    if sg=='Kathablepharidacea': return 'Katablepharidia'
    if t1 in ('Flabellinia','Centramoebia'): return 'Discosea'
    if t1 in ('Eumycetozoa','Variosea','Archamoebea','Cutosea'): return 'Evosea'
    if t1=='Rotosphaerida': return 'Nucleariidae'
    if sg in ('Collodictyonidae','Rigifilida','Mantamonas'): return 'CRuMs'
    if t1 in ('colponemids','Squirmida'): return 'other Alveolata'
    if t1 in ('Endomyxa','eorhiza'): return 'Endomyxa'
    if t1=='Diplonemea': return 'Diplonemea'
    if sg in LS: return sg
    return None
def eukprot():
    import hashlib
    assert hashlib.md5(open(EUKPROT,'rb').read()).hexdigest()==EUKPROT_MD5, 'unexpected EukProt file'
    E=list(csv.DictReader(open(EUKPROT,encoding='utf-8'),delimiter='\t'))
    N=defaultdict(int); names=defaultdict(set)
    for r in E:
        l=eukprot_lineage(r); assert l in LEAVES,(r['Name_to_Use'],l)
        N[l]+=1; names[l].add((r['Genus_UniEuk']+' '+r['Epithet_UniEuk']).strip().lower())
    assert sum(N.values())==len(E)==993
    return N,names

def build_tree():
    """Figure 1. Per lineage: n expanded species (m by Mikus et al. 2025); N EukProt v3 species, of which k expanded
    (km by Mikus); o expanded species without a EukProt counterpart (om by Mikus)."""
    mikstr=set(g(r,'species') for r in rows if 'mikus' in g(r,'pdf_filename').lower() and g(r,'species'))
    sp=defaultdict(set); mk=defaultdict(set)
    for r in rows:
        raw=g(r,'species')
        if not raw: continue
        res,_,_=nsr.resolve(raw)
        if not res: continue
        genus=res.split()[0].rstrip('.')
        if genus in EXCL: continue
        tg=GEN2TG.get(genus)
        if not tg: continue
        sp[tg].add(res)
        if raw in mikstr: mk[tg].add(res)
    assert set(sp)<=set(LEAVES), set(sp)-set(LEAVES)
    N,names=eukprot()
    def L(name):
        e=sp[name]; k={x for x in e if x.lower() in names[name]}; m=mk[name]
        return {'name':name,'leaf':True,'n':len(e),'m':len(m),'N':N[name],'k':len(k),'km':len(k&m),'o':len(e-k),'om':len((e-k)&m)}
    def T(t): return L(t) if isinstance(t,str) else {'name':t[0],'children':[T(c) for c in t[1]]}
    return T(TREE)

BINO=['Homo sapiens','Mus musculus','Rattus norvegicus','Drosophila melanogaster','Danio rerio','Danionella cerebrum','Caenorhabditis elegans','Xenopus laevis','Xenopus tropicalis','Gallus gallus','Sus scrofa','Bos taurus','Macaca fascicularis','Macaca mulatta','Macaca nemestrina','Callithrix jacchus','Canis lupus familiaris','Anopheles gambiae','Apis mellifera','Ascaris suum','Astyanax mexicanus','Lampetra fluviatilis','Pleurodeles waltl','Plodia interpunctella','Schmidtea mediterranea','Potorous tridactylus']
HS,MM,RN='Homo sapiens','Mus musculus','Rattus norvegicus'
# Figure 2 sample types come from the database's curated `sample_type` column (not guessed from the name)
ACATS=['Cultured cells','Tissue','Organoid','Whole organism','Isolated protein','Environmental','Other']
SAMPLEMAP={'cultured_cell':'Cultured cells','tissue':'Tissue','organoid':'Organoid','whole_organism':'Whole organism',
           'isolated_protein':'Isolated protein','environmental':'Environmental','other':'Other',''.strip():'Other'}
def organism(s):
    low=s.lower()
    if 'in vitro' in low or 'isolated protein' in low: return None
    for b in BINO:
        if s.startswith(b): return b
    hs=['a375','a498','a549','beas','bv173','chang','h4','hff','hgadfn','hl-60','hos','huvec','hep3b','huh7','jurkat','lovo','mcf','mda-mb','mm.1s','pc3','rcc4','sh-sy5y','u251','u2os','u87','wm983','htert','hek293','hela','caco','cfbe','ges1','nk-92','sw480','id98','uci0','gbm#','nup','snap-clc','mucilair','sa501','pdx']
    if any(x in low for x in hs) or 'human' in low: return HS
    if any(x in low for x in ['c2c12','mpek','neuro-2a','nih-3t3','raw264','min6','mtec','mesc','mouse']): return MM
    if any(x in low for x in ['ins-1e','nrk49f']) or 'rat' in low: return RN
    if 'cos-7' in low or 'vero' in low or 'bs-c-1' in low: return 'Chlorocebus aethiops'
    if low.startswith('cho'): return 'Cricetulus griseus'
    if low.startswith('bhk'): return 'Mesocricetus auratus'
    if 'mdck' in low: return 'Canis lupus familiaris'
    if 'feline' in low or 'nlfk' in low: return 'Felis catus'
    return HS if 'human' in low else '??'
def stype(s):
    l=s.lower()
    if any(x in l for x in ['platelet','sperm','erythrocyte','synaptosome','synaptic vesicle','extracellular vesicle',' ev','plasma','csf','cerebrospinal','otoferlin']): return 'Isolated / subcellular'
    if 'organoid' in l or 'tumorsphere' in l: return 'Organoid'
    if any(x in l for x in ['ipsc','hipsc','hesc',' esc','embryonic stem','stem cell','pdx','xenograft','mesc']): return 'Stem-cell / PDX'
    if any(x in l for x in ['primary','neuron','hippocamp','cortical','osteoblast','hepatocyte','keratinocyte','macrophage','endothelial','cardiomyocyte','granule','epithelial cell']): return 'Primary cells'
    if any(x in l for x in ['ffpe','biopsy','tissue','tumor','nephrectomy','glomerulus','islet','tonsil','spleen','lymph node','cornea','brain','kidney','retina','liver','muscle','lung','pancreas','intestine','skin','embryo','testis','heart']): return 'Tissue / FFPE'
    if '(' not in s and re.search(r'[A-Z]',s) and (re.search(r'\d',s) or s.isupper() or '-' in s): return 'Cell line'
    if any(c in s for c in ['HeLa','HEK','U2OS','Vero','CHO','MDCK','Jurkat','MCF','NIH','Neuro','RAW','COS','BHK','PtK','Caco']): return 'Cell line'
    return 'Whole organism'
def build_animals():
    asamp=defaultdict(lambda:defaultdict(set))
    for r in rows:
        if g(r,'clade')!='Metazoa' or not g(r,'species'): continue
        res,_,_=nsr.resolve(g(r,'species'))   # same resolver as Fig 1, so the counts agree
        if not res: continue
        st=SAMPLEMAP.get(g(r,'sample_type'),'Other')   # use the curated sample_type column
        asamp[res][st].add(g(r,'species'))
    return {o:{c:len(asamp[o][c]) for c in ACATS if asamp[o][c]} for o in asamp}

def build_prok():
    res={'Bacteria':set(),'Archaea':set()}
    for r in rows:
        cl=g(r,'clade'); sp=g(r,'species')
        if cl not in res or not sp: continue
        rr,_,_=nsr.resolve(sp)
        if not rr: continue
        genus=rr.split()[0].rstrip('.')
        if GEN2TG.get(genus): continue   # a eukaryote mislabelled with a prokaryote clade; counted on the tree, not here
        res[cl].add(rr)
    return {k:len(v) for k,v in res.items()}

def build_extra():
    # publications per year (distinct papers)
    from collections import defaultdict as dd
    yr=dd(set)
    for r in rows:
        y=g(r,'year'); key=g(r,'doi') or g(r,'pdf_filename')
        if y.isdigit() and key: yr[y].add(key)
    years=sorted(y for y in yr if 2014<=int(y)<=2026)
    papersYear=[{'label':y,'value':len(yr[y])} for y in years]
    # distinct resolved species per sample_type
    st=dd(set)
    for r in rows:
        s=g(r,'sample_type'); sp=g(r,'species')
        if not s or not sp: continue
        rr,_,_=nsr.resolve(sp)
        if rr: st[s].add(rr)
    sampleTypes=sorted([{'label':k.replace('_',' '),'value':len(v)} for k,v in st.items()],key=lambda x:-x['value'])
    # gel-chemistry space: sodium-acrylate % vs acrylamide %, coloured by variant
    import re as _re
    def _fnum(s):
        m=_re.search(r'[\d.]+', s.replace('%',''))
        try: return float(m.group()) if m else None
        except: return None
    MAIN={'U-ExM','proExM','TREx','cryo-ExM','Magnify','LR-ExM','MAP'}   # only the headline methods
    pts=set()
    for r in rows:
        sa=_fnum(g(r,'gel_sodium_acrylate_pct')); aa=_fnum(g(r,'gel_acrylamide_pct'))
        v=g(r,'exm_variant'); v=v.split(':',1)[1].strip() if v.startswith('other:') else v
        if sa is not None and aa is not None and v in MAIN and sa<=40 and aa<=55: pts.add((sa,aa,v))
    gelPoints=[{'x':p[0],'y':p[1],'v':p[2]} for p in sorted(pts)]
    # species-accumulation: cumulative distinct resolved species by year of first appearance
    first={}
    for r in rows:
        sp=g(r,'species'); y=g(r,'year')
        if not sp or not y.isdigit(): continue
        res,_,_=nsr.resolve(sp)
        if not res: continue
        yi=int(y)
        if res not in first or yi<first[res]: first[res]=yi
    byyear=dd(int)
    for y in first.values(): byyear[y]+=1
    cum=0; accum=[]
    for y in sorted(k for k in byyear if 2014<=k<=2026):
        cum+=byyear[y]; accum.append({'label':str(y),'value':cum})
    return {'papersYear':papersYear,'sampleTypes':sampleTypes,'gelPoints':gelPoints,'accum':accum}

# ---------- Infographic figures (replaces the static overview_data.json of 19 Sep 2026) ----------
ABBR={'Metazoa':'Met','Alveolata':'Alv','Viridiplantae':'Vir','Discoba':'Dis','Stramenopiles':'Str','Haptophyta':'Hap',
      'Bacteria':'Bac','Fungi':'Fun','Unicellular Holozoa':'U.Hol','Cryptista':'Cry','Amoebozoa':'Amo','Rhodophyta':'Rho',
      'Rhizaria':'Rhi','Glaucophyta':'Gla','Archaea':'Arc'}
def _num(v):
    v=(v or '').lower().replace('~','').replace('≈','')
    if ' or ' in v or not v: return None
    xs=[float(x) for x in re.findall(r'\d+(?:\.\d+)?',v)]
    return round(sum(xs[:2])/len(xs[:2]),2) if xs and 1<=xs[0]<=30 else None
def build_infographic():
    from collections import Counter
    res={}
    for r in rows:
        sp=g(r,'species')
        if sp and sp not in res: res[sp]=nsr.resolve(sp)[0]
    R=lambda r:res.get(g(r,'species'))
    cl=defaultdict(Counter)                                   # one clade per resolved species
    for r in rows:
        if R(r) and g(r,'clade') and g(r,'clade')!='Unknown': cl[R(r)][g(r,'clade')]+=1
    CL={k:v.most_common(1)[0][0] for k,v in cl.items()}
    FAM=[('magnify','Magnify'),('trex','TREx'),('cryo','cryo-ExM'),('iterative','iterative-ExM'),('iu-exm','iterative-ExM'),
         ('expath','ExPath'),('exfish','ExFISH'),('proexm','proExM'),('u-exm','U-ExM'),('lr-exm','LR-ExM'),('x10','X10'),('pan-exm','pan-ExM')]
    def var(r):   # 'other: X' labels folded into a named family when the family name appears in the label
        v=g(r,'exm_variant'); low=v.lower()
        if not low.startswith('other'): return v
        for k,f in FAM:
            if k in low: return f
        return re.sub(r'^other:\s*','',v)
    P=[r for r in rows if g(r,'label_type') in ('primary_antibody','nanobody')]
    # D: distinct species per ExM variant
    vs=defaultdict(set)
    for r in rows:
        if R(r) and var(r): vs[var(r)].add(R(r))
    D=[{'label':k,'value':len(v)} for k,v in sorted(vs.items(),key=lambda x:-len(x[1]))[:9]]
    top=[d['label'] for d in D]
    # one record per protocol instance (study x species x variant)
    inst={}
    for r in rows:
        if R(r) and var(r) in top: inst.setdefault((g(r,'doi').lower(),R(r),var(r)),r)
    EXP=[];HOM=[]
    for v in top:
        I=[r for k,r in inst.items() if k[2]==v]
        nom=sorted(x for x in (_num(g(r,'expansion_factor_nominal')) for r in I) if x)
        mea=sorted(x for x in (_num(g(r,'expansion_factor_measured')) for r in I) if x)
        med=lambda a:round(a[len(a)//2] if len(a)%2 else (a[len(a)//2-1]+a[len(a)//2])/2,1)
        if len(nom)>=5 and len(mea)>=5: EXP.append({'label':v,'nom':med(nom),'mea':med(mea),'n':len(mea)})
        h=Counter({'heat-SDS':'sds','Proteinase K':'pk','both':'both','other':'other'}.get(g(r,'homogenization_method')) for r in I)
        h.pop(None,None); n=sum(h.values())
        if n>=5: HOM.append({'label':v,**{k:round(100*h[k]/n) for k in ('sds','pk','both','other')},'n':n})
    # C: distinct species per primary-antibody target
    ts=defaultdict(set)
    for r in P:
        if R(r) and g(r,'label_target'): ts[g(r,'label_target')].add(R(r))
    C=[{'label':k,'value':len(v)} for k,v in sorted(ts.items(),key=lambda x:-len(x[1]))[:12]]
    # CAT: distinct primary antibodies per category
    cs=defaultdict(set)
    for r in P:
        if g(r,'label_name'): cs[(g(r,'label_category') or 'other').replace('_',' ')].add(g(r,'label_name'))
    CAT=[{'label':k,'value':len(v)} for k,v in sorted(cs.items(),key=lambda x:-len(x[1]))]
    # TRANS: antibodies spanning the most clades
    ac=defaultdict(set); at=defaultdict(Counter)
    for r in P:
        nm=g(r,'label_name')
        if nm and R(r) in CL: ac[nm].add(CL[R(r)]); at[nm][g(r,'label_target')]+=1
    TRANS=[{'label':k,'value':len(v),'tgt':at[k].most_common(1)[0][0]} for k,v in sorted(ac.items(),key=lambda x:(-len(x[1]),x[0]))[:12]]
    # DIFF: per clade, share of species (outcome reported) for which any study reported a partial or failed expansion
    so=defaultdict(set); dst=defaultdict(set)
    for r in rows:
        o=g(r,'protocol_outcome')
        if o in ('success','partial','fail') and R(r) in CL: so[R(r)].add(o); dst[CL[R(r)]].add(g(r,'doi') or g(r,'pdf_filename'))
    dn=Counter(); dbad=Counter()
    for sp_,os_ in so.items():
        dn[CL[sp_]]+=1
        if os_&{'partial','fail'}: dbad[CL[sp_]]+=1
    DIFF=[{'label':k,'value':round(100*dbad[k]/dn[k]),'bad':dbad[k],'n':dn[k],'studies':len(dst[k])} for k in dn if dn[k]>=5]
    DIFF.sort(key=lambda x:(-x['value'],-x['n'],x['label']))
    # MAT: species with a successful stain, per target x clade
    ok=defaultdict(set); okab=defaultdict(set)
    for r in P:
        if g(r,'label_outcome')=='success' and R(r) in CL:
            ok[(g(r,'label_target'),CL[R(r)])].add(R(r)); okab[(g(r,'label_target'),CL[R(r)])].add(g(r,'label_name'))
    tg=[c['label'] for c in C]
    tot=Counter({k:len(v) for k,v in defaultdict(set,{c:{s for s in CL if CL[s]==c} for c in set(CL.values())}).items()})
    cols=[c for c,_ in sorted(tot.items(),key=lambda x:(-x[1],x[0])) if any(ok.get((t,c)) for t in tg)]   # name breaks ties: deterministic
    MAT={'targets':tg,'clades':[ABBR.get(c,c[:3]) for c in cols],'cladesFull':cols,
         'cells':[[len(ok.get((t,c),())) for c in cols] for t in tg],
         'abs':[[sorted(x for x in okab.get((t,c),()) if x) for c in cols] for t in tg]}   # antibodies behind each cell (successful stains)
    return {'D':D,'EXP':EXP,'HOM':HOM,'C':C,'CAT':CAT,'TRANS':TRANS,'DIFF':DIFF,'MAT':MAT}

def build():
    d={'tree':build_tree(),'anim':build_animals(),'acats':ACATS,'prok':build_prok()}
    d.update(build_extra()); return d

if __name__=='__main__':
    data=build(); json.dump(data,open('overview2.json','w',encoding='utf-8'),ensure_ascii=False)
    def tot(n): return n['n'] if n.get('leaf') else sum(tot(c) for c in n['children'])
    def totm(n): return n['m'] if n.get('leaf') else sum(totm(c) for c in n['children'])
    print('overview2.json written | tree species:',tot(data['tree']),'Mikus:',totm(data['tree']),'| animals:',len(data['anim']))
