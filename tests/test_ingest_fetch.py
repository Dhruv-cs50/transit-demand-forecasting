"""
tests/test_ingest_fetch.py
──────────────────────────
S9-04: the closed-month fetchers of the cloud ingestion job
(machine_learning_files/ingest_fetch.py; docs/cloud-ingestion-design.md §2 step 1).

Fake clients and a LocalStorage directory: no network, no GCP, no google or
(in the Python 3.11 serving env) `requests` library.

Run from the repository root:
    python -m pytest -q tests/test_ingest_fetch.py
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import io
import sys
import types

import pandas as pd
import pytest

from machine_learning_files import ingest_fetch
from machine_learning_files.cloud_store import LocalStorage
from machine_learning_files.ingest_fetch import (
    FetchResult,
    fetch_sharks,
    fetch_weather,
    fetch_window,
    last_closed_month_end,
    year_windows,
)

D = dt.date

STATIONS = {
    "diridon":      {"lat": 37.3294, "lng": -121.9022},
    "embarcadero":  {"lat": 37.7929, "lng": -122.3969},
    "millbrae":     {"lat": 37.5994, "lng": -122.3869},
}
CFG = {
    "fetch_floor": "2026-01-01",
    "archive_lag_days": 7,
    "sources": {"weather": {"station_coords": STATIONS}, "nhl": {"sharks_team_id": "SJS"}},
}
TODAY = D(2026, 10, 28)

WEATHER_2026 = "raw/weather/weather_all_stations_2026-01-01_2026-09-30.parquet"
EVENTS_2026 = "raw/events/events_2026-01-01_2026-09-30.parquet"


@pytest.fixture(autouse=True)
def _requests_stub(monkeypatch):
    """fetch_events imports `requests` at module load. The Python 3.11 serving
    env does not have it, and these tests never make a request."""
    if importlib.util.find_spec("requests") is None:
        monkeypatch.setitem(sys.modules, "requests", types.ModuleType("requests"))


@pytest.fixture
def store(tmp_path):
    return LocalStorage(tmp_path / "bucket")


# ── fakes ─────────────────────────────────────────────────────────────────────

class FakeOpenMeteo:
    """OpenMeteoClient.get_historical's contract, with a switch for each failure."""

    def __init__(self, *, fail_on_lat=None, short_by=0, nan_temp=False):
        self.calls: list[tuple] = []
        self.fail_on_lat, self.short_by, self.nan_temp = fail_on_lat, short_by, nan_temp

    def get_historical(self, lat, lng, start, end, timezone="America/Los_Angeles"):
        self.calls.append((lat, lng, start, end))
        if lat == self.fail_on_lat:
            raise RuntimeError("Open-Meteo is down")
        hours = ((end - start).days + 1) * 24 - self.short_by
        df = pd.DataFrame({
            "timestamp": pd.date_range(start, periods=hours, freq="h"),
            "temp_f": 60.0, "precip_in": 0.0, "precip_mm": 0.0,
            "windspeed_mph": 5.0, "cloud_cover_pct": 10.0, "humidity_pct": 50.0,
            "weather_code": 0, "weather_desc": "Clear sky", "is_raining": False,
            "lat": lat, "lng": lng,
        })
        if self.nan_temp:
            df.loc[3, "temp_f"] = float("nan")
        return df


class FakeNHL:
    """NHLClient.get_schedule's contract. `games` are local game dates."""

    def __init__(self, games, *, empty=False):
        self.games, self.empty = list(games), empty
        self.calls: list[tuple] = []

    def get_schedule(self, team, start, end):
        self.calls.append((team, start, end))
        if self.empty:
            return pd.DataFrame()
        rows = [{
            "game_id": 2000 + i,
            "timestamp_start": pd.Timestamp(f"{d.isoformat()} 19:00", tz="America/Los_Angeles"),
            "timestamp_end": pd.Timestamp(f"{d.isoformat()} 22:00", tz="America/Los_Angeles"),
            "event_name": f"Sharks vs OPP{i}", "event_type": "NHL Hockey", "venue": "sap_center",
            "is_sharks_game": True, "home_or_away": "home", "game_type": 2, "season": "20252026",
            "lat": 37.3327, "lng": -121.9010,
        } for i, d in enumerate(self.games) if start <= d <= end]
        return pd.DataFrame(rows)


