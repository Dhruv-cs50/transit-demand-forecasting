#!/usr/bin/env bash
# Live smoke check of the cloud ingestion pipeline and the API that serves its
# store (docs/cloud-ingestion-design.md §7, story S9-09). READ-ONLY: it lists a
# Cloud Run job's executions, reads two objects from the bucket, and calls the
# API's GET /health, GET /stations and POST /forecast. It never writes, deploys
# or executes anything.
#
# Checks (each prints PASS / FAIL / SKIP):
#   1. the latest transit-ingest execution succeeded              (gcloud)
#   2. processed/serving.json exists                              (gcloud)
#   3. the pointer's run's gate.json says passed                  (gcloud)
#   4. /health: store_source == cloud                             (API)
#   5. /health: store_sha256 (and store_run_id) match the pointer (API + gcloud)
#   6. 50 /forecast calls at as_of=2025-06-30 give WAPE 3.21 against the repo
#      store's actuals for the next 6 months                      (API + repo)
#   7. the default forecast starts the month after /health's store_last_month
#
# Usage (from anywhere; the repo store is found relative to this script):
#   API_URL=https://transit-api-xxxx.a.run.app scripts/smoke_cloud.sh
#   scripts/smoke_cloud.sh --local            # skip the gcloud checks; see below
#
# Environment:
#   API_URL    base URL of the API                  (required; --local default
#                                                    http://127.0.0.1:8000)
#   PROJECT    GCP project      (default cs-163-final-project-tra-f1136)
#   REGION     Cloud Run region (default us-west2)
#   BUCKET     bucket name, with or without gs://   (default $PROJECT-transit-data)
#   JOB        Cloud Run job name                   (default transit-ingest)
#   PYTHON     interpreter with pandas + pyarrow    (default python3)
#   AS_OF, EXPECTED_WAPE, EXPECTED_STATIONS, REPO_STORE   override the
#              backtest anchor (2025-06-30), its WAPE (3.21), the station
#              count (50) and the store to score against
#              (data/processed/feature_store.parquet in this repo).
#
# --local: for a uvicorn on your machine. Checks 1-3 are SKIPped (no gcloud).
# The /health store fields come from a later story (S9-08); in --local mode a
# field the API does not return yet is SKIP, not FAIL, and store_source is
# reported (baked or cloud) instead of required to be cloud. Outside --local a
# missing field is a FAIL.
#
# Exit status: 0 if nothing FAILed, 1 otherwise, 2 for a usage error.

set -euo pipefail

LOCAL=0
for arg in "$@"; do
  case "$arg" in
    --local) LOCAL=1 ;;
    -h|--help) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg (try --help)" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PROJECT="${PROJECT:-cs-163-final-project-tra-f1136}"
REGION="${REGION:-us-west2}"
BUCKET="${BUCKET:-${PROJECT}-transit-data}"
BUCKET="${BUCKET#gs://}"
BUCKET="${BUCKET%/}"
JOB="${JOB:-transit-ingest}"
PYTHON="${PYTHON:-python3}"
AS_OF="${AS_OF:-2025-06-30}"
EXPECTED_WAPE="${EXPECTED_WAPE:-3.21}"
EXPECTED_STATIONS="${EXPECTED_STATIONS:-50}"
REPO_STORE="${REPO_STORE:-$REPO_ROOT/data/processed/feature_store.parquet}"
if [ "$LOCAL" -eq 1 ]; then
  API_URL="${API_URL:-http://127.0.0.1:8000}"
fi
if [ -z "${API_URL:-}" ]; then
  echo "API_URL is required (the Cloud Run service URL), or use --local" >&2
  exit 2
fi
API_URL="${API_URL%/}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

N_PASS=0
N_FAIL=0
N_SKIP=0

report() { # status name [detail]
  local status="$1" name="$2" detail="${3:-}"
  case "$status" in
    PASS) N_PASS=$((N_PASS + 1)) ;;
    FAIL) N_FAIL=$((N_FAIL + 1)) ;;
    SKIP) N_SKIP=$((N_SKIP + 1)) ;;
  esac
  if [ -n "$detail" ]; then
    printf '%-5s %-52s %s\n' "$status" "$name" "$detail"
  else
    printf '%-5s %s\n' "$status" "$name"
  fi
}

