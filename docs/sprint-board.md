# Sprint board

## Sprint 4 — Calibrate the P10/P90 intervals (opened 2026-10-22)

**Goal.** Bring every leaderboard model's P10–P90 coverage to ~80% on the
2025-H2 holdout without changing a point forecast. The method is chosen on the
validation split only (2025-H1); the test split is scored once, after the
choice is committed. Branch `feat/interval-calibration`, stacked on
`sprint3/pr-backlog` (PR #136 open).

**Starting state** (pinned env, leaderboard byte-identical to the S3.8 gate):
test coverage SARIMA 96.67%, Prophet 46.0%, Chronos-1 51.0%, SeasonalNaive
94.33%, n=300.

**Decision rules, fixed before any validation number was seen** (user's
defaults, 2026-10-22): a method qualifies if every model lands in 75–85%
validation coverage with neither tail above 15% misses; among qualifiers the
lowest mean interval score wins, one method for all four models preferred.
Prophet MCMC is measured and reported, not eligible. The website's "not
calibrated" wording changes only if every model's calibrated test coverage is
in 75–85%. Serving-path intervals (API, `forecasts.json`) are out of scope.

**Gates.** `Coverage_raw_%` reproduces SARIMA 96.67 / Prophet 46.0 / Chronos-1 51.0 / SeasonalNaive 94.33; WAPE, MAE,
RMSE, MAPE, sMAPE, MASE and n identical to the starting leaderboard; two runs
byte-identical; unit tests pass; `py_compile` and JSX parse pass.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S4.1 | Find why the earlier `mcmc_samples=200` run errored | orchestrator | — | Error reproduced and explained | done — the fit succeeded; the diagnostic read `params['sigma_obs'][0][0]`, which raises `IndexError` under MCMC (1-D, 400 draws). Reproduced in a scratch run (not committed); the earlier command, in the Sprint 3 subagent transcript, sent stderr to `/dev/null`. Recorded in `docs/interval-calibration.md` (215449c) |
| S4.2 | `evaluation/calibration.py`: fit/apply split-conformal, P50 untouched | implementer (orchestrator) | — | `tests/test_calibration.py` passes | done (056bd7b) — 16 tests pass |
| S4.3 | `evaluation/interval_study.py`: validation-only comparison of methods | implementer (orchestrator) | S4.2 | Data cut at `val_end` and asserted; table written | done (904c449) — study run on pinned env; no single method qualifies, see S4.4. A full refit from a clean copy at 215449c reproduced all four result CSVs byte-identical |
| S4.4 | Choose the method by the fixed rule; config + write-up committed before any test run | orchestrator | S4.3 | Commit precedes the S4.5 run | done (215449c, committed 20:30:24; first calibrated run started 20:30:35) — no single method qualified; per model: Prophet `scaled/horizon`, Chronos-1 `relative/pooled`, SARIMA and SeasonalNaive none (no method passed). Website wording therefore stays "not calibrated" (rule needs every model) |
| S4.5 | Wire the chosen method into `benchmarks.py`; run the gates; score test once | implementer (orchestrator) | S4.4 | All gates green | done — wiring in 215449c; test scored once at 215449c, result recorded in `docs/interval-calibration.md` (bf80b8f). Gates below |
| S4.6 | README, website wording, `model_comparison.json` | orchestrator | S4.5 | Wording follows the fixed rule | done (65db1c1) — "not calibrated" kept per rule; range 46–97% → 73–97%; README table gains own-band and interval columns; export carries `Coverage_raw_pct` and `Interval_method` |
| S4.7 | Review the sprint diff | code-reviewer | S4.6 | No BLOCKER open | done — 0 BLOCKER, 1 MAJOR (LaTeX table mixed calibrated and raw coverage unlabelled), 10 MINOR; spec PASS, quality PASS with findings. Findings and their disposition are in the fix-round list below and in the PR description. Fix round in 3dff990; third run byte-identical |
| S4.8 | Audit board against git; open PR (not merged) | delivery-auditor, orchestrator | S4.7 | Audit clean; PR open | in progress — audit on 32a75df..3dff990: 0 HIGH, 1 MEDIUM, 8 LOW, all addressed in this commit. Push and PR are authorized by the task brief ("Branch + PR, do not merge") and the user's "Go ahead with the defaults" on the plan, which included opening a PR stacked on `sprint3/pr-backlog`. Branch first pushed at 65db1c1, before review; re-pushed at 5c7036a with the fix round. Done: PR #138 opened against `sprint3/pr-backlog` (mergeable, not merged; retarget to `main` after #136 merges) |

**Gate results (S4.5, 2026-10-22, pinned env, code at 215449c).**

| Gate | Result |
|---|---|
| Point metrics | WAPE, MAE, RMSE, MAPE, sMAPE, MASE, n, n_expected identical to the starting leaderboard (`assert_frame_equal`); existing column order unchanged |
| Raw coverage | `Coverage_raw_%` = 96.67 / 46.0 / 51.0 / 94.33, the starting coverage exactly |
| Determinism | Two consecutive runs: leaderboard and results CSVs byte-identical |
| Calibrated test coverage (scored once) | Prophet 74.67%, Chronos-1 72.67% (calibrated); SARIMA 96.67%, SeasonalNaive 94.33% (own band). Validation predicted 82.0% / 84.3% for the two calibrated models |
| Website rule | Not every model is in 75–85%, so "not calibrated" stays; only the range figure changes (46–97% → 73–97%) |
| Tests / compile / JSX | 17 unit tests pass; `py_compile` passes on every touched .py; `sections.jsx` and `charts.jsx` parse (TypeScript 5.9.3) |
| After the review fix round | Same configuration re-run: leaderboard and results CSVs byte-identical to the scored run; Chronos validation forecasts identical with the store cut at `val_end`; 28 unit tests pass |

**Review fix round (S4.7).**
- Fixed in code:
  - the LaTeX table now carries `Coverage_raw_%` and `Interval_method` and a caption note (MAJOR);
  - horizon is counted before missing actuals are dropped;
  - a zero P50 with an infinite quantile gives [0, inf], not NaN;
  - the study no longer crashes when `asym_relative` is configured;
  - the Chronos entry carries `validated_for`, so another checkpoint keeps its own band;
  - the Chronos calibration run gets a store cut at `val_end`;
  - `describe()` labels asymmetric spans correctly.
- Wording:
  - the false comment "the leaderboard still rejects" a missing bound is corrected;
  - the doc's runner-up and three-station-check text are corrected;
  - board rows cite hashes.
- Tests: `tests/test_benchmark_calibration.py` added (3dff990).
- Not changed: `accept_model_rows` does not reject a model with missing interval bounds (NaN coverage, still ranked). That is `main`'s behaviour; left as a question for the user. The study's private `_store` swap is kept, restored in `finally`.

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
