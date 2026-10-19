# build/

Deterministic, model-free code that turns `../data/ExM_database_curated.csv` into `../portal/index.html`.

| File | Role |
|---|---|
| `build_portal.py` | Main build. Aggregates the table per species, antibody, dye and study, fills the live counts into the template, embeds all data, writes `../portal/index.html`. Release metadata (version, date, repository URL, DOI) is set in `RELEASE` at the top. |
| `build_overview2.py` | Computes every figure: the EukProt/UniEuk tree (Figure 1), animals by sample type (Figure 2), and the eleven Infographic figures. |
| `normalise_species_resolution.py` | Resolves raw species strings to organisms (cell lines → source species). Used by the build; run alone to regenerate `../data/species_resolution_review.csv`. |
| `portal_template.html` | The app shell (HTML, CSS, JavaScript) with data and count placeholders. |
| `validate_portal.py` | Whole-system check: coherence between figures, table integrity, and every number stated next to a unit in the portal and the docs against the live data. Exit code 0 = all green. |
| `qc_suite.py` | Recomputes quality controls 01, 02, 04, 05, 06 and 08 (see `../QC/`). |
| `test_portal_e2e.js` | End-to-end test of the portal in jsdom: opens every tab, panel, filter and search, fires every export (CSV, BibTeX, RIS, reagent list), follows deep links and method steps, and checks every link it generates (`npm install jsdom && node test_portal_e2e.js ../portal/index.html`). |

```bash
python build_portal.py && python validate_portal.py
```
Standard library only, Python 3.10+. To place a new genus on the tree, add it to the genus → taxogroup map in `build_overview2.py`.