# json_get FILE KEY: print top-level (or a.b.c) KEY of a JSON file; empty if absent.
json_get() {
  "$PYTHON" -c '
import json, sys
try:
    v = json.load(open(sys.argv[1]))
    for k in sys.argv[2].split("."):
        v = v[k]
except Exception:
    sys.exit(0)
print(v if not isinstance(v, (dict, list)) else json.dumps(v))
' "$1" "$2"
}

echo "smoke_cloud: API_URL=$API_URL local=$LOCAL"
if [ "$LOCAL" -eq 0 ]; then
  echo "smoke_cloud: project=$PROJECT region=$REGION bucket=gs://$BUCKET job=$JOB"
fi

if ! "$PYTHON" -c 'import pandas, pyarrow' 2>/dev/null; then
  echo "PYTHON=$PYTHON needs pandas and pyarrow (set PYTHON to a venv's python)" >&2
  exit 2
fi
if [ ! -f "$REPO_STORE" ]; then
  echo "repo store not found: $REPO_STORE (set REPO_STORE)" >&2
  exit 2
fi

POINTER_RUN_ID=""
POINTER_SHA=""

# ── 1-3: gcloud, read-only ────────────────────────────────────────────────────
if [ "$LOCAL" -eq 1 ]; then
  report SKIP "latest $JOB execution succeeded" "--local"
  report SKIP "processed/serving.json exists" "--local"
  report SKIP "gate.json of the served run passed" "--local"
elif ! command -v gcloud >/dev/null 2>&1; then
  report FAIL "latest $JOB execution succeeded" "gcloud not installed"
  report FAIL "processed/serving.json exists" "gcloud not installed"
  report FAIL "gate.json of the served run passed" "gcloud not installed"
else
  # 1. Latest execution = newest metadata.creationTimestamp; succeeded means its
  #    Completed condition is True and no task failed.
  if gcloud run jobs executions list --job="$JOB" --region="$REGION" \
       --project="$PROJECT" --format=json >"$TMP/executions.json" 2>"$TMP/executions.err"; then
    set +e
    verdict="$("$PYTHON" -c '
import json, sys
ex = json.load(open(sys.argv[1]))
if not ex:
    print("no executions found"); sys.exit(1)
latest = max(ex, key=lambda e: e.get("metadata", {}).get("creationTimestamp", ""))
name = latest.get("metadata", {}).get("name", "?")
st = latest.get("status", {})
cond = {c.get("type"): c.get("status") for c in st.get("conditions", [])}
failed = int(st.get("failedCount", 0) or 0)
done = cond.get("Completed")
ok = done == "True" and failed == 0
print("%s: Completed=%s succeeded=%s failed=%s" % (name, done, st.get("succeededCount", 0), failed))
sys.exit(0 if ok else 1)
' "$TMP/executions.json")"
    rc=$?
    set -e
    if [ "$rc" -eq 0 ]; then report PASS "latest $JOB execution succeeded" "$verdict"
    else report FAIL "latest $JOB execution succeeded" "$verdict"; fi
  else
    report FAIL "latest $JOB execution succeeded" "gcloud failed: $(head -c 200 "$TMP/executions.err" | tr '\n' ' ')"
  fi

  # 2. The pointer.
  if gcloud storage cat "gs://$BUCKET/processed/serving.json" --project="$PROJECT" \
       >"$TMP/serving.json" 2>"$TMP/serving.err"; then
    POINTER_RUN_ID="$(json_get "$TMP/serving.json" run_id)"
    POINTER_SHA="$(json_get "$TMP/serving.json" store_sha256)"
    [ -n "$POINTER_SHA" ] || POINTER_SHA="$(json_get "$TMP/serving.json" sha256)"
    if [ -n "$POINTER_RUN_ID" ]; then
      report PASS "processed/serving.json exists" "run_id=$POINTER_RUN_ID sha256=${POINTER_SHA:0:12}"
    else
      report FAIL "processed/serving.json exists" "present but has no run_id"
    fi
  else
    report FAIL "processed/serving.json exists" "gcloud failed: $(head -c 200 "$TMP/serving.err" | tr '\n' ' ')"
  fi

  # 3. The gate result of the run the pointer names.
  if [ -z "$POINTER_RUN_ID" ]; then
    report FAIL "gate.json of the served run passed" "no run_id from the pointer"
  elif gcloud storage cat "gs://$BUCKET/processed/runs/$POINTER_RUN_ID/gate.json" \
         --project="$PROJECT" >"$TMP/gate.json" 2>"$TMP/gate.err"; then
    if [ "$(json_get "$TMP/gate.json" passed)" = "True" ]; then
      report PASS "gate.json of the served run passed" "runs/$POINTER_RUN_ID/gate.json"
    else
      report FAIL "gate.json of the served run passed" "passed=$(json_get "$TMP/gate.json" passed)"
    fi
  else
    report FAIL "gate.json of the served run passed" "gcloud failed: $(head -c 200 "$TMP/gate.err" | tr '\n' ' ')"
  fi
