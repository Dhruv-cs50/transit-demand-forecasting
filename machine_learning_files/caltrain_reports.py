"""Extract Caltrain's monthly average weekday ridership (AWR) from board reports.

Caltrain publishes one systemwide AWR estimate per month, inside the monthly
board packet (the "Key Caltrain Performance Statistics" staff report until
mid-2022, then the Executive Director's Monthly Report). The figure is an
estimate (fare-media sales model, later Clipper and conductor counts), not a
passenger count; see data/caltrain/MANIFEST.md for the method changes.

The PDFs were produced by several generators, so three layouts are read:

``prose``
    "In January 2019, Caltrain's Average Weekday Ridership (AWR) decreased
    2.0 percent to 55,897 from January 2018 AWR of 57,018."
``table``
    A three-column monthly table ("Mar. 2019 Mar. 2021 Mar. 2022") whose
    "Average Weekday Ridership" row ends in the current month.
``chart``
    "Ridership in the Past Year": 13 bar labels (oldest first) after the
    "Average Weekday Ridership" legend, anchored by the caption "Average
    Daily Ridership (Nov-22)" which names the newest bar.

pypdf breaks words at kerning gaps ("Av erage", "Marc h 2022"), so every
keyword is matched with optional whitespace between letters.

Nothing is guessed: when the label or month is missing, or the layout does not
match exactly, ``ExtractionError`` is raised.
"""

from __future__ import annotations

import hashlib
import re
import warnings
from collections.abc import Callable
from pathlib import Path

import pandas as pd

__all__ = [
    "ExtractionError",
    "extract_awr",
    "build_series",
    "pdf_pages",
    "pdf_text",
    "cache_path",
]

SERIES_COLUMNS = ["month", "awr", "report_url", "sha256", "revised_from"]

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]  # fmt: skip


class ExtractionError(ValueError):
    """The expected label/month was not found, or the layout is unrecognised."""


# --------------------------------------------------------------------------
# Text normalisation helpers


def _fz(phrase: str) -> str:
    """Regex for `phrase` tolerating one stray space between any two letters."""
    words = [r"\s?".join(re.escape(ch) for ch in word) for word in phrase.split(" ")]
    return r"\s*".join(words)


def _collapse(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text)


_MONTH_ALT = "|".join(
    [_fz(n) for n in sorted(_MONTH_NAMES, key=len, reverse=True)]
    + [_fz(n[:3]) + r"\.?" for n in _MONTH_NAMES]
    + [_fz("Sept") + r"\.?"]
)
_MONTH = r"(?P<{p}mon>" + _MONTH_ALT + r")"
_YEAR = r"(?P<{p}yr>\d\s?\d\s?\d\s?\d)"
_NUM = r"\d{1,3}(?:,\s?\d{3})*"


def _mon_year(prefix: str) -> str:
    return (_MONTH + r"\s*" + _YEAR).replace("{p}", prefix)


def _month_key(mon: str, yr: str) -> str:
    letters = re.sub(r"[^A-Za-z]", "", mon).lower()
    for i, name in enumerate(_MONTH_NAMES, start=1):
        if letters.startswith(name[:3].lower()):
            return f"{int(re.sub(r'\s', '', yr)):04d}-{i:02d}"
    raise ExtractionError(f"unrecognised month token {mon!r}")


def _int(num: str) -> int:
    return int(re.sub(r"[^\d]", "", num))


