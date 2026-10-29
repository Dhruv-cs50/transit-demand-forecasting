/* SVG chart primitives — WAPE comparison, Forecast bands, HeroOrbit, Gauge.
   Also the page's data loader and date labels, shared with sections.jsx
   (this file loads first). */

/* ── Site data (website/data/*.json) ────────────────────────────────
   Every section reads the exports through loadSiteData(file):
   - one request per file per page load, however many sections read it;
   - cache:'no-cache' makes the browser revalidate with the server, so a
     refreshed export is picked up without waiting out the HTTP cache;
   - a failed request is reported as failed, never as an empty list.
   Resolves to { status:'ok', rows } or { status:'failed', error }. A network
   error, a non-2xx response, invalid JSON and a body that is not an array
   all count as failed. */
const __siteData = {};
const loadSiteData = (file) => {
  if (!__siteData[file]) {
    __siteData[file] = fetch(`data/${file}`, { cache: 'no-cache' })
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(body => {
        if (!Array.isArray(body)) throw new Error('not a JSON array');
        return { status: 'ok', rows: body };
      })
      .catch(err => ({ status: 'failed', error: String((err && err.message) || err) }));
  }
  return __siteData[file];
};

// null while loading, then loadSiteData's result.
const useSiteData = (file) => {
  const [res, setRes] = React.useState(null);
  React.useEffect(() => {
    let live = true;
    loadSiteData(file).then(r => { if (live) setRes(r); });
    return () => { live = false; };
  }, [file]);
  return res;
};

const siteRows = res => (res && res.status === 'ok' ? res.rows : []);
const siteFailed = res => !!res && res.status === 'failed';

/* ── Month and year labels derived from the data ───────────────────── */
const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

// 'YYYY-MM…' → { y, m } (m is 1-12), or null.
const parseYM = ym => {
  const m = /^(\d{4})-(0[1-9]|1[0-2])/.exec(typeof ym === 'string' ? ym : '');
  return m ? { y: +m[1], m: +m[2] } : null;
};

// Records with a `month` field → { range: 'Jul–Dec 2025', through: 'Jun 2025',
// count: 6 }, or null when no record has a valid month. `through` is the month
// before the first one.
const monthSpan = records => {
  const ms = records.map(r => r && parseYM(r.month)).filter(Boolean)
    .sort((a, b) => a.y - b.y || a.m - b.m);
  if (!ms.length) return null;
  const a = ms[0], b = ms[ms.length - 1];
  const range = a.y !== b.y ? `${MONTH_ABBR[a.m-1]} ${a.y}–${MONTH_ABBR[b.m-1]} ${b.y}`
    : a.m !== b.m ? `${MONTH_ABBR[a.m-1]}–${MONTH_ABBR[b.m-1]} ${a.y}`
    : `${MONTH_ABBR[a.m-1]} ${a.y}`;
  const through = a.m === 1 ? `Dec ${a.y - 1}` : `${MONTH_ABBR[a.m-2]} ${a.y}`;
  return { range, through, count: new Set(ms.map(p => p.y * 12 + p.m)).size };
};

// Records with a `month` field → the years they cover, consecutive years
// collapsed: '2019 and 2022–2025'. null when no record has a valid month.
const yearSpan = records => {
  const ys = [...new Set(records.map(r => r && parseYM(r.month)).filter(Boolean).map(p => p.y))]
    .sort((a, b) => a - b);
  if (!ys.length) return null;
  const runs = [];
  ys.forEach(y => {
    const last = runs[runs.length - 1];
    if (last && y === last[1] + 1) last[1] = y; else runs.push([y, y]);
  });
  const parts = runs.map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`));
  return parts.length === 1 ? parts[0]
    : `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
};

/* ── What model_comparison.json scored ─────────────────────────────
   scoredForecasts(): true when a forecast file (forecasts.json for Chronos,
   forecasts_sarima.json for SARIMA) is the run that model_comparison.json's row
   for that model scored — the comparison has exactly one such row (the
   exporter's rule) and its n_predictions equals the number of published
   forecasts. Presence of the row alone is not enough: the exporter publishes
   all six files or none, but a site deployed from mixed copies of
   website/data/ (or a stale cached forecasts.json) can still pair a new
   comparison with old forecasts.

   comparisonSplit(): label parts for the comparison, all from the data —
   `name` ('test split' / 'validation split' / 'held-out split', from
   scored_split), `window` (the forecast months, only when scoredForecasts()
   holds and the split is the test split, since forecasts.json covers the test
   window), `n` (station-months per model, when every row has the same count),
   `stations` (stations in forecasts.json, under the same condition as
   `window`). Missing parts are null; null overall until both files load. */
const scoredForecasts = (fcRes, cmpRes, rowPrefix = 'Chronos') => {
  const fc = siteRows(fcRes), cmp = siteRows(cmpRes);
  if (!fc.length || !cmp.length) return false;
  const rows = cmp.filter(r => r && String(r.model).startsWith(rowPrefix));
  return rows.length === 1 && Number(rows[0].n_predictions) === fc.length;
};

/* The four per-station forecast exports the site shows, in display order. SARIMA
   (forecasts_sarima.json) is the leaderboard's best model and the default;
   Prophet, Chronos-1 (the zero-shot foundation model, forecasts.json) and the
   seasonal-naive baseline follow. rowPrefix finds the model's leaderboard row;
   color is the model's line in the all-models chart. */
