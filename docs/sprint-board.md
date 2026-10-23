# Sprint board

## Sprint 4b — One BART station table (opened 2026-10-22)

(Named 4b, with ids S4b.x, because the parallel interval-calibration branch, PR #138, also adds a "Sprint 4" with S4.x ids. Board-only commit messages on this branch say "S4.x"; they mean these stories.)

**Goal.** One authoritative table (BART 2-letter code → name → website id →
weather location), sourced from repo data, used by the export, the
`merge_pipeline` weather mapping, feature engineering and the website. Closes the
Sprint 3 follow-up "Station-level website JSON exports empty".

**Branch.** `fix/bart-station-table`, cut from `origin/sprint3/pr-backlog` @
`32a75df` because PR #136 is still open; the PR targets that branch.

**Starting state** (measured 2026-10-22):

| Fact | Value |
|---|---|
| Store / workbook codes | 50 two-letter codes (`12 16 19 24 AN AS BE BF … WS`); the workbooks carry no names |
| `fetch_bart_od.STATION_NAMES` | 50 four-letter BART API codes → names; the only name source |
| 2-letter → name link | Only `website/data/stations_meta.json` from `c5f5891` (2026-05-07): 47 of 50 named, BF/ML/WP left as codes. No commit ever held a 2-letter → name dict, so this is one source |
| Export on this code | `stations_ridership.json` `{}`, `ridership_actuals.json` `[]`, `stations_meta.json` names = codes, `website_id` null (0 of 50 mapped) |
| Committed `forecasts.json`, `ridership_actuals.json` | From `c5f5891`, ~4.3× the current Total-Trips target (EM 2023-12: 1.23M committed vs 286k in the store) |
| Same 4-letter gap elsewhere | `HUB_STATIONS` (`is_hub_station` always False); `sections.jsx` `KEY_STATIONS.id`, `api-demo.html` fallback list, `api.py` examples and `predict.py --station` send 4-letter ids the store rejects |
| Map page | `transit-demo.html` never reads `stations_ridership.json`; the export's `baseAM`/`basePM` are normalized × 1.05 / 0.95, not measured |

**Gates.** Leaderboard identical to this branch's baseline run on `32a75df`
(expected SARIMA 3.21 / Prophet 5.75 / Chronos-1 9.70 / SeasonalNaive 10.75,
n=300) or each delta named; store target identical, every other column delta
named; the three station JSONs non-empty for all 50 stations;
`model_comparison.json` identical; website served locally renders the map,
forecast table and calibration chart from the new files; `py_compile` and JSX parse.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S4b.0 | Baseline: rebuild store, benchmarks and export on unmodified `32a75df` | orchestrator | — | Leaderboard and export recorded | done — 3.21 / 5.75 / 9.70 / 10.75, n=300; `model_comparison.json` byte-identical to the committed file; station exports 0 / 0 / 50 unnamed |
| S4b.1 | `machine_learning_files/bart_stations.py`: the table, helpers, `--check` | implementer | user decisions | `--check` passes against `STATION_NAMES`, `sources.yaml`, `transit-demo.html` and the store | done (af10e82) — `--check` OK: 50 stations, 41 website ids, 6 weather stations |
| S4b.2 | Pipeline consumers: `bart_od_from_xlsx.py`, `bart_od_from_csv.py`, `merge_pipeline.py`, `feature_engineering.py`, `api.py`, `predict.py` | implementer | S4b.1 | Rebuilt store: names for 50, per-station weather for the six mapped stations, `is_hub_station` true for the hub set | done (8c92631, 39827b9) |
| S4b.3 | Export: 2-letter `station_id` for all 50, new `stations_meta`/`stations_ridership` schema, `forecasts.json` from the benchmark's Chronos-1 run | implementer | S4b.1 | Export from rebuilt store: 50/50 in each station file | done (4bad2ef) |
| S4b.4 | Website: one id style, map reads `stations_ridership.json`, copy matches the new data | implementer | S4b.3 schema (fixed in this board) | JSX parses; local render shows data | done (ce83caa) |
| S4b.5 | Full rerun, regenerate `website/data/`, run gates | orchestrator | S4b.2–S4b.4 | All gates green or deltas named | done — gate2 on f606498 ALL PASS, export byte-identical to gate1 (two independent runs); `website/data/` regenerated from gate2 in 087adcb; served locally and checked in headless Chrome: forecast table (EM: 12 actual months, then Jul–Dec 2025 actual beside P10/P50/P90), calibration chart with actuals, all 50 stations in the picker, map with 41 of 41 BART nodes on real levels. Earlier: gate1 on ce83caa ALL PASS: leaderboard, all result slices and Chronos preds identical to baseline; store deltas only `station_name`, the six stations' weather (+ `temp_deviation`, `is_rain_onset`, `precip_intensity`, `weather_discomfort`), `is_hub_station` on the ten hubs; export 50/50/3,000/300, `model_comparison.json` identical. Rerun after the fix round; `website/data/` not yet regenerated |
| S4b.6 | Review the branch diff | code-reviewer | S4b.5 | No BLOCKER open | in progress — R1 on ce83caa: spec PASS, quality changes requested; 1 BLOCKER (index-page map copy contradicts the map's new caption), 2 MAJOR (refused forecasts exit 0 and leave the stale file; map's "ons/hr" invented unit beside real boardings), 11 MINOR. Fix round: F1 adf65b6 (refused forecasts exit 1, inputs checked before writes, forecasts tied to the leaderboard row's n, no silent station drop, docs), F2 f606498 (index map copy, unitless load index, tie-break, forecast months from data, late live response dropped, parallel fetch, cache-busters). R2 scoped review of adf65b6..087adcb in progress |
| S4b.7 | Audit board against git | delivery-auditor | S4b.6 | No unresolved disagreement | todo |
| S4b.8 | Push, open PR against `sprint3/pr-backlog` (no merge) | orchestrator | S4b.7 | PR open | todo |

S4b.2, S4b.3 and S4b.4 touch disjoint files and run in parallel after S4b.1.

### Rulings (Sprint 4b)

- **2026-10-22, the user's answers at the Go Ahead gate:**
  1. ML = Milpitas (`MLPT`), WP = Pittsburg/Bay Point (`PITT`), and the
     website `pit` node belongs to WP. The repo cannot pair these alone:
     elimination leaves exactly those two codes for those two names, and ML's
     all-zero 2019 matches BE (Berryessa). Recorded in the table as
     user-confirmed, not repo-sourced. `c5f5891` had given `pit` to PC; that
     mapping is dropped.
  2. `forecasts.json` is regenerated from the benchmark's Chronos-1 zero-shot
     predictions for Jul–Dec 2025 (the leaderboard run), replacing the stale May file.
  3. `HUB_STATIONS` is re-keyed through the table in this PR.
- BF → Bay Fair (`BAYF`): `c5f5891`'s map comment, the `transit-demo.html` node
  `bayp` "Bay Fair", and HEAD's `BAYF → bayp` all agree.
- Weather keeps the six name-matched locations (EM, MB, FM, BE, SO, 19). No
  nearest-location assignment: that would be a modeling change nobody asked for.
- `stations_ridership.json` averages the latest 12 store months. Averaging over
  2019 and 2022–25 mixes levels across the ~2.9× COVID break, and counts BE and
  ML's pre-opening zeros. `baseAM`/`basePM` are dropped: they are not measured.
- F1: with `--allow-val-fallback` and no leaderboard the export now exits 1,
  because forecasts cannot be tied to a scored run. The fallback is opt-in and
  off by default. Cost if wrong: a fallback run needs `|| true`.
- F2: the BARTForecasts heading's "6-month" is derived from `forecasts.json`, so
  the empty-forecasts text cannot contradict it.
- Sibling PRs, all against `sprint3/pr-backlog`: trial merges of this branch with
  #138 (interval calibration) conflict only in this board file; with #137 (API
  serving) only in `machine_learning_files/api.py`, where both sides set the
  examples to `EM` — take #137's file. #137 commits `data/processed/feature_store.parquet`
  built before this branch; it differs from this branch's store only in
  `station_name` and the six stations' weather, so rebuild and commit it after
  both merge.

### Follow-ups (Sprint 4b, found here, not fixed here)

- Published model claims that no run supports: the hero says Chronos-1 is
  "enriched with weather and events data" (`sections.jsx:92`), and the site
  shows feature-importance values (`sections.jsx` ~:206, ~:292). The review found
  the zero-shot path never passes covariates: under chronos-forecasting 2.3.2
  `predict_df(future_df=…)` raises TypeError and the code falls back to
  univariate (50 "Falling back to univariate mode" lines per run). No ranked
  model reads weather, events or `is_hub_station`.
- `models/baselines/fetch_pems_roads.py:49-52` `near` values are four-letter (module unwired).
- `website/data/*.json` fetches carry no cache-buster (`app.yaml` caches 1 day).
- Hard-coded years that go stale on the next refresh: "2019 and 2022–2025" for
  actuals; "Jul–Dec 2025 test split" labels beside `model_comparison.json`.
- Dark mode: `index.html` sets `--primary` inline, so P50 values and forecast
  month labels render navy on the dark background.
- The Google Maps key refuses localhost ("can't load Google Maps correctly"),
  so local checks of `transit-demo.html` show a development watermark.

## Sprint 3 — Clear the open-PR backlog (opened 2026-10-22)

**Goal.** Every still-valid fix in the 104 open PRs reaches `main` through one
reviewed consolidation PR. Every other PR is closed with a written disposition.
Sprint 2's published numbers do not move unless a named change explains it.

**Starting state** (measured 2026-10-22 against `origin/main` @ `cb7da6d`):

| Fact | Value |
|---|---|
| Open PRs | 104, all drafts from the daily `claude/nifty-goodall-*` audit routine |
| Conflict with `main` | 87; the 17 clean ones are mostly log-only |
| Linear chains | #84→#116 (33 PRs, tip #116); #62→#65; #118→#119 |
| Already-merged cumulative tips | #26, #38, #42, #83 (#83 carried the fixes of #43–#82 by content; by ancestry it contains #68–#82) |
| Hunks across non-contained tips | 979: 123 already on main, 84 logs, 415 apply, 336 stale, 21 new root-level log files |

**Gates for closing the sprint.** Leaderboard bit-identical to Sprint 2
(SARIMA 3.21 / Prophet 5.75 / Chronos-1 9.70 / SeasonalNaive 10.75, n=300) or
each delta traced to a named change; website export no worse than `main`
(`model_comparison.json` identical; the station JSONs already export empty on
`main` because of the 4-letter vs 2-letter code gap, a known Sprint 2 follow-up);
`py_compile` passes on every touched file; JSX parses.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S3.1 | Map chains, conflicts and hunk residue for all 104 PRs | orchestrator | — | Tables in this board's starting state | done (recorded in 6c82330) |
| S3.2a | Triage: `api.py`, `scheduler.py`, `Dockerfile.api`, `requirements.txt` | principal-engineer | S3.1 | Ruling per item in report | done — 61 items: KEEP_116 18, ADAPT_116 1, PORT 6 (incl. #122 reworked) — rulings committed in 6b9f48e |
| S3.2b | Triage: `predict.py`, `finetune.py`, `zero_shot.py` | principal-engineer | S3.1 | Ruling per item in report | done — 86 items: KEEP_116 26, ADAPT_116 1, REJECT_116 5, PORT 3, rest closable — rulings committed in 6b9f48e |
| S3.2c | Triage: `merge_pipeline.py`, `validators.py`, `fetch_bart_od.py` | principal-engineer | S3.1 | Ruling per item in report | done — 63 items: KEEP_116 14, ADAPT_116 4, REJECT_116 3, PORT 1 (H58, from #12) — rulings committed in 6b9f48e |
| S3.2d | Triage: `feature_engineering.py`, other `fetch_*`, `fetch_pems_roads.py`, `run_pipeline.sh` | principal-engineer | S3.1 | Ruling per item in report | done — 57 items: KEEP_116 21, ADAPT_116 2 (H232, H233), PORT 0, REJECT 4 (2 unverified) — rulings committed in 6b9f48e |
| S3.2e | Triage: `benchmarks`, `ablation`, `metrics`, `prophet_baseline`, `arima`, `export_website_data` | principal-engineer | S3.1 | Ruling per item; #135 checked against #132 | done — 70 items: KEEP_116 25, ADAPT_116 7, REJECT_116 4, PORT 2; leaderboard recomputed from saved forecasts, unchanged; #135 compatible but closable — rulings committed in 6b9f48e |
| S3.2f | Triage: website JSX/CSS/JSON, README, `docs/`, EDA notebook | principal-engineer | S3.1 | Ruling per item in report | done — 60 items: KEEP_116 31, ADAPT_116 6, REJECT_116 6, PORT 6 — rulings committed in 6b9f48e |
| S3.3 | Identify the routine that opens a PR daily | orchestrator | — | Routine named, with a pause/reconfigure proposal | done (recorded in ded24a6) — remote routine "Test" (`trig_01ML7Tvxyi698UL1sgXPRXa4`), daily 13:00 UTC since 2026-05-03; proposal goes to the user, not changed by us |
| — | **Gate: push, PR closes and the routine change wait for the user** | orchestrator | S3.2*, S3.3 | User's explicit yes | done — 2026-10-22 the user said yes to all three: push and open the PR once review has no open BLOCKER; close the 61 after they merge; pause the routine |
| S3.4 | Merge #116 into this branch; resolve conflicts toward Sprint 2; revert rejected hunks | implementer | Gate | Diff matches S3.2 rulings | done (f919788 merge, ports 7386f5a 42471da 276a21c aa16f59 5e126ec) — rulings checker 0 unexplained failures, invariants 32/32 |
| S3.5 | Merge the log-only PRs | orchestrator | S3.4 | Each merges; only `updates/*.md` change | done (8ce12dc, octopus of 10; 7d3b491, #118 added after the audit) |
| S3.6 | Port KEEP fixes from superseded old PRs, credited to source PR | implementer | S3.5 | One commit per cluster | done — folded into S3.4's port commits |
| S3.7 | Review the whole consolidation diff against `origin/main` | code-reviewer | S3.6 | No BLOCKER open | done — R1: 0 BLOCKER, 2 MAJOR, fixed in 825df57. R2: 2 BLOCKER and 2 MAJOR, fixed in a565f4b, c7de29c and a317cdf. Scoped re-review: all closed except R2-M1 and a B2 residual, fixed in 5cef2c5, 39349b2 and cf728d5. Final scoped review of those three: all approved, 0 BLOCKER/MAJOR, 5 MINOR (listed under follow-ups) |
| S3.8 | Run the sprint gates | orchestrator | S3.7 | All four gates green | done on 8608710 (gate3): leaderboard identical, n = n_expected = 300, 0 rejected, two runs byte-identical; store target identical; export identical; py_compile and JSX re-run by the auditor: pass. Rerun required if the final review changes code |
| S3.9 | Audit board against git | delivery-auditor | S3.8 | No unresolved disagreement | done — 10 disagreements (1 MEDIUM, 9 LOW), all addressed in this board revision and 7d3b491; started before S3.8 closed |
| S3.10 | Open consolidation PR; after the user merges it, close the superseded list | orchestrator | S3.9 | Needs user's yes for the closes | in progress — PR #136 opened (mergeable, clean); routine paused 2026-10-22; 60 close comments prepared; closes run after the user merges #136 |

## Rulings

- `.claude/` was gitignored wholesale. Narrowed to `.claude/*` plus
  `!.claude/agents/` so agent definitions are tracked and local settings stay
  out. Cost if wrong: one `.gitignore` line.
- Root cause of the backlog: the routine's prompt ("check for bugs, prepare
  improvements, create a file for the day's updates") gives it no rule for what
  to do when its previous PR is unmerged, so it opens a new one every day and
  carries the old one forward. Changing the routine is the user's call.
- #116 must never be merged as-is (S3.2c, executed): its side of the
  `merge_pipeline.py` conflict drops Sprint 2's `combined[is_total]` filter, so all
  four BART day-type blocks would be summed; and its new parquet-read helper
  deletes files on any read error, which deleted every BART parquet file when no
  parquet engine was installed. Resolve the conflict to `main`'s side and land the
  S3.2c patches P1–P3 inside the merge commit itself.

## Triage result (S3.2, 397 content-unique items, all ruled)

Every item, its source PRs, ruling, reason and evidence: `docs/sprint3-triage-rulings.jsonl`
(one JSON object per line; item ids such as `H23` are the ones cited in commit messages and PR close comments).

| Ruling | Count |
|---|---|
| KEEP_116 | 135 |
| ADAPT_116 | 21 |
| REJECT_116 | 18 |
| PORT (from older PRs) | 18 |
| SUPERSEDED | 130 |
| OBSOLETE | 12 |
| REJECT | 63 |

## Merge plan (built locally; push, PR closes and the routine change waited for the user's yes, given 2026-10-22)

On `sprint3/pr-backlog`, in this order:

1. **Merge #116** (brings #84–#115 by ancestry). Conflicts in `merge_pipeline.py`,
   `benchmarks.py`, `arima.py`, `prophet_baseline.py`, `README.md`,
   `sections.jsx`, `model_comparison.json` resolve to `main`. The 18 REJECT_116
   reverts and 21 ADAPT_116 replacements land **inside the merge commit**, so no
   commit on the branch's first-parent line has the data-deleting or
   day-type-summing state. #116's own commits stay reachable through the merge's
   second parent, as history.
2. **Port the 18 PORT items**, one commit per cluster, each crediting its source PRs.
3. **Merge the log-only PRs**: #56, #57, #66, #67, #117, #118, #120, #121, #123, #124, #126.
   (#67 also touches two code files, but its changes there are already on `main`;
   merging it changed only its log.)
4. Review, gates, audit, push, open the consolidation PR.

User merges the consolidation PR with **"Create a merge commit"** (not squash or
rebase), which marks #84–#116 and the eleven log-only PRs merged, as happened to
#131–#133 when #134 landed. The remaining 60 PRs are closed with a per-PR
disposition comment, only on the user's yes.

- #122 is not merged as a PR: its second hunk would revert #116's NaN handling.
  Its validate-before-load idea is ported, reworked (S3.2a H392).
- #128's doc text is replaced: it recommends `bart_od_from_csv.py`, whose output
  `load_transit` rejects; the working path is `bart_od_from_xlsx.py` (S3.2f P5).
- #135 only deletes a blank line and its log calls the backlog solved: closed.
- #119's bare-except fix is ported in the form from #17 (H84), not #119's (H391).
- S3.4 and S3.6 merged into one story: the composer applied the PORT items as
  per-cluster commits right after the merge commit, so a separate dispatch would
  only have re-read the same reports.
- Gate environment pinned: /tmp/tdf-venv — Python 3.14.0, pandas 3.0.6, numpy 2.5.4,
  statsmodels 0.15.0, prophet 1.5.0, torch 2.14.1, chronos-forecasting 2.3.2.
- Baseline for the store gate: `main`'s code rebuilds a feature store identical to
  Sprint 2's (3,000 rows, both files, `assert_frame_equal`).
- The 33 `updates/*.md` logs that arrive with #116 and the 10 log-only PRs are
  kept verbatim: dated records of what the routine reported, not current claims.

## Gate results (S3.8, 2026-10-22, pinned env above)

| Gate | Result |
|---|---|
| Leaderboard | Identical to `main` on every metric: SARIMA 3.21 / Prophet 5.75 / Chronos-1 9.70 / SeasonalNaive 10.75 WAPE%, n=300. Adds a MASE column (0.3677 / 0.6585 / 1.1105 / 1.2311). Two runs byte-identical. |
| Feature store | Rebuilt from the same raw files by `main` and by this branch: target identical (0 rows added or lost, max abs diff 0, 50/50 stations). Differences, each traced: new `precip_in`, `humidity_pct` columns (#91); `is_rain_onset` false on 250 rainy months that follow a rainy month (bool-upcast fix, #102: `main` flagged every rainy month as an onset); `hours_to_next_event`/`hours_since_last_event` NaN instead of 0.0 when there are no events (#90: 0.0 meant "event now"); splits now cut from the enriched store (H233). |
| Website export | All five JSON files byte-identical between `main`'s code and this branch; `model_comparison.json` identical to the committed file. Station JSONs export empty on both (known gap). |
| py_compile / JSX | 20 changed .py files compile; both changed .jsx files parse (TypeScript 5.9.3). |
- Review R2 BLOCKER B1 (introduced by #116's metrics hunks): rows with a NaN
  prediction were dropped, so a model that skipped its hardest stations scored
  better (WAPE 2.0 vs 14.86 in the reviewer's repro) and still ranked first.
  Ruling: a missing actual is left out; a missing prediction or interval bound
  where an actual exists makes the metric NaN, and `accept_model_rows` rejects a
  NaN or missing WAPE loudly. Cost if wrong: a model with a legitimately partial
  forecast is excluded instead of scored on what it forecast.
- Review R2 BLOCKER B2 (already on `main`): published text claiming a forecast
  cache baked into the Docker image, a SARIMA(2,1,2) label, 2023 or "validation"
  captions over 2025-H2 test data, and "Chronos-2". Fixed here as one text-only
  commit marked as not from any backlog PR, because this branch's own new text
  contradicts it. The Docker 503 itself is a follow-up.
- B1 extended in a fix round: `compute_metrics` inner-joined predictions onto
  actuals, so a model that omitted rows (rather than emitting NaN) was scored on
  its chosen subset (probe: n=240, WAPE 2.0, accepted). Pre-existing on `main` and
  live (SARIMA, Prophet and SeasonalNaive skip short-history stations). Same rule:
  scored on every test row or rejected, with the missing stations named.
- Review R1 M2 (pre-existing): `scheduler.py` could not import repo packages when
  run as documented. The deferred X1 one-line fix is included after all, because
  #116's ruled scheduler steps (H330, H350) cannot run without it.
- After the fixes, the leaderboard CSV gains an `n_expected` column (appended, so
  existing columns keep their order) and the console/LaTeX tables label MASE
  "in-sample". The CSV column `MASE` and every value are unchanged.
- S3.4's invariant checker now reports 29/32, all three expected: "X1 NOT included"
  is intentionally false (R1 M2 ruling), and two `benchmarks.py` pattern checks are
  stale after 5cef2c5 moved the LaTeX code into `leaderboard_latex()`. At runtime the
  CSV is still written first (`to_csv` at :610) and the LaTeX call (:618) is still
  inside `try/except ImportError`.
- Nine triaged items were rewritten by review fixes (H247–H252, H313, H319, H320);
  each carries a `post_review` note in `docs/sprint3-triage-rulings.jsonl`.
- Store-gate footnotes: `precip_mm` differs only by float noise (max 1.4e-17);
  `forecasts.json` compares identical because the export skips it when no forecast
  run exists, so that comparison is vacuous.
- B1's omission rule covers `benchmarks.py`, which produces the published
  leaderboard. `evaluation/metrics.py` `compute_all_metrics` and `zero_shot.py`
  `evaluate_predictions` still inner-merge and report `n = len(merged)`; neither
  feeds a published number (follow-up).

## Follow-ups (found during this sprint, not caused by the backlog, not fixed here)

- The Docker image ships no forecast cache and no chronos, so `/forecast` returns 503 for known stations; the 503 message still suggests retrying without `as_of`.
- Station-level website JSON exports empty: `export_website_data.py` and `STATION_TO_WEATHER_STATION` use 4-letter station codes; the store uses BART's 2-letter codes. Per-station weather never applies for the same reason.
- `ridership_daily_est` is the monthly Total / 22 and is published, overstating daily riders.
- The raw weather archive ends 2023-12, so 2024-25 weather covariates are NaN.
- Prediction intervals are uncalibrated: Prophet 46%, SARIMA 96.7% against nominal 80%.
- The benchmark test window has no upper bound (`benchmarks.py`), so one more month of data or one failed station fit gets a model rejected; the export then publishes only the survivors.
- Diebold-Mariano tests still run against models the leaderboard rejected; duplicate prediction rows are not checked.
- "Chronos-2" wording remains in code comments (`feature_engineering.py`, `models/`, `zero_shot.py`, `run_pipeline.sh`).
- `fetch_pems_roads.py` deletes the PEMS-BAY CSV on a read error and falls back to synthetic data (standalone module, no automated caller).
- `.gcloudignore:2-3` still says forecast outputs "must be baked into Dockerfile.api".
- `machine_learning_files/README.md:109` still points to `fetch_bart_od.py` for "No BART OD files found" (the working path is `bart_od_from_xlsx.py`).
- `compute_all_metrics` (`evaluation/metrics.py`) and `zero_shot.evaluate_predictions` inner-merge forecasts onto actuals and report `n = len(merged)` (unpublished paths).
- Results tile (`sections.jsx`): a failed fetch of `model_comparison.json` shows "loading…" forever; on a WAPE tie it names one model while Benchmarks highlights every tied row; the lede, MAE tile and footnote are still hard-coded beside the now data-driven tile. Commit 39349b2's message says "text/comment changes only", which is not accurate (it adds the fetch and hooks for that tile).
- `benchmarks.py:585-592` carries a stale history comment.
