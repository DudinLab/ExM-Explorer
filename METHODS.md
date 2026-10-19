# Methods

ExM Explorer v1.0 (released 21 October 2026; https://doi.org/10.5281/zenodo.23439354).

**Literature search and full-text retrieval.** PubMed (NCBI E-utilities) and Europe PMC, which indexes the bioRxiv and medRxiv preprint servers, were queried on 27–28 April 2026 for expansion microscopy method names (expansion microscopy, U-ExM, ultrastructure expansion, proExM, ExPath, ExFISH, Magnify, cryo-ExM and others) published from 2015 onward (`pipeline/harvest.py`). Records were deduplicated by DOI, giving 861 records. Titles and abstracts were scored for ExM, antibody and experimental terms (`pipeline/filter_library.py`; 400 records retained, 461 rejected). As ExM is often used without being named in the abstract, full texts were retrieved for records on both sides of this screen: open-access PDFs by script (164), bioRxiv preprints from the bioRxiv server (224), and the remainder manually through institutional subscriptions. Papers from our laboratories and collaborators not returned by the search were added manually, giving 579 PDFs.

**Data extraction.** To extract experimental details, each PDF was converted to text (PyMuPDF 1.28.2) and read in full, one paper at a time and without cross-paper context, by a large language model (Claude Sonnet 4.6, `claude-sonnet-4-6`; Anthropic API; `pipeline/extract_exm.py`, up to 8,192 output tokens, three attempts per paper). The model first determined whether the paper reported ExM experiments and then returned one record per species × label × paper, comprising the organism, sample type, fixation, anchoring, gel composition, homogenization, nominal and measured expansion factors, labeling strategy, and for each antibody, dye or stain its target, host, supplier, catalog number, dilution, fluorophore and outcome. Unreported fields were left empty, and values inferred from context or uncertain were prefixed `inferred:` or `uncertain:`. Of the 579 PDFs, 525 yielded data (23 after re-running papers that failed or returned incomplete output; `pipeline/retry_failed.py`, `pipeline/fix_pass2.py`), 51 were classified as not reporting ExM experiments, 2 failed and 1 contained no data. Species reported only in Supplementary Table S1 of Mikus et al.¹ were added from that table (`pipeline/enrich_mikus_s1.py`). To capture additional protocol fields and to assess reproducibility, all papers were extracted a second time with an expanded schema (`pipeline/extract_exm_v2.py`, up to 16,384 output tokens); three papers that failed this second extraction retained their first-pass records.

**Curation.** ExM variant names were standardized, species synonyms merged, and each species assigned to one of 15 clades (`pipeline/fix_variants.py`, `pipeline/normalize_species.py`, `pipeline/fix_clades.py`). Preprints and their published versions were identified by title similarity and by shared authors and species (`pipeline/qc_check.py`), classified with the CrossRef API (`pipeline/resolve_duplicates.py`) and confirmed with Claude Sonnet 4.6 (`pipeline/check_duplicates.py`); 116 duplicate PDFs were removed, retaining the published version. A further 30 preprint–publication pairs with changed titles were merged by assigning the preprint records to the DOI of the published article, and two review articles were removed (`pipeline/curate_20261009.py`, `pipeline/curate_20261019.py`; all changes listed in `data/curation_log_20261009.csv`). Antibody, dye and supplier names were mapped to canonical forms (`pipeline/normalise_*.py`), and missing suppliers and catalog numbers were recovered from the source text with Claude Haiku 4.5 (`claude-haiku-4-5`; `pipeline/recover_unknown_suppliers.py`), which filled empty fields only. Environmental ciliates shown in Mikus et al.¹ (Fig. 7) and missed by extraction were added manually. The path of every PDF from search to database is given in `data/paper_provenance.csv`.

| Step | Records |
|---|---|
| Search records (PubMed, Europe PMC; deduplicated) | 861 |
| PDFs retrieved and read | 579 |
| PDFs with ExM data | 525 |
| Studies after removal and merging of duplicates | 381 |
| Rows (species × label × study) | 6,755 |
| Species (after resolution) | 301 (268 eukaryotes, 33 prokaryotes) |
| Primary antibodies and nanobodies | 1,483 |
| Secondary reagents | 946 |
| Dyes and stains | 608 |

**Species resolution and taxonomy.** For counts and figures, entries naming a cell line, strain or tissue were resolved to their source organism (`build/normalise_species_resolution.py`; for example, HeLa and HEK293 to *Homo sapiens*), and eukaryotes were placed on the UniEuk taxonomy² as used in EukProt³ by genus (`build/build_overview2.py`). Cell-line assignments were verified against web sources. Resolution does not modify the database (`data/species_resolution_review.csv`). To express coverage relative to sequenced diversity (Overview, Figure 1), the 993 species of EukProt v3³ were assigned to the same lineages by their UniEuk taxonomy, and each expanded species was matched to EukProt by binomial name; expanded species without a EukProt counterpart are reported separately.

**Quality control.** Eight controls were computed on the released table (`build/qc_suite.py`, `QC/03_test_retest_v1_v2/compare_v1_v2.py`, `QC/07_ncbi_clade_concordance/run_ncbi_check.py`; tables and figures in `QC/`).

| Control | Result |
|---|---|
| Field completeness | core fields ≥96% filled |
| Reagent identifiers | 90.5% of primary antibodies with a catalog number, clone, gift laboratory or supplier |
| Agreement between the two extractions (1,609 aligned rows) | clade 98.8%, protocol outcome 99.4%, label outcome 95.7% |
| Consistency across studies | species → clade 100%; antibody → target 78.1% (178 of 228 antibodies used in ≥2 studies) |
| Controlled vocabularies | 100% |
| Catalog-number syntax | 99.1% of 1,283 catalog numbers |
| Clade agreement with NCBI Taxonomy⁴ | 99.6% (237 of 238 checkable species; 1 August 2026 table) |
| Flagged values | 291 `uncertain:`, 1,632 `inferred:` |

**Portal.** The portal is a single HTML file generated from the database by a deterministic script (`build/build_portal.py`). All data are embedded, no external resources are loaded, and the build reproduces the portal exactly from the same table. Within each species, protocol records sharing every reported parameter were grouped, and each record lists the papers that reported it. In the Overview, the difficulty of each clade is the share of its species for which any study reported a partial or failed expansion, shown for clades with at least five species. Every number stated in the portal and documentation was checked against the data (`build/validate_portal.py`), and all views, links and exports were tested (`build/test_portal_e2e.js`).

**Limitations.** Entries reflect what was published and are biased toward animals and model organisms; absence from the database indicates that ExM has not been tried or reported, not that it fails. Failed experiments are rarely published, so outcomes overestimate success. Values were extracted automatically and may contain errors or omissions, and species shown only in figures or supplements may be missing. Antibody targets are those reported by the authors and were not validated. Exact protocols should be taken from the original publications, linked by DOI.

**Data and code availability.** The database, portal, code, pipeline scripts with their logs and quality-control outputs are available at GitHub (https://github.com/DudinLab/ExM-Explorer) and archived at Zenodo (https://doi.org/10.5281/zenodo.23439354). Code is released under the MIT License and data under CC BY 4.0. Source PDFs are not redistributed.

## References

1. Mikus, F. et al. Charting the landscape of cytoskeletal diversity in microbial eukaryotes. *Cell* (2025). https://doi.org/10.1016/j.cell.2025.09.027
2. Berney, C. et al. UniEuk: time to speak a common language in protistology! *J. Eukaryot. Microbiol.* **64**, 407–411 (2017).
3. Richter, D. J. et al. EukProt: a database of genome-scale predicted proteins across the diversity of eukaryotes. *Peer Community J.* **2**, e56 (2022).
4. Schoch, C. L. et al. NCBI Taxonomy: a comprehensive update on curation, resources and tools. *Database* **2020**, baaa062 (2020).