const FC_MODELS = {
  sarima:  { key:'sarima',  short:'SARIMA',         label:'SARIMA',               file:'forecasts_sarima.json',          rowPrefix:'SARIMA',        color:'var(--primary)' },
  prophet: { key:'prophet', short:'Prophet',        label:'Prophet',              file:'forecasts_prophet.json',         rowPrefix:'Prophet',       color:'var(--gold)' },
  chronos: { key:'chronos', short:'Chronos-1',      label:'Chronos-1 zero-shot',  file:'forecasts.json',                 rowPrefix:'Chronos',       color:'var(--good)',
             full:'Chronos-1 zero-shot (chronos-t5-small)' },
  naive:   { key:'naive',   short:'Seasonal naive', label:'Seasonal-naive baseline', file:'forecasts_seasonal_naive.json', rowPrefix:'SeasonalNaive', color:'var(--ink-soft)' },
};
const FC_ORDER = ['sarima', 'prophet', 'chronos', 'naive'];

// Every forecast export's load result, keyed by model. The four hooks are
// always called, in the same order, so a model toggle never changes hook order;
// the loader caches, so each file is fetched once per page.
const useFcFiles = () => {
  const sarima = useSiteData(FC_MODELS.sarima.file);
  const prophet = useSiteData(FC_MODELS.prophet.file);
  const chronos = useSiteData(FC_MODELS.chronos.file);
  const naive = useSiteData(FC_MODELS.naive.file);
  return { sarima, prophet, chronos, naive };
};

/* ── Backtest windows (website/data/backtest_windows.json) ──────────
   An object, not an array, so it has its own loader: { windows: [{id,
   fit_through, first_month, last_month}], rows: [{window, model, wape, mae, n,
   coverage_own_band, stations_sarima_beats}], source, generated_by }.
   backtestStats() turns it into what the page shows, or says why it cannot:
     null                      still loading
     { failed:true, reason }   missing, unreadable or malformed
     { windows, byWin, models, bestByWindow, ... } otherwise
   byWin[windowId][modelKey] = { wape, mae, n, cov, beats } with wape and cov in
   percent: a file written as fractions (every wape <= 1.5, every coverage <= 1)
   is scaled by 100. modelKey() maps a row's model name to sarima / prophet /
   chronos / naive. */
const __siteJson = {};
const loadSiteJson = (file) => {
  if (!__siteJson[file]) {
    __siteJson[file] = fetch(`data/${file}`, { cache: 'no-cache' })
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(body => {
        if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error('not a JSON object');
        return { status: 'ok', body };
      })
      .catch(err => ({ status: 'failed', error: String((err && err.message) || err) }));
  }
  return __siteJson[file];
};
const useSiteJson = (file) => {
  const [res, setRes] = React.useState(null);
  React.useEffect(() => {
    let live = true;
    loadSiteJson(file).then(r => { if (live) setRes(r); });
    return () => { live = false; };
  }, [file]);
  return res;
};

const modelKey = name => {
  const s = String(name || '').toLowerCase().replace(/[^a-z]/g, '');
  return s.startsWith('sarima') ? 'sarima' : s.startsWith('prophet') ? 'prophet'
    : s.startsWith('chronos') ? 'chronos' : /^(seasonal|snaive|naive)/.test(s) ? 'naive' : null;
};

const backtestStats = (res) => {
  if (!res) return null;
  const fail = reason => ({ failed: true, reason });
  if (res.status === 'failed') return fail(res.error);
  const b = res.body;
  if (!Array.isArray(b.windows) || !b.windows.length || !Array.isArray(b.rows) || !b.rows.length) return fail('no windows or rows');
  const num = v => (typeof v === 'number' && isFinite(v) ? v : null);
  const rows = b.rows.filter(r => r && num(r.wape) != null && modelKey(r.model) && typeof r.window === 'string');
  if (!rows.length) return fail('no scored rows');
  const wapeScale = Math.max(...rows.map(r => r.wape)) <= 1.5 ? 100 : 1;
  const covs = rows.map(r => num(r.coverage_own_band)).filter(v => v != null);
  const covScale = covs.length && Math.max(...covs) <= 1 ? 100 : 1;
  const windows = b.windows.filter(w => w && typeof w.id === 'string')
    .map(w => {
      const a = parseYM(w.first_month), z = parseYM(w.last_month);
      const span = a && z ? monthSpan([{ month: w.first_month }, { month: w.last_month }]) : null;
      return { id: w.id, first: w.first_month, last: w.last_month, label: span ? span.range : w.id };
    })
    .sort((x, y) => String(x.first).localeCompare(String(y.first)));
  if (!windows.length) return fail('no windows');
  const byWin = {};
  rows.forEach(r => {
    (byWin[r.window] = byWin[r.window] || {})[modelKey(r.model)] = {
      wape: r.wape * wapeScale, mae: num(r.mae), n: num(r.n),
      cov: num(r.coverage_own_band) != null ? r.coverage_own_band * covScale : null,
      beats: num(r.stations_sarima_beats),
    };
  });
  // A window is usable when SARIMA and at least one other model were scored on it.
  const usable = windows.filter(w => byWin[w.id] && byWin[w.id].sarima && Object.keys(byWin[w.id]).length > 1);
  if (!usable.length) return fail('no window scores SARIMA against another model');
  const bestByWindow = {};
  usable.forEach(w => {
    const e = Object.entries(byWin[w.id]);
    bestByWindow[w.id] = e.reduce((a, c) => (c[1].wape < a[1].wape ? c : a))[0];
  });
  return { windows: usable, byWin, bestByWindow, source: b.source, generatedBy: b.generated_by,
           models: FC_ORDER.filter(k => usable.some(w => byWin[w.id][k])) };
};