def jan_to_sep_games():
    return [D(2026, 1, 8), D(2026, 2, 14), D(2026, 4, 2), D(2026, 9, 21), D(2026, 9, 30)]


def put_parquet(store, name, rows: int, **cols):
    buf = io.BytesIO()
    pd.DataFrame({"x": range(rows), **cols}).to_parquet(buf, index=False)
    return store.write_bytes(name, buf.getvalue(), if_generation_match=None)


def read_rows(store, name) -> int:
    return len(pd.read_parquet(io.BytesIO(store.read_bytes(name)[0])))


def names(store):
    return [o.name for o in store.list("raw/")]


# ── the window ────────────────────────────────────────────────────────────────

def test_the_window_for_2026_10_28_runs_through_2026_09_30():
    assert last_closed_month_end(D(2026, 10, 28), 7) == D(2026, 9, 30)
    assert fetch_window(D(2026, 10, 28), D(2026, 1, 1)) == (D(2026, 1, 1), D(2026, 9, 30))


@pytest.mark.parametrize("today, expected", [
    (D(2026, 11, 7), D(2026, 10, 31)),    # October ended exactly 7 days ago: closed
    (D(2026, 11, 6), D(2026, 9, 30)),     # 6 days ago: still open
    (D(2026, 10, 7), D(2026, 9, 30)),
    (D(2026, 10, 6), D(2026, 8, 31)),
    (D(2027, 1, 7), D(2026, 12, 31)),     # across New Year
    (D(2027, 1, 6), D(2026, 11, 30)),
    (D(2028, 3, 7), D(2028, 2, 29)),      # leap day
])
def test_last_closed_month_end_boundary(today, expected):
    assert last_closed_month_end(today, 7) == expected


def test_a_different_lag_moves_the_boundary():
    assert last_closed_month_end(D(2026, 10, 28), 28) == D(2026, 9, 30)
    assert last_closed_month_end(D(2026, 10, 27), 28) == D(2026, 8, 31)


def test_the_floor_guard():
    floor = D(2026, 1, 1)
    # Nothing at or after the floor has closed yet.
    assert fetch_window(D(2026, 1, 20), floor) is None
    assert fetch_window(D(2026, 2, 3), floor) is None          # Jan 31 + 7 = Feb 7
    assert fetch_window(D(2026, 2, 7), floor) == (floor, D(2026, 1, 31))
    # A later floor starts later, and an earlier month is never reached.
    assert fetch_window(D(2026, 10, 28), D(2026, 3, 15)) == (D(2026, 3, 15), D(2026, 9, 30))
    assert fetch_window(D(2026, 10, 28), D(2026, 10, 1)) is None
    assert fetch_window(D(2026, 10, 28), D(2026, 1, 1))[0] == D(2026, 1, 1)


def test_a_window_across_new_year_is_cut_per_year():
    assert year_windows(D(2027, 2, 10), D(2026, 1, 1)) == [
        (D(2026, 1, 1), D(2026, 12, 31)), (D(2027, 1, 1), D(2027, 1, 31))]
    assert year_windows(D(2026, 10, 28), D(2026, 1, 1)) == [(D(2026, 1, 1), D(2026, 9, 30))]
    assert year_windows(D(2026, 1, 5), D(2026, 1, 1)) == []


def test_nothing_is_fetched_or_written_before_the_floor(store):
    cfg = dict(CFG)
    om, nhl = FakeOpenMeteo(), FakeNHL(jan_to_sep_games())
    w = fetch_weather(store, cfg, D(2026, 1, 20), client=om)
    s = fetch_sharks(store, cfg, D(2026, 1, 20), client=nhl)
    assert [r.status for r in w + s] == ["skipped", "skipped"]
    assert om.calls == [] and nhl.calls == []
    assert store.list() == []


