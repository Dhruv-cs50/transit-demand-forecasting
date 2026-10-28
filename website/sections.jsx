/* Page section components for the senior project site. */

const { useState, useEffect, useRef, useMemo } = React;

/* ── icon set (inline SVG) ─────────────────────────────────────── */
const I = {
  bus: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M8 6v6"/><path d="M16 6v6"/><path d="M2 12h20"/><path d="M18 18h2a1 1 0 0 0 1-1V8a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v9a1 1 0 0 0 1 1h2"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/></svg>,
  flask: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M9 2v6L4.5 17a3 3 0 0 0 2.6 4.5h9.8A3 3 0 0 0 19.5 17L15 8V2"/><path d="M8 2h8"/><path d="M7 14h10"/></svg>,
  database: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6"/></svg>,
  brain: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M12 5a3 3 0 1 0-5.9-.5A3 3 0 0 0 4 8a3 3 0 0 0 .5 5A3 3 0 0 0 6 18a3 3 0 0 0 6 0V5Z"/><path d="M12 5a3 3 0 1 1 5.9-.5A3 3 0 0 1 20 8a3 3 0 0 1-.5 5A3 3 0 0 1 18 18a3 3 0 0 1-6 0"/></svg>,
  chart: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M3 3v18h18"/><path d="M7 15l4-4 4 3 5-7"/></svg>,
  shield: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M12 2 4 5v6c0 5 3.5 9.7 8 11 4.5-1.3 8-6 8-11V5l-8-3Z"/></svg>,
  target: (p) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>,
  arrowR: (p) => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M5 12h14"/><path d="m13 5 7 7-7 7"/></svg>,
  arrowOut: (p) => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M7 17 17 7"/><path d="M7 7h10v10"/></svg>,
  github: (p) => <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" {...p}><path d="M12 .5C5.7.5.5 5.7.5 12a11.5 11.5 0 0 0 7.86 10.94c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.36-3.88-1.36-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.02 1.75 2.69 1.24 3.34.95.1-.74.4-1.24.72-1.53-2.55-.29-5.23-1.27-5.23-5.66 0-1.25.45-2.27 1.18-3.07-.12-.29-.51-1.46.11-3.04 0 0 .96-.31 3.15 1.17a10.97 10.97 0 0 1 5.74 0c2.19-1.48 3.15-1.17 3.15-1.17.62 1.58.23 2.75.11 3.04.73.8 1.18 1.82 1.18 3.07 0 4.4-2.69 5.36-5.25 5.65.41.36.78 1.06.78 2.15v3.18c0 .31.2.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.7 18.3.5 12 .5Z"/></svg>,
  sun: (p) => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>,
  moon: (p) => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>,
  play: (p) => <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none" {...p}><path d="M6 4l14 8-14 8z"/></svg>,
  pause: (p) => <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none" {...p}><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>,
};

/* ── Reveal-on-scroll wrapper ─────────────────────────────────── */
const Reveal = ({ as: Tag = 'div', className = '', children, delay, ...rest }) => {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { el.classList.add('in'); io.disconnect(); } }, { threshold: 0.12 });
    io.observe(el); return () => io.disconnect();
  }, []);
  return <Tag ref={ref} className={`reveal ${delay?`d${delay}`:''} ${className}`} {...rest}>{children}</Tag>;
};