// "6.36 / 4.27 / 3.21" style list of SARIMA's WAPE over the windows, oldest first.
const sarimaAcrossWindows = bt => (bt && !bt.failed ? bt.windows.map(w => ({ id: w.id, label: w.label, wape: bt.byWin[w.id].sarima.wape })) : null);

const comparisonSplit = (fcRes, cmpRes) => {
  if (!fcRes || !cmpRes) return null;
  const rows = siteRows(cmpRes);
  const splits = new Set(rows.map(r => r && r.scored_split));
  const only = splits.size === 1 ? [...splits][0] : null;
  const name = only === 'test' ? 'test split' : only === 'val' ? 'validation split' : 'held-out split';
  const ns = new Set(rows.map(r => r && r.n_predictions));
  const n0 = ns.size === 1 ? [...ns][0] : null;
  const span = only === 'test' && scoredForecasts(fcRes, cmpRes) ? monthSpan(siteRows(fcRes)) : null;
  return {
    name,
    window: span ? span.range : null,
    n: Number.isFinite(n0) ? n0 : null,
    stations: span ? new Set(siteRows(fcRes).map(r => r && r.station_id)).size : null,
    label: span ? `${span.range} ${name}` : name,
  };
};

/* ── Headline numbers, all from model_comparison.json ──────────────
   headlineStats(cmpRes, fcRes): the figures the page quotes in prose — best
   model and its WAPE/MAE, each baseline's row, station-months scored, the
   coverage range — read from the leaderboard rows so no copy keeps its own
   literal. null until model_comparison.json has loaded with a scored row.
     rows      rows with a WAPE_pct, in file order
     best      the lowest-WAPE row (first one on a tie)
     sarima, prophet, naive, chronos
               the row whose model name starts SARIMA / Prophet / SeasonalNaive
               / Chronos, or undefined
     n         station-months per model when every row agrees, else null
     window    the scored forecast months ('Jul–Dec 2025'), only when
               forecasts.json is the run that was scored (comparisonSplit),
               else null — callers then say just "holdout"
     covLo, covHi  smallest and largest Coverage_pct, or null
   The formatters match how each figure is printed today (1 decimal, '3.1k',
   '3,086'); a missing value prints as '—'. */
const headlineStats = (cmpRes, fcRes) => {
  const rows = siteRows(cmpRes).filter(r => r && typeof r.WAPE_pct === 'number' && isFinite(r.WAPE_pct));
  if (!rows.length) return null;
  const best = rows.reduce((a, b) => (b.WAPE_pct < a.WAPE_pct ? b : a));
  const named = prefix => rows.find(r => String(r.model).startsWith(prefix));
  const ns = new Set(rows.map(r => r.n_predictions));
  const n0 = ns.size === 1 ? [...ns][0] : null;
  const split = comparisonSplit(fcRes, cmpRes);
  const covs = rows.map(r => r.Coverage_pct).filter(v => typeof v === 'number' && isFinite(v));
  return {
    rows, best,
    sarima: named('SARIMA'), prophet: named('Prophet'), naive: named('SeasonalNaive'), chronos: named('Chronos'),
    n: Number.isFinite(n0) ? n0 : null,
    window: split && split.window,
    covLo: covs.length ? Math.min(...covs) : null,
    covHi: covs.length ? Math.max(...covs) : null,
  };
};
const fmtPct = v => (typeof v === 'number' && isFinite(v) ? v.toFixed(1) + '%' : '—');
const fmtInt = v => (typeof v === 'number' && isFinite(v) ? Math.round(v).toLocaleString('en-US') : '—');
const fmtK = v => (typeof v === 'number' && isFinite(v) ? (v / 1000).toFixed(1) + 'k' : '—');
// 'Chronos1_ZeroShot (chronos-t5-small)' → 'Chronos1_ZeroShot'; 'SARIMA' unchanged.
const shortModel = m => String(m).replace(/\s*\(.*\)\s*$/, '');
// 'Jul–Dec 2025 holdout' when the window is known, else just 'holdout'.
const holdoutLabel = hs => `${hs && hs.window ? hs.window + ' ' : ''}holdout`;

// Centred status text in place of a chart; SVG text does not wrap, so each
// line is its own tspan.
const ChartMessage = ({ width, height, lines }) => (
  <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display:'block' }}>
    <text x="50%" y={height / 2 - (lines.length - 1) * 9} textAnchor="middle" fontSize="13" fill="var(--ink-muted)">
      {lines.map((l, i) => <tspan key={i} x="50%" dy={i ? 18 : 0}>{l}</tspan>)}
    </text>
  </svg>
);

