# Daily Updates — Transit Demand Forecasting

---

## 2026-06-25

### Bug Fixes

#### 1. `fetch_weather_openmeteo.py` — NaN crash in weather code decoder (lines 170–173)
**Problem:** `int(c)` raises `ValueError` when `weather_code` contains a `NaN` value,
crashing the entire weather ingestion run and losing all rows fetched up to that point.

**Fix:** Added `pd.notna(c)` guard before the `int()` conversion. NaN codes now map to
`"Unknown"` / `False` (i.e., not raining) instead of crashing.

```python
# Before
lambda c: WEATHER_CODE_MAP.get(int(c), ("Unknown", False))[0]

# After
lambda c: WEATHER_CODE_MAP.get(int(c), ("Unknown", False))[0] if pd.notna(c) else "Unknown"
```

---

#### 2. `merge_pipeline.py` — TypeError when `--start`/`--end` flags are passed (lines 314–316)
**Problem:** `pd.Timestamp(start, tz="America/Los_Angeles")` creates a timezone-aware
timestamp, but `base["timestamp"]` is timezone-naive (timezone was stripped during loading).
Comparing naive vs aware raises `TypeError: Cannot compare tz-naive and tz-aware timestamps`.
This bug is triggered whenever the pipeline is run with explicit `--start` or `--end` arguments.

**Fix:** Use `pd.Timestamp(start)` without attaching a timezone, matching the naive dtype
already on the column.

```python
# Before
base = base[base["timestamp"] >= pd.Timestamp(start, tz="America/Los_Angeles")]

# After
base = base[base["timestamp"] >= pd.Timestamp(start)]
```

---

#### 3. `fetch_bart_od.py` — Brittle column rename after `melt` (lines 164–169)
**Problem:** `long.columns = ["origin", "destination", "riders"]` relies on column order
being exactly [id_var, var_name, value_name]. If an extra column slips in (e.g., a
multi-level index after `reset_index`), the rename silently corrupts the schema.

**Fix:** Capture the actual index name before the melt and rename only that column
explicitly, leaving the other columns untouched.

```python
# Before
long = df.reset_index().melt(id_vars=df.index.name or "index", ...)
long.columns = ["origin", "destination", "riders"]

# After
idx_name = df.index.name or "index"
long = df.reset_index().melt(id_vars=idx_name, ...)
long = long.rename(columns={idx_name: "origin"})
```

---

### Known Issues (not yet fixed — tracked for follow-up)

| File | Location | Issue |
|------|----------|-------|
| `merge_pipeline.py` | `compute_event_features()` line 208 | `hours_to_event` stores event *count*, not hours-to-event. Docstring and schema comment claim "hours until next event." Misleads the model. |
| `fetch_events.py` | `NHLClient.get_schedule()` line 84 | If `startTimeUTC` is absent in the API response, `pd.to_datetime(None)` → `NaT` with no timezone — row is silently written with `NaT` timestamps instead of being skipped. |
| `fetch_events.py` | `TicketmasterClient` lines 166–168 | Pagination errors break out of the while-loop silently; no log records how many pages were successfully fetched vs missed. |
| `fetch_bart_od.py` | line 170 | `pd.to_numeric(..., errors="coerce").fillna(0)` converts non-numeric rider values to 0 with no warning — masks data quality problems. |

---