/* ── Nav ───────────────────────────────────────────────────────── */
const Nav = ({ dark, onToggleDark }) => {
  const links = [
    ['overview','Overview'], ['method','Method'], ['data','Data'],
    ['results','Results'], ['demo','Demo'], ['recs','Recommendations'], ['eda','EDA'], ['about','About']
  ];
  const extLinks = [
    { href:'transit-demo.html?v=26', label:'Map Demo ↗' },
    { href:'api-demo.html?v=26',     label:'API Playground ↗' },
  ];
  const [active, setActive] = useState('overview');
  useEffect(() => {
    const ids = links.map(([id])=>id);
    const onScroll = () => {
      let cur = ids[0];
      for (const id of ids) {
        const el = document.getElementById(id); if (!el) continue;
        if (el.getBoundingClientRect().top < window.innerHeight * 0.4) cur = id;
      }
      setActive(cur);
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  return (
    <nav className="nav" aria-label="Section navigation">
      <div className="brand">
        <span className="dot" />
        <b>TransitForecast</b>
      </div>
      {links.map(([id,label]) => (
        <a key={id} className={`lnk ${active===id?'active':''}`} href={`#${id}`}>{label}</a>
      ))}
      {extLinks.map(l => (
        <a key={l.href} className="lnk" href={l.href} target="_blank" rel="noopener noreferrer">{l.label}</a>
      ))}
      <button className="toggle" onClick={onToggleDark} aria-label="Toggle dark mode">
        {dark ? <I.sun /> : <I.moon />} {dark ? 'Light' : 'Dark'}
      </button>
    </nav>
  );
};

/* ── Hero ──────────────────────────────────────────────────────── */
const Hero = () => {
  const hs = headlineStats(useSiteData('model_comparison.json'), useSiteData('forecasts.json'));
  return (
  <section id="overview">
    <div className="wrap hero-grid">
      <Reveal>
        <div className="eyebrow"><span className="pip" /> CS 163 · Senior Project · Fall 2026</div>
        <div style={{ height: 22 }} />
        <h1 className="hero-title">
          Forecasting <em>public transit ridership</em>, station by station, month by month.
        </h1>
        <div style={{ height: 20 }} />
        <p className="lede">
          A machine‑learning pipeline that forecasts monthly ridership at all 50 BART stations,
          six months ahead, built to support service planning decisions. Four models are scored
          on the same holdout: SARIMA, Prophet, a seasonal‑naïve baseline and Chronos‑1
          (chronos-t5-small), a pretrained time‑series foundation model run zero‑shot. None of the
          ranked models uses weather or event data yet.
        </p>
        <div style={{ height: 28 }} />
        <div className="flex gap-md" style={{ flexWrap:'wrap' }}>
          <a href="#demo" className="btn btn-primary">Try the map demo <I.arrowR /></a>
          <a href="#results" className="btn btn-secondary">See results</a>
        </div>
        <div style={{ height: 28 }} />
        <div className="hero-meta">
          <span className="meta-chip"><b>Author</b> · Dhruv Punit Shah</span>
          <span className="meta-chip"><b>Department</b> · Computer Science, SJSU</span>
        </div>
      </Reveal>
      <Reveal delay="2">
        <div className="hero-art">
          <HeroOrbit />
          <div className="float-card" style={{ top: '6%', left: '-4%' }}>
            <div className="mono" style={{ fontSize: 11, color:'var(--ink-muted)' }}>ALL 50 STATIONS</div>
            <div style={{ display:'flex', alignItems:'baseline', gap:8 }}>
              <div className="mono" style={{ fontSize: 22, fontWeight:600, color:'var(--accent)' }}>{hs ? fmtPct(hs.best.WAPE_pct) : '—'}</div>
              <div style={{ fontSize: 12, color:'var(--ink-muted)' }}>WAPE · best model</div>
            </div>
            <div style={{ fontSize: 11, color:'var(--ink-soft)' }}>{hs ? `${shortModel(hs.best.model)} · ${holdoutLabel(hs)}` : '—'}</div>
          </div>
          <div className="float-card b" style={{ bottom:'4%', right:'-4%' }}>
            <div className="mono" style={{ fontSize: 11, color:'var(--ink-muted)' }}>MODEL · {hs ? shortModel(hs.best.model).toUpperCase() : '—'}</div>
            <div className="mono" style={{ fontSize: 13, fontWeight:600 }}>MAE {hs ? fmtInt(hs.best.MAE) : '—'}</div>
            <div style={{ fontSize: 11, color:'var(--ink-soft)' }}>6-mo horizon · 50 BART stations</div>
          </div>
        </div>
      </Reveal>
    </div>
  </section>
  );
};

/* ── At-a-glance metrics ───────────────────────────────────────── */
const AtAGlance = () => {
  const hs = headlineStats(useSiteData('model_comparison.json'), useSiteData('forecasts.json'));
  const items = [
    { ic: <I.target />, num: hs ? hs.best.WAPE_pct.toFixed(1) : '—', unit:'% WAPE',
      lbl: hs ? `${shortModel(hs.best.model)} best model${hs.prophet && hs.prophet !== hs.best ? ` — vs ${fmtPct(hs.prophet.WAPE_pct)} Prophet` : ''}` : 'Best model',
      delta: hs ? `${holdoutLabel(hs)}${hs.n != null ? ` · ${fmtInt(hs.n)} station-months` : ''}` : 'loading…' },
    { ic: <I.chart />, num: '50', unit:' stations', lbl:'Full BART network covered', delta:'Entry-station boardings' },
    { ic: <I.database />, num: '3,000', unit:' records', lbl:'Station-month ridership records', delta:'2019 + 2022–2025 BART OD' },
    { ic: <I.bus />, num: '3', unit:' quantiles', lbl:'P10 / P50 / P90 per station', delta:'Intervals not calibrated yet', dn:true },
  ];
  return (
    <section id="overview-metrics" style={{ padding:'40px 0 80px', borderTop:'none' }}>
      <div className="wrap">
        <div className="metrics">
          {items.map((m,i) => (
            <Reveal key={i} delay={i+1} className="card metric">
              <div className="icon">{m.ic}</div>
              <div className="num">{m.num}<span className="unit">{m.unit}</span></div>
              <div className="lbl">{m.lbl}</div>
              <span className={`delta ${m.dn?'dn':''}`}>{m.dn ? '↓' : '↑'} {m.delta}</span>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
};

/* ── Methodology: five rows, each a rail (step, title, tools) + a short body ── */
const Method = () => {
  const hs = headlineStats(useSiteData('model_comparison.json'), useSiteData('forecasts.json'));
  const hy = halfYearFigures(backtestStats(useSiteJson('backtest_windows.json')));
  const halfYears = hy.rows.map(h => h.wape).join(' / ');
  const hyWord = ['', 'one', 'two', 'three', 'four', 'five'][hy.rows.length] || String(hy.rows.length);
  const flow = ['Cloud Scheduler (daily)', 'Cloud Run job', 'Cloud Storage', '10-check publish gate', 'Published feature store'];
  const steps = [
    { ic: <I.database />, n:'01', t:'Data ingestion', tools:['BART reports','Open-Meteo','Cloud Run job','Cloud Storage','Parquet'],
      head:'Monthly BART ridership, joined with weather and a Sharks schedule.',
      bullets:[
        "Ridership: BART's public ridership reports (bart.gov workbooks, 2019 + 2022–2025; none published for 2020–21), downloaded by hand because bart.gov blocks automated downloads.",
        'Open-Meteo weather, aggregated to months, covers every month in the store. The Sharks home-game schedule starts in September 2019, so January–May 2019 games are missing.',
      ],
      flow,
      details:'A daily Cloud Run job, triggered by Cloud Scheduler, fetches the weather and the schedule into Cloud Storage and rebuilds the station-month feature store (Parquet) from the files in the bucket. It publishes the store only if all 10 checks pass — among them that ridership matches the committed store exactly and that the SARIMA backtest reproduces its published score.' },
    { ic: <I.flask />, n:'02', t:'Feature engineering', tools:['pandas'],
      head:'Built, but no ranked model reads these features.',
      bullets:[
        'Lag and rolling-mean features, calendar flags, monthly weather summaries and Sharks game-day indicators.',
        'SARIMA and the seasonal-naive baseline are univariate, Prophet uses only a US federal holiday calendar, and the Chronos-1 checkpoint cannot accept covariates.',
        'A separate experiment that adds the covariates to SARIMA does not improve it.',
      ],
      details:'The weather and game data reach December 2025, the test window included. That weather is observed, so for the test window it is hindsight, not a forecast.' },
    { ic: <I.brain />, n:'03', t:'Modeling', tools:['Chronos-1','Prophet','SARIMA','Seasonal naive'],
      head: hs ? `${shortModel(hs.best.model)} is the best of four models: ${fmtPct(hs.best.WAPE_pct)} WAPE on the ${holdoutLabel(hs)}.` : 'Four models compared on one holdout.',
      bullets:[
        'Chronos-1 (amazon/chronos-t5-small), applied zero-shot.',
        'SARIMA, Prophet and a seasonal-naive baseline.',
      ] },
    { ic: <I.shield />, n:'04', t:'Validation', tools:['WAPE','MAE'],
      head:'Temporal train/val/test splits — no random shuffling.',
      bullets:[
        'Scored with WAPE, MAE and P10/P90 interval coverage across all 50 BART stations.',
        'Point forecasts were never tuned on the test window. Interval methods were revised after three looks at it, and the intervals are not yet calibrated.',
        `The same SARIMA scored ${halfYears}% WAPE on ${hyWord} half-year holdouts (${hy.rows.map(h => h.window).join(', ')}); the headline figure is ${hy.latestBest ? 'the best' : 'not the best'} of the ${hyWord}.`,
      ],
      details: hy.fromReview ? 'The two earlier half-year figures come from the project review of 2026-10-28 (docs/review-2026-10-28.md), not from the exported site data.' : 'The half-year figures come from backtest_windows.json, which runs every model on each of the holdout windows.' },
    { ic: <I.chart />, n:'05', t:'Deployment', tools:['FastAPI','Cloud Run','React','JSON'],
      head:'A Cloud Run API for live forecasts; a static site for everything else.',
      bullets:[
        'A FastAPI service on Google Cloud Run (P10/P50/P90 per station) fits SARIMA on request from the latest published feature store. Its /health names the store it read.',
        'The website itself is static. It reads JSON exported from the benchmark run on the store committed in the repo (forecasts, actuals, station levels, the model comparison), so the leaderboard and charts do not move with the cloud store.',
      ] },
  ];
  return (
    <section id="method">
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Methodology</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>Five steps from BART's monthly ridership reports to a per‑station forecast.</h2>
            <p className="lede" style={{ maxWidth:'60ch' }}>The leaderboard comes from one seeded benchmark run (models/baselines/benchmarks.py) on the rebuilt feature store; two consecutive runs gave bit‑identical leaderboards.</p>
          </div></Reveal>
        </div>
        <div className="mth">
          {steps.map((s,i) => (
            <Reveal key={i} delay={Math.min(i+1,4)} className="card mth-row">
              <div className="mth-rail">
                <div className="mth-id">
                  <div className="ico">{s.ic}</div>
                  <div>
                    <div className="num">PHASE {s.n}</div>
                    <h4>{s.t}</h4>
                  </div>
                </div>
                <div className="tools">{s.tools.map(t => <span key={t} className="tag">{t}</span>)}</div>
              </div>
              <div className="mth-body">
                <p className="mth-head">{s.head}</p>
                <ul>{s.bullets.map((b,j) => <li key={j}>{b}</li>)}</ul>
                {s.flow && (
                  <div className="mth-flow" aria-label="Cloud ingest pipeline">
                    {s.flow.map((f,j) => <React.Fragment key={f}>{j > 0 && <span className="arr" aria-hidden="true">→</span>}<span className="node">{f}</span></React.Fragment>)}
                  </div>
                )}
                {s.details && <details className="mth-more"><summary>Details</summary><p>{s.details}</p></details>}
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
};

/* ── Dataset ───────────────────────────────────────────────────── */
const Dataset = () => {
  const splits = [
    { nm:'Train (Jan 2022–Dec 2024)', v:1800, w:0.75 },
    { nm:'Validation (Jan–Jun 2025)', v:300, w:0.125 },
    { nm:'Test (Jul–Dec 2025)', v:300, w:0.125 },
  ];
  // Columns of feature_store_enriched.parquet. p = external data: weather for
  // every store month, Sharks games from Sep 2019 (data/MANIFEST.md).
  const features = [
    {n:'Lagged ridership (1, 2, 3, 6, 12 months back)'}, {n:'Rolling mean (3, 12 months)'}, {n:'Rolling std (3 months)'},
    {n:'Month-of-year'}, {n:'Temperature (°F)', p:true}, {n:'Precipitation (mm)', p:true},
    {n:'Wind speed (mph)', p:true}, {n:'Sharks game day', p:true},
  ];
  return (
    <section id="data">
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Dataset</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>BART OD · 3,000 station‑months across 50 stations.</h2>
            <p className="lede" style={{ maxWidth:'60ch' }}>Monthly origin-destination ridership from BART's public ridership reports (bart.gov, downloaded by hand), joined with Open-Meteo weather and a San Jose Sharks home-game schedule (weather for every month, the schedule from September 2019; no ranked model uses them). Splits are strictly temporal — never random — so the test set genuinely simulates deployment six months ahead.</p>
          </div></Reveal>
        </div>
        <div className="ds-grid">
          <Reveal className="card ds-card" style={{ gridColumn:'1 / -1' }}>
            <h3>Temporal splits <span className="text-muted mono" style={{ fontSize: 12, fontWeight:400 }}>· station-months per split · n = 2,400</span></h3>
            <div className="flex flex-col gap-md">
              {splits.map(s => (
                <div key={s.nm} className="bar-row">
                  <span className="nm">{s.nm}</span>
                  <span className="bar"><i style={{ '--w': s.w }} /></span>
                  <span className="v">{s.v.toLocaleString('en-US')}</span>
                </div>
              ))}
            </div>
            <div className="divider" />
            <p className="text-muted" style={{ fontSize: 13 }}>
              Forecast horizon covers the 6-month test period. No future leakage: every model is fit only on data before the test window. All 50 BART stations are included; Embarcadero has the highest volume.
            </p>
          </Reveal>
        </div>
        <div style={{ height: 24 }} />
        <Reveal className="card" style={{ padding: 28 }}>
          <h3 style={{ display:'flex', alignItems:'center', gap:10, marginBottom: 18 }}>
            <I.flask /> Feature catalog <span className="text-muted mono" style={{ fontSize: 12, fontWeight:400 }}>· feature store columns</span>
          </h3>
          <div className="pills">
            {features.map(f => (
              <span key={f.n} className={`pill ${f.p?'p':''}`}>{f.p && <span className="d" />}{f.n}</span>
            ))}
          </div>
          <div className="divider" />
          <p className="text-muted" style={{ fontSize: 13 }}>
            <span className="mono" style={{ color:'var(--ink)' }}>●</span> external data: weather for every month in the store; Sharks games from September 2019, so January–May 2019 reads as months without a game. Lags and rolling windows count calendar months; a lag that lands in 2020–21 is empty; a rolling window uses only the months in it that have data, and is empty when too few do. No ranked model reads any of these columns. A separate, pre-registered experiment that added weather and Sharks games to SARIMA found no improvement (docs/covariate-experiment.md).
          </p>
        </Reveal>
      </div>
    </section>
  );
};

/* ── Which P10/P90 band forecasts.json carries ─────────────────────
   Read from the records' interval_method (the leaderboard's Interval_method
   label); exports written before the label existed carry the model's own
   band. A split-conformal band's quantile is fit on the validation split,
   Jan–Jun 2025 (configs/model.yaml train_end..val_end, the saved
   calibrator's window). That window is not in the export, so it is named
   here, and only shown under the split-conformal label. A bias-shifted band
   (Sprint 6) is fit on forecasts from every monthly origin first_origin ..
   val_end − 1 month (configs/model.yaml), scored on actuals through val_end;
   BAND_POOL_WINDOW names those origins, shown only under its label. */
const BAND_FIT_WINDOW = 'Jan–Jun 2025';
const BAND_POOL_WINDOW = 'Dec 2023 – May 2025';
const BAND_FIT_END = 'Jun 2025';  // val_end: calibrators are fit on data through this month
const bandKind = records => {
  const labels = [...new Set((Array.isArray(records) ? records : []).map(r =>
    r && typeof r.interval_method === 'string' && r.interval_method ? r.interval_method : null))];
  const label = labels.length === 1 ? labels[0] : null;
  const raw = label && /^raw: (.+)$/.exec(label);
  return {
    label,
    conformal: !!label && /^split-conformal \S+, fit on validation$/.test(label),
    shifted: !!label && /^bias-shifted rolling-origin conformal \S+, .+, fit on data to val_end$/.test(label),
    // A rolling-origin conformal band (Prophet, seasonal naive): set from the model's own recent errors on data to val_end.
    rolling: !!label && /^rolling-origin conformal \S+, .+, fit on data to val_end$/.test(label),
    rawReason: raw ? raw[1] : null,
    labelled: labels.some(l => l !== null),
  };
};

/* ── Results ───────────────────────────────────────────────────── */
const Results = () => {
  const [chart, setChart] = useState('roc');
  const [fcModel, setFcModel] = useState('sarima');
  // Best-model tile is derived from the same file the WAPE chart and the
  // Benchmarks table read, so its model name, WAPE and model count cannot drift.
  const cmpRes = useSiteData('model_comparison.json');
  const fcRes = useSiteData('forecasts.json');
  const split = comparisonSplit(fcRes, cmpRes);
  const hs = headlineStats(cmpRes, fcRes);
  const sar = hs && hs.sarima;
  const ahead = hs ? [
    hs.prophet && hs.prophet !== hs.best && `Prophet at ${fmtPct(hs.prophet.WAPE_pct)}`,
    hs.naive && hs.naive !== hs.best && `a seasonal-naïve baseline at ${fmtPct(hs.naive.WAPE_pct)}`,
  ].filter(Boolean) : [];
  const cmpRows = siteRows(cmpRes).filter(r => r && r.WAPE_pct != null);
  const bestRow = cmpRows.length ? cmpRows.reduce((a, b) => (b.WAPE_pct < a.WAPE_pct ? b : a)) : null;
  const bestNote = bestRow ? `best of ${cmpRows.length} models`
    : !cmpRes ? 'loading…'
    : siteFailed(cmpRes) ? 'model_comparison.json could not be loaded'
    : 'no scored models in model_comparison.json';
  // WAPE chart subtitle: split, window and station-months all come from the data.
  const wapeSub = !split ? 'Loading the model comparison…'
    : siteFailed(cmpRes) ? 'model_comparison.json could not be loaded'
    : `${split.label[0].toUpperCase()}${split.label.slice(1)}${split.n != null ? ` · ${split.n.toLocaleString('en-US')} station-months` : ''} · lower WAPE is better`;
  // The Intervals chart (charts.jsx Calibration) draws forecasts.json's
  // P10/P90; its subtitle names that band. Loading, an unreadable file, an
  // unlabelled (older) export or mixed labels keep the plain subtitle.
  // forecasts.json comes from the shared loader (fcRes above), so the page
  // still makes one request for it.
  const FC = FC_MODELS[fcModel];
  const fcFiles = useFcFiles();
  const fcRecords = siteRows(fcFiles[fcModel]);
  const chartBand = bandKind(fcRecords);
  const chartBandNote = chartBand.conformal
    ? ` · P10–P90 range set from the model's errors on ${BAND_FIT_WINDOW}, not a validated 80% interval`
    : chartBand.shifted
      ? ` · P10–P90 range re-centred on the model's recent errors (forecasts made ${BAND_POOL_WINDOW})`
    : chartBand.rolling
      ? ` · P10–P90 range set from the model's recent errors on data through ${BAND_FIT_END}, not a validated 80% interval`
    : chartBand.rawReason
      ? " · P10–P90 is the model's own band, not a validated 80% interval"
      : '';
  return (
    <section id="results" style={{ background:'var(--bg-muted)' }}>
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Results</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>Accurate point forecasts across all 50 stations.</h2>
            <p className="lede" style={{ maxWidth:'60ch' }}>{hs ? `${shortModel(hs.best.model)} reaches ${fmtPct(hs.best.WAPE_pct)} WAPE on a ${holdoutLabel(hs)} never used to tune the point forecasts${ahead.length ? `, ahead of ${ahead.join(' and ')}` : ''}.` : 'Loading the model comparison…'} Interval methods were revised after three looks at that window, and the intervals are not yet calibrated — see the note below.</p>
          </div></Reveal>
        </div>
        <div className="results-grid">
          <Reveal className="card chart-card">
            <div className="chart-head">
              <div>
                <h3>{chart === 'roc' ? 'WAPE by model — test set' : 'Forecast intervals — Embarcadero'}</h3>
                <p>{chart === 'roc' ? wapeSub : `P10 / P50 / P90 ${FC.label} forecast with actual riders${chartBandNote} · Embarcadero (highest-volume BART station)`}</p>
              </div>
              <div className="chip-grp">
                <button className={chart==='roc'?'on':''} onClick={()=>setChart('roc')}>WAPE</button>
                <button className={chart==='cal'?'on':''} onClick={()=>setChart('cal')}>Intervals</button>
              </div>
            </div>
            {chart === 'cal' && (
              <div className="chip-grp" role="group" aria-label="Forecast model" style={{ marginBottom: 10 }}>
                {FC_ORDER.map(k => (
                  <button key={k} className={fcModel===k?'on':''} onClick={()=>setFcModel(k)}>{FC_MODELS[k].short}</button>
                ))}
              </div>
            )}
            <div>{chart === 'roc' ? <ROCCurve /> : <Calibration model={fcModel} />}</div>
          </Reveal>
          <Reveal delay="1" className="card chart-card">
            <div className="chart-head">
              <div>
                <h3>Test-window accuracy</h3>
                <p>Station-months · test period{hs && hs.window ? ` ${hs.window}` : ''} · 50 BART stations</p>
              </div>
            </div>
            <div className="cm">
              <div className="cm-cell tp"><div className="v">{bestRow ? bestRow.WAPE_pct.toFixed(1) + '%' : '—'}</div><div className="l">WAPE · {bestRow ? bestRow.model : 'best model'}</div><div className="text-muted" style={{ fontSize:11 }}>{bestNote}</div></div>
              <div className="cm-cell tn"><div className="v">{hs ? fmtK(hs.best.MAE) : '—'}</div><div className="l">MAE (riders/mo)</div><div className="text-muted" style={{ fontSize:11 }}>{hs && hs.prophet && hs.prophet !== hs.best ? `vs ${fmtK(hs.prophet.MAE)} Prophet` : ''}</div></div>
              <div className="cm-cell fp"><div className="v">P10/P90</div><div className="l">not calibrated</div><div className="text-muted" style={{ fontSize:11 }}>{hs && hs.covLo != null ? `${Math.round(hs.covLo)}–${Math.round(hs.covHi)}% ` : ''}vs nominal 80%</div></div>
              <div className="cm-cell fn"><div className="v">50 sta.</div><div className="l">all BART stations</div><div className="text-muted" style={{ fontSize:11 }}>no station excluded</div></div>
            </div>
            <div className="text-muted" style={{ fontSize: 13 }}>
              {`SARIMA airline (0,1,1)(0,1,1,12): WAPE ${fmtPct(sar && sar.WAPE_pct)} · MAE ${fmtInt(sar && sar.MAE)} riders/month · ${holdoutLabel(hs)}${hs && hs.n != null ? ` · ${fmtInt(hs.n)} station-months` : ''}`}
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
};

/* ── Map demo: teaser card linking to standalone map page ──────── */
const Demo = () => {
  const features = [
    { icon: '🗺', title: 'Interactive map', desc: '50 BART stations at GTFS coordinates on six real routes, plus 39 VTA stops at approximate positions.' },
    { icon: '🌡', title: 'Heat overlay', desc: 'Color-coded relative load index: green → amber → coral as the index rises.' },
    { icon: '⏱', title: 'Hour scrubber', desc: 'Drag the slider or hit Play to step an illustrative hour-of-day curve through a full 24-hour day.' },
    { icon: '🌧', title: 'Weather + events', desc: 'Toggle rain, heat, or a major event to apply an illustrative adjustment. These effects are not modeled.' },
  ];
  return (
    <section id="demo">
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Map demo</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>Explore the network on a map.</h2>
            <p className="lede" style={{ maxWidth:'60ch' }}>
              An interactive Google Maps view of BART and VTA. Each BART station's base level comes from
              its measured average monthly boardings over the latest 12 months (stations_ridership.json,
              BART Total Trips). The hour-of-day, day, weather and event effects and all VTA levels
              are illustrative, not modeled. Scrub through the hour, change the day, add weather or
              a major event, and the heat overlay updates as you change them.
            </p>
          </div></Reveal>
        </div>

        <Reveal className="card" style={{ padding:'32px' }}>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(200px,1fr))', gap:20, marginBottom:32 }}>
            {features.map(f => (
              <div key={f.title} style={{ display:'flex', gap:14, alignItems:'flex-start' }}>
                <div style={{ fontSize:28, lineHeight:1, flexShrink:0 }}>{f.icon}</div>
                <div>
                  <div style={{ fontWeight:600, fontSize:14, marginBottom:4 }}>{f.title}</div>
                  <div style={{ fontSize:13, color:'var(--ink-muted)', lineHeight:1.5 }}>{f.desc}</div>
                </div>
              </div>
            ))}
          </div>
          <div style={{ display:'flex', gap:12, flexWrap:'wrap', alignItems:'center' }}>
            <a
              href="transit-demo.html?v=26"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display:'inline-flex', alignItems:'center', gap:8,
                padding:'12px 24px', borderRadius:10, background:'var(--primary)',
                color:'var(--bg)', fontWeight:600, fontSize:15, textDecoration:'none',
                fontFamily:'var(--display)',
              }}>
              Open Interactive Map ↗
            </a>
            <span style={{ fontSize:13, color:'var(--ink-muted)' }}>
              Opens in a new tab · Google Maps, with an OpenStreetMap fallback · no install required
            </span>
          </div>
        </Reveal>
      </div>
    </section>
  );
};

/* SARIMA's WAPE on three half-year holdouts, from the project review of
   2026-10-28 (docs/review-2026-10-28.md). Not in model_comparison.json, which
   scores the latest window only; update here if the review is re-run. */
const REVIEW_HALF_YEARS = [
  { window:'Jul–Dec 2024', wape:'6.36' },
  { window:'Jan–Jun 2025', wape:'4.27' },
  { window:'Jul–Dec 2025', wape:'3.21' },
];

/* SARIMA's WAPE on each half-year holdout, oldest first, for the Method and
   Benchmarks copy: from backtest_windows.json when it is usable (bt from
   backtestStats), else the review's three figures (fromReview). `latestBest`
   is whether the latest window's figure is the lowest of them. */
const halfYearFigures = bt => {
  const w = sarimaAcrossWindows(bt);
  const rows = w && w.length > 1 ? w.map(x => ({ window: x.label, wape: x.wape.toFixed(2) })) : REVIEW_HALF_YEARS;
  const v = rows.map(r => +r.wape);
  return { rows, fromReview: !(w && w.length > 1), latestBest: v[v.length - 1] === Math.min(...v) };
};

/* ── Benchmarks + Recommendations ──────────────────────────────── */
const Benchmarks = () => {
  const hy = halfYearFigures(backtestStats(useSiteJson('backtest_windows.json')));
  const hyWord = ['', 'one', 'two', 'three', 'four', 'five'][hy.rows.length] || String(hy.rows.length);
  const cmpRes = useSiteData('model_comparison.json');
  const cmpFailed = siteFailed(cmpRes);
  const cmpData = cmpRes ? siteRows(cmpRes).filter(Boolean) : null;
  const hs = headlineStats(cmpRes, useSiteData('forecasts.json'));
  const benchScope = hs ? [hs.window, hs.n != null && `${fmtInt(hs.n)} station-months`].filter(Boolean).join(', ') : '';
  const benchLede = `All models evaluated on the same temporal split${benchScope ? ` (${benchScope})` : ''} — point forecasts were never tuned on this holdout; interval methods were revised after three looks at it. Lower WAPE and MAE is better.`
    + (hs ? ` ${shortModel(hs.best.model)} reaches ${fmtPct(hs.best.WAPE_pct)} WAPE${hs.prophet && hs.prophet !== hs.best ? `, ahead of Prophet at ${fmtPct(hs.prophet.WAPE_pct)}` : ''}.` : '');
  // Chronos recommendation: figures from the comparison; the ranking claims are
  // kept only while the numbers still say so.
  const chr = hs && hs.chronos;
  const chrRank = chr ? [
    hs.naive && chr.WAPE_pct < hs.naive.WAPE_pct && `ahead of seasonal-naïve at ${fmtPct(hs.naive.WAPE_pct)}`,
    hs.sarima && hs.prophet && chr.WAPE_pct > hs.sarima.WAPE_pct && chr.WAPE_pct > hs.prophet.WAPE_pct && 'behind both classical baselines',
  ].filter(Boolean) : [];
  const chronosRec = chr
    ? `Zero-shot Chronos-1 (chronos-t5-small) scores ${fmtPct(chr.WAPE_pct)} WAPE here${chrRank.length ? ` — ${chrRank.join(', ')}` : ''}. It also runs univariate, since the pipeline cannot pass covariates to this checkpoint. Fixing that, then fine-tuning per station cluster, is the path worth testing.`
    : 'Zero-shot Chronos-1 (chronos-t5-small) runs univariate, since the pipeline cannot pass covariates to this checkpoint. Fixing that, then fine-tuning per station cluster, is the path worth testing.';

  const fmtN = n => n >= 1e6 ? (n/1e6).toFixed(2)+'M' : n >= 1e3 ? (n/1e3).toFixed(0)+'k' : String(Math.round(n));

  const MODEL_LABELS = {
    'SARIMA': 'SARIMA airline (0,1,1)(0,1,1,12)',
    'Prophet': 'Prophet (per-station)',
    'SeasonalNaive': 'Seasonal naive',
  };

  const scoredWAPEs = cmpData ? cmpData.map(r => r.WAPE_pct).filter(v => v != null) : [];
  const bestWAPE = scoredWAPEs.length ? Math.min(...scoredWAPEs) : null;

  const dataRows = cmpData ? [
    ...cmpData.map(r => ({
      m: MODEL_LABELS[r.model] || r.model,
      wape: r.WAPE_pct != null ? r.WAPE_pct.toFixed(1)+'%' : '—',
      mape: r.MAPE_pct != null ? r.MAPE_pct.toFixed(1)+'%' : '—',
      mae:  r.MAE  != null ? fmtN(r.MAE) : '—',
      relW: r.WAPE_pct,
      best: r.WAPE_pct != null && r.WAPE_pct === bestWAPE,
    })),
  ] : [];

  const recs = [
    { n:'01', t:'Keep weather and Sharks games out of the monthly forecast.', d:"The only event data ingested is a Sharks home-game schedule (the pipeline has no Ticketmaster key). It and the weather now run through December 2025, the end of the test window. A pre-registered experiment added them to the leaderboard SARIMA: observed weather made the test forecast worse (3.79% against 3.21% WAPE) and Sharks games made no measurable difference, so at monthly station totals they do not help. Not tested: a daily or hourly grain, a model that pools one effect across stations, and events other than Sharks games.", who:'Operations Control' },
    { n:'02', t:'Fine-tune Chronos per station cluster.', d:chronosRec, who:'Data / ML' },
    { n:'03', t:'Test fresher data sources.', d:"The model trains on BART's monthly ridership reports. The 511 SF Bay API offers real-time stop monitoring and historical stop observations (arrival times, not ridership counts); the repo has a fetcher for them, but nothing joins them into the feature store yet. Whether they would cut data staleness, and how much of the residual error staleness accounts for, has not been measured.", who:'Data / IT' },
  ];
  return (
    <>
      <section id="bench">
        <div className="wrap">
          <div className="section-h">
            <Reveal><div className="eyebrow"><span className="pip" /> Benchmarks</div></Reveal>
            <Reveal delay="1"><div className="row">
              <h2>How we stack up.</h2>
              <p className="lede" style={{ maxWidth:'60ch' }}>{benchLede}</p>
            </div></Reveal>
          </div>
          <Reveal className="card bench">
            <table>
              <thead>
                <tr><th>Model</th><th style={{ textAlign:'right' }}>WAPE %</th><th style={{ textAlign:'right' }}>MAPE %</th><th style={{ textAlign:'right' }}>MAE (riders/mo)</th><th>Relative</th></tr>
              </thead>
              <tbody>
                {cmpData === null ? (
                  <tr><td colSpan={5} style={{ textAlign:'center', color:'var(--ink-muted)', padding:'20px 10px' }}>Loading…</td></tr>
                ) : cmpFailed ? (
                  <tr><td colSpan={5} style={{ textAlign:'center', color:'var(--ink-muted)', padding:'20px 10px' }}>The model comparison (model_comparison.json) could not be loaded. Reload the page to try again.</td></tr>
                ) : dataRows.map((r,i) => (
                  <tr key={i} className={r.best?'best':''}>
                    <td className="model">
                      {r.m}
                      {r.note && <span style={{ display:'block', fontSize:11, color:'var(--ink-muted)', fontWeight:400, marginTop:2 }}>{r.note}</span>}
                    </td>
                    <td className="num">{r.wape}</td>
                    <td className="num">{r.mape}</td>
                    <td className="num">{r.mae}</td>
                    <td className="barcell"><span className="b"><i style={{ '--w': r.relW != null ? Math.min(1, bestWAPE / r.relW) : 0 }} /></span></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-muted" style={{ fontSize: 13, margin:0, padding:'14px 18px 16px', borderTop:'1px solid var(--line)' }}>
              The same SARIMA, refit on earlier half-year holdouts, scored {hy.rows.map(h => `${h.wape}% WAPE (${h.window})`).join(', ')}.
              {` The headline figure is ${hy.latestBest ? 'the best' : 'not the best'} of the ${hyWord}. `}
              {hy.fromReview ? 'The earlier figures come from the project review of 2026-10-28 (docs/review-2026-10-28.md), not from the exported data above.' : 'All of them come from backtest_windows.json, which runs every model on each window.'}
            </p>
          </Reveal>
        </div>
      </section>
      <section id="recs">
        <div className="wrap">
          <div className="section-h">
            <Reveal><div className="eyebrow"><span className="pip" /> Recommendations</div></Reveal>
            <Reveal delay="1"><div className="row">
              <h2>What BART planners should do next.</h2>
              <p className="lede" style={{ maxWidth:'46ch' }}>Three next steps, drawn from what the benchmark and its audit show.</p>
            </div></Reveal>
          </div>
          <div className="recs">
            {recs.map((r,i) => (
              <Reveal key={i} delay={i+1} className="card rec">
                <div className="num">REC {r.n}</div>
                <h3>{r.t}</h3>
                <p>{r.d}</p>
                <span className="who">For: {r.who}</span>
              </Reveal>
            ))}
          </div>
          <div style={{ height: 36 }} />
          <Reveal>
            <div className="pull">
              "Forecasts on dashboards don't change service. A forecast with three reasons next to it does."
              <cite>— project takeaway</cite>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
};

/* ── Why SARIMA: every model, three windows ────────────────────────
   Everything on this panel is read from the data: the per-model figures from
   model_comparison.json (the latest window), "stations SARIMA beats" and the
   three-window table from backtest_windows.json, the chart from the four
   forecast exports. The lede says which windows SARIMA won and names any it
   lost; nothing here assumes SARIMA is first. */
const WhySarima = () => {
  const cmpRes = useSiteData('model_comparison.json');
  const btRes = useSiteJson('backtest_windows.json');
  const files = useFcFiles();
  const bt = backtestStats(btRes);
  const cmp = siteRows(cmpRes).filter(r => r && modelKey(r.model) && typeof r.WAPE_pct === 'number');
  const cmpBy = {}; cmp.forEach(r => { cmpBy[modelKey(r.model)] = r; });
  const stationCount = new Set(siteRows(files.sarima).map(r => r && r.station_id).filter(Boolean)).size;
  const fcSpan = monthSpan(siteRows(files.sarima));
  const name = k => FC_MODELS[k].short;
  const f2 = v => (typeof v === 'number' && isFinite(v) ? v.toFixed(2) + '%' : '—');

  const ok = bt && !bt.failed;
  const last = ok ? bt.windows[bt.windows.length - 1] : null;
  const lastRows = ok ? bt.byWin[last.id] : {};

  // Lede: which windows SARIMA won, and which it lost.
  let lede;
  if (!btRes) lede = 'Loading the backtest…';
  else if (!ok) lede = `The backtest (backtest_windows.json) could not be used${bt.reason ? ` (${bt.reason})` : ''}, so only the latest window is compared here. Reload the page to try again.`;
  else {
    const N = bt.windows.length;
    const lost = bt.windows.filter(w => bt.bestByWindow[w.id] !== 'sarima');
    const word = ['zero', 'one', 'two', 'three', 'four', 'five'][N] || String(N);
    const gaps = bt.windows.filter(w => bt.bestByWindow[w.id] === 'sarima').map(w => {
      const others = Object.entries(bt.byWin[w.id]).filter(([k]) => k !== 'sarima').map(([, v]) => v.wape);
      return others.length ? Math.min(...others) - bt.byWin[w.id].sarima.wape : null;
    }).filter(v => v != null);
    if (!lost.length) {
      lede = `SARIMA has the lowest WAPE in all ${word} half-year windows (${bt.windows.map(w => `${w.label}: ${f2(bt.byWin[w.id].sarima.wape)}`).join('; ')}).`
        + (gaps.length ? ` Its lead over the next-best model is ${Math.min(...gaps).toFixed(2)}–${Math.max(...gaps).toFixed(2)} percentage points.` : '');
    } else {
      lede = `SARIMA has the lowest WAPE in ${N - lost.length} of ${N} half-year windows. `
        + lost.map(w => { const bk = bt.bestByWindow[w.id]; return `In ${w.label}, ${name(bk)} was lower (${f2(bt.byWin[w.id][bk].wape)} against SARIMA's ${f2(bt.byWin[w.id].sarima.wape)}).`; }).join(' ');
    }
  }

  // Consistency: the backtest's latest window must agree with the leaderboard.
  const mismatches = ok ? Object.keys(lastRows).filter(k => cmpBy[k] && Math.abs(lastRows[k].wape - cmpBy[k].WAPE_pct) > 0.06) : [];

  const models = ok ? bt.models : FC_ORDER.filter(k => cmpBy[k]);
  const beatsCell = k => {
    if (k === 'sarima') return '—';
    const b = ok && lastRows[k] ? lastRows[k].beats : null;
    return b != null ? `${b}${stationCount ? ` of ${stationCount}` : ''} stations` : '—';
  };
  const bestLatest = cmp.length ? cmp.reduce((a, b) => (b.WAPE_pct < a.WAPE_pct ? b : a)) : null;

  return (
    <section id="why-sarima">
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Why SARIMA</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>{`Four models${ok ? `, ${['', 'one', 'two', 'three', 'four', 'five'][bt.windows.length] || bt.windows.length} half-year windows` : ''}: how they compare.`}</h2>
            <p className="lede" style={{ maxWidth:'60ch' }}>{lede}</p>
          </div></Reveal>
        </div>

        <div className="results-grid">
          <Reveal className="card chart-card">
            <div className="chart-head">
              <div>
                <h3>Each model, latest window</h3>
                <p>{ok ? `${last.label} · ` : ''}{cmp.length && cmp[0].n_predictions ? `${fmtInt(cmp[0].n_predictions)} station-months · ` : ''}scored by model_comparison.json</p>
              </div>
            </div>
            <div style={{ overflowX:'auto' }}>
              <table className="why-table">
                <thead><tr><th>Model</th><th>WAPE</th><th>MAE</th><th title="Share of station-months inside the model's own P10–P90 band; the nominal level is 80%">Coverage</th><th>SARIMA beats it at</th></tr></thead>
                <tbody>
                  {(cmp.length ? FC_ORDER.filter(k => cmpBy[k]) : []).map(k => {
                    const r = cmpBy[k];
                    return (
                      <tr key={k} className={bestLatest && r === bestLatest ? 'best' : ''}>
                        <td className="model">{name(k)}</td>
                        <td className="num">{fmtPct(r.WAPE_pct)}</td>
                        <td className="num">{fmtK(r.MAE)}</td>
                        <td className="num">{typeof r.Coverage_pct === 'number' ? `${Math.round(r.Coverage_pct)}%` : '—'}</td>
                        <td className="num">{beatsCell(k)}</td>
                      </tr>
                    );
                  })}
                  {!cmpRes && <tr><td colSpan={5} style={{ textAlign:'center', color:'var(--ink-muted)' }}>Loading…</td></tr>}
                  {siteFailed(cmpRes) && <tr><td colSpan={5} style={{ textAlign:'center', color:'var(--ink-muted)' }}>model_comparison.json could not be loaded.</td></tr>}
                </tbody>
              </table>
            </div>
            <p className="text-muted" style={{ fontSize:12 }}>
              Coverage is the share of station-months inside each model's own P10–P90 band (nominal level 80%).
              {ok ? '' : ' “SARIMA beats it at” needs the backtest, which is not loaded.'}
              {mismatches.length ? ` Check: backtest_windows.json's ${last.label} figure differs from the leaderboard for ${mismatches.map(name).join(', ')}.` : ''}
            </p>
          </Reveal>
          <Reveal delay="1" className="card chart-card">
            <div className="chart-head">
              <div>
                <h3>Embarcadero — all four forecasts</h3>
                <p>P50 of each model against actual riders{fcSpan ? ` · ${fcSpan.range}` : ''} · the highest-volume BART station</p>
              </div>
            </div>
            <div><ModelCompare width={460} height={300} /></div>
          </Reveal>
        </div>

        {ok && (
          <Reveal className="card bench" style={{ marginTop:24 }}>
            <div style={{ overflowX:'auto' }}>
              <table className="why-windows">
                <thead>
                  <tr>
                    <th>Model · WAPE</th>
                    {bt.windows.map(w => <th key={w.id} className="r">{w.label}<span className="wid">{w.id}{typeof bt.byWin[w.id].sarima.n === 'number' ? ` · n = ${fmtInt(bt.byWin[w.id].sarima.n)}` : ''}</span></th>)}
                  </tr>
                </thead>
                <tbody>
                  {bt.models.map(k => (
                    <tr key={k}>
                      <td className="model">{name(k)}</td>
                      {bt.windows.map(w => {
                        const v = bt.byWin[w.id][k];
                        const win = bt.bestByWindow[w.id] === k;
                        return (
                          <td key={w.id} className={`num${win ? ' win' : ''}`}>
                            {v ? <>
                              <b>{f2(v.wape)}</b>
                              <span className="sub">{[v.mae != null && `MAE ${fmtK(v.mae)}`, v.cov != null && `cov ${Math.round(v.cov)}%`].filter(Boolean).join(' · ') || ' '}</span>
                            </> : '—'}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-muted" style={{ fontSize:13, margin:0, padding:'14px 18px 16px', borderTop:'1px solid var(--line)' }}>
              Lowest WAPE in each window is shaded. Each model was run on the same three half-year holdouts; coverage (“cov”) is each model's own P10–P90 band in that window (nominal 80%), and calibrators fit on data through {BAND_FIT_END} are not applied to earlier windows, which would leak.
              {typeof bt.source === 'string' && bt.source ? ` Source: ${bt.source}` : ''}{typeof bt.generatedBy === 'string' && bt.generatedBy ? ` (${bt.generatedBy})` : ''}.
            </p>
          </Reveal>
        )}
      </div>
    </section>
  );
};

/* ── EDA Visualizations ────────────────────────────────────────── */
// PNGs and captions come from transit_eda/notebooks/eda_complete.ipynb. When the
// notebook is rerun, its last cell fails unless each caption below (and EDA_NOTE)
// matches its own output exactly, under the same file. Edit captions there, not here.
const EDA_PLOTS = [
  { file:'01_ridership_levels.png', tab:'Network level', title:'Network Total Trips per month, 2019 and 2022–2025',
    desc:'Total Trips per month, summed over all 50 stations. Yearly totals as a share of 2019: 2022 35.0%, 2023 40.5%, 2024 43.1%, 2025 47.3%, rising every year. Berryessa/North San José and Milpitas record 0 trips in 2019; over the other 48 stations 2025 is 46.5% of 2019. The store has no rows for 2020 or 2021, so the line breaks there: the fall between 2019 and 2022 is not observed month by month.' },
  { file:'02_monthly_seasonality.png', tab:'Seasonality', title:'Seasonal index by month and year',
    desc:'Each cell is one month of network Total Trips divided by the mean monthly total of the same year. In all 5 years December, January and February are below 1 and August, September and October are above 1, also after dividing by the days in each month. Leaving out 2022, the December to February cells run from 0.84 to 0.97 and the August to October cells from 1.01 to 1.15. The 2022 row spans 0.64 (January) to 1.19 (September), the widest of the five years, partly from growth during 2022: January 2023 was 51.4% above January 2022, December 2023 only 9.8% above December 2022.' },
  { file:'03_station_ranking.png', tab:'Station ranking', title:'Station ranking, 2022–2025 vs 2019',
    desc:'Median monthly Total Trips per station over 2022 to 2025 (bars, top 20 of 50) and in 2019 (circles). Embarcadero (349k), Powell St. (327k) and Montgomery St. (287k) lead. Montgomery St. had the highest 2019 median (974k). The four busiest stations carry 29.2% of all 2022 to 2025 trips.' },
  { file:'04_data_coverage.png', tab:'Data coverage', title:'Data coverage by month',
    desc:'Each column is one month from January 2019 to December 2025. All 50 stations have a row in each of the 60 months in the store; the 24 months of 2020 and 2021 are not in it. Berryessa/North San José (BE) and Milpitas (ML) record 0 trips in every 2019 month. Weather is filled for every month in the store. The Sharks schedule files run from 2019-09-17 to 2025-12-31, so the game flags for the 8 store months outside that window (January to August 2019) are False for lack of data, not observed zeros.' },
];
const EDA_NOTE = 'No weather or Sharks-game plot. Comparing each month with the same month a year earlier, for the 3 pairs of consecutive years with both (2022 to 2023, 2023 to 2024, 2024 to 2025), the correlation of growth with extra rain is +0.82, -0.27, +0.26 and with extra home games -0.05, +0.41, +0.20. Neither keeps one sign across the pairs, and each value rests on 12 months, so neither is plotted (notebook section 5). Hourly, day-of-week and game-night views need hourly or daily rows; the store has one row per station per month (section 6).';

const EDAViz = () => {
  const [active, setActive] = React.useState(0);
  const plot = EDA_PLOTS[active];
  return (
    <section id="eda" style={{ background:'var(--bg)' }}>
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Exploratory Analysis</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>Patterns in the data.</h2>
            <p className="lede" style={{ maxWidth:'60ch' }}>Four views of the feature store at its own grain, one row per station per month: the 2019 and 2022–2025 levels, seasonality, the station ranking and the gaps. Each caption is written by the EDA notebook (<code style={{ overflowWrap:'anywhere' }}>transit_eda/notebooks/eda_complete.ipynb</code>) from numbers it prints.</p>
          </div></Reveal>
        </div>
        <div className="chip-grp" role="tablist" aria-label="EDA plots" style={{ marginTop:32, flexWrap:'wrap' }}>
          {EDA_PLOTS.map((p, i) => (
            <button key={p.file} role="tab" aria-selected={i === active}
              className={i === active ? 'on' : ''} onClick={() => setActive(i)}>{p.tab}</button>
          ))}
        </div>
        <Reveal key={active}>
          <div className="card" style={{ padding:0, overflow:'hidden', marginTop:16 }}>
            <img src={`data/eda_plots/${plot.file}`} alt={plot.title}
              style={{ width:'100%', display:'block', background:'#fff' }} />
            <div style={{ padding:'16px 20px' }}>
              <h4 style={{ margin:0 }}>{plot.title}</h4>
              <p style={{ margin:'6px 0 0', color:'var(--ink-muted)', fontSize:14 }}>{plot.desc}</p>
            </div>
          </div>
        </Reveal>
        <p style={{ marginTop:16, color:'var(--ink-muted)', fontSize:13, maxWidth:'80ch' }}>{EDA_NOTE}</p>
      </div>
    </section>
  );
};

/* ── About + Resources ─────────────────────────────────────────── */
const About = () => (
  <section id="about" style={{ background:'var(--bg-muted)' }}>
    <div className="wrap">
      <div className="about">
        <Reveal>
          <div className="avatar">
            <div className="initials">DS</div>
          </div>
        </Reveal>
        <Reveal delay="1">
          <div className="eyebrow"><span className="pip" /> About the author</div>
          <div style={{ height: 18 }} />
          <h2>Dhruv Punit Shah.</h2>
          <div style={{ height: 14 }} />
          <p className="lede">
            Senior in Computer Science at San José State University.
            Interested in applied ML for transportation and infrastructure, time-series forecasting,
            and the gap between a "good" validation MAPE and a model that anyone actually trusts on
            a Wednesday morning service planning meeting.
          </p>
          <div style={{ height: 18 }} />
          <p className="lede" style={{ fontSize: 16 }}>
            Previously: data intern at a Bay Area mobility startup; teaching assistant for
            CS 122 (Data Structures &amp; Algorithms II); two summers building inference pipelines
            on AWS.
          </p>
          <div className="links">
            <a className="btn btn-secondary" href="https://github.com/Dhruv-cs50/transit-demand-forecasting" target="_blank" rel="noopener noreferrer"><I.github /> github.com/Dhruv-cs50</a>
            <a className="btn btn-secondary" href="https://www.linkedin.com/in/dhruv-shah911/" target="_blank" rel="noopener noreferrer">LinkedIn <I.arrowOut /></a>
            <a className="btn btn-ghost" href="mailto:dhruv.shah@sjsu.edu">dhruv.shah@sjsu.edu</a>
          </div>
        </Reveal>
      </div>
      <div style={{ height: 64 }} />
      <div className="section-h">
        <Reveal><div className="eyebrow"><span className="pip" /> Resources</div></Reveal>
        <Reveal delay="1"><h2 style={{ fontSize: 32 }}>Read deeper.</h2></Reveal>
      </div>
      <div className="res">
        {[
          { lbl:'Repo · GitHub', t:'Source code', d:'Pipeline scripts, the benchmark runner (SARIMA, Prophet, seasonal naive, Chronos-1 zero-shot) and this website.', href:'https://github.com/Dhruv-cs50/transit-demand-forecasting' },
          { lbl:'Notebook', t:'Exploratory analysis', d:'Summary statistics, seasonality, missing-data and correlation plots. Its saved plots come from an earlier version of the feature store and are due to be regenerated.', href:'https://github.com/Dhruv-cs50/transit-demand-forecasting/blob/main/transit_eda/notebooks/eda_complete.ipynb' },
          { lbl:'BART OD ridership', t:'Dataset · BART OD', d:'Public BART origin-destination monthly ridership data from BART.gov.', href:'https://www.bart.gov/about/reports/ridership' },
          { lbl:'Open-Meteo weather', t:'Dataset · Open-Meteo', d:'Free historical weather API. The feature store holds its monthly aggregates for 2019 and 2022–2025, and the cloud ingest job fetches it daily; no ranked model uses it yet.', href:'https://open-meteo.com' },
        ].map((r,i) => (
          <Reveal key={i} delay={(i%3)+1}>
            <a href={r.href} target={r.href !== '#' ? '_blank' : undefined} rel="noopener noreferrer">
              <span className="lbl">{r.lbl}</span>
              <h4>{r.t} <span className="arr"><I.arrowOut /></span></h4>
              <p>{r.d}</p>
            </a>
          </Reveal>
        ))}
      </div>
    </div>
  </section>
);

const Footer = () => (
  <footer>
    <div className="wrap ftr">
      <div className="left">
        <span className="dot" />
        <small>TransitForecast · CS 163 Senior Project · San José State University · © 2026 Dhruv Shah &amp; Ryder Sabale</small>
      </div>
      <small className="text-muted">Built with React, Chronos-1 (chronos-t5-small), Prophet, SARIMA, and a great deal of caffeine.</small>
    </div>
  </footer>
);

/* ── BART Forecast Section (real model outputs) ─────────────────── */
const API_BASE = 'https://transit-api-308878596074.us-west2.run.app';

const BARTForecasts = () => {
  // Each file's load result is kept, so a failed fetch is told apart from a
  // file that loaded and is empty.
  // SARIMA is the default; the toggle switches between the four models.
  const [fcModel, setFcModel] = React.useState('sarima');
  const FC = FC_MODELS[fcModel];
  const fcRes   = useFcFiles()[fcModel];
  const acRes   = useSiteData('ridership_actuals.json');
  const cmpRes  = useSiteData('model_comparison.json');
  const metaRes = useSiteData('stations_meta.json');
  const loading = !fcRes || !acRes || !cmpRes || !metaRes;
  const forecasts  = siteRows(fcRes).filter(r => r && typeof r.month === 'string');
  const actuals    = siteRows(acRes).filter(r => r && typeof r.month === 'string');
  const comparison = siteRows(cmpRes).filter(Boolean);
  // The model the leaderboard ranks first; labelled on its toggle button.
  const bestRow = comparison.filter(r => typeof r.WAPE_pct === 'number').reduce((a, b) => (!a || b.WAPE_pct < a.WAPE_pct ? b : a), null);
  const bestModelKey = bestRow ? modelKey(bestRow.model) : null;
  const meta       = siteRows(metaRes).filter(m => m && m.bart_id);
  const fcFailed = siteFailed(fcRes);
  const acFailed = siteFailed(acRes);
  const [station, setStation]     = React.useState('EM');
  const [liveData, setLiveData]   = React.useState(null);
  const [liveFetching, setLiveFetching] = React.useState(false);
  const [liveError, setLiveError] = React.useState(null);
  const [liveHealth, setLiveHealth] = React.useState(null);

  // `id` is BART's two-letter station code, the feature store's station_id.
  // The same code filters the static data/*.json exports and is sent to the
  // live /forecast API.
  const KEY_STATIONS = [
    { id:'EM', name:'Embarcadero' },
    { id:'MT', name:'Montgomery St' },
    { id:'12', name:'12th St Oakland' },
    { id:'BE', name:'Berryessa' },
    { id:'FM', name:'Fremont' },
  ];

  // Each live request gets a sequence number; changing station bumps it, so a
  // response (or error) for a previously selected station is dropped.
  const liveReq = React.useRef(0);
  const fetchLive = () => {
    const reqId = ++liveReq.current;
    setLiveFetching(true);
    setLiveError(null);
    setLiveHealth(null);
    // /health says how far the store reaches, i.e. what the forecast is "from".
    // Its failure only drops the caption; the forecast itself does not wait on it.
    fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(45000) })
      .then(r => r.ok ? r.json() : null).catch(() => null)
      .then(h => { if (reqId === liveReq.current) setLiveHealth(h || { unavailable: true }); });
    fetch(`${API_BASE}/forecast`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ station_id: station, horizon_hours: 6 }),
      signal: AbortSignal.timeout(45000),  // a cold Cloud Run start can take 30 s
    })
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || 'API error')))
      .then(data => { if (reqId !== liveReq.current) return; setLiveData(data); setLiveFetching(false); })
      .catch(err => { if (reqId !== liveReq.current) return; setLiveError(String(err)); setLiveFetching(false); });
  };

  React.useEffect(() => {
    liveReq.current++;
    setLiveData(null); setLiveError(null); setLiveFetching(false); setLiveHealth(null);
  }, [station]);

  // "Forecast from data through {month}" — the store's last month, from /health.
  const lastMonth = liveHealth && typeof liveHealth.store_last_month === 'string' ? monthSpan([{ month: liveHealth.store_last_month }]) : null;
  const storeSrc = liveHealth && typeof liveHealth.store_source === 'string' && liveHealth.store_source
    ? ` · feature store: ${liveHealth.store_source}${typeof liveHealth.store_run_id === 'string' && liveHealth.store_run_id ? `, run ${liveHealth.store_run_id}` : ''}` : '';
  const liveOrigin = lastMonth ? `Forecast from data through ${lastMonth.range}${storeSrc}`
    : liveHealth ? 'Forecast origin unavailable (/health did not report the store\'s last month)'
    : 'Reading the forecast origin from /health…';

  const metaById = {};
  meta.forEach(m => { metaById[m.bart_id] = m; });
  const nameFor = id => metaById[id]?.station_name || KEY_STATIONS.find(s => s.id === id)?.name || id;
  const stationOptions = meta
    .map(m => ({ id: m.bart_id, name: m.station_name || m.bart_id }))
    .sort((a, b) => a.name.localeCompare(b.name));

  const stationActuals = actuals
    .filter(r => r.station_id === station && r.ridership != null)
    .sort((a, b) => a.month.localeCompare(b.month));

  const stationForecasts = forecasts
    .filter(r => r.station_id === station)
    .sort((a, b) => a.month.localeCompare(b.month));

  // One row per month: the 12 actual months before the first forecast month,
  // then each forecast month with its actual (if any) beside P10/P50/P90.
  // A station with no forecasts shows its last 12 actual months.
  const actualByMonth = {};
  stationActuals.forEach(r => { actualByMonth[r.month] = r.ridership; });
  const firstFc = stationForecasts[0]?.month;
  const tableRows = firstFc
    ? [
        ...stationActuals.filter(r => r.month < firstFc).slice(-12)
          .map(r => ({ month: r.month, actual: r.ridership, fc: null })),
        ...stationForecasts.map(f => ({ month: f.month, actual: actualByMonth[f.month] ?? null, fc: f })),
      ]
    : stationActuals.slice(-12).map(r => ({ month: r.month, actual: r.ridership, fc: null }));

  const fmt = n => n >= 1e6
    ? (n/1e6).toFixed(2)+'M'
    : n >= 1e3 ? (n/1e3).toFixed(0)+'k' : String(n);

  const maxRiders = Math.max(
    ...tableRows.map(r => r.actual || 0),
    ...tableRows.map(r => (r.fc && r.fc.p90) || 0),
    1
  );

  // Every month and year named in the copy comes from the data: the forecast
  // months from forecasts.json (first to last; "through" is the month before
  // the first), the actuals' years from ridership_actuals.json.
  const fcSpan = monthSpan(forecasts);
  const fcRange = fcSpan ? fcSpan.range : null;
  const fcThrough = fcSpan ? fcSpan.through : null;
  const fcCount = fcSpan ? fcSpan.count : 0;
  const acYears = yearSpan(actuals.filter(r => r.ridership != null));
  // "Scored in the model comparison below" only when that comparison has the
  // Chronos row these forecasts were scored as (see scoredForecasts).
  const fcScored = scoredForecasts(fcRes, cmpRes, FC.rowPrefix);
  const split = comparisonSplit(fcRes, cmpRes);
  const reloadHint = fcFailed || acFailed ? ' Reload the page to try again.' : '';

  const forecastSentence = fcFailed
    ? `The forecast export (${FC.file}) could not be loaded${acFailed ? '.' : ', so the table shows actual ridership only.'}`
    : fcRange
      ? `Static export (${FC.file}) of ${FC.full || FC.short} P10/P50/P90 monthly ridership for ${fcRange}, forecast from data through ${fcThrough}${fcScored ? ': the predictions scored in the model comparison below.' : '.'}`
      : `No forecasts are published in the static export (${FC.file})${acFailed ? '.' : ', so the table shows actual ridership only.'}`;
  const actualsSentence = acFailed
    ? 'The actual ridership (ridership_actuals.json) could not be loaded, so no actuals are shown.'
    : acYears
      ? `Actuals are BART monthly Total Trips boardings per entry station, ${acYears}.`
      : 'No actual ridership is published (ridership_actuals.json).';
  const tableNote = fcRange
    ? acFailed
      ? `▶ Forecast months (${fcRange}, forecast from data through ${fcThrough}) shown in blue with P10/P50/P90. Bars sized by P50 (coral).`
      : `▶ Forecast months (${fcRange}, forecast from data through ${fcThrough}) shown in blue, each with its actual riders beside P10/P50/P90. Bars sized by ridership volume: blue = actual, coral = P50.`
    : fcFailed
      ? `Forecasts could not be loaded (${FC.file}), so ${acFailed ? 'there is nothing to show' : 'the table shows the last 12 actual months. Bars sized by ridership volume'}.`
      : `No forecasts are published, so the table shows the last 12 actual months. Bars sized by ridership volume.`;
  const actualsNote = acFailed
    ? 'Actuals could not be loaded (ridership_actuals.json).'
    : acYears
      ? `Actuals are BART monthly Total Trips boardings per entry station (ridership_actuals.json: ${acYears}).`
      : 'No actuals are published (ridership_actuals.json).';

  // Which band P10/P90 is (bandKind, above Results). A coverage figure is
  // shown only when the comparison scored these forecasts (fcScored) and its
  // Chronos leaderboard row carries the same label, so the number always
  // scores the band on screen; it scores the forecast months (fcRange), and
  // the comparison word follows the number. Without it, a split-conformal
  // band still gets the "not validated" caveat.
  const band = bandKind(forecasts);
  const bandRow = fcScored && band.label && comparison.find(r =>
    r && String(r.model || '').startsWith(FC.rowPrefix) && r.Interval_method === band.label
    && typeof r.Coverage_pct === 'number' && isFinite(r.Coverage_pct));
  const bandCov = bandRow ? Math.round(bandRow.Coverage_pct * 10) / 10 : null;
  const bandCoverage = bandRow
    ? ` Over ${fcRange} it held the actual ridership in ${bandCov.toFixed(1)}% of station-months, `
      + `${bandCov < 80 ? 'short of' : bandCov > 80 ? 'above' : 'matching'} the 80% it aims for.`
    : '';
  const bandNote = band.conformal
    ? `The P10–P90 range is set from the model's errors on ${BAND_FIT_WINDOW}`
      + (bandCoverage ? `.${bandCoverage}` : ', but it is not a validated 80% interval.')
    : band.shifted
      ? `The P10–P90 range is re-centred on the model's recent errors (forecasts made ${BAND_POOL_WINDOW}, `
        + `scored on actuals through Jun 2025)`
        + (bandCoverage ? `.${bandCoverage}` : ', but it is not a validated 80% interval.')
    : band.rolling
      ? `The P10–P90 range is set from the model's recent errors on data through ${BAND_FIT_END}`
        + (bandCoverage ? `.${bandCoverage}` : ', but it is not a validated 80% interval.')
    : band.rawReason
      ? `P10/P90 is the model's own band (${band.rawReason}), not a validated 80% interval.${bandCoverage}`
      : band.labelled
        ? 'P10/P90 has no single recognised band label, so it is not a validated 80% interval.'
        : "P10/P90 is the model's own band, not a validated 80% interval.";

  return (
    <section id="bart-data" style={{ background:'var(--bg-muted)', padding:'80px 0' }}>
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Real BART Data</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>{loading ? 'Model outputs — 50 stations.'
              : fcFailed ? 'Model outputs — 50 stations, forecasts unavailable.'
              : fcCount ? `Model outputs — 50 stations, ${fcCount}-month forecast.`
              : 'Model outputs — 50 stations, no forecasts published.'}</h2>
            <p className="lede" style={{ maxWidth:'52ch' }}>
              {loading
                ? `Loading the static export (${FC.file}) of ${FC.full || FC.short} forecasts…`
                : `${forecastSentence}${!fcFailed && fcRange ? ` ${bandNote}` : ''} ${actualsSentence}${reloadHint}`}
              {' '}The button below requests a forecast from the Cloud Run API.
            </p>
          </div></Reveal>
        </div>

        <Reveal className="card" style={{ padding:'24px', marginBottom:24 }}>
          <div role="group" aria-label="Forecast model" style={{ display:'flex', gap:8, flexWrap:'wrap', marginBottom:14, alignItems:'center', fontSize:13 }}>
            <span style={{ color:'var(--ink-muted)' }}>Forecasts from:</span>
            {FC_ORDER.map(k => FC_MODELS[k]).map(m => (
              <button key={m.key}
                onClick={() => setFcModel(m.key)}
                style={{
                  padding:'5px 12px', borderRadius:6, border:'1.5px solid var(--line)',
                  background: fcModel===m.key ? 'var(--primary)' : 'transparent',
                  color: fcModel===m.key ? 'var(--bg)' : 'var(--ink)',
                  cursor:'pointer', fontSize:13, fontWeight:500,
                }}>
                {m.short}{m.key===bestModelKey ? ' (best model)' : ''}
              </button>
            ))}
          </div>
          <div style={{ display:'flex', gap:12, flexWrap:'wrap', marginBottom:20, alignItems:'center' }}>
            {KEY_STATIONS.map(s => (
              <button key={s.id}
                onClick={() => setStation(s.id)}
                style={{
                  padding:'6px 14px', borderRadius:6, border:'1.5px solid var(--line)',
                  background: station===s.id ? 'var(--primary)' : 'transparent',
                  color: station===s.id ? 'var(--bg)' : 'var(--ink)',
                  cursor:'pointer', fontSize:13, fontWeight:500,
                }}>
                {metaById[s.id]?.station_name || s.name}
              </button>
            ))}
            {stationOptions.length > 0 && (
              <select
                aria-label="All stations"
                value={station}
                onChange={e => setStation(e.target.value)}
                style={{
                  padding:'6px 10px', borderRadius:6, border:'1.5px solid var(--line)',
                  background:'var(--bg-elev)', color:'var(--ink)', fontSize:13, fontFamily:'inherit',
                }}>
                {stationOptions.map(o => (
                  <option key={o.id} value={o.id}>{o.name} ({o.id})</option>
                ))}
              </select>
            )}
            <button
              onClick={fetchLive}
              disabled={liveFetching}
              style={{
                marginLeft:'auto', padding:'6px 16px', borderRadius:6,
                border:'1.5px solid var(--accent)', background: liveFetching ? 'var(--bg-muted)' : 'var(--accent)',
                color: liveFetching ? 'var(--ink-muted)' : 'var(--bg)', cursor: liveFetching ? 'default' : 'pointer', fontSize:13, fontWeight:600,
                opacity: liveFetching ? 0.7 : 1,
              }}>
              {liveFetching ? 'Calling API… (cold start: up to 45 s)' : '⚡ Fetch Live from API'}
            </button>
          </div>

          {liveError && (
            <div style={{ marginBottom:16, padding:'10px 14px', borderRadius:8, background:'color-mix(in oklab, var(--accent) 12%, transparent)', color:'var(--accent)', fontSize:13 }}>
              API error: {liveError}
            </div>
          )}
          {liveData && (
            <div style={{ marginBottom:20, padding:'14px 16px', borderRadius:8, background:'color-mix(in oklab, var(--primary) 7%, transparent)', border:'1px solid color-mix(in oklab, var(--primary) 20%, transparent)' }}>
              <div style={{ fontSize:12, color:'var(--primary)', fontWeight:700, marginBottom:8, letterSpacing:'.04em', textTransform:'uppercase' }}>
                ⚡ Live Cloud Run Response — {nameFor(station)} · {typeof liveData.model === 'string' && liveData.model ? liveData.model : 'model not reported'}
              </div>
              <div style={{ fontSize:12, color:'var(--ink-muted)', marginBottom:8 }}>
                {liveOrigin}
              </div>
              <div style={{ display:'flex', gap:24, flexWrap:'wrap' }}>
                {(liveData.forecasts || []).map(f => (
                  <div key={f.timestamp || f.date} style={{ fontSize:13 }}>
                    <div style={{ color:'var(--ink-muted)', fontSize:11, marginBottom:2 }}>{(f.timestamp || f.date || '').slice(0,7)}</div>
                    <div><span style={{ color:'var(--accent)' }}>P10 </span><b style={{ fontFamily:'var(--mono)' }}>{f.p10 != null ? fmt(f.p10) : '—'}</b></div>
                    <div><span style={{ color:'var(--primary)' }}>P50 </span><b style={{ fontFamily:'var(--mono)', fontWeight:700 }}>{f.p50 != null ? fmt(f.p50) : '—'}</b></div>
                    <div><span style={{ color:'var(--accent)' }}>P90 </span><b style={{ fontFamily:'var(--mono)' }}>{f.p90 != null ? fmt(f.p90) : '—'}</b></div>
                  </div>
                ))}
              </div>
              <div style={{ marginTop:10, fontSize:12, color:'var(--ink-muted)' }}>
                {typeof liveData.interval?.description === 'string' && liveData.interval.description.trim()
                  ? liveData.interval.description.trim()
                  : 'P10/P90: band not labelled by this API version; not a validated 80% interval.'}
                {typeof liveData.interval?.label === 'string' && liveData.interval.label ? ` (band: ${liveData.interval.label})` : ''}
              </div>
            </div>
          )}

          {loading ? (
            <div style={{ textAlign:'center', color:'var(--ink-muted)', padding:40 }}>Loading forecast data…</div>
          ) : (
            <div style={{ overflowX:'auto' }}>
              <table style={{ width:'100%', fontSize:13, borderCollapse:'collapse' }}>
                <thead>
                  <tr style={{ borderBottom:'1px solid var(--line)' }}>
                    <th style={{ textAlign:'left', padding:'6px 10px', color:'var(--ink-muted)' }}>Month</th>
                    <th style={{ textAlign:'right', padding:'6px 10px', color:'var(--ink-muted)' }}>Actual Riders</th>
                    <th style={{ textAlign:'right', padding:'6px 10px', color:'var(--accent)' }}>{FC.short} P10</th>
                    <th style={{ textAlign:'right', padding:'6px 10px', color:'var(--primary)' }}>{FC.short} P50</th>
                    <th style={{ textAlign:'right', padding:'6px 10px', color:'var(--accent)' }}>{FC.short} P90</th>
                    <th style={{ padding:'6px 10px' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map(row => row.fc ? (
                    <tr key={row.month} style={{ borderBottom:'1px solid var(--line)', background:'color-mix(in oklab, var(--primary) 4%, transparent)' }}>
                      <td style={{ padding:'5px 10px', fontFamily:'var(--mono)', fontSize:12, color:'var(--primary)' }}>{row.month} ▶</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', fontWeight:600, color: row.actual != null ? 'var(--ink)' : 'var(--ink-muted)' }}>{row.actual != null ? fmt(row.actual) : '—'}</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', color:'var(--accent)', fontFamily:'var(--mono)' }}>{row.fc.p10 != null ? fmt(row.fc.p10) : '—'}</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', color:'var(--primary)', fontWeight:700, fontFamily:'var(--mono)' }}>{row.fc.p50 != null ? fmt(row.fc.p50) : '—'}</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', color:'var(--accent)', fontFamily:'var(--mono)' }}>{row.fc.p90 != null ? fmt(row.fc.p90) : '—'}</td>
                      <td style={{ padding:'5px 10px' }}>
                        {row.actual != null && (
                          <div style={{ background:'var(--primary)', opacity:0.15+0.6*(row.actual/maxRiders), height:6, borderRadius:3, width: `${Math.round(100*row.actual/maxRiders)}%`, minWidth:4, marginBottom:2 }} />
                        )}
                        <div style={{ background:'var(--accent)', opacity:0.7, height:6, borderRadius:3, width: `${Math.round(100*(row.fc.p50||0)/maxRiders)}%`, minWidth:4 }} />
                      </td>
                    </tr>
                  ) : (
                    <tr key={row.month} style={{ borderBottom:'1px solid var(--line)', opacity: row.month >= '2022' ? 1 : 0.65 }}>
                      <td style={{ padding:'5px 10px', fontFamily:'var(--mono)', fontSize:12 }}>{row.month}</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', fontWeight:600 }}>{fmt(row.actual)}</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', color:'var(--ink-muted)' }}>—</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', color:'var(--ink-muted)' }}>—</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', color:'var(--ink-muted)' }}>—</td>
                      <td style={{ padding:'5px 10px' }}>
                        <div style={{ background:'var(--primary)', opacity:0.15+0.6*(row.actual/maxRiders), height:6, borderRadius:3, width: `${Math.round(100*row.actual/maxRiders)}%`, minWidth:4 }} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {tableRows.length === 0 && (
                <div style={{ textAlign:'center', color:'var(--ink-muted)', padding:'24px 10px', fontSize:13 }}>
                  No ridership or forecasts to show for {nameFor(station)}.
                </div>
              )}
              <div style={{ marginTop:12, fontSize:12, color:'var(--ink-muted)' }}>
                {tableNote}{' '}{actualsNote}{reloadHint}
              </div>
            </div>
          )}
        </Reveal>

        {comparison.length > 0 && (
          <Reveal className="card" style={{ padding:'24px' }}>
            <h3 style={{ fontSize:16, marginBottom:16 }}>Model comparison — {split ? split.label : 'held-out split'}{split && split.stations ? `, ${split.stations} stations` : ''}</h3>
            <div style={{ overflowX:'auto' }}>
            <table style={{ width:'100%', fontSize:13, borderCollapse:'collapse' }}>
              <thead>
                <tr style={{ borderBottom:'1px solid var(--line)' }}>
                  <th style={{ textAlign:'left', padding:'6px 10px', color:'var(--ink-muted)' }}>Model</th>
                  <th style={{ textAlign:'right', padding:'6px 10px', color:'var(--ink-muted)' }}>MAPE %</th>
                  <th style={{ textAlign:'right', padding:'6px 10px', color:'var(--ink-muted)' }}>WAPE %</th>
                  <th style={{ textAlign:'right', padding:'6px 10px', color:'var(--ink-muted)' }}>MAE (riders)</th>
                  <th style={{ textAlign:'right', padding:'6px 10px', color:'var(--ink-muted)' }}>n</th>
                </tr>
              </thead>
              <tbody>
                {comparison.map((r, i) => (
                  <tr key={i} style={{ borderBottom:'1px solid var(--line)', background: i===0 ? 'color-mix(in oklab, var(--primary) 4%, transparent)' : 'transparent' }}>
                    <td style={{ padding:'6px 10px', fontWeight:600 }}>{r.model}</td>
                    <td style={{ textAlign:'right', padding:'6px 10px', fontFamily:'var(--mono)' }}>{r.MAPE_pct != null ? r.MAPE_pct.toFixed(1)+'%' : '—'}</td>
                    <td style={{ textAlign:'right', padding:'6px 10px', fontFamily:'var(--mono)' }}>{r.WAPE_pct != null ? r.WAPE_pct.toFixed(1)+'%' : '—'}</td>
                    <td style={{ textAlign:'right', padding:'6px 10px', fontFamily:'var(--mono)' }}>{r.MAE != null ? fmt(r.MAE) : '—'}</td>
                    <td style={{ textAlign:'right', padding:'6px 10px', color:'var(--ink-muted)' }}>{r.n_predictions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </Reveal>
        )}
      </div>
    </section>
  );
};

Object.assign(window, { Nav, Hero, AtAGlance, Method, Dataset, Results, Demo, Benchmarks, WhySarima, EDAViz, About, Footer, BARTForecasts });