/* ── WAPE comparison bar chart (real data from model_comparison.json) ── */
const ROCCurve = ({ width = 460, height = 280 }) => {
  const cmpRes = useSiteData('model_comparison.json');
  const fcRes = useSiteData('forecasts.json');
  const split = comparisonSplit(fcRes, cmpRes);
  const data = cmpRes && cmpRes.status === 'ok' ? cmpRes.rows : null;
  const [hl] = useModelHighlight();  // page-wide model highlight (interactions.jsx)

  const message = (...lines) => <ChartMessage width={width} height={height} lines={lines} />;
  if (!cmpRes || !fcRes) return message('Loading…');
  if (siteFailed(cmpRes)) return message('The model comparison could not be loaded.', 'model_comparison.json · reload the page to try again');
  if (!data.length) return message('model_comparison.json lists no models.');

  const DISPLAY_CAP = 30; // cap x-axis at 30%; a bar past the cap is drawn to it with an overflow mark (▶)
  const pad = { l: 170, r: 70, t: 20, b: 38 };
  const W = width - pad.l - pad.r;
  const H = height - pad.t - pad.b;
  const rowH = H / data.length;

  const gridLines = [0, 10, 20, 30];
  // Best bar = lowest WAPE in the data, same rule as Benchmarks' bestWAPE in
  // sections.jsx. Never hard-code a model name.
  const bestWAPE = Math.min(...data.map(r => r.WAPE_pct).filter(v => v != null));

  const labelFor = m => ({
    'SARIMA': 'SARIMA (0,1,1)(0,1,1,12)',
    'Prophet': 'Prophet',
  }[m] || m);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display:'block' }}>
      {/* grid */}
      {gridLines.map(v => (
        <g key={v}>
          <line
            x1={pad.l + (v / DISPLAY_CAP) * W} y1={pad.t}
            x2={pad.l + (v / DISPLAY_CAP) * W} y2={pad.t + H}
            stroke="var(--line)" strokeDasharray={v === 0 ? '' : '2 4'}
          />
          <text
            x={pad.l + (v / DISPLAY_CAP) * W} y={pad.t + H + 16}
            textAnchor="middle" fontSize="10" fill="var(--ink-soft)" fontFamily="var(--mono)"
          >{v}%</text>
        </g>
      ))}
      <line x1={pad.l} y1={pad.t + H} x2={pad.l + W} y2={pad.t + H} stroke="var(--line)" />

      {/* bars */}
      {data.map((r, i) => {
        const isBest = r.WAPE_pct != null && r.WAPE_pct === bestWAPE;
        const wape = r.WAPE_pct != null ? r.WAPE_pct : 0;
        const disp = Math.min(wape, DISPLAY_CAP);
        const barW = (disp / DISPLAY_CAP) * W;
        const overflow = wape > DISPLAY_CAP;
        const y = pad.t + i * rowH + rowH * 0.18;
        const bH = rowH * 0.56;
        const hk = modelKey(r.model);
        return (
          <g key={i} className="chart-series" opacity={hl && hk !== hl ? 0.3 : 1}>
            {hl && hk === hl && <rect x={2} y={y - rowH * 0.12} width={width - 4} height={bH + rowH * 0.24} rx="5" fill="none" stroke="var(--primary)" strokeWidth="1.5" />}
            <text
              x={pad.l - 10} y={y + bH / 2 + 4}
              textAnchor="end" fontSize="11.5" fontFamily="var(--body)"
              fontWeight={isBest ? 600 : 400}
              fill={isBest ? 'var(--accent)' : 'var(--ink)'}
            >{labelFor(r.model)}</text>
            <rect
              x={pad.l} y={y} width={barW} height={bH} rx="3"
              fill={isBest ? 'var(--accent)' : 'var(--primary)'}
              opacity={isBest ? 0.88 : 0.45}
            />
            <text
              x={pad.l + barW + (overflow ? 6 : 8)} y={y + bH / 2 + 4}
              fontSize="11" fontFamily="var(--mono)"
              fontWeight={isBest ? 700 : 400}
              fill={isBest ? 'var(--accent)' : 'var(--ink)'}
            >{r.WAPE_pct != null ? r.WAPE_pct.toFixed(1) + '%' : '—'}{overflow ? ' ▶' : ''}</text>
          </g>
        );
      })}

      <text
        x={pad.l + W / 2} y={height - 4}
        textAnchor="middle" fontSize="11" fill="var(--ink-muted)"
      >WAPE % on the {split.label} · lower is better</text>
    </svg>
  );
};

