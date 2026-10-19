# Data

## Files

| File | Contents |
|---|---|
| `ExM_database_curated.csv` | the database, one row per species × label × study (43 columns, 6,755 rows, UTF-8) |
| `paper_provenance.csv` | one row per PDF: source, keyword-screen verdict, extraction outcome, duplicate handling and inclusion |
| `curation_log_20261009.csv` | every value changed and row removed in the final curation (9 and 19 October 2026), with old value, new value and reason |
| `species_resolution_review.csv` | the organism assigned to each species entry, with genus, method and confidence |
| `EukProt_included_data_sets.v03.2021_11_22.txt` | EukProt v3 species list (Richter et al. 2022; CC BY 4.0), used unchanged as the denominator of Overview Figure 1 |

## Design

Each row describes one species × label × study, so that a study testing five species with three antibodies contributes fifteen rows. Studies are identified by `doi`; where a study exists as a preprint and as a published article, rows from both are assigned to the published DOI, and `pdf_filename` gives the source file of each row.

## Columns

**Paper**

| Column | Meaning |
|---|---|
| `pdf_filename` | the PDF the row was extracted from |
| `doi`, `title`, `first_author`, `last_author`, `year`, `journal` | bibliography of the study |
| `exm_variant` | standardized ExM method (`U-ExM`, `proExM`, `ExPath`, `ExFISH`, `TREx`, `Magnify`, `cryo-ExM`, `MAP`, `iterative-ExM`) or a named variant as `other: [name]` |
| `paper_type` | `methods`, `application` or `protocol`; one `review` (Övermöhle 2026) is kept for its virus imaging |
| `new_protocol` | whether the paper introduces a new protocol |

**Species and sample**

| Column | Meaning |
|---|---|
| `species` | the sample as named in the paper, which may be a cell line, strain or tissue; resolved to an organism for display (`species_resolution_review.csv`) |
| `clade` | one of 15 controlled values (Alveolata, Viridiplantae, Stramenopiles, Haptophyta, Cryptista, Unicellular Holozoa, Discoba, Rhodophyta, Fungi, Rhizaria, Glaucophyta, Amoebozoa, Metazoa, Archaea, Bacteria) or `Unknown` |
| `sample_type` | `cultured_cell`, `tissue`, `whole_organism`, `organoid`, `environmental`, `isolated_protein` or `other` |

**Protocol**

| Column | Meaning |
|---|---|
| `fixation_reagent`, `_concentration`, `_duration`, `_temperature`, `_buffer` | fixation |
| `anchoring_reagent`, `_concentration`, `_duration`, `_temperature` | anchoring |
| `gel_sodium_acrylate_pct`, `gel_acrylamide_pct`, `gel_bis_pct`, `gel_other_components` | gel composition |
| `homogenization_method` | `Proteinase K`, `heat-SDS`, `both` or `other` |
| `expansion_factor_nominal`, `expansion_factor_measured` | intended and measured expansion, kept separate as they often differ |
| `labelling_strategy` | `pre-expansion`, `post-expansion` or `both` |
| `protocol_outcome` | `success`, `partial`, `fail`, or empty when not reported |

**Label (antibody, dye or stain)**

| Column | Meaning |
|---|---|
| `label_target`, `label_name` | what the label detects, and its name |
| `label_type` | `primary_antibody`, `secondary_antibody`, `nanobody`, `dye`, `phalloidin`, `lectin`, `tag` or `other` |
| `label_host_species`, `label_supplier`, `label_catalogue_number`, `label_dilution`, `label_fluorophore`, `label_application_timing` | reagent details |
| `label_outcome` | per-label `success`, `partial`, `fail`, or empty |
| `label_category` | biological grouping of the target (cytoskeleton, cilia and centrosome, chromatin and others) |
| `extraction_notes` | free-text notes from extraction and curation |

## Conventions

Empty cells denote values not reported in the paper; no values were inferred to fill them. Values prefixed `uncertain:` or `inferred:` were flagged by the extraction model as uncertain or inferred from context and should be checked against the source. Antibodies obtained as gifts are recorded with `gift: [lab]` as supplier and no catalog number.

Outcomes are defined as follows: `success`, clean signal, good preservation and isotropic expansion of all cells; `partial`, weak or inconsistent signal, uneven expansion, or only some cells or targets labeled; `fail`, no signal, gel failure or destroyed sample; empty, not reported.
