"""
machine_learning_files/bart_stations.py
────────────────────────────────────────
The one table of BART's 50 stations. Every station map in the repo (names,
website node ids, weather locations, API codes) should derive from STATIONS
here instead of keeping its own literal.

The feature store's `station_id` is BART's two-letter workbook code (`EM`,
`12`, ...): the code the monthly origin-destination ridership workbooks use
for their rows and columns. The four-letter BART API code (`EMBR`) is kept as
`api_code` for the consumers still keyed by it. Rows are in the workbooks'
row order.

Columns and where they come from:
    code             two-letter workbook code = the feature store's station_id
    api_code         four-letter BART API code
    name             fetch_bart_od.py's former STATION_NAMES[api_code], copied
                     verbatim; fetch_bart_od now imports API_CODE_TO_NAME
                     from here under that name
    website_id       node id in the `const BART = [ ... ];` array of
                     website/transit-demo.html (all 50 stations; the nine
                     added in S10-04 -- EP AS SH WC NC OA WS ML PC -- take
                     their coordinates from BART's GTFS stops.txt)
    weather_station  key of configs/sources.yaml `weather.station_coords` for
                     the six locations that name-match a BART station
                     (`diridon` has no BART station and stays regional-only)
    source           which evidence fixed the row; one of the five texts:

    SRC_META       META: name from website/data/stations_meta.json as
                   committed in c5f5891 (2026-05-07), equal to
                   STATION_NAMES[api_code]. (Its website node, where it has one,
                   was added in S10-04, not by this evidence.)
    SRC_META_MAPS  META+MAPS: META, plus website id from both c5f5891's
                   2-letter BART_CODE_TO_WEBSITE_ID and the 4-letter map that
                   replaced it.
    SRC_BF         BF: c5f5891's map entry "BF": "bayp" (Bay Fair), the
                   transit-demo.html node bayp "Bay Fair", and the 4-letter
                   map's BAYF -> bayp agree; c5f5891's stations_meta.json
                   left BF unnamed.
    SRC_USER       USER: not decidable from repo data. Elimination leaves ML
                   and WP for Milpitas and Pittsburg/Bay Point; ML has zero
                   ridership through 2019, as BE (Berryessa) does. Pairing
                   and the `pit` node confirmed by the user, 2026-10-22.
    SRC_META_PC    META_PC: META; c5f5891 gave website node `pit` to PC, the
                   user's 2026-10-22 ruling gives it to WP.

The module is stdlib-only at import time. check() imports yaml lazily, and
pandas only when given a feature store to compare against.

Usage:
    python machine_learning_files/bart_stations.py            # print the table
    python machine_learning_files/bart_stations.py --check
    python machine_learning_files/bart_stations.py --check \\
        --store data/processed/feature_store.parquet
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBSITE_HTML = REPO_ROOT / "website" / "transit-demo.html"
SOURCES_YAML = REPO_ROOT / "configs" / "sources.yaml"

SRC_META = (
    "META: name from website/data/stations_meta.json as committed in c5f5891 "
    "(2026-05-07), equal to STATION_NAMES[api_code]; no website node."
)
SRC_META_MAPS = (
    "META+MAPS: META, plus website id from both c5f5891's 2-letter "
    "BART_CODE_TO_WEBSITE_ID and the 4-letter map that replaced it."
)
SRC_BF = (
    "BF: c5f5891's map entry \"BF\": \"bayp\"  # Bay Fair, transit-demo.html "
    "node bayp \"Bay Fair\", and the 4-letter map's BAYF -> bayp agree. "
    "(c5f5891's stations_meta.json left BF unnamed.)"
)
SRC_USER = (
    "USER: not decidable from repo data: elimination leaves ML and WP for "
    "Milpitas and Pittsburg/Bay Point; ML has zero ridership through 2019, as "
    "BE (Berryessa) does. Pairing and the pit node confirmed by the user, "
    "2026-10-22."
)
SRC_META_PC = (
    "META_PC: META; c5f5891 gave website node pit to PC, the user's "
    "2026-10-22 ruling gives it to WP."
)


@dataclass(frozen=True)
class BartStation:
    code: str                    # two-letter workbook code = feature store station_id
    api_code: str                # four-letter BART API code
    name: str
    website_id: str | None       # node id in website/transit-demo.html's BART array
    weather_station: str | None  # key of sources.yaml weather.station_coords
    source: str                  # one of the SRC_* texts above


# Workbook row order. Names are fetch_bart_od's former STATION_NAMES, verbatim.
STATIONS: tuple[BartStation, ...] = (
    BartStation("RM", "RICH", "Richmond", "rich", None, SRC_META_MAPS),
    BartStation("EN", "DELN", "El Cerrito Del Norte", "elc", None, SRC_META_MAPS),
    BartStation("EP", "PLZA", "El Cerrito Plaza", "elp", None, SRC_META),
    BartStation("NB", "NBRK", "North Berkeley", "nbk", None, SRC_META_MAPS),
    BartStation("BK", "DBRK", "Downtown Berkeley", "bky", None, SRC_META_MAPS),
    BartStation("AS", "ASHB", "Ashby", "ash", None, SRC_META),
    BartStation("MA", "MCAR", "MacArthur", "mac", None, SRC_META_MAPS),
    BartStation("19", "19TH", "19th St. Oakland", "19th", "oakland_19th", SRC_META_MAPS),
    BartStation("12", "12TH", "12th St. Oakland City Center", "12th", None, SRC_META_MAPS),
    BartStation("LM", "LAKE", "Lake Merritt", "lkm", None, SRC_META_MAPS),
    BartStation("FV", "FTVL", "Fruitvale", "fvw", None, SRC_META_MAPS),
    BartStation("CL", "COLS", "Coliseum", "col", None, SRC_META_MAPS),
    BartStation("SL", "SANL", "San Leandro", "sl", None, SRC_META_MAPS),
    BartStation("BF", "BAYF", "Bay Fair", "bayp", None, SRC_BF),
    BartStation("HY", "HAYW", "Hayward", "hyw", None, SRC_META_MAPS),
    BartStation("SH", "SHAY", "South Hayward", "shy", None, SRC_META),
    BartStation("UC", "UCTY", "Union City", "unc", None, SRC_META_MAPS),
    BartStation("FM", "FRMT", "Fremont", "frm", "fremont_bart", SRC_META_MAPS),
    BartStation("CN", "CONC", "Concord", "ccd", None, SRC_META_MAPS),
    BartStation("PH", "PHIL", "Pleasant Hill/Contra Costa Centre", "plh", None, SRC_META_MAPS),
    BartStation("WC", "WCRK", "Walnut Creek", "wlc", None, SRC_META),
    BartStation("LF", "LAFY", "Lafayette", "lfy", None, SRC_META_MAPS),
    BartStation("OR", "ORIN", "Orinda", "orn", None, SRC_META_MAPS),
    BartStation("RR", "ROCK", "Rockridge", "rkr", None, SRC_META_MAPS),
    BartStation("OW", "WOAK", "West Oakland", "wo", None, SRC_META_MAPS),
    BartStation("EM", "EMBR", "Embarcadero", "emb", "embarcadero", SRC_META_MAPS),
    BartStation("MT", "MONT", "Montgomery St.", "mtg", None, SRC_META_MAPS),
    BartStation("PL", "POWL", "Powell St.", "pwl", None, SRC_META_MAPS),
    BartStation("CC", "CIVC", "Civic Center/UN Plaza", "cvc", None, SRC_META_MAPS),
    BartStation("16", "16TH", "16th St. Mission", "16th", None, SRC_META_MAPS),
    BartStation("24", "24TH", "24th St. Mission", "24th", None, SRC_META_MAPS),
    BartStation("GP", "GLEN", "Glen Park", "gln", None, SRC_META_MAPS),
    BartStation("BP", "BALB", "Balboa Park", "bls", None, SRC_META_MAPS),
    BartStation("DC", "DALY", "Daly City", "daly", None, SRC_META_MAPS),
    BartStation("CM", "COLM", "Colma", "colm", None, SRC_META_MAPS),
    BartStation("CV", "CAST", "Castro Valley", "cas", None, SRC_META_MAPS),
    BartStation("ED", "DUBL", "Dublin/Pleasanton", "dub", None, SRC_META_MAPS),
    BartStation("NC", "NCON", "North Concord/Martinez", "ncn", None, SRC_META),
    BartStation("WP", "PITT", "Pittsburg/Bay Point", "pit", None, SRC_USER),
    BartStation("SS", "SSAN", "South San Francisco", "ssf", None, SRC_META_MAPS),
    BartStation("SB", "SBRN", "San Bruno", "sbr", None, SRC_META_MAPS),
    BartStation("SO", "SFIA", "SFO", "sfo", "sfo", SRC_META_MAPS),
    BartStation("MB", "MLBR", "Millbrae", "mil", "millbrae", SRC_META_MAPS),
    BartStation("WD", "WDUB", "West Dublin/Pleasanton", "wdb", None, SRC_META_MAPS),
    BartStation("OA", "OAKL", "Oakland International Airport", "oak", None, SRC_META),
    BartStation("WS", "WARM", "Warm Springs/South Fremont", "wsp", None, SRC_META),
    BartStation("ML", "MLPT", "Milpitas", "mlp", None, SRC_USER),
    BartStation("BE", "BERY", "Berryessa/North San José", "brb", "berryessa", SRC_META_MAPS),
    BartStation("PC", "PCTR", "Pittsburg Center", "pcr", None, SRC_META_PC),
    BartStation("AN", "ANTC", "Antioch", "ant", None, SRC_META_MAPS),
)

BY_CODE: dict[str, BartStation] = {s.code: s for s in STATIONS}
CODES: tuple[str, ...] = tuple(s.code for s in STATIONS)
CODE_TO_NAME: dict[str, str] = {s.code: s.name for s in STATIONS}
CODE_TO_WEBSITE_ID: dict[str, str] = {
    s.code: s.website_id for s in STATIONS if s.website_id is not None
}
CODE_TO_WEATHER_STATION: dict[str, str] = {
    s.code: s.weather_station for s in STATIONS if s.weather_station is not None
}
API_TO_CODE: dict[str, str] = {s.api_code: s.code for s in STATIONS}
API_CODE_TO_NAME: dict[str, str] = {s.api_code: s.name for s in STATIONS}

_NUMERIC_CODES = {"12", "16", "19", "24"}


def _duplicates(values: list) -> list:
    seen: set = set()
    dupes: list = []
    for v in values:
        if v in seen and v not in dupes:
            dupes.append(v)
        seen.add(v)
    return dupes


def _website_node_ids() -> set[str] | None:
    """The `id:'...'` entries of the `const BART = [ ... ];` array, or None."""
    text = WEBSITE_HTML.read_text(encoding="utf-8")
    m = re.search(r"const BART = \[(.*?)\];", text, re.DOTALL)
    if m is None:
        return None
    return set(re.findall(r"id:'([^']+)'", m.group(1)))


def _weather_station_keys() -> set[str]:
    import yaml  # lazy: keep the module importable without pyyaml

    with open(SOURCES_YAML, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return set(cfg["weather"]["station_coords"])


def check(store_path: str | None = None) -> list[str]:
    """Return the table's problems (empty list = pass)."""
    problems: list[str] = []

    if len(STATIONS) != 50:
        problems.append(f"expected 50 stations, found {len(STATIONS)}")

    codes = [s.code for s in STATIONS]
    if dupes := _duplicates(codes):
        problems.append(f"duplicate codes: {dupes}")
    bad = [c for c in codes if not (re.fullmatch(r"[A-Z]{2}", c) or c in _NUMERIC_CODES)]
    if bad:
        problems.append(f"codes neither two capitals nor one of 12/16/19/24: {bad}")

    api_codes = [s.api_code for s in STATIONS]
    if dupes := _duplicates(api_codes):
        problems.append(f"duplicate api codes: {dupes}")
    bad = [a for a in api_codes if len(a) != 4]
    if bad:
        problems.append(f"api codes not 4 characters: {bad}")

    bad = [s.code for s in STATIONS if not s.name or not s.name.strip()]
    if bad:
        problems.append(f"empty names for codes: {bad}")

    website_ids = [s.website_id for s in STATIONS if s.website_id is not None]
    if dupes := _duplicates(website_ids):
        problems.append(f"duplicate website ids: {dupes}")
    try:
        nodes = _website_node_ids()
    except OSError as e:
        problems.append(f"cannot read {WEBSITE_HTML}: {e}")
    else:
        if not nodes:
            problems.append(f"could not find the `const BART = [ ... ];` array in {WEBSITE_HTML}")
        else:
            missing = sorted(nodes - set(website_ids))
            extra = sorted(set(website_ids) - nodes)
            if missing:
                problems.append(f"website nodes with no station: {missing}")
            if extra:
                problems.append(f"website ids not in the BART array: {extra}")

    weather = [s.weather_station for s in STATIONS if s.weather_station is not None]
    if dupes := _duplicates(weather):
        problems.append(f"duplicate weather stations: {dupes}")
    try:
        keys = _weather_station_keys()
    except Exception as e:  # missing pyyaml, unreadable file, or missing keys
        problems.append(f"cannot read weather.station_coords from {SOURCES_YAML}: {e!r}")
    else:
        extra = sorted(set(weather) - keys)
        if extra:
            problems.append(f"weather stations not in weather.station_coords: {extra}")

    if store_path is not None:
        try:
            import pandas as pd  # lazy: only needed to compare against a store

            ids = pd.read_parquet(store_path, columns=["station_id"])["station_id"]
        except Exception as e:
            problems.append(f"cannot read station_id from {store_path}: {e!r}")
        else:
            store_codes = {str(v) for v in ids.dropna().unique()}
            missing = sorted(set(CODES) - store_codes)
            extra = sorted(store_codes - set(CODES))
            if missing:
                problems.append(f"codes absent from the store: {missing}")
            if extra:
                problems.append(f"store station_ids not in the table: {extra}")

    return problems


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="The BART station table.")
    parser.add_argument("--check", action="store_true", help="validate the table and exit")
    parser.add_argument(
        "--store",
        metavar="PATH",
        help="feature store parquet whose station_id set must equal CODES (implies --check)",
    )
    args = parser.parse_args(argv)

    if args.check or args.store is not None:
        problems = check(args.store)
        if problems:
            for p in problems:
                print(f"PROBLEM: {p}")
            return 1
        print(
            f"OK: {len(STATIONS)} stations, {len(CODE_TO_WEBSITE_ID)} website ids, "
            f"{len(CODE_TO_WEATHER_STATION)} weather stations"
        )
        return 0

    print(f"{'code':<5} {'api':<5} {'name':<34} {'website_id':<11} weather_station")
    for s in STATIONS:
        print(
            f"{s.code:<5} {s.api_code:<5} {s.name:<34} "
            f"{s.website_id or '-':<11} {s.weather_station or '-'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(_main())
