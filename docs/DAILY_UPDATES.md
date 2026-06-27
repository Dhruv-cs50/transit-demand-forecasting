# Daily Updates

Automated daily log of bug fixes and improvements applied to the codebase.

---

## 2026-06-27

### Bug Fixes

**`evaluation/metrics.py`** — Falsy zero-value check in `MetricsReport.to_dict()`
- `round(self.mase, 4) if self.mase else None` treated `mase=0.0` (perfect prediction) as `None`
- Same issue affected `coverage` and `int_width` fields
- Fixed: changed all three checks to `if ... is not None`

**`scripts/export_website_data.py`** — `tz_localize(None)` on timezone-aware timestamp
- `export_ridership_actuals` called `ts.tz_localize(None)` on a tz-aware `pd.Timestamp`, which raises `TypeError` in pandas
- Fixed: changed to `ts.tz_convert(None)` (the correct method to strip timezone)

**`evaluation/validators.py`** — Same `tz_localize(None)` bug in `check_station_coverage`
- `dt.tz_localize(None)` on an already tz-aware column raises `TypeError`
- Fixed: now checks `dt.tz is not None` first and uses `dt.tz_convert(None)` when needed

**`Processing/feature_engineering.py`** — `n_new` counter always zero in `build_features()`
- `n_new = n_features - len(df.columns)` computed the same value both sides
- Fixed: capture `n_input_cols = len(df.columns)` before feature engineering begins; updated log message to report new column count

**`machine_learning_files/api.py`** — `datetime.utcnow()` deprecated in Python 3.12+
- `datetime.utcnow()` is deprecated and will be removed; both `/health` and `/forecast` endpoints used it
- Fixed: imported `timezone` and replaced with `datetime.now(timezone.utc)`

**`machine_learning_files/api.py`** — `pd.Timestamp(as_of, tz=...)` fails on tz-aware strings
- If the `as_of` request field already carried timezone info, the constructor would raise `TypeError`
- Fixed: parse with `pd.Timestamp(as_of)` first, then conditionally `tz_localize` only when needed

**`machine_learning_files/merge_pipeline.py`** — Timezone mismatch in date-range filter
- `pd.Timestamp(start, tz="America/Los_Angeles")` compared against a column that has no timezone after the weather merge, causing `TypeError` at filter time
- Fixed: detect the column's tz-awareness and normalize the filter timestamp to match before comparison

**`machine_learning_files/zero_shot.py`** — Redundant f-string with no interpolation
- `f"mean"` is equivalent to `"mean"` but confuses readers
- Fixed: changed to a plain string literal

