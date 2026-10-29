# Caltrain monthly average weekday ridership (AWR): manifest

`awr_monthly.csv` holds one row per month, **2019-01 to 2026-08 (92 months, no gaps)**, rebuilt by
`python -m machine_learning_files.caltrain_reports` from `report_index.csv` (month, report URL, role).
Source: the board packets (Executive Director's monthly report; before mid-2022 the "Key Caltrain
Performance Statistics" staff report) on <https://www.caltrain.com/about-caltrain/meetings/caltrain-meetings-past>.
The PDFs are cached in the gitignored `data/caltrain/pdf_cache/` and are never committed; every row
records the sha256 of the PDF it came from. A full rebuild reads about 90 large packets with pypdf and
takes roughly ten minutes.

**What the numbers are.** Caltrain has no fare gates, so AWR is an *estimate*, not a passenger count
(<https://www.caltrain.com/about-caltrain/statistics-reports/ridership>, "Ridership": monthly figures
come from fare-media sales and, in the COVID period, conductor and Clipper counts). Each month's figure
is published about two months later: the board packet of month *M+2* reports month *M*.

## Coverage

* Start: **2019-01**, reported in the March 7 2019 packet (media 2400). The online archive has no
  board packet for the January and February 2019 meetings, so nothing earlier than Jan 2019 was
  collected (the 2019 packets quote 2018 months only as prior-year comparisons).
* End: **2026-08**, from the Oct 1 2026 packet (media 37883). September 2026 is not yet published.
* No month is missing, but 11 months are not the headline of any packet and were **gap-filled**
  (role `gap-fill`, see below). Reasons: the May and June 2019 board packets in the archive are
  agenda-only (no report); the May 2020 packet (media 106) and the Nov 2021 packet (media 18475)
  contain no extractable AWR figure; the archive shows no regular July board meeting in 2022 to
  2026, so May is never a headline (2022-05, 2023-05, 2024-05, 2025-05, 2026-05); the Sep 2022
  packet (media 22506) draws its chart differently (7 bars, labels in the text; it prints Jul 2022
  = 16,932, the same figure the gap-fill source gives); and the Jan 2024 packet (media 32476)
  has the caption defect described under "Source defects".

## Roles in `report_index.csv`

* `headline`: the report that first publishes the month (its "In <Month>, ... AWR ... to N" sentence,
  Table A column, or the newest bar of the "Ridership in the Past Year" chart).
* `gap-fill`: the month is not a headline anywhere; the value is read from the first later report that
  prints it with a month label: 2019-03 (Mar 2022 table, pre-pandemic column), 2019-04 and 2020-03
  (prior-year comparison in the 2020 and 2021 reports), and 2021-09, 2022-05, 2022-07, 2023-05,
  2023-11, 2024-05, 2025-05, 2026-05 (bar of the next packet's 13-month chart; 2021-09 is printed
  only in media 24300, the others also appear in later charts that agree with the chosen value to
  within 1%).
* `restatement`: a later report restates a month with a different, explicitly labelled figure
  (asterisk "adjusted after thorough review of data from past Fiscal Years", or "calibrated"). In
  `build_series` the **last row for a month wins** and the first figure is kept in `revised_from`:

| month | first published | restated to | restating report |
|---|---|---|---|
| 2019-01 | 55,897 | 63,044 | Mar 2020 packet (media 18933) |
| 2021-03 | 3,954 | 3,965 | May 2022 packet (18350) |
| 2021-04 | 4,688 | 4,693 | Jun 2022 packet (19263) |
| 2021-06 | 7,118 | 7,143 | Aug 2022 packet (21498) |
| 2021-08 | 9,053 | 9,096 | Oct 2022 packet (23270) |

  Other restatements exist but are **not applied**: the middle (prior-year) column of the
  fiscal-year-headed Table A in media 18566, 18500, 8137, 18373 and 18403 restates Jul 2020
  3,421 to 3,419, Aug 2020 3,526 to 3,517, Nov 2020 3,742 to 3,760, Dec 2020 3,147 to 3,162 and
  Jan 2021 3,056 to 3,058 (at most 0.5%). Their header names no month, the parser does not read
  them, and all five months fall inside `exclude`.

  The January 2019 jump is the change of method: the Jan 2019 report (media 2400, p14) still used "the
  current ridership estimating methodology that has been in use since the inception of the service",
  and the Apr 2019 packet (media 2403, p16) introduces "The new methodology [that] makes use of
  historical ticket sales, the annual counts and triennial survey data". Jan 2019 is restated on the
  new basis; every later 2019 month was published on it.
* Values from the chart era (2022-09 onward) are the **first published** figures, and Caltrain
  keeps revising them in later packets. The revisions found, comparing against the later charts: Nov
  2022 16,857 to 16,429 (-2.5%), Feb 2023 16,489 to 16,829 (+2.1%), May, Jun and Jul 2023 about +1%
  (18,678 to 18,853; 20,452 to 20,663; 20,334 to 20,525), Jun 2025 39,902 to 40,084 (+0.5%), and under
  0.3% for every other month. These chart revisions are **not applied**: the charts carry no month
  labels in their text and a few windows are printed shifted or with typos (below), so only the
  explicitly labelled 2019-2021 restatements are. The latest months (2026) are the least settled.

## Source defects found (none of these values is used)

* **May 2021**: the prose says 5,520, Table A says 5,521 (same packet, media 3527 p15 and p17). The
  table value 5,521 is used (`extract_awr` warns and prefers the table).
* **Media 32476** (Jan 4 2024 packet, p15): the chart is captioned "(Oct-23)" but the page footer says
  "Monthly Report - December 2023" and the bars end one month later (Nov-23 = 20,900). `extract_awr`
  refuses such a page; Nov 2023 is gap-filled from media 32695 (20,877).
* **Media 33129** (Apr 4 2024 packet, p14): the Dec-23 bar prints 20,870 (it is the Nov-23 figure
  again; every other packet has 17,358 to 17,388). **Media 34922** (Mar 6 2025, p15): the May-24 bar
  prints 14,464 (24,464 everywhere else).
* **Aug 2024**: the bar label is 24,741 but the daily weekday chart beside it prints 24,742; the bar
  label (the series Caltrain plots) is used. The extractor accepts a difference of 1 between the two.
* **Media 37907** (Oct 1 2026 Executive Director slides, p5): the AWR chart's last bar is labelled
  "Jul-26" (47,459) although the text discusses August; the packet report (media 37883, p15) has
  Aug-26 = 49,685 and is the source used.

## Method changes documented by Caltrain

| when | change | evidence |
|---|---|---|
| **Feb 2019** (data month) | weekday-weighted ticket-sales model replaces the original estimate. It is introduced in the Apr 4 2019 packet with Feb 2019 data; Jan 2019 was first published on the old basis and is restated on the new one in this series | media 2403 p16-18 |
| **Apr 2020** | daily conductor counts at 14 stations plus Clipper tag-ons replace the sales model | media 111 p14 ("temporary methodology to estimate the ridership starting in April 2020") |
| **Nov 2023** | fully fare-media-sales-based model | media 32238 p12 ("November 2023, on: Caltrain implemented a ridership estimation model that is based entirely on fare media sales data"); packets from Dec 2025 say "Since DECEMBER 2023" instead |
| **Jan 2025** | rides per monthly pass raised from 26 to 37 per month | the ridership page only (<https://www.caltrain.com/about-caltrain/statistics-reports/ridership>, read 2026-10-28); no board packet mentions it. The series steps up here: Dec 2024 24,037, Jan 2025 29,052 (+21%; +14% a year earlier) |

`configs/caltrain.yaml` carries `method_changes: ["2019-02", "2020-04", "2023-11", "2025-01"]`, one
entry per row of the table above. The 2019 entry is the first data month published on the new model
(Feb 2019); because Jan 2019 is restated on that model, `awr_monthly.csv` has no break there, and 2019
is outside the training window anyway. The Nov 2023 and Jan 2025 changes fall inside the training
window; Task 2 encodes each as a step regressor so that the Jan 2025 jump (Dec 2024 24,037 to Jan
2025 29,052, +21%) is not read as demand.

## Electrification launch

`electrification_start: "2024-09"`. Caltrain board packet of Oct 3 2024 (media 34193), Executive
Director's Monthly Report - September 2024, **PDF page 25**: "Caltrain Commences Fully Electrified
Service. On September 21st Caltrain launched its new electrified schedule, bringing the 160-year-old
San Francisco-San Jose rail corridor from diesel power to electric." The same packet (p44-45) dates the
earlier soft launch: inaugural ride on August 10 and "EMU soft launch service with mixed fleet
operations on August 11th" 2024, so August 2024 is a mixed month. Corroborated by the Sep 5 2024
Executive Director report (media 34015, p5): "Launch New Electric Schedule ... September 21 & 22".

## train_start

`train_start: "2022-01"`: the first month after the COVID exclusion (`exclude` ends 2021-12), which
matches the BART train start. The series has a published value for it (9,044, media 18403, Mar 3 2022
packet, p19, Table A "Jan 2022"). The training window runs through the Nov 2023 and Jan 2025 method
changes, which is why they are in `method_changes`.

## How "hand-checked" was done

Each row below was read **independently of `extract_awr`**: the figure is located with a second PDF
engine (PyMuPDF, not pypdf) on the page given, and the quoted line is the physical text line of that
page that holds the figure (kerning artifacts such as "Av erage" are the PDF's own).
`checked by hand (text)` means that line and the month it belongs to were read in the PyMuPDF text.
`checked by hand (text+image)` means the page was also rendered and read by eye: for all 48 chart pages the
month label printed under each bar and the bar value were read off the image; for 9 sampled prose and
table rows (2019-01, 2019-03, 2019-12, 2020-03, 2020-05, 2021-06, 2021-10, 2022-03, 2022-08) the
quoted line was read in the rendered page. For `table` rows the quoted "line" is the visual table row:
PyMuPDF returns each cell as its own text line, shown joined with `/`. "PDF page" is the 1-based page of the downloaded file, not
the packet's own item page number. `report` links are the `/media/<id>/download` URLs in
`report_index.csv`; the meeting is the board month the packet belongs to.

## Per-month evidence

| month | AWR | role | report | PDF page | evidence line | status |
|---|---|---|---|---|---|---|
| 2019-01 | 55,897 | headline | [2400](https://www.caltrain.com/media/2400/download) 2019-03 board | 14 | prose: line: "to 55,897 from January 2018 AWR of 57,018.  The total number of passengers who rode" ; month sentence line: "In January 2019, Caltrain's Average Weekday Ridership (AWR) decreased 2.0 percent" | superseded by the restatement row; checked by hand (text+image) |
| 2019-01 | 63,044 | restatement | [18933](https://www.caltrain.com/media/18933/download) 2020-03 board | 11 | prose: line: "to 64,806 from January 2019 AWR of 63,044.  The total number of passengers who rode" ; month sentence line: "to 64,806 from January 2019 AWR of 63,044.  The total number of passengers who rode" | **used**; checked by hand (text) |
| 2019-02 | 64,041 | headline | [2403](https://www.caltrain.com/media/2403/download) 2019-04 board | 18 | prose: line: "to 64,041 from calibrated February 2018 AWR of 66,414.  The total number of passengers" ; month sentence line: "In February 2019, Caltrain's Average Weekday Ridership (AWR) decreased 3.6 percent" | **used**; checked by hand (text) |
| 2019-03 | 65,057 | gap-fill | [18350](https://www.caltrain.com/media/18350/download) 2022-05 board | 21 | table: row: "Av erage Weekday Ridership / 65,057 / 3,965* / 12,539 / 216.2%" ; column heading(s): Mar. 2019 / Mar. 2021 / Mar. 2022 | **used**; checked by hand (text+image) |
| 2019-04 | 67,728 | gap-fill | [111](https://www.caltrain.com/media/111/download) 2020-06 board | 14 | prose: line: "to 1,547 from April 2019 AWR of 67,728.  The total number of passengers who rode" ; month sentence line: "to 1,547 from April 2019 AWR of 67,728.  The total number of passengers who rode" | **used**; checked by hand (text) |
| 2019-05 | 68,326 | headline | [2421](https://www.caltrain.com/media/2421/download) 2019-07 board | 16 | prose: line: "68,326 from calibrated May 2018 AWR of 69,758.  The total number of passengers who" ; month sentence line: "In May 2019, Caltrain's Average Weekday Ridership (AWR) decreased 2.1 percent to" | **used**; checked by hand (text) |
| 2019-06 | 72,370 | headline | [2431](https://www.caltrain.com/media/2431/download) 2019-08 board | 23 | prose: line: "72,370 from calibrated June 2018 AWR of 72,207.  The total number of passengers who" ; month sentence line: "In June 2019, Caltrain's Average Weekday Ridership (AWR) increased 0.2 percent to" | **used**; checked by hand (text) |
| 2019-07 | 70,493 | headline | [2444](https://www.caltrain.com/media/2444/download) 2019-09 board | 17 | prose: line: "70,493 from calibrated July 2018 AWR of 71,234.  The total number of passengers who" ; month sentence line: "In July 2019, Caltrain's Average Weekday Ridership (AWR) decreased by 1.0 percent to" | **used**; checked by hand (text) |
| 2019-08 | 71,557 | headline | [2468](https://www.caltrain.com/media/2468/download) 2019-10 board | 22 | prose: line: "to 71,557 from calibrated August 2018 AWR of 70,547.  The total number of passengers" ; month sentence line: "In August 2019, Caltrain's Average Weekday Ridership (AWR) increased by 1.4 percent" | **used**; checked by hand (text) |
| 2019-09 | 72,387 | headline | [2476](https://www.caltrain.com/media/2476/download) 2019-11 board | 2 | prose: line: "percent to 72,387 from calibrated September 2018 AWR of 71,479.  The total number of" ; month sentence line: "In September 2019, Caltrain's Average Weekday Ridership (AWR) increased by 1.3" | **used**; checked by hand (text) |
| 2019-10 | 70,360 | headline | [2473](https://www.caltrain.com/media/2473/download) 2019-12 board | 12 | prose: line: "percent to 70,360 from calibrated October 2018 AWR of 66,345.  The total number of" ; month sentence line: "In October 2019, Caltrain's Average Weekday Ridership (AWR) increased by 6.1" | **used**; checked by hand (text) |
| 2019-11 | 69,607 | headline | [2525](https://www.caltrain.com/media/2525/download) 2020-01 board | 18 | prose: line: "percent to 69,607 from November 2018 AWR of 65,601.  The total number of passengers" ; month sentence line: "In November 2019, Caltrain's Average Weekday Ridership (AWR) increased by 6.1" | **used**; checked by hand (text) |
| 2019-12 | 62,480 | headline | [18947](https://www.caltrain.com/media/18947/download) 2020-02 board | 9 | prose: line: "percent to 62,480 from December 2018 AWR of 60,202.  The total number of passengers" ; month sentence line: "In December 2019, Caltrain's Average Weekday Ridership (AWR) increased by 3.8" | **used**; checked by hand (text+image) |
| 2020-01 | 64,806 | headline | [18933](https://www.caltrain.com/media/18933/download) 2020-03 board | 11 | prose: line: "to 64,806 from January 2019 AWR of 63,044.  The total number of passengers who rode" ; month sentence line: "In January 2020, Caltrain's Average Weekday Ridership (AWR) increased by 2.8 percent" | **used**; checked by hand (text) |
| 2020-02 | 67,218 | headline | [3533](https://www.caltrain.com/media/3533/download) 2020-04 board | 11 | prose: line: "percent to 67,218 from February 2019 AWR of 64,041.  The total number of passengers" ; month sentence line: "In February 2020, Caltrain's Average Weekday Ridership (AWR) increased by 5.0" | **used**; checked by hand (text) |
| 2020-03 | 49,276 | gap-fill | [435](https://www.caltrain.com/media/435/download) 2021-05 board | 11 | prose: line: "to 3,954 from March 2020 AWR of 49,276.  The total number of passengers who rode" ; month sentence line: "to 3,954 from March 2020 AWR of 49,276.  The total number of passengers who rode" | **used**; checked by hand (text+image) |
| 2020-04 | 1,547 | headline | [111](https://www.caltrain.com/media/111/download) 2020-06 board | 14 | prose: line: "to 1,547 from April 2019 AWR of 67,728.  The total number of passengers who rode" ; month sentence line: "In April 2020, Caltrain's Average Weekday Ridership (AWR) decreased by 97.7 percent" | **used**; checked by hand (text) |
| 2020-05 | 1,936 | headline | [3568](https://www.caltrain.com/media/3568/download) 2020-07 board | 13 | prose: line: "to 1,936 from May 2019 AWR of 68,326.  Average weekday ridership slightly increased by" ; month sentence line: "In May 2020, Caltrain's Average Weekday Ridership (AWR) decreased by 97.2 percent" | **used**; checked by hand (text+image) |
| 2020-06 | 2,884 | headline | [121](https://www.caltrain.com/media/121/download) 2020-08 board | 23 | prose: line: "2,884 from June 2019 AWR of 72,370.  Average weekday ridership  increased by 49" ; month sentence line: "In June 2020, Caltrain's Average Weekday Ridership (AWR) decreased by 96 percent to" | **used**; checked by hand (text) |
| 2020-07 | 3,421 | headline | [126](https://www.caltrain.com/media/126/download) 2020-09 board | 24 | prose: line: "to 3,421 from July 2019 AWR of 70,493.  AWR  increased by 19 percent (537 riders) from" ; month sentence line: "In July 2020, Caltrain's Average Weekday Ridership (AWR) decreased by 95.1 percent" | **used**; checked by hand (text) |
| 2020-08 | 3,526 | headline | [129](https://www.caltrain.com/media/129/download) 2020-10 board | 13 | prose: line: "percent to 3,526 from August 2019 AWR of 71,557.  The total number of passengers who" ; month sentence line: "In August 2020, Caltrain's Average Weekday Ridership (AWR) decreased by 95.1" | **used**; checked by hand (text) |
| 2020-09 | 3,654 | headline | [132](https://www.caltrain.com/media/132/download) 2020-11 board | 14 | prose: line: "percent to 3,654 from September 2019 AWR of 72,387.  The total number of passengers" ; month sentence line: "In September 2020, Caltrain's Average Weekday Ridership (AWR) decreased by 95" | **used**; checked by hand (text) |
| 2020-10 | 3,873 | headline | [436](https://www.caltrain.com/media/436/download) 2020-12 board | 14 | prose: line: "percent to 3,873 from October 2019 AWR of 70,360.  The total number of passengers" ; month sentence line: "In October 2020, Caltrain's Average Weekday Ridership (AWR) decreased by 94.5" | **used**; checked by hand (text) |
| 2020-11 | 3,742 | headline | [72](https://www.caltrain.com/media/72/download) 2021-01 board | 22 | prose: line: "percent to 3,742 from November 2019 AWR of 69,607.  The total number of passengers" ; month sentence line: "In November 2020, Caltrain's Average Weekday Ridership (AWR) decreased by 94.6" | **used**; checked by hand (text) |
| 2020-12 | 3,147 | headline | [1160](https://www.caltrain.com/media/1160/download) 2021-02 board | 13 | prose: line: "percent to 3,147 from December 2019 AWR of 62,480.  The total number of passengers" ; month sentence line: "In December 2020, Caltrain's Average Weekday Ridership (AWR) decreased by 95" | **used**; checked by hand (text) |
| 2021-01 | 3,056 | headline | [144](https://www.caltrain.com/media/144/download) 2021-03 board | 10 | prose: line: "percent to 3,056 from January 2020 AWR of 64,806.  The total number of passengers" ; month sentence line: "In January 2021, Caltrain's Average Weekday Ridership (AWR) decreased by 95.3" | **used**; checked by hand (text) |
| 2021-02 | 3,484 | headline | [158](https://www.caltrain.com/media/158/download) 2021-04 board | 38 | prose: line: "percent to 3,484 from February 2020 AWR of 67,218.  The total number of passengers" ; month sentence line: "In February 2021, Caltrain's Average Weekday Ridership (AWR) decreased by 94.8" | **used**; checked by hand (text) |
| 2021-03 | 3,954 | headline | [435](https://www.caltrain.com/media/435/download) 2021-05 board | 11 | prose: line: "to 3,954 from March 2020 AWR of 49,276.  The total number of passengers who rode" ; month sentence line: "In March 2021, Caltrain's Average Weekday Ridership (AWR) decreased by 92 percent" | superseded by the restatement row; checked by hand (text) |
| 2021-03 | 3,965 | restatement | [18350](https://www.caltrain.com/media/18350/download) 2022-05 board | 21 | table: row: "Av erage Weekday Ridership / 65,057 / 3,965* / 12,539 / 216.2%" ; column heading(s): Mar. 2019 / Mar. 2021 / Mar. 2022 | **used**; checked by hand (text) |
| 2021-04 | 4,688 | headline | [182](https://www.caltrain.com/media/182/download) 2021-06 board | 17 | prose: line: "4,688 from April 2020 AWR of 1,547.  The total number of passengers who rode Caltrain" ; month sentence line: "In April 2021, Caltrain's Average Weekday Ridership (AWR) increased by 203 percent to" | superseded by the restatement row; checked by hand (text) |
| 2021-04 | 4,693 | restatement | [19263](https://www.caltrain.com/media/19263/download) 2022-06 board | 19 | table: row: "Av erage Weekday Ridership / 67,728 / 4,693* / 15,451 / 229.2%" ; column heading(s): Apr. 2019 / Apr. 2021 / Apr. 2022 | **used**; checked by hand (text) |
| 2021-05 | 5,521 | headline | [3527](https://www.caltrain.com/media/3527/download) 2021-07 board | 17 | table: row: "Average Weekday Ridership / 68,326 / 1,936 / 5,521 / 185.2%" ; column heading(s): May 2021 | **used**; checked by hand (text) |
| 2021-06 | 7,118 | headline | [195](https://www.caltrain.com/media/195/download) 2021-08 board | 15 | prose: line: "Average Weekday Ridership (AWR) increased by 146.8 percent to 7,118 from" ; month sentence line: "In June 2021, Caltrain's ridership was estimated as follows:" | superseded by the restatement row; checked by hand (text+image) |
| 2021-06 | 7,143 | restatement | [21498](https://www.caltrain.com/media/21498/download) 2022-08 board | 25 | table: row: "Average Weekday Ridership / 72,370 / 7,143* / 18,187 / 154.6%" ; column heading(s): Jun. 2019 / Jun. 2021 / Jun. 2022 | **used**; checked by hand (text) |
| 2021-07 | 8,714 | headline | [18566](https://www.caltrain.com/media/18566/download) 2021-09 board | 12 | prose: line: "Average Weekday Ridership (AWR) increased by 154.9 percent to 8,714 from" ; month sentence line: "In July 2021, Caltrain's ridership was estimated as follows:" | **used**; checked by hand (text) |
| 2021-08 | 9,053 | headline | [18500](https://www.caltrain.com/media/18500/download) 2021-10 board | 26 | prose: line: "Average Weekday Ridership (AWR) increased by 157.4 percent to 9,053 from" ; month sentence line: "In August 2021, Caltrain's ridership was estimated as follows:" | superseded by the restatement row; checked by hand (text) |
| 2021-08 | 9,096 | restatement | [23270](https://www.caltrain.com/media/23270/download) 2022-10 board | 23 | table: row: "Av erage Weekday Ridership / 71,557 / 9,096* / 18,609 / 104.6%" ; column heading(s): Aug. 2019 / Aug. 2021 / Aug. 2022 | **used**; checked by hand (text) |
| 2021-09 | 11,881 | gap-fill | [24300](https://www.caltrain.com/media/24300/download) 2022-11 board | 199 | chart: label "11,881" is bar 1 of 13 (11,881 ... 18,709) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Sep-22)"; axis label for this bar, read on the rendered page: Sep-21 | **used**; checked by hand (text+image) |
| 2021-10 | 11,673 | headline | [18457](https://www.caltrain.com/media/18457/download) 2021-12 board | 23 | table: row: "Average Weekday Ridership / 70,360 / 3,873* / 11,673 / 201.4%" ; column heading(s): October 2021 | **used**; checked by hand (text+image) |
| 2021-11 | 11,787 | headline | [8137](https://www.caltrain.com/media/8137/download) 2022-01 board | 45 | table: row: "Average Weekday Ridership / 69,607 / 3,760* / 11,787 / 213.5%" ; column heading(s): November 2021 | **used**; checked by hand (text) |
| 2021-12 | 9,687 | headline | [18373](https://www.caltrain.com/media/18373/download) 2022-02 board | 16 | table: row: "Average Weekday Ridership / 62,480 / 3,162* / 9,687 / 206.4%" ; column heading(s): December 2021 | **used**; checked by hand (text) |
| 2022-01 | 9,044 | headline | [18403](https://www.caltrain.com/media/18403/download) 2022-03 board | 19 | table: row: "Average Weekday Ridership / 64,806 / 3,058* / 9,044 / 195.7%" ; column heading(s): January 2022 | **used**; checked by hand (text) |
| 2022-02 | 10,956 | headline | [18233](https://www.caltrain.com/media/18233/download) 2022-04 board | 21 | table: row: "Average Weekday Ridership / 67,218 / 3,484* / 10,956 / 214.5%" ; column heading(s): Feb. 2020 / Feb. 2021 / Feb. 2022 | **used**; checked by hand (text) |
| 2022-03 | 12,539 | headline | [18350](https://www.caltrain.com/media/18350/download) 2022-05 board | 21 | table: row: "Av erage Weekday Ridership / 65,057 / 3,965* / 12,539 / 216.2%" ; column heading(s): Mar. 2019 / Mar. 2021 / Mar. 2022 | **used**; checked by hand (text+image) |
| 2022-04 | 15,451 | headline | [19263](https://www.caltrain.com/media/19263/download) 2022-06 board | 19 | table: row: "Av erage Weekday Ridership / 67,728 / 4,693* / 15,451 / 229.2%" ; column heading(s): Apr. 2019 / Apr. 2021 / Apr. 2022 | **used**; checked by hand (text) |
| 2022-05 | 15,757 | gap-fill | [24300](https://www.caltrain.com/media/24300/download) 2022-11 board | 199 | chart: label "15,757" is bar 9 of 13 (11,881 ... 18,709) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Sep-22)"; axis label for this bar, read on the rendered page: May-22 | **used**; checked by hand (text+image) |
| 2022-06 | 18,187 | headline | [21498](https://www.caltrain.com/media/21498/download) 2022-08 board | 25 | table: row: "Average Weekday Ridership / 72,370 / 7,143* / 18,187 / 154.6%" ; column heading(s): Jun. 2019 / Jun. 2021 / Jun. 2022 | **used**; checked by hand (text) |
| 2022-07 | 16,932 | gap-fill | [24300](https://www.caltrain.com/media/24300/download) 2022-11 board | 199 | chart: label "16,932" is bar 11 of 13 (11,881 ... 18,709) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Sep-22)"; axis label for this bar, read on the rendered page: Jul-22 | **used**; checked by hand (text+image) |
| 2022-08 | 18,609 | headline | [23270](https://www.caltrain.com/media/23270/download) 2022-10 board | 23 | table: row: "Av erage Weekday Ridership / 71,557 / 9,096* / 18,609 / 104.6%" ; column heading(s): Aug. 2019 / Aug. 2021 / Aug. 2022 | **used**; checked by hand (text+image) |
| 2022-09 | 18,709 | headline | [24300](https://www.caltrain.com/media/24300/download) 2022-11 board | 199 | chart: label "18,709" is bar 13 of 13 (11,881 ... 18,709) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Sep-22)"; axis label for this bar, read on the rendered page: Sep-22 | **used**; checked by hand (text+image) |
| 2022-10 | 18,583 | headline | [25257](https://www.caltrain.com/media/25257/download) 2022-12 board | 12 | chart: label "18,583" is bar 13 of 13 (11,673 ... 18,583) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Oct-22)"; axis label for this bar, read on the rendered page: Oct-22 | **used**; checked by hand (text+image) |
| 2022-11 | 16,857 | headline | [26750](https://www.caltrain.com/media/26750/download) 2023-01 board | 19 | chart: label "16,857" is bar 13 of 13 (11,787 ... 16,857) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Nov-22)"; axis label for this bar, read on the rendered page: Nov-22 | **used**; checked by hand (text+image) |
| 2022-12 | 12,513 | headline | [27986](https://www.caltrain.com/media/27986/download) 2023-02 board | 60 | chart: label "12,513" is bar 13 of 13 (9,687 ... 12,513) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Dec-22)"; axis label for this bar, read on the rendered page: Dec-22 | **used**; checked by hand (text+image) |
| 2023-01 | 14,655 | headline | [28710](https://www.caltrain.com/media/28710/download) 2023-03 board | 12 | chart: label "14,655" is bar 13 of 13 (9,044 ... 14,655) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Jan-23)"; axis label for this bar, read on the rendered page: Jan-23 | **used**; checked by hand (text+image) |
| 2023-02 | 16,489 | headline | [29542](https://www.caltrain.com/media/29542/download) 2023-03 board | 12 | chart: label "16,489" is bar 13 of 13 (10,956 ... 16,489) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Feb-23)"; axis label for this bar, read on the rendered page: Feb-23 | **used**; checked by hand (text+image) |
| 2023-03 | 16,628 | headline | [30295](https://www.caltrain.com/media/30295/download) 2023-05 board | 33 | chart: label "16,628" is bar 13 of 13 (12,539 ... 16,628) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Mar-23)"; axis label for this bar, read on the rendered page: Mar-23 | **used**; checked by hand (text+image) |
| 2023-04 | 18,621 | headline | [30516](https://www.caltrain.com/media/30516/download) 2023-06 board | 12 | chart: label "18,621" is bar 13 of 13 (15,451 ... 18,621) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Apr-23)"; axis label for this bar, read on the rendered page: Apr-23 | **used**; checked by hand (text+image) |
| 2023-05 | 18,678 | gap-fill | [31302](https://www.caltrain.com/media/31302/download) 2023-08 board | 12 | chart: label "18,678" is bar 12 of 13 (18,008 ... 20,452) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (June-23)"; axis label for this bar, read on the rendered page: May-23 | **used**; checked by hand (text+image) |
| 2023-06 | 20,452 | headline | [31302](https://www.caltrain.com/media/31302/download) 2023-08 board | 12 | chart: label "20,452" is bar 13 of 13 (18,008 ... 20,452) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (June-23)"; axis label for this bar, read on the rendered page: Jun-23 | **used**; checked by hand (text+image) |
| 2023-07 | 20,334 | headline | [31538](https://www.caltrain.com/media/31538/download) 2023-09 board | 12 | chart: label "20,334" is bar 13 of 13 (16,767 ... 20,334) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (July-23)"; axis label for this bar, read on the rendered page: Jul-23 | **used**; checked by hand (text+image) |
| 2023-08 | 20,284 | headline | [31725](https://www.caltrain.com/media/31725/download) 2023-10 board | 11 | chart: label "20,284" is bar 13 of 13 (18,598 ... 20,284) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Aug-23)"; axis label for this bar, read on the rendered page: Aug-23 | **used**; checked by hand (text+image) |
| 2023-09 | 21,366 | headline | [31940](https://www.caltrain.com/media/31940/download) 2023-11 board | 12 | chart: label "21,366" is bar 13 of 13 (18,696 ... 21,366) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Sep-23)"; axis label for this bar, read on the rendered page: Sep-23 | **used**; checked by hand (text+image) |
| 2023-10 | 19,939 | headline | [32238](https://www.caltrain.com/media/32238/download) 2023-12 board | 12 | chart: label "19,939" is bar 13 of 13 (18,565 ... 19,939) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Oct-23)"; axis label for this bar, read on the rendered page: Oct-23 | **used**; checked by hand (text+image) |
| 2023-11 | 20,877 | gap-fill | [32695](https://www.caltrain.com/media/32695/download) 2024-02 board | 15 | chart: label "20,877" is bar 12 of 13 (12,513 ... 17,383) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Dec-23)"; axis label for this bar, read on the rendered page: Nov-23 | **used**; checked by hand (text+image) |
| 2023-12 | 17,383 | headline | [32695](https://www.caltrain.com/media/32695/download) 2024-02 board | 15 | chart: label "17,383" is bar 13 of 13 (12,513 ... 17,383) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Dec-23)"; axis label for this bar, read on the rendered page: Dec-23 | **used**; checked by hand (text+image) |
| 2024-01 | 19,790 | headline | [32972](https://www.caltrain.com/media/32972/download) 2024-03 board | 15 | chart: label "19,790" is bar 13 of 13 (14,655 ... 19,790) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Jan-24)"; axis label for this bar, read on the rendered page: Jan-24 | **used**; checked by hand (text+image) |
| 2024-02 | 21,193 | headline | [33129](https://www.caltrain.com/media/33129/download) 2024-04 board | 14 | chart: label "21,193" is bar 13 of 13 (16,829 ... 21,193) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Feb-24)"; axis label for this bar, read on the rendered page: Feb-24 | **used**; checked by hand (text+image) |
| 2024-03 | 21,773 | headline | [33327](https://www.caltrain.com/media/33327/download) 2024-05 board | 14 | chart: label "21,773" is bar 13 of 13 (16,628 ... 21,773) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Mar-24)"; axis label for this bar, read on the rendered page: Mar-24 | **used**; checked by hand (text+image) |
| 2024-04 | 23,122 | headline | [33565](https://www.caltrain.com/media/33565/download) 2024-06 board | 15 | chart: label "23,122" is bar 13 of 13 (18,621 ... 23,122) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Apr-24)"; axis label for this bar, read on the rendered page: Apr-24 | **used**; checked by hand (text+image) |
| 2024-05 | 24,457 | gap-fill | [33783](https://www.caltrain.com/media/33783/download) 2024-08 board | 16 | chart: label "24,457" is bar 12 of 13 (20,663 ... 24,583) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Jun-24)"; axis label for this bar, read on the rendered page: May-24 | **used**; checked by hand (text+image) |
| 2024-06 | 24,583 | headline | [33783](https://www.caltrain.com/media/33783/download) 2024-08 board | 16 | chart: label "24,583" is bar 13 of 13 (20,663 ... 24,583) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Jun-24)"; axis label for this bar, read on the rendered page: Jun-24 | **used**; checked by hand (text+image) |
| 2024-07 | 23,286 | headline | [33993](https://www.caltrain.com/media/33993/download) 2024-09 board | 16 | chart: label "23,286" is bar 13 of 13 (20,525 ... 23,286) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Jul-24)"; axis label for this bar, read on the rendered page: Jul-24 | **used**; checked by hand (text+image) |
| 2024-08 | 24,741 | headline | [34193](https://www.caltrain.com/media/34193/download) 2024-10 board | 16 | chart: label "24,741" is bar 13 of 13 (20,284 ... 24,741) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Aug-24)"; axis label for this bar, read on the rendered page: Aug-24 | **used**; checked by hand (text+image) |
| 2024-09 | 26,541 | headline | [34377](https://www.caltrain.com/media/34377/download) 2024-11 board | 16 | chart: label "26,541" is bar 13 of 13 (21,366 ... 26,541) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Sep-24)"; axis label for this bar, read on the rendered page: Sep-24 | **used**; checked by hand (text+image) |
| 2024-10 | 27,583 | headline | [34492](https://www.caltrain.com/media/34492/download) 2024-12 board | 16 | chart: label "27,583" is bar 13 of 13 (19,939 ... 27,583) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Oct-24)"; axis label for this bar, read on the rendered page: Oct-24 | **used**; checked by hand (text+image) |
| 2024-11 | 25,868 | headline | [34670](https://www.caltrain.com/media/34670/download) 2025-01 board | 16 | chart: label "25,868" is bar 13 of 13 (20,904 ... 25,868) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Nov-24)"; axis label for this bar, read on the rendered page: Nov-24 | **used**; checked by hand (text+image) |
| 2024-12 | 24,037 | headline | [34821](https://www.caltrain.com/media/34821/download) 2025-02 board | 15 | chart: label "24,037" is bar 13 of 13 (17,358 ... 24,037) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Dec-24)"; axis label for this bar, read on the rendered page: Dec-24 | **used**; checked by hand (text+image) |
| 2025-01 | 29,052 | headline | [34922](https://www.caltrain.com/media/34922/download) 2025-03 board | 15 | chart: label "29,052" is bar 13 of 13 (19,802 ... 29,052) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Jan-25)"; axis label for this bar, read on the rendered page: Jan-25 | **used**; checked by hand (text+image) |
| 2025-02 | 30,077 | headline | [35046](https://www.caltrain.com/media/35046/download) 2025-04 board | 15 | chart: label "30,077" is bar 13 of 13 (21,237 ... 30,077) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Feb-25)"; axis label for this bar, read on the rendered page: Feb-25 | **used**; checked by hand (text+image) |
| 2025-03 | 32,418 | headline | [35191](https://www.caltrain.com/media/35191/download) 2025-05 board | 15 | chart: label "32,418" is bar 13 of 13 (21,783 ... 32,418) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Mar-25)"; axis label for this bar, read on the rendered page: Mar-25 | **used**; checked by hand (text+image) |
| 2025-04 | 35,374 | headline | [35405](https://www.caltrain.com/media/35405/download) 2025-06 board | 17 | chart: label "35,374" is bar 13 of 13 (23,131 ... 35,374) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Apr-25)"; axis label for this bar, read on the rendered page: Apr-25 | **used**; checked by hand (text+image) |
| 2025-05 | 37,495 | gap-fill | [35692](https://www.caltrain.com/media/35692/download) 2025-08 board | 16 | chart: label "37,495" is bar 13 of 14 (24,464 ... 39,902) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Jun-25)"; axis label for this bar, read on the rendered page: May-25 | **used**; checked by hand (text+image) |
| 2025-06 | 39,902 | headline | [35692](https://www.caltrain.com/media/35692/download) 2025-08 board | 16 | chart: label "39,902" is bar 14 of 14 (24,464 ... 39,902) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Jun-25)"; axis label for this bar, read on the rendered page: Jun-25 | **used**; checked by hand (text+image) |
| 2025-07 | 40,015 | headline | [35820](https://www.caltrain.com/media/35820/download) 2025-09 board | 16 | chart: label "40,015" is bar 14 of 14 (24,589 ... 40,015) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Jul-25)"; axis label for this bar, read on the rendered page: Jul-25 | **used**; checked by hand (text+image) |
| 2025-08 | 39,986 | headline | [35953](https://www.caltrain.com/media/35953/download) 2025-10 board | 17 | chart: label "39,986" is bar 14 of 14 (23,291 ... 39,986) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Aug-25)"; axis label for this bar, read on the rendered page: Aug-25 | **used**; checked by hand (text+image) |
| 2025-09 | 41,065 | headline | [36025](https://www.caltrain.com/media/36025/download) 2025-11 board | 15 | chart: label "41,065" is bar 14 of 14 (24,762 ... 41,065) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Sep-25)"; axis label for this bar, read on the rendered page: Sep-25 | **used**; checked by hand (text+image) |
| 2025-10 | 39,900 | headline | [36143](https://www.caltrain.com/media/36143/download) 2025-12 board | 15 | chart: label "39,900" is bar 13 of 13 (27,600 ... 39,900) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Oct-25)"; axis label for this bar, read on the rendered page: Oct-25 | **used**; checked by hand (text+image) |
| 2025-11 | 37,779 | headline | [36365](https://www.caltrain.com/media/36365/download) 2026-01 board | 22 | chart: label "37,779" is bar 13 of 13 (25,892 ... 37,779) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Nov-25)"; axis label for this bar, read on the rendered page: Nov-25 | **used**; checked by hand (text+image) |
| 2025-12 | 33,546 | headline | [36490](https://www.caltrain.com/media/36490/download) 2026-02 board | 14 | chart: label "33,546" is bar 13 of 13 (24,047 ... 33,546) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Dec-25)"; axis label for this bar, read on the rendered page: Dec-25 | **used**; checked by hand (text+image) |
| 2026-01 | 37,827 | headline | [36688](https://www.caltrain.com/media/36688/download) 2026-03 board | 15 | chart: label "37,827" is bar 13 of 13 (29,055 ... 37,827) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Jan-26)"; axis label for this bar, read on the rendered page: Jan-26 | **used**; checked by hand (text+image) |
| 2026-02 | 38,585 | headline | [36846](https://www.caltrain.com/media/36846/download) 2026-04 board | 14 | chart: label "38,585" is bar 13 of 13 (30,080 ... 38,585) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Feb-26)"; axis label for this bar, read on the rendered page: Feb-26 | **used**; checked by hand (text+image) |
| 2026-03 | 42,003 | headline | [37013](https://www.caltrain.com/media/37013/download) 2026-05 board | 15 | chart: label "42,003" is bar 14 of 14 (30,080 ... 42,003) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Mar-26)"; axis label for this bar, read on the rendered page: Mar-26 | **used**; checked by hand (text+image) |
| 2026-04 | 43,410 | headline | [37123](https://www.caltrain.com/media/37123/download) 2026-06 board | 15 | chart: label "43,410" is bar 13 of 13 (35,434 ... 43,410) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Apr-26)"; axis label for this bar, read on the rendered page: Apr-26 | **used**; checked by hand (text+image) |
| 2026-05 | 45,268 | gap-fill | [37410](https://www.caltrain.com/media/37410/download) 2026-08 board | 14 | chart: label "45,268" is bar 12 of 13 (40,084 ... 48,802) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Jun-26)"; axis label for this bar, read on the rendered page: May-26 | **used**; checked by hand (text+image) |
| 2026-06 | 48,802 | headline | [37410](https://www.caltrain.com/media/37410/download) 2026-08 board | 14 | chart: label "48,802" is bar 13 of 13 (40,084 ... 48,802) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Jun-26)"; axis label for this bar, read on the rendered page: Jun-26 | **used**; checked by hand (text+image) |
| 2026-07 | 47,459 | headline | [37685](https://www.caltrain.com/media/37685/download) 2026-09 board | 15 | chart: label "47,459" is bar 13 of 13 (39,987 ... 47,459) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Jul-26)"; axis label for this bar, read on the rendered page: Jul-26 | **used**; checked by hand (text+image) |
| 2026-08 | 49,685 | headline | [37883](https://www.caltrain.com/media/37883/download) 2026-10 board | 15 | chart: label "49,685" is bar 13 of 13 (39,986 ... 49,685) under the "Average Weekday Ridership" legend; caption "Average Daily Ridership (Aug-26)"; axis label for this bar, read on the rendered page: Aug-26 | **used**; checked by hand (text+image) |
