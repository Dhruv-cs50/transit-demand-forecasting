"""
Covariate zero-fill guard (S8-09).

A month that no weather or event archive covers must read as unknown (<NA> for
a flag, NaN for a number), not as "no game" / "dry". A month the archive covers
with nothing in it stays False / 0. These tests pin both sides, for
merge_pipeline.compute_event_features and Processing.feature_engineering.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from machine_learning_files import merge_pipeline as mp  # noqa: E402
from machine_learning_files.merge_pipeline import (  # noqa: E402
    compute_event_features,
    event_coverage,
    file_event_coverage,
    merge_coverage,
    months_covered,
    unknown_event_features,
)
from Processing.feature_engineering import add_event_features, add_weather_features  # noqa: E402

LA = "America/Los_Angeles"
FLAGS = ["is_game_day", "is_sharks_game", "is_playoff"]


def _events(*dates: str) -> pd.DataFrame:
    """Sharks home games at 19:00 LA on the given dates."""
    ts = pd.to_datetime(list(dates)) + pd.Timedelta(hours=19)
    return pd.DataFrame({
        "timestamp_start": ts.tz_localize(LA),
        "venue": "SAP Center",
        "event_name": [f"game {d}" for d in dates],
        "is_sharks_game": True,
        "is_playoff": False,
        "game_start_hour": 19,
    })


def _with_coverage(events: pd.DataFrame, *files: str) -> pd.DataFrame:
    """Attach coverage as the loaders do, from (events subset, filename) pairs."""
    spans = []
    for name in files:
        start, end = name[len("events_"):-len(".parquet")].split("_")
        part = events[
            (events["timestamp_start"].dt.tz_localize(None) >= start)
            & (events["timestamp_start"].dt.tz_localize(None) <= pd.Timestamp(end) + pd.Timedelta(days=1))
        ]
        spans.append(file_event_coverage(part, Path(name)))
    out = events.copy()
    out.attrs["coverage"] = merge_coverage(spans)
    return out


def _months(*months: str) -> pd.Series:
    return pd.Series(pd.to_datetime([f"{m}-01" for m in months]))


def _is_na(series: pd.Series) -> list[bool]:
    return series.isna().tolist()


# ── Coverage spans ─────────────────────────────────────────────────────────────

def test_file_coverage_starts_at_first_event_not_filename():
    ev = _events("2019-09-17", "2019-10-03")
    start, end = file_event_coverage(ev, Path("events_2019-01-01_2023-12-31.parquet"))
    assert start == pd.Timestamp("2019-09-01")
    assert end == pd.Timestamp("2023-12-31")


def test_file_coverage_unparseable_name_ends_with_last_event_month():
    ev = _events("2025-12-04")
    start, end = file_event_coverage(ev, Path("events_latest.parquet"))
    assert (start, end) == (pd.Timestamp("2025-12-01"), pd.Timestamp("2025-12-31"))


def test_file_coverage_of_empty_file_is_none():
    assert file_event_coverage(_events().iloc[0:0], Path("events_2024-01-01_2025-12-31.parquet")) is None


def test_merge_coverage_joins_touching_spans_and_keeps_gaps():
    d = pd.Timestamp
    joined = merge_coverage([(d("2024-01-01"), d("2025-12-31")), (d("2019-09-01"), d("2023-12-31"))])
    assert joined == [(d("2019-09-01"), d("2025-12-31"))]
    gapped = merge_coverage([(d("2019-09-01"), d("2021-12-31")), (d("2023-01-01"), d("2023-12-31"))])
    assert len(gapped) == 2


def test_months_covered_needs_the_whole_month():
    cov = [(pd.Timestamp("2019-09-01"), pd.Timestamp("2019-10-15"))]
    got = months_covered(_months("2019-08", "2019-09", "2019-10", "2019-11"), cov)
    assert got.tolist() == [False, True, False, False]


# ── merge_pipeline.compute_event_features ──────────────────────────────────────

def test_uncovered_month_is_unknown_and_covered_empty_month_is_zero():
    # Archive covers Sep 2019 .. Dec 2019; the Sharks play in Sep and Nov.
    ev = _with_coverage(
        _events("2019-09-17", "2019-11-05", "2019-11-09"),
        "events_2019-01-01_2019-12-31.parquet",
    )
    stamps = _months("2019-05", "2019-09", "2019-10", "2019-11", "2020-03")
    out = compute_event_features(stamps, ev)

    # before the first archived game: unknown
    assert out.loc[0, ["is_game_day", "is_sharks_game", "is_playoff"]].isna().all()
    assert np.isnan(out.loc[0, "hours_to_event"])
    # a covered month with games
    assert out.loc[1, "is_game_day"] == True  # noqa: E712
    assert out.loc[3, "hours_to_event"] == 2.0
    # a covered month with no game: a real zero
    assert out.loc[2, "is_game_day"] == False  # noqa: E712
    assert out.loc[2, "is_sharks_game"] == False  # noqa: E712
    assert out.loc[2, "is_playoff"] == False  # noqa: E712
    assert out.loc[2, "hours_to_event"] == 0.0
    # after the archive's end: unknown
    assert out.loc[4, FLAGS].isna().all()
    assert np.isnan(out.loc[4, "hours_to_event"])


def test_rebuild_without_the_2024_25_file_leaves_those_months_unknown():
    # docs/covariate-experiment.md: a store rebuilt without the 2024-25 Sharks
    # file used to produce zeros for those months.
    historical = _events("2019-09-17", "2023-11-02")
    ev = _with_coverage(historical, "events_2019-01-01_2023-12-31.parquet")
    out = compute_event_features(_months("2023-11", "2024-01", "2025-03"), ev)
    assert out.loc[0, "is_game_day"] == True  # noqa: E712
    assert out.loc[1:, FLAGS].isna().all().all()
    assert out.loc[1:, "hours_to_event"].isna().all()


def test_both_files_cover_2024_25_games_and_the_offseason_between_them():
    ev = _with_coverage(
        _events("2019-09-17", "2023-11-02", "2024-01-12", "2025-12-05"),
        "events_2019-01-01_2023-12-31.parquet",
        "events_2024-01-01_2025-12-31.parquet",
    )
    out = compute_event_features(_months("2024-01", "2024-07", "2025-12"), ev)
    assert out["is_game_day"].tolist() == [True, False, True]
    assert out["hours_to_event"].tolist() == [1.0, 0.0, 1.0]


def test_a_missing_middle_file_is_a_gap_not_a_run_of_zeros():
    ev = _with_coverage(
        _events("2019-09-17", "2024-01-12"),
        "events_2019-01-01_2019-12-31.parquet",
        "events_2024-01-01_2024-12-31.parquet",
    )
    out = compute_event_features(_months("2019-11", "2021-06", "2024-01"), ev)
    assert _is_na(out["is_game_day"]) == [False, True, False]


def test_no_archive_at_all_is_unknown_everywhere():
    stamps = _months("2019-09", "2024-01")
    for events in (pd.DataFrame(), _events().iloc[0:0]):
        out = compute_event_features(stamps, events)
        assert out[FLAGS].isna().all().all()
        assert out["hours_to_event"].isna().all()
    assert unknown_event_features(stamps.index)[FLAGS].isna().all().all()


def test_frame_without_recorded_coverage_spans_first_to_last_event_month():
    ev = _events("2019-09-17", "2019-11-05")
    assert event_coverage(ev) == [(pd.Timestamp("2019-09-01"), pd.Timestamp("2019-11-30"))]
    out = compute_event_features(_months("2019-08", "2019-10", "2019-12"), ev)
    assert _is_na(out["is_game_day"]) == [True, False, True]
    assert out.loc[1, "is_game_day"] == False  # noqa: E712


def test_event_flags_are_nullable_boolean_and_survive_parquet():
    ev = _with_coverage(_events("2019-09-17"), "events_2019-01-01_2019-12-31.parquet")
    out = compute_event_features(_months("2019-05", "2019-09", "2019-10"), ev)
    for col in FLAGS:
        assert str(out[col].dtype) == "boolean"
    assert out["hours_to_event"].dtype == np.float64

    buf = io.BytesIO()
    out.to_parquet(buf)
    buf.seek(0)
    back = pd.read_parquet(buf)
    for col in FLAGS:
        assert str(back[col].dtype) == "boolean", f"{col} came back as {back[col].dtype}"
    pd.testing.assert_frame_equal(back, out)
    # `~` must stay a logical NOT that keeps <NA>, not a bitwise invert.
    assert (~back["is_game_day"]).tolist()[1:] == [False, True]
    assert (~back["is_game_day"]).isna().tolist() == [True, False, False]


def test_load_events_records_coverage_from_files(tmp_path, monkeypatch):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    _events("2019-09-17", "2023-11-02").to_parquet(events_dir / "events_2019-01-01_2023-12-31.parquet")
    monkeypatch.setattr(mp, "RAW_DIR", tmp_path)
    loaded = mp.load_events()
    assert event_coverage(loaded) == [(pd.Timestamp("2019-09-01"), pd.Timestamp("2023-12-31"))]
    out = compute_event_features(_months("2019-03", "2020-07", "2024-02"), loaded)
    assert _is_na(out["is_game_day"]) == [True, False, True]
    assert out.loc[1, "is_game_day"] == False  # noqa: E712


def test_build_feature_store_without_events_writes_unknown_not_false(tmp_path, monkeypatch):
    transit = pd.DataFrame({
        "timestamp": pd.to_datetime(["2022-01-01", "2022-02-01"]),
        "station_id": ["EM", "EM"],
        "ridership": [100.0, 110.0],
    })
    monkeypatch.setattr(mp, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(mp, "load_configs", lambda: ({"weather": {"station_coords": {}}}, {}))
    monkeypatch.setattr(mp, "load_transit", lambda freq: transit.copy())
    monkeypatch.setattr(mp, "load_weather", lambda freq, coords: pd.DataFrame())
    monkeypatch.setattr(mp, "load_events", lambda: pd.DataFrame())
    store = mp.build_feature_store(freq="MS")
    assert store[FLAGS].isna().all().all()
    assert store["hours_to_event"].isna().all()
    assert len(store) == 2


# ── feature_engineering: events ────────────────────────────────────────────────

def _station_months(*months: str) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.to_datetime([f"{m}-01" for m in months]),
        "station_id": "EM",
        "ridership": 1000.0,
    })


EVENT_FEATURE_FLAGS = ["is_sharks_game_window", "is_any_event_day", "is_pre_event_window", "is_post_event_window"]
EVENT_FEATURE_NUMBERS = ["event_proximity_score", "nearest_event_attendance_tier",
                         "hours_to_next_event", "hours_since_last_event"]


def test_monthly_event_features_unknown_outside_coverage_zero_inside():
    ev = _with_coverage(
        _events("2019-09-17", "2019-11-05", "2019-11-09"),
        "events_2019-01-01_2019-12-31.parquet",
    )
    df = add_event_features(_station_months("2019-05", "2019-09", "2019-10", "2019-11", "2020-03"), ev)

    assert df.loc[0, EVENT_FEATURE_FLAGS].isna().all()
    assert df.loc[0, ["event_proximity_score", "nearest_event_attendance_tier"]].isna().all()
    assert df.loc[4, EVENT_FEATURE_FLAGS].isna().all()

    # covered month, no game: False / 0
    assert df.loc[2, "is_sharks_game_window"] == False  # noqa: E712
    assert df.loc[2, "is_any_event_day"] == False  # noqa: E712
    assert df.loc[2, "event_proximity_score"] == 0.0
    assert df.loc[2, "nearest_event_attendance_tier"] == 0.0
    # covered month with games
    assert df.loc[3, "is_sharks_game_window"] == True  # noqa: E712
    assert df.loc[3, "nearest_event_attendance_tier"] == 2.0
    assert df.loc[3, "event_proximity_score"] == 1.0
    assert df.loc[1, "event_proximity_score"] == 0.5


def test_monthly_event_features_with_no_archive_do_not_crash_and_are_unknown():
    for events in (pd.DataFrame(), _events().iloc[0:0]):
        df = add_event_features(_station_months("2019-09", "2019-10"), events)
        assert df[EVENT_FEATURE_FLAGS].isna().all().all()
        assert df[EVENT_FEATURE_NUMBERS].isna().all().all()


def test_monthly_event_features_when_no_month_is_covered_do_not_crash():
    ev = _with_coverage(_events("2019-09-17"), "events_2019-01-01_2019-12-31.parquet")
    df = add_event_features(_station_months("2022-01", "2022-02"), ev)
    assert df[EVENT_FEATURE_FLAGS].isna().all().all()
    assert df["event_proximity_score"].isna().all()


def test_subdaily_event_rows_in_uncovered_months_are_unknown():
    ev = _with_coverage(_events("2019-09-17"), "events_2019-01-01_2019-12-31.parquet")
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(["2019-09-17 17:00", "2019-09-20 08:00", "2019-03-05 17:00", "2020-02-01 12:00"]),
        "station_id": "EM",
    })
    out = add_event_features(df, ev)
    assert out["is_sharks_game_window"].tolist()[:2] == [True, False]
    assert out["is_any_event_day"].isna().tolist() == [False, False, True, True]
    assert out["event_proximity_score"].isna().tolist() == [False, False, True, True]
    assert out["hours_to_next_event"].isna().tolist()[2:] == [True, True]
    assert out["nearest_event_attendance_tier"].tolist()[:2] == [2.0, 0.0]


# ── feature_engineering: weather ───────────────────────────────────────────────

def _weather(precip, temp=None, wind=None) -> pd.DataFrame:
    n = len(precip)
    return pd.DataFrame({
        "timestamp": pd.date_range("2022-01-01", periods=n, freq="MS"),
        "station_id": "EM",
        "precip_mm": precip,
        "temp_f": temp if temp is not None else [60.0] * n,
        "windspeed_mph": wind if wind is not None else [5.0] * n,
    })


def test_months_without_weather_are_unknown_not_dry_calm_or_mild():
    df = add_weather_features(_weather(
        precip=[0.0, np.nan, 3.0],
        temp=[60.0, np.nan, 95.0],
        wind=[5.0, np.nan, 25.0],
    ))
    for col in ("is_raining", "is_very_cold", "is_very_hot", "is_windy"):
        assert df.loc[1, col] is pd.NA, col
    assert np.isnan(df.loc[1, "weather_discomfort"])
    assert np.isnan(df.loc[1, "precip_intensity"])
    # measured months keep real values: a dry, mild month is False, not unknown
    assert df.loc[0, "is_raining"] == False  # noqa: E712
    assert df.loc[0, "is_very_cold"] == False  # noqa: E712
    assert df.loc[0, "weather_discomfort"] == 0.0
    assert df.loc[2, "is_raining"] == True  # noqa: E712
    assert df.loc[2, "is_very_hot"] == True  # noqa: E712
    assert df.loc[2, "is_windy"] == True  # noqa: E712


def test_rain_onset_is_a_logical_not_and_unknown_without_a_prior_month():
    df = add_weather_features(_weather(precip=[0.0, 1.0, 1.0, 0.0, 2.0]))
    assert df["is_rain_onset"].tolist() == [False, True, False, False, True]
    # raining in a station's first row, with no month before it: onset unknown,
    # not "no onset" (it used to be fillna(False))
    first = add_weather_features(_weather(precip=[1.0, 1.0]))
    assert first.loc[0, "is_rain_onset"] is pd.NA
    assert first.loc[1, "is_rain_onset"] == False  # noqa: E712


def test_rain_onset_after_a_month_without_weather_is_unknown():
    df = add_weather_features(_weather(precip=[0.0, np.nan, 1.0, 1.0]))
    assert df["is_rain_onset"].isna().tolist() == [False, True, True, False]
    assert df.loc[0, "is_rain_onset"] == False  # noqa: E712
    assert df.loc[3, "is_rain_onset"] == False  # noqa: E712


def test_weather_flags_are_nullable_boolean_and_survive_parquet():
    df = add_weather_features(_weather(precip=[0.0, np.nan]))
    buf = io.BytesIO()
    df.to_parquet(buf)
    buf.seek(0)
    back = pd.read_parquet(buf)
    for col in ("is_raining", "is_rain_onset", "is_very_cold", "is_very_hot", "is_windy"):
        assert str(back[col].dtype) == "boolean", col