/* ── Forecast interval chart — P10/P50/P90 vs actual riders for Embarcadero (real data) ── */
const Calibration = ({ width = 460, height = 260, model = 'sarima' }) => {
  const FC = FC_MODELS[model] || FC_MODELS.sarima;
  const fcRes = useFcFiles()[FC.key];
  const acRes = useSiteData('ridership_actuals.json');
  const message = (...lines) => <ChartMessage width={width} height={height} lines={lines} />;
  if (!fcRes || !acRes) return message('Loading…');
  if (siteFailed(fcRes)) return message('The forecasts could not be loaded.', `${FC.file} · reload the page to try again`);

  // Station ids are BART's two-letter codes everywhere (data files and live API).
  const pts = siteRows(fcRes).filter(r => r && r.station_id === 'EM' && typeof r.month === 'string')
    .sort((a, b) => a.month.localeCompare(b.month));
  const actualByMonth = {};
  siteRows(acRes).forEach(r => {
    if (r && r.station_id === 'EM' && r.ridership != null) actualByMonth[r.month] = r.ridership;
  });

  // export_website_data.py's _finite_or_none() documents that p10/p50/p90
  // can each independently be null for a given row. Passing a null straight
  // into sy() below (`v - minV`) coerces it to 0 - minV -- a finite but
  // wrong y-coordinate -- silently drawing a spurious spike/dip instead of
  // skipping the point. Drop any row missing a quantile before building the
  // paths.
  const validPts = pts.filter(r => r.p10 != null && r.p50 != null && r.p90 != null);
  if (validPts.length === 0) return message(`No Embarcadero forecasts are published in ${FC.file}.`);

  // Actual riders for the forecast months, at the same x index as validPts.
  const actualPts = validPts
    .map((r, i) => ({ i, v: actualByMonth[r.month] }))
    .filter(a => a.v != null);
  const hasActual = actualPts.length > 0;

  const pad = { l: 58, r: 20, t: 44, b: 38 };
  const W = width - pad.l - pad.r;
  const H = height - pad.t - pad.b;
  const n = validPts.length;

  // Actuals join the y-domain so a month outside the band is still drawn.
  // Misses happen with the calibrated band too (docs/interval-calibration.md).
  const allVals = [...validPts.flatMap(r => [r.p10, r.p50, r.p90]), ...actualPts.map(a => a.v)];
  const minV = Math.min(...allVals) * 0.92;
  const maxV = Math.max(...allVals) * 1.05;

  const sx = i => pad.l + (n === 1 ? W / 2 : (i / (n - 1)) * W);
  const sy = v => pad.t + (1 - (v - minV) / (maxV - minV)) * H;
  const fmtK = v => v >= 1e6 ? (v / 1e6).toFixed(2) + 'M' : (v / 1e3).toFixed(0) + 'k';
  const monthLabel = s => { const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']; return mo[parseInt(s.slice(5,7),10)-1]; };
  const firstYear = validPts[0].month.slice(0, 4);
  const lastYear = validPts[n - 1].month.slice(0, 4);
  const yearLabel = firstYear === lastYear ? firstYear : `${firstYear}–${lastYear}`;

  const bandPath = [
    ...validPts.map((r, i) => `${i === 0 ? 'M' : 'L'}${sx(i).toFixed(1)},${sy(r.p90).toFixed(1)}`),
    ...validPts.slice().reverse().map((r, i) => `L${sx(n - 1 - i).toFixed(1)},${sy(r.p10).toFixed(1)}`),
    'Z',
  ].join(' ');
  const p50Path = validPts.map((r, i) => `${i === 0 ? 'M' : 'L'}${sx(i).toFixed(1)},${sy(r.p50).toFixed(1)}`).join(' ');
  const p10Path = validPts.map((r, i) => `${i === 0 ? 'M' : 'L'}${sx(i).toFixed(1)},${sy(r.p10).toFixed(1)}`).join(' ');
  const p90Path = validPts.map((r, i) => `${i === 0 ? 'M' : 'L'}${sx(i).toFixed(1)},${sy(r.p90).toFixed(1)}`).join(' ');
  const actualPath = actualPts.map((a, k) => `${k === 0 ? 'M' : 'L'}${sx(a.i).toFixed(1)},${sy(a.v).toFixed(1)}`).join(' ');

  const gridVals = [0.25, 0.5, 0.75, 1].map(t => minV + (maxV - minV) * t);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display:'block' }}>
      <defs>
        <linearGradient id="bandFill2" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.16" />
          <stop offset="100%" stopColor="var(--primary)" stopOpacity="0.03" />
        </linearGradient>
      </defs>

      {/* grid */}
      {gridVals.map((v, i) => (
        <g key={i}>
          <line x1={pad.l} x2={pad.l + W} y1={sy(v)} y2={sy(v)} stroke="var(--line)" strokeDasharray="2 4" />
          <text x={pad.l - 6} y={sy(v) + 4} textAnchor="end" fontSize="9.5" fill="var(--ink-soft)" fontFamily="var(--mono)">{fmtK(v)}</text>
        </g>
      ))}

      {/* P10/P90 band */}
      <path d={bandPath} fill="url(#bandFill2)" />
      {/* P10 / P90 dashed edges */}
      <path d={p90Path} fill="none" stroke="var(--primary)" strokeWidth="1.2" strokeDasharray="4 3" opacity="0.5" />
      <path d={p10Path} fill="none" stroke="var(--primary)" strokeWidth="1.2" strokeDasharray="4 3" opacity="0.5" />
      {/* P50 median */}
      <path d={p50Path} fill="none" stroke="var(--primary)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      {validPts.map((r, i) => (
        <circle key={i} cx={sx(i)} cy={sy(r.p50)} r="3.5" fill="var(--bg-elev)" stroke="var(--primary)" strokeWidth="1.8" />
      ))}
      {/* actual riders */}
      {hasActual && (
        <path d={actualPath} fill="none" stroke="var(--accent)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      )}
      {actualPts.map(a => (
        <circle key={`a${a.i}`} className="actual-pt" cx={sx(a.i)} cy={sy(a.v)} r="3.5" fill="var(--accent)" stroke="var(--bg-elev)" strokeWidth="1.2" />
      ))}

      {/* x labels */}
      {validPts.map((r, i) => (
        <text key={i} x={sx(i)} y={pad.t + H + 16} textAnchor="middle" fontSize="10" fill="var(--ink-soft)" fontFamily="var(--mono)">{monthLabel(r.month)}</text>
      ))}

      {/* annotations */}
      <text x={pad.l} y={14} fontSize="10" fill="var(--ink-soft)" fontFamily="var(--mono)">{`Embarcadero · ${FC.label} forecast`}</text>
      <text x={pad.l + W} y={pad.t + H + 30} textAnchor="end" fontSize="10" fill="var(--ink-muted)">{yearLabel}</text>

      {/* legend */}
      <g transform={`translate(${pad.l}, 30)`}>
        <line x1="0" y1="0" x2="18" y2="0" stroke="var(--primary)" strokeWidth="2.4" />
        <circle cx="9" cy="0" r="3" fill="var(--bg-elev)" stroke="var(--primary)" strokeWidth="1.8" />
        <text x="24" y="4" fontSize="10.5" fill="var(--ink)" fontFamily="var(--body)">P50 median</text>
        <rect x="100" y="-4" width="18" height="8" rx="2" fill="var(--primary)" opacity="0.16" />
        <line x1="100" y1="-4" x2="118" y2="-4" stroke="var(--primary)" strokeWidth="1" strokeDasharray="3 2" opacity="0.5" />
        <line x1="100" y1="4" x2="118" y2="4" stroke="var(--primary)" strokeWidth="1" strokeDasharray="3 2" opacity="0.5" />
        <text x="124" y="4" fontSize="10.5" fill="var(--ink)" fontFamily="var(--body)">P10–P90 band</text>
        {hasActual && (
          <g transform="translate(212, 0)">
            <line x1="0" y1="0" x2="18" y2="0" stroke="var(--accent)" strokeWidth="1.6" />
            <circle cx="9" cy="0" r="3" fill="var(--accent)" />
            <text x="24" y="4" fontSize="10.5" fill="var(--ink)" fontFamily="var(--body)">Actual riders</text>
          </g>
        )}
      </g>
    </svg>
  );
};