def _shift(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    n = y * 12 + (m - 1) + delta
    return f"{n // 12:04d}-{n % 12 + 1:02d}"


# --------------------------------------------------------------------------
# Layout parsers. Each returns {month: (value, rank)}; lower rank wins.
# rank 0: figure is the report's headline month; 1: older bar/column;
# 2: prior-year comparison quoted in prose.

_LABEL = _fz("Average Weekday Ridership")

_PROSE = re.compile(
    r"In\s+" + _mon_year("c") + r"\s*,?\s+" + _fz("Caltrain") + r"\W{0,3}s\s+"
    r"(?:" + _fz("ridership was estimated as follows:") + r"\W{0,4}\s*)?"
    + _LABEL + r"\s*\(\s*AWR\s*\)\s*"
    r"(?:increased|decreased)(?:\s+by)?\s+[\d.]+\s*percent\s+to\s+(?P<cur>" + _NUM + r")"
    r"\s+from\s+(?:calibrated\s+)?"
    r"(?:" + _mon_year("p") + r"\s+" + _fz("AWR") + r"\s+of\s+(?P<prior>" + _NUM + r"))?"
)

_TABLE_ROW = re.compile(
    _LABEL + r"\s+(?P<a>" + _NUM + r")\*?\s+(?P<b>" + _NUM + r")\*?\s+(?P<c>" + _NUM + r")\*?"
    r"\s+-?[\d.]+\s*%"
)
_TOTAL_RIDERSHIP = re.compile(_fz("Total Ridership"))
_ANY_MON_YEAR = re.compile(_mon_year("t"))

_THREE_COLUMNS = re.compile(
    _mon_year("a") + r"\s+" + _mon_year("b") + r"\s+" + _mon_year("c") + r"\s*%\s*Change"
)

_CHART_CAPTION = re.compile(
    _fz("Average Daily Ridership") + r"\s*\(\s*(?P<mon>[A-Za-z]+)\s*-\s*(?P<yy>\d\d)\s*\)"
)
_CHART_TITLE = re.compile(_fz("Monthly Report") + r"\s*[\u2013-]\s*" + _mon_year("t"))
_CHART_LEGEND = re.compile(_LABEL)
_COMMA_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+")
# A bar label is a line holding nothing but one number with a thousands comma
# (prose such as "12.5 percent" must not be mistaken for a bar).
_BAR_LINE = re.compile(r"^\s*(\d{1,3}(?:,\d{3})+)\s*$", re.M)


def _parse_prose(text: str) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for m in _PROSE.finditer(_collapse(text)):
        _put(out, _month_key(m["cmon"], m["cyr"]), _int(m["cur"]), 0)
        if m["prior"]:
            _put(out, _month_key(m["pmon"], m["pyr"]), _int(m["prior"]), 2)
    return out


def _parse_table(text: str) -> dict[str, tuple[int, int]]:
    """Monthly KPI table: the third number is the current month.

    When the header names all three columns ("Mar. 2019 Mar. 2021 Mar. 2022")
    the two older columns are returned too, as prior-year style comparisons.
    """
    flat = _collapse(text)
    out: dict[str, tuple[int, int]] = {}
    row = _TABLE_ROW.search(flat)
    if not row:
        return out
    # The heading that belongs to this table is the last month/year token before
    # the "Total Ridership" row that precedes the AWR row.
    head = flat[: row.start()]
    totals = list(_TOTAL_RIDERSHIP.finditer(head))
    if not totals:
        return out
    head = head[: totals[-1].start()]
    tokens = list(_ANY_MON_YEAR.finditer(head))
    if not tokens:
        return out
    cur = tokens[-1]
    _put(out, _month_key(cur["tmon"], cur["tyr"]), _int(row["c"]), 0)
    cols = _THREE_COLUMNS.search(head[-160:])
    if cols and _month_key(cols["cmon"], cols["cyr"]) == _month_key(cur["tmon"], cur["tyr"]):
        _put(out, _month_key(cols["amon"], cols["ayr"]), _int(row["a"]), 2)
        _put(out, _month_key(cols["bmon"], cols["byr"]), _int(row["b"]), 2)
    return out


def _parse_chart(text: str) -> dict[str, tuple[int, int]]:
    """'Ridership in the Past Year': 13-14 bar labels ending on the caption month.

    The bar labels are single-number lines that follow the caption/legend,
    mixed in with round axis ticks (5,000, 10,000, ...). The newest bar is
    anchored on the weekday figure of the 'Average Daily Ridership (Mon-YY)'
    bar chart printed on the same page (the largest non-round number before the
    bars; allowed to differ by 1 because the two charts round independently),
    and the run of non-round numbers ending there is the bar series.
    """
    out: dict[str, tuple[int, int]] = {}
    cap = _CHART_CAPTION.search(text)
    if not cap:
        return out
    anchor = _month_key(cap["mon"], f"20{cap['yy']}")
    # The page footer names the report month ("Monthly Report - December 2022"),
    # always the month after the data month. A caption that disagrees (one board
    # packet captions December data "Oct-23") means the page cannot be trusted.
    title = _CHART_TITLE.search(_collapse(text))
    if title and _shift(_month_key(title["tmon"], title["tyr"]), -1) != anchor:
        raise ExtractionError(
            f"chart caption {cap['mon']}-{cap['yy']} disagrees with the page title "
            f"{title['tmon']} {title['tyr']}"
        )
    legend = _CHART_LEGEND.search(text)
    if not legend:
        raise ExtractionError("chart caption found but no 'Average Weekday Ridership' legend")
    start = max(cap.end(), legend.end())
    daily = [_int(n) for n in _COMMA_NUMBER.findall(text[:start])]
    daily = [n for n in daily if n % 500 != 0]  # round numbers are axis ticks
    if not daily:
        raise ExtractionError("no daily weekday figure found before the AWR bars")
    weekday = max(daily)

    # Runs of consecutive single-number lines after the caption.
    runs: list[list[int]] = [[]]
    for line in text[start:].splitlines():
        m = _BAR_LINE.fullmatch(line)
        if m:
            runs[-1].append(_int(m[1]))
        elif line.strip() == "0" or not line.strip():
            continue  # axis origin / blank lines do not break a run of labels
        elif runs[-1]:
            runs.append([])
    bars: list[int] = []
    for run in runs:
        hits = [i for i, v in enumerate(run) if abs(v - weekday) <= 1 and v % 500 != 0]
        if hits:
            upto = run[: hits[-1] + 1]
            # Bars are the trailing stretch of non-round numbers; round numbers
            # glued to the front of the run are axis ticks.
            k = len(upto)
            while k > 0 and upto[k - 1] % 500 != 0:
                k -= 1
            bars = upto[k:]
            break
    if len(bars) not in (13, 14):
        raise ExtractionError(
            f"expected 13-14 AWR bars ending on the daily weekday figure {weekday:,}, found {len(bars)}"
        )
    n = len(bars)
    for i, value in enumerate(bars):
        _put(out, _shift(anchor, i - (n - 1)), value, 0 if i == n - 1 else 1)
    return out


def _put(out: dict[str, tuple[int, int]], month: str, value: int, rank: int) -> None:
    """Keep the best-ranked value per month; equal-rank conflicts are an error."""
    prev = out.get(month)
    if prev is None or rank < prev[1]:
        out[month] = (value, rank)
    elif rank == prev[1] and value != prev[0]:
        raise ExtractionError(f"conflicting AWR values {prev[0]} and {value} for {month}")


def extract_awr(pdf_text: str, month: str) -> int:
    """Return the average weekday ridership printed for `month` ("YYYY-MM").

    Raises ``ExtractionError`` when the "Average Weekday Ridership" label or the
    month cannot be found in a recognised layout. Where a report quotes the
    month more than once, the headline figure wins over older bars/columns and
    prior-year comparisons. If a report's prose and its Table A print different
    headline figures (May 2021: 5,520 vs 5,521), the table is used and a
    warning is issued; any other disagreement raises.
    """
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError(f"month must be 'YYYY-MM', got {month!r}")
    candidates: list[tuple[int, int, str]] = []  # (rank, value, source)
    for source, parser in (("table", _parse_table), ("prose", _parse_prose), ("chart", _parse_chart)):
        got = parser(pdf_text).get(month)
        if got is not None:
            candidates.append((got[1], got[0], source))
    if not candidates:
        raise ExtractionError(
            f"no Average Weekday Ridership value for {month} in a recognised layout"
        )
    best = min(rank for rank, _, _ in candidates)
    top = [(value, source) for rank, value, source in candidates if rank == best]
    if len({value for value, _ in top}) > 1:
        sources = {source for _, source in top}
        if sources == {"table", "prose"}:
            warnings.warn(
                f"{month}: prose says {dict((s_, v) for v, s_ in top)['prose']:,} but the "
                f"table says {dict((s_, v) for v, s_ in top)['table']:,}; using the table",
                stacklevel=2,
            )
        else:
            raise ExtractionError(f"conflicting AWR values for {month}: {top}")
    return top[0][0]


# --------------------------------------------------------------------------
# PDF access


def pdf_pages(pdf_path: Path) -> list[str]:
    """Text of every page, via pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - a broken page must not hide the rest
            pages.append("")
    return pages


_RELEVANT = re.compile(_LABEL + r"|\bAWR\b")


def pdf_text(pdf_path: Path) -> str:
    """Text of the pages that mention AWR, joined with form feeds."""
    return "\f".join(p for p in pdf_pages(pdf_path) if _RELEVANT.search(_collapse(p)))


def cache_path(cache_dir: Path, url: str) -> Path:
    media = re.search(r"/media/(\d+)", url)
    name = media.group(1) if media else re.sub(r"\W+", "_", url).strip("_")
    return Path(cache_dir) / f"{name}.pdf"


def _default_fetch(url: str) -> bytes:
    import requests

    resp = requests.get(url, timeout=300, headers={"User-Agent": "transit-demand-forecasting"})
    resp.raise_for_status()
    if not resp.content.startswith(b"%PDF"):
        raise ExtractionError(f"{url} did not return a PDF")
    return resp.content


def build_series(
    index_csv: Path,
    cache_dir: Path,
    *,
    fetch: Callable[[str], bytes] | None = None,
    to_text: Callable[[bytes], str] | None = None,
) -> pd.DataFrame:
    """Build the monthly AWR series from ``report_index.csv`` (month, report_url).

    Each report is downloaded once into `cache_dir` (gitignored) and its sha256
    recorded. A month may appear on several rows (the report that first
    published it, then later reports that restate it). Rows are processed in
    file order: the last row's value is kept, and when it differs from the
    first row's value that earlier figure is stored in ``revised_from``.

    `fetch` and `to_text` are injectable for tests; they default to an HTTP GET
    and the pypdf-based ``pdf_text``.
    """
    fetch = fetch or _default_fetch
    index = pd.read_csv(index_csv, dtype=str)
    missing = {"month", "report_url"} - set(index.columns)
    if missing:
        raise ValueError(f"{index_csv} is missing columns {sorted(missing)}")
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    blobs: dict[str, tuple[bytes, str]] = {}  # url -> (bytes, sha256)

    def load(url: str) -> bytes:
        if url not in blobs:
            path = cache_path(cache_dir, url)
            if path.exists():
                data = path.read_bytes()
            else:
                data = fetch(url)
                path.write_bytes(data)
            blobs[url] = (data, hashlib.sha256(data).hexdigest())
        return blobs[url][0]

    texts: dict[str, str] = {}
    rows: dict[str, dict] = {}
    for month, url in zip(index["month"], index["report_url"], strict=True):
        data = load(url)
        if url not in texts:
            if to_text is not None:
                texts[url] = to_text(data)
            else:
                texts[url] = pdf_text(cache_path(cache_dir, url))
        try:
            value = extract_awr(texts[url], month)
        except ExtractionError as exc:
            raise ExtractionError(f"{month} in {url}: {exc}") from exc
        row = rows.setdefault(month, {"first": value})
        row.update(awr=value, report_url=url, sha256=blobs[url][1])

    out = []
    for month in sorted(rows):
        r = rows[month]
        out.append(
            {
                "month": month,
                "awr": r["awr"],
                "report_url": r["report_url"],
                "sha256": r["sha256"],
                "revised_from": r["first"] if r["first"] != r["awr"] else pd.NA,
            }
        )
    df = pd.DataFrame(out, columns=SERIES_COLUMNS)
    df["awr"] = df["awr"].astype("Int64")
    df["revised_from"] = df["revised_from"].astype("Int64")
    return df


def main(argv: list[str] | None = None) -> None:
    """Rebuild data/caltrain/awr_monthly.csv from report_index.csv."""
    import argparse

    root = Path(__file__).resolve().parent.parent / "data" / "caltrain"
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--index", type=Path, default=root / "report_index.csv")
    ap.add_argument("--cache", type=Path, default=root / "pdf_cache")
    ap.add_argument("--out", type=Path, default=root / "awr_monthly.csv")
    args = ap.parse_args(argv)
    df = build_series(args.index, args.cache)
    df.to_csv(args.out, index=False)
    print(f"wrote {len(df)} months ({df.month.iloc[0]}..{df.month.iloc[-1]}) to {args.out}")


if __name__ == "__main__":
    main()