def test_the_hand_seeded_archives_are_never_touched(store):
    seeded = [
        "raw/weather/weather_all_stations_2019-01-01_2023-12-31.parquet",
        "raw/weather/weather_all_stations_2024-01-01_2025-12-31.parquet",
        "raw/events/events_2019-01-01_2023-12-31.parquet",
        "raw/events/events_2024-01-01_2025-12-31.parquet",
        "raw/weather/weather_all_stations_2025-01-01_2025-12-31.parquet",   # one year, below the floor
    ]
    gens = {n: put_parquet(store, n, 500).generation for n in seeded}

    fetch_weather(store, CFG, TODAY, client=FakeOpenMeteo())
    fetch_sharks(store, CFG, TODAY, client=FakeNHL(jan_to_sep_games()))

    for n in seeded:
        assert store.read_bytes(n)[1] == gens[n], f"{n} was rewritten"
        assert read_rows(store, n) == 500
    assert WEATHER_2026 in names(store) and EVENTS_2026 in names(store)


# ── weather ───────────────────────────────────────────────────────────────────

def test_weather_object_name_rows_and_columns(store):
    om = FakeOpenMeteo()
    [res] = fetch_weather(store, CFG, TODAY, client=om)

    assert res == FetchResult("weather", WEATHER_2026, 3 * 273 * 24, "written", res.detail)
    assert names(store) == [WEATHER_2026]
    assert [(c[2], c[3]) for c in om.calls] == [(D(2026, 1, 1), D(2026, 9, 30))] * 3
    df = pd.read_parquet(io.BytesIO(store.read_bytes(WEATHER_2026)[0]))
    assert len(df) == 3 * 273 * 24                    # 273 days Jan..Sep 2026
    assert set(df["station"]) == set(STATIONS)
    assert {"timestamp", "temp_f", "precip_mm", "precip_in", "windspeed_mph", "is_raining",
            "weather_code", "cloud_cover_pct", "humidity_pct", "station"} <= set(df.columns)


def test_names_are_deterministic_for_a_given_day(tmp_path):
    a, b = LocalStorage(tmp_path / "a"), LocalStorage(tmp_path / "b")
    fetch_weather(a, CFG, TODAY, client=FakeOpenMeteo())
    fetch_weather(b, CFG, D(2026, 10, 31), client=FakeOpenMeteo())    # same window
    assert names(a) == names(b) == [WEATHER_2026]


def test_a_second_run_fetches_nothing_and_does_not_rewrite(store):
    fetch_weather(store, CFG, TODAY, client=FakeOpenMeteo())
    gen = store.read_bytes(WEATHER_2026)[1]

    om = FakeOpenMeteo()
    [res] = fetch_weather(store, CFG, D(2026, 10, 29), client=om)

    assert res.status == "unchanged" and res.rows == 3 * 273 * 24
    assert om.calls == []
    assert store.read_bytes(WEATHER_2026)[1] == gen      # same generation: the fingerprint holds


def test_a_newer_same_year_object_replaces_and_deletes_the_older(store):
    fetch_weather(store, CFG, TODAY, client=FakeOpenMeteo())
    assert names(store) == [WEATHER_2026]

    [res] = fetch_weather(store, CFG, D(2026, 11, 20), client=FakeOpenMeteo())    # October closed

    newer = "raw/weather/weather_all_stations_2026-01-01_2026-10-31.parquet"
    assert res.status == "written" and res.object_name == newer
    assert WEATHER_2026 in res.detail                    # says what it deleted
    assert names(store) == [newer]
    assert read_rows(store, newer) == 3 * 304 * 24


def test_a_window_across_new_year_writes_one_object_per_year(store):
    results = fetch_weather(store, CFG, D(2027, 2, 10), client=FakeOpenMeteo())
    assert [r.status for r in results] == ["written", "written"]
    assert names(store) == [
        "raw/weather/weather_all_stations_2026-01-01_2026-12-31.parquet",
        "raw/weather/weather_all_stations_2027-01-01_2027-01-31.parquet"]


