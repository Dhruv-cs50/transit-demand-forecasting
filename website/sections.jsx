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
    { href:'transit-demo.html', label:'Map Demo ↗' },
    { href:'api-demo.html',     label:'API Playground ↗' },
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
const Hero = () => (
  <section id="overview">
    <div className="wrap hero-grid">
      <Reveal>
        <div className="eyebrow"><span className="pip" /> CS 163 · Senior Project · Spring 2026</div>
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
              <div className="mono" style={{ fontSize: 22, fontWeight:600, color:'var(--accent)' }}>3.2%</div>
              <div style={{ fontSize: 12, color:'var(--ink-muted)' }}>WAPE · best model</div>
            </div>
            <div style={{ fontSize: 11, color:'var(--ink-soft)' }}>SARIMA · Jul–Dec 2025 holdout</div>
          </div>
          <div className="float-card b" style={{ bottom:'4%', right:'-4%' }}>
            <div className="mono" style={{ fontSize: 11, color:'var(--ink-muted)' }}>MODEL · SARIMA</div>
            <div className="mono" style={{ fontSize: 13, fontWeight:600 }}>MAE 3,086</div>
            <div style={{ fontSize: 11, color:'var(--ink-soft)' }}>6-mo horizon · 50 BART stations</div>
          </div>
        </div>
      </Reveal>
    </div>
  </section>
);

