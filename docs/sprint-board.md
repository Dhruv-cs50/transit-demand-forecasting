# Sprint board

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
| Already-merged cumulative tips | #26, #38, #42, #83 (#83 carried #43–#82) |
| Hunks across non-contained tips | 979: 123 already on main, 84 logs, 415 apply, 336 stale |

**Gates for closing the sprint.** Leaderboard bit-identical to Sprint 2
(SARIMA 3.21 / Prophet 5.75 / Chronos-1 9.70 / SeasonalNaive 10.75, n=300) or
each delta traced to a named change; website export emits non-empty JSON;
`py_compile` passes on every touched file; JSX parses.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S3.1 | Map chains, conflicts and hunk residue for all 104 PRs | orchestrator | — | Tables in this board's starting state | done |
| S3.2a | Triage: `api.py`, `scheduler.py`, `Dockerfile.api`, `requirements.txt` | principal-engineer | S3.1 | Ruling per item in report | in progress |
| S3.2b | Triage: `predict.py`, `finetune.py`, `zero_shot.py` | principal-engineer | S3.1 | Ruling per item in report | in progress |
| S3.2c | Triage: `merge_pipeline.py`, `validators.py`, `fetch_bart_od.py` | principal-engineer | S3.1 | Ruling per item in report | in progress |
| S3.2d | Triage: `feature_engineering.py`, other `fetch_*`, `fetch_pems_roads.py`, `run_pipeline.sh` | principal-engineer | S3.1 | Ruling per item in report | in progress |
| S3.2e | Triage: `benchmarks`, `ablation`, `metrics`, `prophet_baseline`, `arima`, `export_website_data` | principal-engineer | S3.1 | Ruling per item; #135 checked against #132 | in progress |
| S3.2f | Triage: website JSX/CSS/JSON, README, `docs/`, EDA notebook | principal-engineer | S3.1 | Ruling per item in report | in progress |
| S3.3 | Identify the routine that opens a PR daily | orchestrator | — | Routine named, with a pause/reconfigure proposal | done — remote routine "Test" (`trig_01ML7Tvxyi698UL1sgXPRXa4`), daily 13:00 UTC since 2026-05-03; proposal goes to the user, not changed by us |
| — | **Gate: merge order and close list shown to the user; wait for Go Ahead** | orchestrator | S3.2*, S3.3 | User's explicit yes | todo |
| S3.4 | Merge #116 into this branch; resolve conflicts toward Sprint 2; revert rejected hunks | implementer | Gate | Diff matches S3.2 rulings | todo |
| S3.5 | Merge the vetted small PRs and log-only PRs | implementer | S3.4 | Each merges; rulings honoured | todo |
| S3.6 | Port KEEP fixes from superseded old PRs, credited to source PR | implementer | S3.5 | One commit per cluster | todo |
| S3.7 | Review the whole consolidation diff against `origin/main` | code-reviewer | S3.6 | No BLOCKER open | todo |
| S3.8 | Run the sprint gates | orchestrator | S3.7 | All four gates green | todo |
| S3.9 | Audit board against git | delivery-auditor | S3.8 | No unresolved disagreement | todo |
| S3.10 | Open consolidation PR; after the user merges it, close the superseded list | orchestrator | S3.9 | Needs user's yes for the closes | todo |

## Rulings

- `.claude/` was gitignored wholesale. Narrowed to `.claude/*` plus
  `!.claude/agents/` so agent definitions are tracked and local settings stay
  out. Cost if wrong: one `.gitignore` line.
- Root cause of the backlog: the routine's prompt ("check for bugs, prepare
  improvements, create a file for the day's updates") gives it no rule for what
  to do when its previous PR is unmerged, so it opens a new one every day and
  carries the old one forward. Changing the routine is the user's call.