def test_a_wider_existing_same_year_object_is_left_alone(store):
    wide = "raw/weather/weather_all_stations_2026-01-01_2026-12-31.parquet"
    gen = put_parquet(store, wide, 10).generation
    om = FakeOpenMeteo()
    [res] = fetch_weather(store, CFG, TODAY, client=om)
    assert res.status == "unchanged" and om.calls == []
    assert names(store) == [wide] and store.read_bytes(wide)[1] == gen


def test_weather_refuses_to_replace_an_object_with_fewer_rows(store):
    older = "raw/weather/weather_all_stations_2026-01-01_2026-08-31.parquet"
    put_parquet(store, older, 1_000_000)               # more rows than a fresh fetch can give
    gen = store.read_bytes(older)[1]

    [res] = fetch_weather(store, CFG, TODAY, client=FakeOpenMeteo())

    assert res.status == "refused" and res.failed
    assert "1000000" in res.detail
    assert names(store) == [older] and store.read_bytes(older)[1] == gen


@pytest.mark.parametrize("client", [
    FakeOpenMeteo(fail_on_lat=STATIONS["millbrae"]["lat"]),    # a location raises
    FakeOpenMeteo(short_by=5),                                  # a location comes back short
    FakeOpenMeteo(nan_temp=True),                               # holes in temperature
], ids=["raises", "short", "nan"])
def test_a_weather_failure_writes_nothing(store, client):
    older = "raw/weather/weather_all_stations_2026-01-01_2026-08-31.parquet"
    put_parquet(store, older, 10)
    before = [(o.name, o.generation) for o in store.list()]

    [res] = fetch_weather(store, CFG, TODAY, client=client)

    assert res.status == "failed" and res.failed and res.rows == 0
    assert [(o.name, o.generation) for o in store.list()] == before     # nothing written, nothing deleted


def test_a_weather_failure_with_an_empty_bucket_leaves_it_empty(store):
    [res] = fetch_weather(store, CFG, TODAY, client=FakeOpenMeteo(fail_on_lat=STATIONS["diridon"]["lat"]))
    assert res.status == "failed"
    assert store.list() == []


def test_dry_run_fetches_but_writes_nothing(store):
    class ReadOnly:
        dry_run = True

        def __init__(self, inner):
            self._inner = inner

        def list(self, prefix=""):
            return self._inner.list(prefix)

        def read_bytes(self, name):
            return self._inner.read_bytes(name)

        def write_bytes(self, *a, **k):
            raise AssertionError("dry run wrote")

        def delete(self, *a, **k):
            raise AssertionError("dry run deleted")

    om = FakeOpenMeteo()
    [res] = fetch_weather(ReadOnly(store), CFG, TODAY, client=om)
    assert res.status == "dry-run" and len(om.calls) == 3
    assert store.list() == []


# ── Sharks ────────────────────────────────────────────────────────────────────

def test_sharks_object_name_and_columns(store):
    nhl = FakeNHL(jan_to_sep_games())
    [res] = fetch_sharks(store, CFG, TODAY, client=nhl)

    assert res.status == "written" and res.object_name == EVENTS_2026 and res.rows == 5
    assert names(store) == [EVENTS_2026]
    df = pd.read_parquet(io.BytesIO(store.read_bytes(EVENTS_2026)[0]))
    assert df["timestamp_start"].is_monotonic_increasing
    # enrich_events ran, as fetch_all() does.
    assert {"is_game_day", "game_start_hour", "is_weekend_event", "is_playoff",
            "is_sharks_game", "venue", "event_name"} <= set(df.columns)
    assert df["is_game_day"].all() and not df["is_playoff"].any()
    assert nhl.calls[0][0] == "SJS" and nhl.calls[0][1] == D(2026, 1, 1)