fi

# ── 4-7: the API ──────────────────────────────────────────────────────────────
# One Python helper does the HTTP and the scoring; it prints one
# "STATUS|name|detail" line per check, which is tallied here.
cat >"$TMP/api_checks.py" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

api = os.environ["API_URL"]
local = os.environ["SMOKE_LOCAL"] == "1"
as_of = os.environ["AS_OF"]
expected_wape = float(os.environ["EXPECTED_WAPE"])
expected_stations = int(os.environ["EXPECTED_STATIONS"])
pointer_run = os.environ.get("POINTER_RUN_ID", "")
pointer_sha = os.environ.get("POINTER_SHA", "")
store_path = os.environ["REPO_STORE"]


def out(status, name, detail=""):
    print(f"{status}|{name}|{detail}", flush=True)


def call(method, path, body=None, timeout=300):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(api + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    last = None
    for _ in range(2):  # one retry: a cold Cloud Run instance can drop the first call
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.read()[:120]!r}"
        except Exception as e:  # noqa: BLE001 - reported, not raised
            last = f"{type(e).__name__}: {e}"
    raise RuntimeError(last)


def missing(name, field):
    """A /health field the API does not return."""
    if local:
        out("SKIP", name, f"/health has no {field} yet (--local)")
    else:
        out("FAIL", name, f"/health has no {field}")


# ---- /health ----
try:
    health = call("GET", "/health", timeout=120)
except RuntimeError as e:
    for name in ("health: store_source == cloud", "health: store_sha256 matches the pointer",
                 f"{expected_stations} forecasts at as_of={as_of}: WAPE {expected_wape:.2f}",
                 "default forecast starts after store_last_month"):
        out("FAIL", name, f"GET /health failed: {e}")
    sys.exit(0)

name = "health: store_source == cloud"
src = health.get("store_source")
if src is None:
    missing(name, "store_source")
elif local:
    out("PASS", "health: store_source reported", f"{src} (--local: cloud not required)")
elif src == "cloud":
    out("PASS", name, f"store_run_id={health.get('store_run_id')}")
else:
    out("FAIL", name, f"store_source={src!r}")

name = "health: store_sha256 matches the pointer"
sha = health.get("store_sha256")
if sha is None:
    missing(name, "store_sha256")
elif local:
    out("SKIP", name, f"no pointer in --local (store_sha256={str(sha)[:12]})")
elif not pointer_sha:
    out("FAIL", name, "the pointer has no store sha256 to compare with")
elif sha == pointer_sha and (not pointer_run or health.get("store_run_id") in (None, pointer_run)):
    out("PASS", name, str(sha)[:12])
else:
    out("FAIL", name, f"health sha={str(sha)[:12]} run={health.get('store_run_id')} "
                      f"pointer sha={pointer_sha[:12]} run={pointer_run}")

