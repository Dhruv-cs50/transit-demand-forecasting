"""Caltrain feature store: the monthly systemwide AWR series in the BART store's shape.

``build_caltrain_store(cfg)`` reads ``data/caltrain/awr_monthly.csv`` (Task 1) and
``configs/caltrain.yaml`` and returns one row per usable month:

``timestamp``        month start, ``datetime64[us]`` (same arrow type as the BART store)
``station_id``      the constant ``"CALTRAIN_SYSTEM"``
``ridership``       the average weekday ridership (AWR), ``float64``, so the BART model
                    functions apply unchanged
``method_period``   the latest ``method_changes`` entry at or before the row's month
``method_<YYYY_MM>`` one 0/1 step column per method change inside the training window
                    (``>= train_start``): the model reads a counting change as a level
                    shift, not demand
``electrified``     0 before ``electrification_start``, 1 from that month on

The 2020-2021 months in ``exclude`` are dropped. A month earlier than every listed
change (January 2019) takes the first period: data/caltrain/MANIFEST.md restates it on
the Feb 2019 basis, so there is no break between it and the next month.

Run ``python -m machine_learning_files.caltrain_store`` to rebuild
``data/processed/caltrain_store.parquet`` and print its sha256.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import yaml

__all__ = ["build_caltrain_store", "load_config", "step_column", "STATION_ID"]

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "configs" / "caltrain.yaml"
DEFAULT_AWR_CSV = ROOT / "data" / "caltrain" / "awr_monthly.csv"
DEFAULT_STORE_PATH = ROOT / "data" / "processed" / "caltrain_store.parquet"

STATION_ID = "CALTRAIN_SYSTEM"


def load_config(path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text())


def _month_start(month: str) -> pd.Timestamp:
    return pd.Timestamp(f"{month}-01")


def step_column(change: str) -> str:
    """``"2023-11"`` -> ``"method_2023_11"``."""
    return "method_" + change.replace("-", "_")


def build_caltrain_store(cfg: dict) -> pd.DataFrame:
    """Build the monthly store from the AWR series and the Caltrain config.

    `cfg` is ``configs/caltrain.yaml`` as a dict. Optional keys: ``awr_csv`` (input
    series) and ``store_path`` (parquet output; default
    ``data/processed/caltrain_store.parquet``). The parquet is written and its
    sha256 printed.
    """
    awr = pd.read_csv(cfg.get("awr_csv", DEFAULT_AWR_CSV), dtype={"month": str})
    dupes = sorted(awr.loc[awr["month"].duplicated(), "month"].unique())
    if dupes:
        raise ValueError(f"AWR series has duplicate months: {dupes}")
    missing = awr.loc[awr["awr"].isna(), "month"].tolist()
    if missing:
        raise ValueError(f"AWR series has missing awr values for months: {missing}")
    changes = sorted(cfg["method_changes"])
    excluded = set(cfg["exclude"])
    train_start = _month_start(cfg["train_start"])
    electrification = _month_start(cfg["electrification_start"])

    awr = awr[~awr["month"].isin(excluded)].sort_values("month").reset_index(drop=True)
    ts = pd.to_datetime(awr["month"] + "-01").astype("datetime64[us]")

    # Latest change at or before the month; the first period for earlier months.
    change_ts = [_month_start(c) for c in changes]
    period = []
    for t in ts:
        idx = max((i for i, c in enumerate(change_ts) if c <= t), default=0)
        period.append(changes[idx])

    out = pd.DataFrame(
        {
            "timestamp": ts,
            "station_id": STATION_ID,
            "ridership": awr["awr"].astype("float64"),
            "method_period": pd.Series(period, dtype="str"),
        }
    )
    for change in changes:
        if _month_start(change) >= train_start:
            out[step_column(change)] = (ts >= _month_start(change)).astype("int64")
    out["electrified"] = (ts >= electrification).astype("int64")

    store_path = Path(cfg.get("store_path", DEFAULT_STORE_PATH))
    store_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(store_path, index=False)
    digest = hashlib.sha256(store_path.read_bytes()).hexdigest()
    print(f"caltrain store: {len(out)} rows -> {store_path}\nsha256 {digest}")
    return out


def main() -> None:
    build_caltrain_store(load_config())


if __name__ == "__main__":
    main()