def test_sharks_query_reaches_october_but_the_object_stops_at_the_window(store):
    """NHLClient only visits next season when the query end reaches 1 October;
    games after the window are cut."""
    nhl = FakeNHL(jan_to_sep_games() + [D(2026, 10, 3), D(2026, 10, 20)])
    [res] = fetch_sharks(store, CFG, TODAY, client=nhl)

    assert nhl.calls[0][2] == D(2026, 10, 1)             # widened to reach the next season
    assert res.rows == 5                                 # 3 Oct games would not have been closed
    df = pd.read_parquet(io.BytesIO(store.read_bytes(EVENTS_2026)[0]))
    assert df["timestamp_start"].dt.tz_localize(None).max() < pd.Timestamp("2026-10-01")


def test_sharks_second_run_is_unchanged(store):
    fetch_sharks(store, CFG, TODAY, client=FakeNHL(jan_to_sep_games()))
    gen = store.read_bytes(EVENTS_2026)[1]
    nhl = FakeNHL(jan_to_sep_games())
    [res] = fetch_sharks(store, CFG, D(2026, 10, 30), client=nhl)
    assert res.status == "unchanged" and nhl.calls == []
    assert store.read_bytes(EVENTS_2026)[1] == gen


def test_sharks_same_year_replace_and_delete(store):
    older = "raw/events/events_2026-01-01_2026-08-31.parquet"
    fetch_sharks(store, CFG, D(2026, 9, 20), client=FakeNHL(jan_to_sep_games()))
    assert names(store) == [older]

    [res] = fetch_sharks(store, CFG, TODAY, client=FakeNHL(jan_to_sep_games()))

    assert res.status == "written" and res.object_name == EVENTS_2026
    assert names(store) == [EVENTS_2026]
    assert read_rows(store, EVENTS_2026) == 5


def test_sharks_refuses_to_replace_an_object_with_fewer_rows(store):
    older = "raw/events/events_2026-01-01_2026-08-31.parquet"
    fetch_sharks(store, CFG, D(2026, 9, 20), client=FakeNHL(jan_to_sep_games()))      # 3 games by 08-31
    rows_before = read_rows(store, older)
    gen = store.read_bytes(older)[1]

    # The NHL client swallowed a failing season and returned a thinner answer.
    [res] = fetch_sharks(store, CFG, TODAY, client=FakeNHL([D(2026, 1, 8)]))

    assert res.status == "refused" and res.failed
    assert names(store) == [older]
    assert store.read_bytes(older)[1] == gen and read_rows(store, older) == rows_before


def test_a_sharks_failure_writes_nothing(store):
    [res] = fetch_sharks(store, CFG, TODAY, client=FakeNHL([], empty=True))
    assert res.status == "failed" and res.failed
    assert store.list() == []

    class Boom:
        def get_schedule(self, *a):
            raise RuntimeError("NHL API down")

    [res] = fetch_sharks(store, CFG, TODAY, client=Boom())
    assert res.status == "failed" and "NHL API down" in res.detail
    assert store.list() == []


def test_a_failure_does_not_stop_the_other_source(store):
    w = fetch_weather(store, CFG, TODAY, client=FakeOpenMeteo(fail_on_lat=STATIONS["diridon"]["lat"]))
    s = fetch_sharks(store, CFG, TODAY, client=FakeNHL(jan_to_sep_games()))
    assert [r.status for r in w] == ["failed"] and [r.status for r in s] == ["written"]
    assert names(store) == [EVENTS_2026]


def test_sources_come_from_configs_sources_yaml_when_cfg_has_none(store):
    cfg = {"fetch_floor": "2026-01-01", "archive_lag_days": 7}
    om = FakeOpenMeteo()
    [res] = fetch_weather(store, cfg, TODAY, client=om)
    assert res.status == "written"
    assert len(om.calls) == 7                            # the 7 locations of configs/sources.yaml
    nhl = FakeNHL(jan_to_sep_games())
    fetch_sharks(store, cfg, TODAY, client=nhl)
    assert nhl.calls[0][0] == "SJS"


def test_module_defaults_match_the_config_contract():
    assert ingest_fetch.DEFAULT_ARCHIVE_LAG_DAYS == 7
    assert ingest_fetch.DEFAULT_FETCH_FLOOR == D(2026, 1, 1)
