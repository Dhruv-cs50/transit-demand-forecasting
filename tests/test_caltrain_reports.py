"""Tests for the Caltrain monthly average weekday ridership (AWR) extractor.

Fixtures under tests/fixtures/caltrain/ are pypdf text of real Caltrain board
reports (two different layouts):

* ``jpb_2019-03-07_key_stats_jan2019_pp14-15.txt``: prose layout, "In January
  2019, Caltrain's Average Weekday Ridership (AWR) decreased ... to 55,897".
* ``jpb_2023-01-05_ed_report_dec2022_p19.txt``: chart layout, 13 bar labels
  under "Average Weekday Ridership", anchored by "Average Daily Ridership
  (Nov-22)".

The table layout (2021-07 to 2022-10) is covered by a verbatim excerpt kept
inline, because its pypdf text is full of kerning gaps ("Av erage").
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from machine_learning_files.caltrain_reports import (
    ExtractionError,
    build_series,
    extract_awr,
)

FIXTURES = Path(__file__).parent / "fixtures" / "caltrain"
PROSE = (FIXTURES / "jpb_2019-03-07_key_stats_jan2019_pp14-15.txt").read_text()
CHART = (FIXTURES / "jpb_2023-01-05_ed_report_dec2022_p19.txt").read_text()

# Verbatim pypdf output for the monthly table in the May 5 2022 board packet
# (March 2022 data); note the broken kerning inside words.
TABLE = (
    "MONTHLY UPDATE\nMarc h 2022\nP re-P andemic P rior F Y Current F Y F Y21 to F Y22\n"
    " P re-\nP andemic  \nto F Y22 \nMar. 2019 Mar. 2021 Mar. 2022 % Change % Change\n"
    "T otal Ridership 1,487,889 109,519* 337,078 207.8% -77.3%\n"
    "Av erage Weekday Ridership 65,057 3,965* 12,539 216.2% -80.7%\n"
    "T otal F arebox Rev enue 8,065,294$       3,025,589$     2,992,204$     -1.1% -62.9%\n"
)

# Verbatim page text from the August 7 2025 packet (June 2025 data): from mid-2025
# the chart shows 14 bars (May 2024 .. Jun 2025) and no month labels in the text.
CHART14 = (
    "Ridership and Revenue\nRidership in the Past Year\n\u2588 \u2588 Average Weekday Ridership   "
    "\u25ac Total Monthly Ridership\nAverage weekday ridership (AWR) \nincreased by approximately 62 "
    "percent \ncompared to June of last year\nAWR\nTotal Ridership\n39,902\n23,953\n20,809\n0\n5,000\n"
    "10,000\n15,000\n20,000\n25,000\n30,000\n35,000\n40,000\n45,000\nWeekday Saturday Sunday\n"
    "Average Daily Ridership (Jun-25)\n24,464\n24,589\n23,291\n24,762\n26,586\n27,600\n25,892\n24,047\n"
    "29,052\n30,077\n32,419\n35,408\n37,495\n39,902\n1,037,795\n0\n200,000\n400,000\n600,000\n"
    "800,000\n1,000,000\n1,200,000\n0\n5,000\n10,000\n15,000\n20,000\n25,000\n30,000\n35,000\n"
    "40,000\n45,000\n11 | Caltrain Executive Director\u2019s Monthly Report \u2013 July 2025\n"
)

# May 2021 packet: the prose says 5,520 but Table A says 5,521.
PROSE_VS_TABLE = (
    "In May 2021\n, Caltrain\u2019s ridership was estimated as follows: \n\u2022 Average Weekday Ridership "
    "(AWR) increased by 209 percent to 5,520 from May\n2020 (1,936);\nTable A\nMay 2021\nFY20* to FY21\n"
    "FY2019 FY2020* FY2021 % Change\nTotal Ridership 1,618,825 48,771 150,801 209.2%\n"
    "Average Weekday Ridership 68,326 1,936 5,521 185.2%\n"
)


def test_extract_known_value():
    # Prose layout: the figure printed in the PDF is 55,897.
    assert extract_awr(PROSE, "2019-01") == 55897
    # Chart layout: the last bar (Nov-22) is 16,857, and an older bar is read
    # by its position in the 13-month window (Feb-22 = 10,956).
    assert extract_awr(CHART, "2022-11") == 16857
    assert extract_awr(CHART, "2022-02") == 10956
    # Table layout: the current-month column (Mar. 2022).
    assert extract_awr(TABLE, "2022-03") == 12539


def test_unmatched_layout_raises():
    with pytest.raises(ExtractionError):
        extract_awr("Totally unrelated text with 12,345 in it.", "2019-01")
    # Label present, month not reported anywhere in this document.
    with pytest.raises(ExtractionError):
        extract_awr(PROSE, "2019-02")
    # A chart month outside the 13-month window.
    with pytest.raises(ExtractionError):
        extract_awr(CHART, "2021-10")
    # Chart whose bar count is not 13 must not be guessed at.
    broken = CHART.replace("11,787|", "").replace("11,787\n", "")
    assert broken != CHART
    with pytest.raises(ExtractionError):
        extract_awr(broken, "2022-11")


def test_chart_with_fourteen_bars_and_mismatched_caption():
    assert extract_awr(CHART14, "2025-06") == 39902
    assert extract_awr(CHART14, "2024-05") == 24464  # oldest of the 14 bars
    with pytest.raises(ExtractionError):
        extract_awr(CHART14, "2024-04")
    # A caption that disagrees with the page's own "Monthly Report - <month>"
    # title is a source error, not something to guess around.
    with pytest.raises(ExtractionError, match="disagrees"):
        extract_awr(CHART.replace("(Nov-22)", "(Oct-22)"), "2022-10")


def test_table_beats_prose_when_the_source_disagrees_with_itself():
    with pytest.warns(UserWarning, match="5,520.*5,521"):
        assert extract_awr(PROSE_VS_TABLE, "2021-05") == 5521


def test_revision_kept_and_recorded(tmp_path):
    # The same month is reported by two reports with different values: the
    # later report wins and the earlier value is recorded in revised_from.
    later = CHART.replace("16,857", "16,900")
    assert later != CHART
    blobs = {
        "https://example.test/first.pdf": CHART.encode(),
        "https://example.test/second.pdf": later.encode(),
        "https://example.test/only.pdf": PROSE.encode(),
    }
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return blobs[url]

    index = tmp_path / "report_index.csv"
    pd.DataFrame(
        {
            "month": ["2022-11", "2022-11", "2019-01"],
            "report_url": list(blobs),
        }
    ).to_csv(index, index=False)

    df = build_series(index, tmp_path / "cache", fetch=fetch, to_text=lambda b: b.decode())

    assert list(df.columns) == ["month", "awr", "report_url", "sha256", "revised_from"]
    assert len(df) == 2
    nov = df[df.month == "2022-11"].iloc[0]
    assert nov.awr == 16900
    assert nov.revised_from == 16857
    assert nov.report_url == "https://example.test/second.pdf"
    assert nov.sha256 == hashlib.sha256(later.encode()).hexdigest()
    jan = df[df.month == "2019-01"].iloc[0]
    assert jan.awr == 55897
    assert pd.isna(jan.revised_from)

    # Each report is downloaded once, and a second build reuses the cache.
    assert sorted(calls) == sorted(blobs)
    build_series(index, tmp_path / "cache", fetch=fetch, to_text=lambda b: b.decode())
    assert sorted(calls) == sorted(blobs)


ROOT = Path(__file__).parent.parent


def test_committed_series_is_complete_and_cited():
    df = pd.read_csv(ROOT / "data/caltrain/awr_monthly.csv", dtype={"month": str})
    assert list(df.columns) == ["month", "awr", "report_url", "sha256", "revised_from"]
    assert df["month"].tolist() == [str(p) for p in pd.period_range("2019-01", "2026-08", freq="M")]
    assert (df["awr"] > 0).all()
    assert df["sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert df["report_url"].str.fullmatch(r"https://www\.caltrain\.com/media/\d+/download").all()
    revised = df.dropna(subset=["revised_from"])
    assert len(revised) > 0 and (revised["awr"] != revised["revised_from"]).all()
    # Every row's report is in the index, and every month has a line in the manifest.
    index = pd.read_csv(ROOT / "data/caltrain/report_index.csv", dtype=str)
    assert set(df["report_url"]) <= set(index["report_url"])
    manifest = (ROOT / "data/caltrain/MANIFEST.md").read_text()
    assert all(f"| {m} |" in manifest for m in df["month"])
    # Figures re-read from the PDFs by hand (see MANIFEST.md).
    by_month = df.set_index("month")["awr"]
    for month, value in {
        "2019-02": 64041, "2020-04": 1547, "2022-06": 18187, "2024-09": 26541, "2026-08": 49685,
    }.items():  # fmt: skip
        assert by_month[month] == value


def test_config_keys():
    import yaml

    cfg = yaml.safe_load((ROOT / "configs/caltrain.yaml").read_text())
    # A superset: later tasks add the holdout windows to this file.
    assert set(cfg) >= {"electrification_start", "method_changes", "exclude", "train_start"}
    assert cfg["electrification_start"] == "2024-09"
    assert cfg["method_changes"] == ["2020-04", "2022-06"]
    assert cfg["exclude"] == [str(p) for p in pd.period_range("2020-01", "2021-12", freq="M")]
    assert cfg["train_start"] >= "2022-06"