/* ── All four models' P50 forecasts against actual riders — Embarcadero ──
   One line per model that has Embarcadero rows in its export; a model whose
   export is missing, unreadable or has no Embarcadero rows is named under the
   chart instead of silently dropped. Months are the union of the forecast
   months; actuals come from ridership_actuals.json. */
const ModelCompare = ({ width = 640, height = 300, station = 'EM', stationName = 'Embarcadero' }) => {
  const files = useFcFiles();
  const acRes = useSiteData('ridership_actuals.json');
  // Page-wide model highlight (interactions.jsx): the highlighted series is
  // drawn on top and thicker, the other models fade.
  const [hl] = useModelHighlight();
  const fade = k => (hl && hl !== k ? 0.18 : 1);
  const message = (...lines) => <ChartMessage width={width} height={height} lines={lines} />;
  if (!acRes || FC_ORDER.some(k => !files[k])) return message('Loading…');

  const series = FC_ORDER.map(k => {
    const pts = siteRows(files[k]).filter(r => r && r.station_id === station && typeof r.month === 'string' && r.p50 != null)
      .sort((a, b) => a.month.localeCompare(b.month));
    return { k, m: FC_MODELS[k], pts };
  });
  const shown = series.filter(x => x.pts.length);
  const missing = series.filter(x => !x.pts.length).map(x => x.m.short);
  if (!shown.length) return message(`No ${stationName} forecasts are published.`);

  const months = [...new Set(shown.flatMap(x => x.pts.map(p => p.month)))].sort();
  const actualByMonth = {};
  siteRows(acRes).forEach(r => { if (r && r.station_id === station && r.ridership != null) actualByMonth[r.month] = r.ridership; });
  const actuals = months.map((m, i) => ({ i, v: actualByMonth[m] })).filter(a => a.v != null);

  const pad = { l: 58, r: 20, t: 52, b: 34 };
  const W = width - pad.l - pad.r, H = height - pad.t - pad.b;
  const n = months.length;
  const allVals = [...shown.flatMap(x => x.pts.map(p => p.p50)), ...actuals.map(a => a.v)];
  const minV = Math.min(...allVals) * 0.94, maxV = Math.max(...allVals) * 1.04;
  const sx = i => pad.l + (n === 1 ? W / 2 : (i / (n - 1)) * W);
  const sy = v => pad.t + (1 - (v - minV) / (maxV - minV)) * H;
  const fmtK2 = v => v >= 1e6 ? (v / 1e6).toFixed(2) + 'M' : (v / 1e3).toFixed(0) + 'k';
  const idx = {}; months.forEach((m, i) => { idx[m] = i; });
  const path = pts => pts.map((p, j) => `${j ? 'L' : 'M'}${sx(idx[p.month]).toFixed(1)},${sy(p.p50).toFixed(1)}`).join(' ');
  const span = monthSpan(months.map(m => ({ month: m })));
  const gridVals = [0.25, 0.5, 0.75, 1].map(t => minV + (maxV - minV) * t);

  // Legend: two rows of up to three entries.
  const entries = [...shown.map(x => ({ id: x.k, label: x.m.short, color: x.m.color, dash: x.k === 'naive' ? '5 3' : '' })),
    ...(actuals.length ? [{ id: 'actual', label: 'Actual riders', color: 'var(--accent)', actual: true }] : [])];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display:'block' }} role="img"
      aria-label={`${stationName}: P50 forecast of each model against actual riders${span ? `, ${span.range}` : ''}`}>
      {gridVals.map((v, i) => (
        <g key={i}>
          <line x1={pad.l} x2={pad.l + W} y1={sy(v)} y2={sy(v)} stroke="var(--line)" strokeDasharray="2 4" />
          <text x={pad.l - 6} y={sy(v) + 4} textAnchor="end" fontSize="9.5" fill="var(--ink-soft)" fontFamily="var(--mono)">{fmtK2(v)}</text>
        </g>
      ))}
      {[...shown.filter(x => x.k !== hl), ...shown.filter(x => x.k === hl)].map(x => (
        <g key={x.k} className="chart-series" opacity={fade(x.k)}>
          <path d={path(x.pts)} fill="none" stroke={x.m.color} strokeWidth={x.k === hl ? 3.4 : x.k === 'sarima' ? 2.6 : 1.8}
            strokeDasharray={x.k === 'naive' ? '5 3' : ''} strokeLinecap="round" strokeLinejoin="round" />
          {x.pts.map(p => <circle key={p.month} cx={sx(idx[p.month])} cy={sy(p.p50)} r={x.k === 'sarima' ? 3.2 : 2.4} fill="var(--bg-elev)" stroke={x.m.color} strokeWidth="1.6" />)}
        </g>
      ))}
      {actuals.length > 0 && (
        <g>
          <path d={actuals.map((a, j) => `${j ? 'L' : 'M'}${sx(a.i).toFixed(1)},${sy(a.v).toFixed(1)}`).join(' ')} fill="none" stroke="var(--accent)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          {actuals.map(a => <circle key={a.i} cx={sx(a.i)} cy={sy(a.v)} r="3.4" fill="var(--accent)" stroke="var(--bg-elev)" strokeWidth="1.2" />)}
        </g>
      )}
      {months.map((m, i) => (
        <text key={m} x={sx(i)} y={pad.t + H + 16} textAnchor="middle" fontSize="10" fill="var(--ink-soft)" fontFamily="var(--mono)">{MONTH_ABBR[parseInt(m.slice(5, 7), 10) - 1]}</text>
      ))}
      <text x={pad.l} y={14} fontSize="10" fill="var(--ink-soft)" fontFamily="var(--mono)">{`${stationName} · P50 forecast of each model${span ? ` · ${span.range}` : ''}`}</text>
      <text x={pad.l + W} y={pad.t + H + 30} textAnchor="end" fontSize="10" fill="var(--ink-muted)">{span ? span.range.replace(/^[A-Za-z]+(?:–[A-Za-z]+)?\s/, '') : ''}</text>
      <g transform={`translate(${pad.l}, 30)`}>
        {entries.map((e, i) => {
          const x = (i % 3) * 125, y = Math.floor(i / 3) * 14;
          return (
            <g key={e.id} transform={`translate(${x}, ${y})`} className="chart-series" opacity={e.actual ? 1 : fade(e.id)}>
              <line x1="0" y1="0" x2="18" y2="0" stroke={e.color} strokeWidth={e.id === 'sarima' ? 2.6 : 1.8} strokeDasharray={e.dash || ''} />
              <circle cx="9" cy="0" r="2.6" fill={e.actual ? e.color : 'var(--bg-elev)'} stroke={e.color} strokeWidth="1.5" />
              <text x="24" y="4" fontSize="10.5" fill="var(--ink)" fontFamily="var(--body)">{e.label}</text>
            </g>
          );
        })}
      </g>
      {missing.length > 0 && (
        <text x={pad.l} y={height - 2} fontSize="10" fill="var(--ink-muted)">{`Not shown (no ${stationName} forecasts published): ${missing.join(', ')}`}</text>
      )}
    </svg>
  );
};

