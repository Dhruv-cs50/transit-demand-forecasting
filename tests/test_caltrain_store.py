"""Tests for the Caltrain feature store and the per-station annual table.

The store is the monthly systemwide AWR series (data/caltrain/awr_monthly.csv)
shaped like the BART store, plus the method-change step columns and the
electrification step from configs/caltrain.yaml.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest
import yaml

from machine_learning_files.caltrain_store import build_caltrain_store

ROOT = Path(__file__).resolve().parent.parent
CFG_PATH = ROOT / "configs" / "caltrain.yaml"
BART_STORE = ROOT / "data" / "processed" / "feature_store.parquet"
COMMITTED_STORE = ROOT / "data" / "processed" / "caltrain_store.parquet"
STATION_CSV = ROOT / "data" / "caltrain" / "station_annual.csv"
MANIFEST = ROOT / "data" / "caltrain" / "MANIFEST.md"


@pytest.fixture(scope="module")
def cfg() -> dict:
    return yaml.safe_load(CFG_PATH.read_text())


@pytest.fixture()
def store(cfg, tmp_path) -> pd.DataFrame:
    # Never write the committed parquet from a test.
    return build_caltrain_store({**cfg, "store_path": str(tmp_path / "caltrain_store.parquet")})


def _row(store: pd.DataFrame, month: str) -> pd.Series:
    hit = store[store["timestamp"] == pd.Timestamp(month + "-01")]
    assert len(hit) == 1, f"expected exactly one row for {month}, got {len(hit)}"
    return hit.iloc[0]


# --------------------------------------------------------------------------
# Store


def test_excludes_2020_2021(store, cfg):
    months = store["timestamp"].dt.strftime("%Y-%m")
    assert not months.isin(cfg["exclude"]).any()
    assert not months.str.startswith(("2020", "2021")).any()
    # Everything outside the exclusion is kept: 2019 (12) + 2022-01..2026-08 (56).
    assert len(store) == 68
    assert months.is_unique and months.is_monotonic_increasing
    assert months.iloc[0] == "2019-01" and months.iloc[-1] == "2026-08"


def test_method_period_boundaries(store):
    assert _row(store, "2023-10")["method_period"] == "2020-04"
    assert _row(store, "2023-11")["method_period"] == "2023-11"
    assert _row(store, "2024-12")["method_period"] == "2023-11"
    assert _row(store, "2025-01")["method_period"] == "2025-01"
    assert _row(store, "2026-08")["method_period"] == "2025-01"
    # step columns flip on the same boundaries
    assert (_row(store, "2023-10")["method_2023_11"], _row(store, "2023-11")["method_2023_11"]) == (0, 1)
    assert (_row(store, "2024-12")["method_2025_01"], _row(store, "2025-01")["method_2025_01"]) == (0, 1)


def test_step_columns_only_for_changes_inside_training(store, cfg):
    steps = sorted(c for c in store.columns if c.startswith("method_") and c != "method_period")
    assert steps == ["method_2023_11", "method_2025_01"]
    for gone in ("method_2019_02", "method_2020_04"):
        assert gone not in store.columns
    assert set(store["method_2023_11"].unique()) <= {0, 1}
    assert set(store["method_2025_01"].unique()) <= {0, 1}


def test_first_month_before_every_change_takes_the_first_period(store):
    # Jan 2019 predates every listed change, but MANIFEST restates it on the
    # Feb 2019 basis, so it belongs to the first period (never NaN).
    assert _row(store, "2019-01")["method_period"] == "2019-02"
    assert _row(store, "2019-02")["method_period"] == "2019-02"
    assert store["method_period"].notna().all()


def test_electrified_step(store, cfg):
    start = pd.Timestamp(cfg["electrification_start"] + "-01")
    assert (store.loc[store["timestamp"] < start, "electrified"] == 0).all()
    assert (store.loc[store["timestamp"] >= start, "electrified"] == 1).all()
    assert _row(store, "2024-08")["electrified"] == 0
    assert _row(store, "2024-09")["electrified"] == 1


def test_columns_match_bart_contract(store):
    for col in ("timestamp", "station_id", "ridership"):
        assert col in store.columns
    assert (store["station_id"] == "CALTRAIN_SYSTEM").all()
    # ridership is the AWR itself
    awr = pd.read_csv(ROOT / "data" / "caltrain" / "awr_monthly.csv")
    expect = dict(zip(awr["month"], awr["awr"], strict=True))
    got = dict(zip(store["timestamp"].dt.strftime("%Y-%m"), store["ridership"], strict=True))
    assert all(got[m] == expect[m] for m in got)
    assert got["2022-01"] == 9044
    # Same arrow types as the BART store for the shared columns, so the BART
    # model functions apply unchanged.
    bart = pq.read_schema(BART_STORE)
    import pyarrow as pa

    table = pa.Table.from_pandas(store, preserve_index=False)
    for col in ("timestamp", "station_id", "ridership"):
        assert table.schema.field(col).type == bart.field(col).type, col


def test_store_written_to_configured_path_and_hash_stable(cfg, tmp_path, capsys):
    a = tmp_path / "a.parquet"
    b = tmp_path / "b.parquet"
    build_caltrain_store({**cfg, "store_path": str(a)})
    out = capsys.readouterr().out
    build_caltrain_store({**cfg, "store_path": str(b)})
    digest = hashlib.sha256(a.read_bytes()).hexdigest()
    assert digest == hashlib.sha256(b.read_bytes()).hexdigest()
    assert digest in out  # the build prints the store's sha256


def test_committed_store_is_the_current_build(store):
    assert COMMITTED_STORE.exists(), "data/processed/caltrain_store.parquet must be committed"
    pd.testing.assert_frame_equal(pd.read_parquet(COMMITTED_STORE), store)


# --------------------------------------------------------------------------
# Per-station annual table

STATIONS = 29


@pytest.fixture(scope="module")
def stations() -> pd.DataFrame:
    return pd.read_csv(STATION_CSV, dtype={"station": str, "report_url": str})


def test_station_table_contract(stations):
    assert list(stations.columns) == ["fiscal_year", "station", "avg_midweek_boardings", "report_url"]
    # Only years with a published station-level table: the 2019 count (inside
    # FY2019) and the three annual reports FY2024-FY2026. FY2020-FY2023 do not exist.
    assert sorted(stations["fiscal_year"].unique()) == [2019, 2024, 2025, 2026]
    assert stations["avg_midweek_boardings"].dtype.kind == "i"
    assert (stations["avg_midweek_boardings"] > 0).all()
    assert not stations.duplicated(["fiscal_year", "station"]).any()


def test_station_table_same_29_stations_every_year(stations):
    sets = {y: set(g["station"]) for y, g in stations.groupby("fiscal_year")}
    assert all(len(s) == STATIONS for s in sets.values()), {y: len(s) for y, s in sets.items()}
    assert len({frozenset(s) for s in sets.values()}) == 1
    names = next(iter(sets.values()))
    assert {"South San Francisco", "California Ave", "San Jose Diridon"} <= names
    assert not {"So. San Francisco", "California Avenue", "California Ave."} & names


def test_station_table_matches_printed_totals(stations):
    by_year = stations.groupby("fiscal_year")["avg_midweek_boardings"].sum()
    # 2019: FY2026 report Table 3 (county) TOTAL. The 2019 count's own table I prints
    # 63,597 (its rows are "averaged over two days and rounded"); see MANIFEST.
    assert by_year[2019] == 63_606
    assert by_year[2024] == 23_477  # FY2024 report, table 6 TOTAL
    assert by_year[2025] == 32_448  # FY2026 report Table 3 (county) TOTAL, FY2025 column
    assert by_year[2026] == 44_262  # FY2026 report Table 3 (county) TOTAL
    sf = stations[(stations["station"] == "San Francisco")].set_index("fiscal_year")["avg_midweek_boardings"]
    assert sf.to_dict() == {2019: 15_027, 2024: 4_803, 2025: 6_874, 2026: 9_714}


def test_every_station_row_is_recorded_in_manifest(stations):
    text = MANIFEST.read_text()
    section = text.split("## Per-station annual table", 1)
    assert len(section) == 2, "MANIFEST.md needs a '## Per-station annual table' section"
    body = section[1]
    for r in stations.itertuples():
        pattern = re.compile(
            rf"^\|\s*{r.fiscal_year}\s*\|\s*{re.escape(r.station)}\s*\|\s*{r.avg_midweek_boardings:,}\s*\|"
            rf".*{re.escape(r.report_url)}",
            re.M,
        )
        assert pattern.search(body), f"MANIFEST has no evidence row for {r.fiscal_year} {r.station}"