/* ── At-a-glance metrics ───────────────────────────────────────── */
const AtAGlance = () => {
  const items = [
    { ic: <I.target />, num: '3.2', unit:'% WAPE', lbl:'SARIMA best model — vs 5.8% Prophet', delta:'Jul–Dec 2025 holdout · 300 station-months' },
    { ic: <I.chart />, num: '50', unit:' stations', lbl:'Full BART network covered', delta:'All OD pairs · Bay Area' },
    { ic: <I.database />, num: '3,000', unit:' mo', lbl:'Station-month ridership records', delta:'2019 + 2022–2025 BART OD' },
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

/* ── Methodology timeline ──────────────────────────────────────── */
const Method = () => {
  const steps = [
    { ic: <I.database />, n:'01', t:'Data ingestion', d:"Pulled monthly OD ridership from BART's public ridership reports (bart.gov workbooks, 2019 + 2022–2025; BART published none for 2020–21), joined with Open-Meteo weather aggregated to months and a San Jose Sharks home-game schedule. Both archives end in December 2023. Stored as Parquet in a local feature store.", tools:['BART reports','Open-Meteo','Parquet'] },
    { ic: <I.flask />, n:'02', t:'Feature engineering', d:'Built lag and rolling-mean features, calendar flags, monthly weather summaries and Sharks game-day indicators. Because both archives end in 2023, the 2024–2025 rows, the test window included, have no weather and no games. No ranked model reads these features: SARIMA and the seasonal-naive baseline are univariate, Prophet uses only a US federal holiday calendar, and the Chronos-1 checkpoint cannot accept covariates.', tools:['pandas'] },
    { ic: <I.brain />, n:'03', t:'Modeling', d:'Applied Chronos-1 (amazon/chronos-t5-small) zero-shot alongside SARIMA, Prophet and a seasonal-naive baseline. AutoGluon fine-tuning is scaffolded but has never been run — autogluon.timeseries will not install on this Python.', tools:['Chronos-1','Prophet','SARIMA','Seasonal naive'] },
    { ic: <I.shield />, n:'04', t:'Validation', d:'Temporal train/val/test splits — no random shuffling. Evaluated with WAPE, MAE and P10/P90 interval coverage across all 50 BART stations. Intervals are not yet calibrated.', tools:['WAPE','MAE'] },
    { ic: <I.chart />, n:'05', t:'Deployment', d:'Forecasts served via FastAPI (P10/P50/P90 per station). The website reads JSON exported from the pipeline: forecasts, actuals, station levels and the model comparison.', tools:['FastAPI','React','JSON'] },
  ];
  return (
    <section id="method">
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Methodology</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>Five steps from BART's monthly ridership reports to a per‑station forecast.</h2>
            <p className="lede" style={{ maxWidth:'42ch' }}>The published leaderboard comes from one benchmark run (models/baselines/benchmarks.py) on the rebuilt feature store. Its sampling models are seeded, and two consecutive runs produced bit‑identical leaderboards.</p>
          </div></Reveal>
        </div>
        <div className="timeline">
          {steps.map((s,i) => (
            <Reveal key={i} delay={i+1} className="card tl-step">
              <div className="num">PHASE {s.n}</div>
              <div className="ico">{s.ic}</div>
              <h4>{s.t}</h4>
              <p>{s.d}</p>
              <div className="tools">{s.tools.map(t => <span key={t} className="tag">{t}</span>)}</div>
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
  // Columns of feature_store_enriched.parquet. p = external data, which
  // covers 2019–2023 only (the weather and Sharks archives end there).
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
            <p className="lede" style={{ maxWidth:'46ch' }}>Monthly origin-destination ridership from BART's public ridership reports (bart.gov), joined with Open-Meteo weather and a San Jose Sharks home-game schedule (both 2019–2023 only; no ranked model uses them). Splits are strictly temporal — never random — so the test set genuinely simulates deployment six months ahead.</p>
          </div></Reveal>
        </div>
        <div className="ds-grid">
          <Reveal className="card ds-card" style={{ gridColumn:'1 / -1' }}>
            <h3>Temporal splits <span className="text-muted mono" style={{ fontSize: 12, fontWeight:400 }}>· n = 2,400 station-months</span></h3>
            <div className="flex flex-col gap-md">
              {splits.map(s => (
                <div key={s.nm} className="bar-row">
                  <span className="nm">{s.nm}</span>
                  <span className="bar"><i style={{ '--w': s.w }} /></span>
                  <span className="v">{s.v} mo</span>
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
            <span className="mono" style={{ color:'var(--ink)' }}>●</span> external data, available for 2019–2023 only. Lags and rolling windows count calendar months; a lag that lands in 2020–21 is empty; a rolling window uses only the months in it that have data, and is empty when too few do. No ranked model reads any of these columns, so their influence on the forecasts has not been measured.
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
   here, and only shown under the split-conformal label. */
const BAND_FIT_WINDOW = 'Jan–Jun 2025';
const bandKind = records => {
  const labels = [...new Set((Array.isArray(records) ? records : []).map(r =>
    r && typeof r.interval_method === 'string' && r.interval_method ? r.interval_method : null))];
  const label = labels.length === 1 ? labels[0] : null;
  const raw = label && /^raw: (.+)$/.exec(label);
  return {
    label,
    conformal: !!label && /^split-conformal \S+, fit on validation$/.test(label),
    rawReason: raw ? raw[1] : null,
    labelled: labels.some(l => l !== null),
  };
};

/* ── Results ───────────────────────────────────────────────────── */
const Results = () => {
  const [chart, setChart] = useState('roc');
  // Best-model tile is derived from the same file the WAPE chart and the
  // Benchmarks table read, so its model name, WAPE and model count cannot drift.
  const [cmp, setCmp] = React.useState(null);
  React.useEffect(() => {
    fetch('data/model_comparison.json').then(r => r.json()).catch(() => []).then(setCmp);
  }, []);
  const cmpRows = Array.isArray(cmp) ? cmp.filter(r => r.WAPE_pct != null) : [];
  const bestRow = cmpRows.length ? cmpRows.reduce((a, b) => (b.WAPE_pct < a.WAPE_pct ? b : a)) : null;
  // The Intervals chart (charts.jsx Calibration) draws forecasts.json's
  // P10/P90; its subtitle names that band. Loading, an unreadable file, an
  // unlabelled (older) export or mixed labels keep the plain subtitle.
  const [fcRecords, setFcRecords] = React.useState(null);
  React.useEffect(() => {
    fetch('data/forecasts.json').then(r => r.json()).catch(() => []).then(setFcRecords);
  }, []);
  const chartBand = bandKind(fcRecords);
  const chartBandNote = chartBand.conformal
    ? ` · P10–P90 range set from the model's errors on ${BAND_FIT_WINDOW}, not a validated 80% interval`
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
            <p className="lede" style={{ maxWidth:'46ch' }}>SARIMA reaches 3.2% WAPE on a Jul–Dec 2025 holdout never used for model selection, ahead of Prophet at 5.8% and a seasonal-naïve baseline at 10.8%. Prediction intervals are not yet calibrated — see the note below.</p>
          </div></Reveal>
        </div>
        <div className="results-grid">
          <Reveal className="card chart-card">
            <div className="chart-head">
              <div>
                <h3>{chart === 'roc' ? 'WAPE by model — test set' : 'Forecast intervals — Embarcadero'}</h3>
                <p>{chart === 'roc' ? 'Jul–Dec 2025 test split · 300 station-months · lower WAPE is better' : `P10 / P50 / P90 Chronos-1 zero-shot forecast with actual riders${chartBandNote} · Embarcadero (highest-volume BART station)`}</p>
              </div>
              <div className="chip-grp">
                <button className={chart==='roc'?'on':''} onClick={()=>setChart('roc')}>WAPE</button>
                <button className={chart==='cal'?'on':''} onClick={()=>setChart('cal')}>Intervals</button>
              </div>
            </div>
            <div>{chart === 'roc' ? <ROCCurve /> : <Calibration />}</div>
          </Reveal>
          <Reveal delay="1" className="card chart-card">
            <div className="chart-head">
              <div>
                <h3>Forecast error bands</h3>
                <p>Station-months · test period Jul–Dec 2025 · 50 BART stations</p>
              </div>
            </div>
            <div className="cm">
              <div className="cm-cell tp"><div className="v">{bestRow ? bestRow.WAPE_pct.toFixed(1) + '%' : '—'}</div><div className="l">WAPE · {bestRow ? bestRow.model : 'best model'}</div><div className="text-muted" style={{ fontSize:11 }}>{bestRow ? `best of ${cmpRows.length} models` : 'loading…'}</div></div>
              <div className="cm-cell tn"><div className="v">3.1k</div><div className="l">MAE (riders/mo)</div><div className="text-muted" style={{ fontSize:11 }}>vs 5.5k Prophet</div></div>
              <div className="cm-cell fp"><div className="v">P10/P90</div><div className="l">not calibrated</div><div className="text-muted" style={{ fontSize:11 }}>73–97% vs nominal 80%</div></div>
              <div className="cm-cell fn"><div className="v">50 sta.</div><div className="l">all BART stations</div><div className="text-muted" style={{ fontSize:11 }}>no station excluded</div></div>
            </div>
            <div className="text-muted" style={{ fontSize: 13 }}>
              SARIMA airline (0,1,1)(0,1,1,12): WAPE 3.21% · MAE 3,086 riders/month · Jul–Dec 2025 holdout · 300 station-months
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
    { icon: '🗺', title: 'Real Google Maps', desc: '41 BART and 39 VTA stations plotted at true lat/lng.' },
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
            <p className="lede" style={{ maxWidth:'52ch' }}>
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
              href="transit-demo.html"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display:'inline-flex', alignItems:'center', gap:8,
                padding:'12px 24px', borderRadius:10, background:'var(--primary)',
                color:'#fff', fontWeight:600, fontSize:15, textDecoration:'none',
                fontFamily:'var(--display)',
              }}>
              Open Interactive Map ↗
            </a>
            <span style={{ fontSize:13, color:'var(--ink-muted)' }}>
              Opens in a new tab · BART + VTA · no install required
            </span>
          </div>
        </Reveal>
      </div>
    </section>
  );
};

/* ── Benchmarks + Recommendations ──────────────────────────────── */
const Benchmarks = () => {
  const [cmpData, setCmpData] = React.useState(null);
  React.useEffect(() => {
    fetch('data/model_comparison.json').then(r => r.json()).catch(() => []).then(setCmpData);
  }, []);

  const fmtN = n => n >= 1e6 ? (n/1e6).toFixed(2)+'M' : n >= 1e3 ? (n/1e3).toFixed(0)+'k' : String(Math.round(n));

  const MODEL_LABELS = {
    'SARIMA': 'SARIMA airline (0,1,1)(0,1,1,12)',
    'Prophet': 'Prophet (per-station)',
    'SeasonalNaive': 'Seasonal naive',
  };

  const bestWAPE = cmpData
    ? Math.min(...cmpData.map(r => r.WAPE_pct).filter(v => v != null))
    : null;

  const dataRows = cmpData ? [
    ...cmpData.map(r => ({
      m: MODEL_LABELS[r.model] || r.model,
      wape: r.WAPE_pct != null ? r.WAPE_pct.toFixed(1)+'%' : '—',
      mape: r.MAPE_pct != null ? r.MAPE_pct.toFixed(1)+'%' : '—',
      mae:  r.MAE  != null ? fmtN(r.MAE) : '—',
      relW: r.WAPE_pct,
      best: r.WAPE_pct != null && r.WAPE_pct === bestWAPE,
    })),
    { m:'AutoETS (AutoGluon)', wape:'—', mape:'—', mae:'—', relW:null, note:'Not benchmarked — autogluon.timeseries unavailable on this Python' },
  ] : [];

  const recs = [
    { n:'01', t:'Extend event and weather data through the forecast window.', d:"The only event data ingested is a Sharks home-game schedule that ends in 2023 (the pipeline has no Ticketmaster key), and no ranked model reads it. Extending the event and weather archives through the forecast window, then fitting a model that accepts covariates, is what would let surge effects be measured at all, let alone flagged ahead of time.", who:'Operations Control' },
    { n:'02', t:'Fine-tune Chronos per station cluster.', d:'Zero-shot Chronos-1 (chronos-t5-small) scores 9.7% WAPE here — ahead of seasonal-naïve at 10.8%, behind both classical baselines. It also runs univariate, since the pipeline cannot pass covariates to this checkpoint. Fixing that, then fine-tuning per station cluster, is the path worth testing.', who:'Data / ML' },
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
              <p className="lede" style={{ maxWidth:'46ch' }}>All models evaluated on the same temporal split (Jul–Dec 2025, 300 station-months) — a holdout not used for model selection. Lower WAPE and MAE is better. SARIMA reaches 3.2% WAPE, ahead of Prophet at 5.8%.</p>
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
            <p className="lede" style={{ maxWidth:'46ch' }}>Four views of the feature store at its own grain, one row per station per month: the 2019 and 2022–2025 levels, seasonality, the station ranking and the gaps. Each caption is written by the EDA notebook (<code style={{ overflowWrap:'anywhere' }}>transit_eda/notebooks/eda_complete.ipynb</code>) from numbers it prints.</p>
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
            Senior in Computer Science at San José State University, graduating Spring 2026.
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
          { lbl:'Repo · GitHub', t:'Source code', d:'Pipeline scripts, the benchmark runner (SARIMA, Prophet, seasonal naive, Chronos-1 zero-shot) and this website. AutoGluon fine-tuning code is included but has never been run.', href:'https://github.com/Dhruv-cs50/transit-demand-forecasting' },
          { lbl:'Notebook', t:'Exploratory analysis', d:'Summary statistics, seasonality, missing-data and correlation plots. Its saved plots come from an earlier version of the feature store and are due to be regenerated.', href:'https://github.com/Dhruv-cs50/transit-demand-forecasting/blob/main/transit_eda/notebooks/eda_complete.ipynb' },
          { lbl:'BART OD ridership', t:'Dataset · BART OD', d:'Public BART origin-destination monthly ridership data from BART.gov.', href:'https://www.bart.gov/about/reports/ridership' },
          { lbl:'Open-Meteo weather', t:'Dataset · Open-Meteo', d:'Free historical weather API. The feature store aggregates it to months for 2019–2023; no ranked model uses it yet.', href:'https://open-meteo.com' },
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
  const [forecasts, setForecasts] = React.useState([]);
  const [actuals, setActuals]     = React.useState([]);
  const [meta, setMeta]           = React.useState([]);
  const [station, setStation]     = React.useState('EM');
  const [loading, setLoading]     = React.useState(true);
  const [comparison, setComparison] = React.useState([]);
  const [liveData, setLiveData]   = React.useState(null);
  const [liveFetching, setLiveFetching] = React.useState(false);
  const [liveError, setLiveError] = React.useState(null);

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

  React.useEffect(() => {
    Promise.all([
      fetch('data/forecasts.json').then(r => r.json()).catch(() => []),
      fetch('data/ridership_actuals.json').then(r => r.json()).catch(() => []),
      fetch('data/model_comparison.json').then(r => r.json()).catch(() => []),
      fetch('data/stations_meta.json').then(r => r.json()).catch(() => []),
    ]).then(([fc, ac, cmp, sm]) => {
      setForecasts(Array.isArray(fc) ? fc : []);
      setActuals(Array.isArray(ac) ? ac : []);
      setComparison(Array.isArray(cmp) ? cmp : []);
      setMeta(Array.isArray(sm) ? sm.filter(m => m && m.bart_id) : []);
      setLoading(false);
    });
  }, []);

  // Each live request gets a sequence number; changing station bumps it, so a
  // response (or error) for a previously selected station is dropped.
  const liveReq = React.useRef(0);
  const fetchLive = () => {
    const reqId = ++liveReq.current;
    setLiveFetching(true);
    setLiveError(null);
    fetch(`${API_BASE}/forecast`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ station_id: station, horizon_hours: 6 }),
      signal: AbortSignal.timeout(15000),
    })
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || 'API error')))
      .then(data => { if (reqId !== liveReq.current) return; setLiveData(data); setLiveFetching(false); })
      .catch(err => { if (reqId !== liveReq.current) return; setLiveError(String(err)); setLiveFetching(false); });
  };

  React.useEffect(() => {
    liveReq.current++;
    setLiveData(null); setLiveError(null); setLiveFetching(false);
  }, [station]);

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

  // The forecast months named in the copy come from forecasts.json (min/max
  // month over all records); "through" is the month before the first one.
  const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const parseYM = ym => {
    const m = /^(\d{4})-(0[1-9]|1[0-2])/.exec(typeof ym === 'string' ? ym : '');
    return m ? { y: +m[1], m: +m[2] } : null;
  };
  const fcMonths = forecasts.map(r => r && parseYM(r.month)).filter(Boolean)
    .sort((a, b) => a.y - b.y || a.m - b.m);
  const fcFirst = fcMonths[0];
  const fcLast = fcMonths[fcMonths.length - 1];
  const fcRange = !fcFirst ? null
    : fcFirst.y !== fcLast.y ? `${MON[fcFirst.m-1]} ${fcFirst.y}–${MON[fcLast.m-1]} ${fcLast.y}`
    : fcFirst.m !== fcLast.m ? `${MON[fcFirst.m-1]}–${MON[fcLast.m-1]} ${fcFirst.y}`
    : `${MON[fcFirst.m-1]} ${fcFirst.y}`;
  const fcThrough = !fcFirst ? null
    : fcFirst.m === 1 ? `Dec ${fcFirst.y - 1}` : `${MON[fcFirst.m-2]} ${fcFirst.y}`;
  const fcCount = new Set(fcMonths.map(p => p.y * 12 + p.m)).size;

  // Which band P10/P90 is (bandKind, above Results). A coverage figure is
  // shown only when the Chronos leaderboard row carries the same label, so
  // the number always scores the band on screen; it scores the forecast
  // months (fcRange), and the comparison word follows the number. Without
  // it, a split-conformal band still gets the "not validated" caveat.
  const band = bandKind(forecasts);
  const bandRow = band.label && comparison.find(r =>
    r && /^Chronos/.test(r.model || '') && r.Interval_method === band.label
    && typeof r.Coverage_pct === 'number' && isFinite(r.Coverage_pct));
  const bandCov = bandRow ? Math.round(bandRow.Coverage_pct * 10) / 10 : null;
  const bandCoverage = bandRow
    ? ` Over ${fcRange} it held the actual ridership in ${bandCov.toFixed(1)}% of station-months, `
      + `${bandCov < 80 ? 'short of' : bandCov > 80 ? 'above' : 'matching'} the 80% it aims for.`
    : '';
  const bandNote = band.conformal
    ? `The P10–P90 range is set from the model's errors on ${BAND_FIT_WINDOW}`
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
              : fcCount ? `Model outputs — 50 stations, ${fcCount}-month forecast.`
              : 'Model outputs — 50 stations, no forecasts published.'}</h2>
            <p className="lede" style={{ maxWidth:'52ch' }}>
              {loading
                ? 'Loading the static export (forecasts.json) of Chronos-1 zero-shot (chronos-t5-small) forecasts…'
                : fcRange
                  ? `Static export (forecasts.json) of Chronos-1 zero-shot (chronos-t5-small) P10/P50/P90 monthly ridership for ${fcRange}, forecast from data through ${fcThrough}: the predictions scored in the model comparison below. ${bandNote}`
                  : 'No forecasts are published in the static export (forecasts.json), so the table shows actual ridership only.'}
              {' '}Actuals are BART monthly Total Trips boardings per entry station, 2019 and 2022–2025.
              The button below requests a forecast from the Cloud Run API.
            </p>
          </div></Reveal>
        </div>

        <Reveal className="card" style={{ padding:'24px', marginBottom:24 }}>
          <div style={{ display:'flex', gap:12, flexWrap:'wrap', marginBottom:20, alignItems:'center' }}>
            {KEY_STATIONS.map(s => (
              <button key={s.id}
                onClick={() => setStation(s.id)}
                style={{
                  padding:'6px 14px', borderRadius:6, border:'1.5px solid var(--line)',
                  background: station===s.id ? 'var(--primary)' : 'transparent',
                  color: station===s.id ? '#fff' : 'var(--ink)',
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
                color:'#fff', cursor: liveFetching ? 'default' : 'pointer', fontSize:13, fontWeight:600,
                opacity: liveFetching ? 0.7 : 1,
              }}>
              {liveFetching ? 'Calling API…' : '⚡ Fetch Live from API'}
            </button>
          </div>

          {liveError && (
            <div style={{ marginBottom:16, padding:'10px 14px', borderRadius:8, background:'rgba(238,108,77,0.12)', color:'var(--accent)', fontSize:13 }}>
              API error: {liveError}
            </div>
          )}
          {liveData && (
            <div style={{ marginBottom:20, padding:'14px 16px', borderRadius:8, background:'rgba(42,47,143,0.07)', border:'1px solid rgba(42,47,143,0.2)' }}>
              <div style={{ fontSize:12, color:'var(--primary)', fontWeight:700, marginBottom:8, letterSpacing:'.04em', textTransform:'uppercase' }}>
                ⚡ Live Cloud Run Response — {nameFor(station)}
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
                    <th style={{ textAlign:'right', padding:'6px 10px', color:'var(--accent)' }}>Chronos P10</th>
                    <th style={{ textAlign:'right', padding:'6px 10px', color:'var(--primary)' }}>Chronos P50</th>
                    <th style={{ textAlign:'right', padding:'6px 10px', color:'var(--accent)' }}>Chronos P90</th>
                    <th style={{ padding:'6px 10px' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map(row => row.fc ? (
                    <tr key={row.month} style={{ borderBottom:'1px solid var(--line)', background:'rgba(42,47,143,0.04)' }}>
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
              <div style={{ marginTop:12, fontSize:12, color:'var(--ink-muted)' }}>
                {fcRange
                  ? `▶ Forecast months (${fcRange}, forecast from data through ${fcThrough}) shown in blue, each with its actual riders beside P10/P50/P90. Bars sized by ridership volume: blue = actual, coral = P50.`
                  : 'No forecasts are published, so the table shows the last 12 actual months. Bars sized by ridership volume.'}
                {' '}Actuals are BART monthly Total Trips boardings per entry station (ridership_actuals.json: 2019 and 2022–2025).
              </div>
            </div>
          )}
        </Reveal>

        {comparison.length > 0 && (
          <Reveal className="card" style={{ padding:'24px' }}>
            <h3 style={{ fontSize:16, marginBottom:16 }}>Model comparison — Jul–Dec 2025 test split, 50 stations</h3>
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
                  <tr key={i} style={{ borderBottom:'1px solid var(--line)', background: i===0 ? 'rgba(42,47,143,0.04)' : 'transparent' }}>
                    <td style={{ padding:'6px 10px', fontWeight:600 }}>{r.model}</td>
                    <td style={{ textAlign:'right', padding:'6px 10px', fontFamily:'var(--mono)' }}>{r.MAPE_pct != null ? r.MAPE_pct.toFixed(1)+'%' : '—'}</td>
                    <td style={{ textAlign:'right', padding:'6px 10px', fontFamily:'var(--mono)' }}>{r.WAPE_pct != null ? r.WAPE_pct.toFixed(1)+'%' : '—'}</td>
                    <td style={{ textAlign:'right', padding:'6px 10px', fontFamily:'var(--mono)' }}>{r.MAE != null ? fmt(r.MAE) : '—'}</td>
                    <td style={{ textAlign:'right', padding:'6px 10px', color:'var(--ink-muted)' }}>{r.n_predictions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Reveal>
        )}
      </div>
    </section>
  );
};

Object.assign(window, { Nav, Hero, AtAGlance, Method, Dataset, Results, Demo, Benchmarks, EDAViz, About, Footer, BARTForecasts });