# ExM Explorer

ExM Explorer is a search engine for expansion microscopy (ExM) experiments compiled from the literature. For each study it records the organisms expanded, the protocol used, and the antibodies and dyes applied, with their outcome and a link to the source paper. Version 1.0 (21 October 2026) covers 381 studies, 301 species, 1,483 primary antibodies and 608 dyes and stains.

**Open the portal:** https://dudinlab.github.io/ExM-Explorer/, or open `portal/index.html` in any browser (it runs offline). Code and data: https://github.com/DudinLab/ExM-Explorer.

Felix Mikus, Paula Lorena Llanos Fuentes, Karla Azucena Juárez Núñez, Diego Beltrame, Gautam Dey and Omaya Dudin, [Dey Lab](https://www.evonuclab.org) (EMBL) and [Dudin Lab](https://www.dudinlab.com) (University of Geneva), supported by the [Gordon and Betty Moore Foundation](https://www.moore.org). Contact: omaya.dudin@unige.ch.

## Contents

| | |
|---|---|
| `portal/` | the portal, a single HTML file (`index.html` at the root forwards to it when served with GitHub Pages) |
| `data/` | the database (`ExM_database_curated.csv`) with its column dictionary, the provenance of every PDF, the curation log, the species-resolution table and the EukProt v3 species list used for Overview Figure 1 |
| `METHODS.md` | how the database was built, quality control and limitations |
| `QC/` | quality-control tables, figures and code |
| `build/` | code that generates and tests the portal from the database |
| `pipeline/` | the search, extraction and curation scripts as run, with their logs |

## Rebuild

```bash
pip install -r requirements.txt
cd build
python build_portal.py       # data/ExM_database_curated.csv -> portal/index.html
python validate_portal.py    # checks every number in the portal and docs against the data
```

Re-running the extraction requires an Anthropic API key and the source PDFs, which are not distributed.

## License and citation

Code is released under the MIT License (`LICENSE`) and data under CC BY 4.0 (`LICENSE-DATA.md`). Please cite ExM Explorer as: Mikus F, Llanos Fuentes PL, Juárez Núñez KA, Beltrame D, Dey G, Dudin O (2026). ExM Explorer v1.0: a search engine for expansion microscopy. Zenodo. https://doi.org/10.5281/zenodo.23439354 (see also `CITATION.cff`).
