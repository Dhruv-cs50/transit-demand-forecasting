"""BART station lookup from the project's bundled monthly data.

Reads three files that ship in the image (``website/data``): station metadata,
typical monthly ridership and the SARIMA forecast. This is *monthly* context.
It says nothing about how crowded a station is right now, and every value
derived from it is labelled that way by the caller.

Place names arrive as Google writes them ("Powell St", "12th St / Oakland"),
which rarely equal the project's ("Powell St.", "12th St. Oakland City Center"),
so lookup is by normalised tokens and returns ``None`` rather than guess when
a name is unknown or ambiguous.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

LABEL = "monthly context, not live crowding"

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "website" / "data"

# Words Google adds or spells differently from the project's station names.
_DROP = {"station", "bart", "the"}
_REWRITE = {"street": "st", "avenue": "ave", "boulevard": "blvd", "saint": "st"}
# Names a rider uses that share no tokens with the project's station name.
_ALIASES = {
    "sfo": "SO",
    "san francisco international airport": "SO",
    "san francisco airport": "SO",
    "oak": "OA",
    "oakland airport": "OA",
}
_FUZZY_CUTOFF = 0.88


def data_dir() -> Path:
    override = os.environ.get("STATION_DATA_DIR")
    return Path(override) if override else DEFAULT_DATA_DIR


def _tokens(text: str) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    words = re.findall(r"[a-z0-9]+", text)
    return tuple(_REWRITE.get(w, w) for w in words if w not in _DROP)


@lru_cache(maxsize=1)
def _load() -> dict:
    """``{bart_id: {"name", "typical_monthly", "forecast_month", "forecast_p50"}}``."""
    base = data_dir()
    meta = json.loads((base / "stations_meta.json").read_text(encoding="utf-8"))
    ridership = json.loads((base / "stations_ridership.json").read_text(encoding="utf-8"))
    forecasts = json.loads((base / "forecasts_sarima.json").read_text(encoding="utf-8"))

    # The latest SARIMA month in the data: the forecast nearest to today.
    latest_forecast: dict[str, dict] = {}
    for row in forecasts:
        sid = str(row["station_id"])
        if sid not in latest_forecast or row["month"] > latest_forecast[sid]["month"]:
            latest_forecast[sid] = row

    stations: dict[str, dict] = {}
    for row in meta:
        sid = row["bart_id"]
        rid = ridership.get(sid, {})
        fc = latest_forecast.get(sid)
        if not rid or fc is None:
            continue
        stations[sid] = {
            "name": rid.get("station_name") or row["station_name"],
            "typical_monthly": int(round(rid["avg_monthly_ridership"])),
            "forecast_month": fc["month"],
            "forecast_p50": int(round(fc["p50"])),
        }
    return stations


def reset() -> None:
    """Drop the loaded data (tests point ``STATION_DATA_DIR`` elsewhere)."""
    _load.cache_clear()


def _best(query: tuple[str, ...], index: dict[str, tuple[str, ...]]) -> str | None:
    wanted = set(query)

    exact = [sid for sid, toks in index.items() if toks == query]
    if len(exact) == 1:
        return exact[0]

    # One name's words inside the other's: "12th St / Oakland" and
    # "12th St. Oakland City Center". Several candidates means the name is
    # ambiguous ("Oakland", "Berkeley"), so there is no answer.
    nested = [
        sid
        for sid, toks in index.items()
        if wanted <= set(toks) or set(toks) <= wanted
    ]
    if nested:
        return nested[0] if len(nested) == 1 else None

    joined = " ".join(query)
    scored = sorted(
        (
            (difflib.SequenceMatcher(None, joined, " ".join(toks)).ratio(), sid)
            for sid, toks in index.items()
        ),
        reverse=True,
    )
    close = [(r, sid) for r, sid in scored if r >= _FUZZY_CUTOFF]
    if len(close) == 1 or (len(close) > 1 and close[0][0] > close[1][0]):
        return close[0][1]
    return None


def find_station(name: str) -> dict | None:
    """The station record for ``name``, or ``None`` if unknown or ambiguous."""
    query = _tokens(name)
    if not query:
        return None
    stations = _load()
    alias = _ALIASES.get(" ".join(query))
    if alias:
        return stations.get(alias)
    index = {sid: _tokens(rec["name"]) for sid, rec in stations.items()}
    sid = _best(query, index)
    return stations[sid] if sid else None