# ---- 50 forecasts at as_of vs the repo store's actuals ----
name = f"{expected_stations} forecasts at as_of={as_of}: WAPE {expected_wape:.2f}"
try:
    stations = call("GET", "/stations", timeout=120)["stations"]
    if len(stations) != expected_stations:
        out("FAIL", name, f"/stations lists {len(stations)}, expected {expected_stations}")
    else:
        store = pd.read_parquet(store_path, columns=["station_id", "timestamp", "ridership"])
        store["timestamp"] = pd.to_datetime(store["timestamp"])
        months = sorted(store.loc[store["timestamp"] > pd.Timestamp(as_of), "timestamp"].unique())[:6]
        actual = {(r.station_id, pd.Timestamp(r.timestamp).strftime("%Y-%m")): r.ridership
                  for r in store[store["timestamp"].isin(months)].itertuples()}

        def one(sid):
            r = call("POST", "/forecast", {"station_id": sid, "horizon_hours": 6, "as_of": as_of})
            return sid, r["forecasts"]

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(one, stations))
        err = tot = 0.0
        problems = []
        for sid, rows in results:
            got = {pd.Timestamp(f["timestamp"]).strftime("%Y-%m"): f["p50"] for f in rows}
            for (s, m), y in actual.items():
                if s != sid:
                    continue
                p = got.get(m)
                if p is None:
                    problems.append(f"{sid}@{m}")
                    continue
                err += abs(p - y)
                tot += abs(y)
        if problems:
            out("FAIL", name, f"{len(problems)} station-month(s) without a P50, e.g. {problems[:3]}")
        else:
            wape = err / tot * 100
            ok = round(wape, 2) == round(expected_wape, 2)
            out("PASS" if ok else "FAIL", name, f"WAPE {wape:.4f} -> {wape:.2f}% over {len(actual)} station-months")
except Exception as e:  # noqa: BLE001
    out("FAIL", name, f"{type(e).__name__}: {e}")

# ---- the default forecast starts the month after store_last_month ----
name = "default forecast starts after store_last_month"
last = health.get("store_last_month")
if last is None:
    missing(name, "store_last_month")
else:
    try:
        sid = sorted(call("GET", "/stations", timeout=120)["stations"])[0]
        r = call("POST", "/forecast", {"station_id": sid, "horizon_hours": 6})
        want = (pd.Timestamp(last).to_period("M") + 1).strftime("%Y-%m")
        got = pd.Timestamp(r["forecasts"][0]["timestamp"]).strftime("%Y-%m")
        out("PASS" if got == want else "FAIL", name,
            f"{sid}: first month {got}, store_last_month {last} -> expected {want}")
    except Exception as e:  # noqa: BLE001
        out("FAIL", name, f"{type(e).__name__}: {e}")
PY

set +e
api_out="$(API_URL="$API_URL" SMOKE_LOCAL="$LOCAL" AS_OF="$AS_OF" EXPECTED_WAPE="$EXPECTED_WAPE" \
  EXPECTED_STATIONS="$EXPECTED_STATIONS" POINTER_RUN_ID="$POINTER_RUN_ID" POINTER_SHA="$POINTER_SHA" \
  REPO_STORE="$REPO_STORE" "$PYTHON" "$TMP/api_checks.py" 2>"$TMP/api_checks.err")"
api_rc=$?
set -e

if [ -n "$api_out" ]; then
  while IFS='|' read -r status name detail; do
    report "$status" "$name" "$detail"
  done <<<"$api_out"
fi
if [ "$api_rc" -ne 0 ]; then
  report FAIL "API checks helper" "exited $api_rc: $(tail -n 3 "$TMP/api_checks.err" | tr '\n' ' ')"
fi

echo "smoke_cloud: $N_PASS passed, $N_FAIL failed, $N_SKIP skipped"
if [ "$N_FAIL" -gt 0 ]; then
  echo "smoke_cloud: FAIL"
  exit 1
fi
echo "smoke_cloud: PASS"
