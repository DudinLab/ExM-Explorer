# Quality control

Eight controls were computed on the released database (6,755 rows, 381 studies). Each folder holds the result table and figure.

| Folder | Control | Result |
|---|---|---|
| `01_field_completeness` | fraction of rows with a value, per column | core fields ≥96% |
| `02_reagent_identifier_completeness` | primary antibodies with a catalog number, clone, gift laboratory or supplier | 90.5% of 1,483 |
| `03_test_retest_v1_v2` | agreement between the two extractions (1,609 aligned rows) | clade 98.8%, protocol outcome 99.4%, label outcome 95.7% |
| `04_cross_paper_corroboration` | same annotation in independent studies | species → clade 100%; antibody → target 78.1% (178 of 228) |
| `05_controlled_vocabulary` | values within controlled vocabularies | 100% |
| `06_catalogue_format_validity` | catalog numbers matching vendor syntax | 99.1% of 1,283 |
| `07_ncbi_clade_concordance` | clade agreement with NCBI Taxonomy | 99.6% (237 of 238; 1 August 2026 table) |
| `08_honest_abstention` | values flagged by the extraction model | 291 `uncertain:`, 1,632 `inferred:` |

To reproduce:

```bash
python ../build/qc_suite.py ../data/ExM_database_curated.csv .    # 01, 02, 04, 05, 06, 08
python 03_test_retest_v1_v2/compare_v1_v2.py                      # 03
python 07_ncbi_clade_concordance/run_ncbi_check.py                # 07 (internet access required)
python qc_figures.py                                              # figures
```
