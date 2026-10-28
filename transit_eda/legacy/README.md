# Legacy EDA

**The canonical EDA is `transit_eda/notebooks/eda_complete.ipynb`.** It reads the committed
feature store (`data/processed/feature_store.parquet`) and writes the plots the website shows
(`website/data/eda_plots/`). Nothing in this folder feeds the models, the API or the website.

## What is here

| Path | What it is |
|---|---|
| `eda_complete.py` | The first-pass EDA script, kept for the record. |
| `outputs/figures/s*.png` | The eight figures that script wrote (`s1` to `s5`). |
| `data/vta_clean.csv` | The cleaned VTA table that script wrote. |

## Why its target differs

The script analyses a different quantity from the project's forecasting target:

- It works on BART *Avg Weekday OD* sheets (average weekday trips per origin-destination pair),
  with self-loops (origin equal to destination) dropped. The feature store's target is monthly
  Network Total Trips per station.
- It reads raw BART `.xlsx` workbooks from `transit_eda/data/bart/<year>/`, which are not in git,
  so it cannot be run from a clean checkout. It also reads the two raw VTA CSVs in
  `transit_eda/data/vta/`.
- Its figures predate the 2022-2025 feature store, so they do not describe the data the models
  were trained on.

## Running it

It is not expected to run from a clean checkout. If you have the raw workbooks, run
`python transit_eda/legacy/eda_complete.py`. Figures and CSVs are written under this folder
only. It no longer touches `transit_eda/data/bart_clean.csv`.

## What stayed where it was

`transit_eda/data/bart_clean.csv` was originally written by this script, but it stays put: it is
the input of the fallback loader `machine_learning_files/bart_od_from_csv.py` and is listed in
`data/MANIFEST.md`. `transit_eda/data/bart_combined.csv`, `vta_yearly_clean.csv` and the raw VTA
CSVs under `transit_eda/data/vta/` were not moved either: the script does not write the first two,
and the raw VTA files are its inputs rather than its outputs.