const HeroOrbit = () => {
  const hs = headlineStats(useSiteData('model_comparison.json'), null);
  return (
    <svg viewBox="0 0 520 520" width="100%" style={{ display:'block', overflow:'visible' }}>
      <defs>
        <radialGradient id="core" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity=".55" />
          <stop offset="60%" stopColor="var(--primary)" stopOpacity=".22" />
          <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="ring" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="var(--primary)" />
          <stop offset="100%" stopColor="var(--accent)" />
        </linearGradient>
      </defs>
      <circle cx="260" cy="260" r="240" fill="url(#core)" />
      {[80, 130, 180, 230].map((r, i) => (
        <circle key={i} cx="260" cy="260" r={r} fill="none" stroke="var(--line-strong)" strokeWidth="1" strokeDasharray={i%2?'':'4 6'} opacity=".7" />
      ))}
      <circle cx="260" cy="260" r="180" fill="none" stroke="url(#ring)" strokeWidth="2.5" strokeDasharray="540 600" strokeLinecap="round" transform="rotate(-130 260 260)">
        <animateTransform attributeName="transform" type="rotate" from="-130 260 260" to="230 260 260" dur="22s" repeatCount="indefinite" />
      </circle>
      {Array.from({length:24}).map((_,i)=>{
        const a = (i / 24) * Math.PI * 2;
        const r1 = 80, r2 = 230;
        const x1 = 260 + Math.cos(a)*r1, y1 = 260 + Math.sin(a)*r1;
        const x2 = 260 + Math.cos(a)*r2, y2 = 260 + Math.sin(a)*r2;
        return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--line)" strokeWidth="0.6" />;
      })}
      {[
        {a: 0.2, r: 230, c: 'var(--accent)', s: 7},
        {a: 0.7, r: 230, c: 'var(--primary)', s: 5},
        {a: 1.3, r: 180, c: 'var(--accent)', s: 6},
        {a: 1.9, r: 230, c: 'var(--primary)', s: 5},
        {a: 2.6, r: 180, c: 'var(--gold)', s: 4},
        {a: 3.3, r: 230, c: 'var(--primary)', s: 5},
        {a: 4.1, r: 180, c: 'var(--accent)', s: 6},
        {a: 4.9, r: 230, c: 'var(--primary)', s: 5},
        {a: 5.6, r: 180, c: 'var(--accent)', s: 7},
      ].map((p,i)=>{
        const x = 260 + Math.cos(p.a)*p.r;
        const y = 260 + Math.sin(p.a)*p.r;
        return (
          <g key={i}>
            <circle cx={x} cy={y} r={p.s+5} fill={p.c} opacity=".15">
              <animate attributeName="r" values={`${p.s+3};${p.s+10};${p.s+3}`} dur={`${2+i*0.3}s`} repeatCount="indefinite" />
              <animate attributeName="opacity" values=".25;.05;.25" dur={`${2+i*0.3}s`} repeatCount="indefinite" />
            </circle>
            <circle cx={x} cy={y} r={p.s} fill={p.c} />
          </g>
        );
      })}
      <g transform="translate(260,260)">
        <circle r="56" fill="var(--bg-elev)" stroke="var(--line-strong)" />
        <circle r="56" fill="url(#core)" opacity=".6" />
        <text textAnchor="middle" y="-6" fontFamily="var(--mono)" fontSize="11" fill="var(--ink-muted)">WAPE · test</text>
        <text textAnchor="middle" y="22" fontFamily="var(--display)" fontWeight="600" fontSize="30" fill="var(--ink)" letterSpacing="-1">{hs ? fmtPct(hs.best.WAPE_pct) : '—'}</text>
      </g>
    </svg>
  );
};

const Gauge = ({ value = 0.42 }) => {
  const w = 280, h = 160;
  const cx = w/2, cy = h - 14;
  const r = 110;
  const start = Math.PI;
  const end = 0;
  const arc = (from, to) => {
    const x1 = cx + r * Math.cos(from), y1 = cy + r * Math.sin(-from);
    const x2 = cx + r * Math.cos(to),   y2 = cy + r * Math.sin(-to);
    const large = Math.abs(to - from) > Math.PI ? 1 : 0;
    const sweep = to > from ? 0 : 1;
    return `M${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 ${large} ${sweep} ${x2.toFixed(2)},${y2.toFixed(2)}`;
  };
  const ang = start + (end - start) * value;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" className="arc">
      <defs>
        <linearGradient id="gaugeG" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="var(--good)" />
          <stop offset="55%" stopColor="var(--warn)" />
          <stop offset="100%" stopColor="var(--danger)" />
        </linearGradient>
      </defs>
      <path d={arc(start, end)} fill="none" stroke="var(--bg-muted)" strokeWidth="14" strokeLinecap="round" />
      <path d={arc(start, ang)} fill="none" stroke="url(#gaugeG)" strokeWidth="14" strokeLinecap="round" style={{ transition:'all .5s cubic-bezier(.2,.7,.2,1)' }} />
      {[0,0.25,0.5,0.75,1].map(t => {
        const a = start + (end - start) * t;
        const x1 = cx + (r+10) * Math.cos(a), y1 = cy + (r+10) * Math.sin(-a);
        const x2 = cx + (r+18) * Math.cos(a), y2 = cy + (r+18) * Math.sin(-a);
        return <line key={t} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--ink-soft)" strokeWidth="1" />;
      })}
      <text x={cx - r - 4} y={h - 2} fontFamily="var(--mono)" fontSize="10" fill="var(--ink-soft)" textAnchor="middle">0%</text>
      <text x={cx + r + 4} y={h - 2} fontFamily="var(--mono)" fontSize="10" fill="var(--ink-soft)" textAnchor="middle">100%</text>
    </svg>
  );
};

Object.assign(window, {
  ROCCurve, Calibration, ModelCompare, HeroOrbit, Gauge,
  loadSiteData, useSiteData, siteRows, siteFailed, monthSpan, yearSpan, scoredForecasts, comparisonSplit,
  FC_MODELS, FC_ORDER, useFcFiles, loadSiteJson, useSiteJson, modelKey, backtestStats, sarimaAcrossWindows, headlineStats, fmtPct, fmtInt, fmtK, shortModel, holdoutLabel,
});
