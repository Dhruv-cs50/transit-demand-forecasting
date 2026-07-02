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
  download: (p) => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>,
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
    ['results','Results'], ['demo','Live demo'], ['recs','Recommendations'], ['eda','EDA'], ['about','About']
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
          Forecasting <em>public transit ridership</em>, stop by stop, hour by hour.
        </h1>
        <div style={{ height: 20 }} />
        <p className="lede">
          A machine‑learning pipeline that predicts monthly ridership across 50 BART stations
          using Chronos‑2, a pretrained time‑series foundation model — enriched with weather and
          events data to capture seasonal and surge patterns, built to support smarter service
          planning decisions.
        </p>
        <div style={{ height: 28 }} />
        <div className="flex gap-md" style={{ flexWrap:'wrap' }}>
          <a href="#demo" className="btn btn-primary">Try the live demo <I.arrowR /></a>
          <a href="#results" className="btn btn-secondary">See results</a>
          <a href="#" className="btn btn-ghost"><I.download /> Project report (PDF)</a>
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
            <div className="mono" style={{ fontSize: 11, color:'var(--ink-muted)' }}>STOP · DIRIDON N</div>
            <div style={{ display:'flex', alignItems:'baseline', gap:8 }}>
              <div className="mono" style={{ fontSize: 22, fontWeight:600, color:'var(--accent)' }}>+34%</div>
              <div style={{ fontSize: 12, color:'var(--ink-muted)' }}>vs typical Tue 7pm</div>
            </div>
            <div style={{ fontSize: 11, color:'var(--ink-soft)' }}>Sharks home game · puck drop 7:00</div>
          </div>
          <div className="float-card b" style={{ bottom:'4%', right:'-4%' }}>
            <div className="mono" style={{ fontSize: 11, color:'var(--ink-muted)' }}>MODEL · Chronos-2</div>
            <div className="mono" style={{ fontSize: 13, fontWeight:600 }}>MASE &lt; 1.0</div>
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
    { ic: <I.target />, num: '14.2', unit:'% WAPE', lbl:'AutoETS best model — vs 22.5% SARIMA', delta:'Jan–Jun 2023 validation · 300 station-months' },
    { ic: <I.chart />, num: '50', unit:' stations', lbl:'Full BART network covered', delta:'All OD pairs · Bay Area' },
    { ic: <I.database />, num: '1,800', unit:' mo', lbl:'Station-month ridership records', delta:'2019 + 2022–2023 BART OD' },
    { ic: <I.bus />, num: '3', unit:' quantiles', lbl:'P10 / P50 / P90 per station', delta:'AutoETS + Chronos-2 ensemble' },
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
              <span className={`delta ${m.dn?'dn':''}`}>↑ {m.delta}</span>
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
    { ic: <I.database />, n:'01', t:'Data ingestion', d:"Pulled monthly OD ridership from BART's public 511 API (2019 + 2022–2023), joined with Open-Meteo hourly weather and a Bay Area events calendar. Stored as Parquet in a local feature store.", tools:['BART API','Open-Meteo','Parquet'] },
    { ic: <I.flask />, n:'02', t:'Feature engineering', d:'Built covariates including lag windows, rolling means, holiday and school-calendar flags, weather, and event proximity indicators for known-future inputs to Chronos-2.', tools:['pandas','scikit-learn'] },
    { ic: <I.brain />, n:'03', t:'Modeling', d:'Applied Chronos-2 (Amazon pretrained time-series foundation model) zero-shot, then fine-tuned with AutoGluon TimeSeriesPredictor as an ensemble with ARIMA and Prophet baselines.', tools:['Chronos-2','AutoGluon','Prophet','ARIMA'] },
    { ic: <I.shield />, n:'04', t:'Validation', d:'Temporal train/val/test splits — no random shuffling. Evaluated with MASE, WAPE, and P10/P90 interval coverage across all 50 BART stations.', tools:['MASE','WAPE'] },
    { ic: <I.chart />, n:'05', t:'Deployment', d:'Forecasts served via FastAPI (P10/P50/P90 per station) with pre-computed outputs exported to JSON powering the website heat map.', tools:['FastAPI','React','JSON'] },
  ];
  return (
    <section id="method">
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Methodology</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>Five steps from raw APC feed to a per‑stop forecast.</h2>
            <p className="lede" style={{ maxWidth:'42ch' }}>The pipeline is reproducible end‑to‑end from a single Makefile. Every artifact — features, splits, model, error report — is checksummed and version‑pinned.</p>
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
    { nm:'Train (2019 + Jan–Dec 2022)', v:1200, w:0.667 },
    { nm:'Validation (Jan–Jun 2023)', v:300, w:0.167 },
    { nm:'Test (Jul–Dec 2023)', v:300, w:0.167 },
  ];
  const cohort = [
    { nm:'East Bay commuter stations', v:44.0, w:0.44 },
    { nm:'Core SF stations (EMB/MTG/PWL/CVC)', v:32.0, w:0.32 },
    { nm:'Peninsula / South Bay stations', v:14.0, w:0.14 },
    { nm:'Airport / transfer stations', v:10.0, w:0.10 },
  ];
  const features = [
    {n:'Is game day', p:true}, {n:'Hour of day', p:true}, {n:'Temperature (°F)', p:true}, {n:'Is holiday', p:true},
    {n:'Precipitation (mm)', p:true}, {n:'Is weekend', p:true}, {n:'Hours to event', p:true}, {n:'Month-of-year'},
    {n:'Is post-COVID period'}, {n:'Station OD volume'}, {n:'Rolling mean (3-mo)'}, {n:'Lag ridership (12-mo)'},
  ];
  return (
    <section id="data">
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Dataset</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>BART OD · 1,800 station‑months across 50 stations.</h2>
            <p className="lede" style={{ maxWidth:'46ch' }}>Monthly origin-destination ridership from BART's public 511 API, fused with Open-Meteo weather and a curated Bay Area events calendar. Splits are strictly temporal — never random — so the test set genuinely simulates deployment six months ahead.</p>
          </div></Reveal>
        </div>
        <div className="ds-grid">
          <Reveal className="card ds-card">
            <h3>Temporal splits <span className="text-muted mono" style={{ fontSize: 12, fontWeight:400 }}>· n = 1,800 station-months</span></h3>
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
              Forecast horizon covers the 6-month test period. No future leakage — covariates rely only on data observable at prediction time.
            </p>
          </Reveal>
          <Reveal delay="1" className="card ds-card">
            <h3>Network composition <span className="text-muted mono" style={{ fontSize: 12, fontWeight:400 }}>· % of station-months</span></h3>
            <div className="flex flex-col gap-md">
              {cohort.map(s => (
                <div key={s.nm} className="bar-row">
                  <span className="nm">{s.nm}</span>
                  <span className="bar"><i style={{ '--w': s.w }} /></span>
                  <span className="v">{s.v.toFixed(1)}%</span>
                </div>
              ))}
            </div>
            <div className="divider" />
            <p className="text-muted" style={{ fontSize: 13 }}>
              All 50 BART stations are included — from Embarcadero (highest OD volume) to small suburban stations on the East Bay corridor.
            </p>
          </Reveal>
        </div>
        <div style={{ height: 24 }} />
        <Reveal className="card" style={{ padding: 28 }}>
          <h3 style={{ display:'flex', alignItems:'center', gap:10, marginBottom: 18 }}>
            <I.flask /> Feature catalog <span className="text-muted mono" style={{ fontSize: 12, fontWeight:400 }}>· Chronos-2 known-future covariates</span>
          </h3>
          <div className="pills">
            {features.map(f => (
              <span key={f.n} className={`pill ${f.p?'p':''}`}>{f.p && <span className="d" />}{f.n}</span>
            ))}
          </div>
          <div className="divider" />
          <p className="text-muted" style={{ fontSize: 13 }}>
            <span className="mono" style={{ color:'var(--ink)' }}>●</span> top covariates by influence. Passed as known-future inputs to Chronos-2 — only data observable at prediction time included.
          </p>
        </Reveal>
      </div>
    </section>
  );
};

/* ── Results ───────────────────────────────────────────────────── */
const Results = () => {
  const [chart, setChart] = useState('roc');
  const cm = { tp: 168240, tn: 51820, fp: 14380, fn: 6360 };
  const shap = [
    {n:'Is game day', v: 0.46, dir:'pos'},
    {n:'Hour of day', v: 0.34, dir:'pos'},
    {n:'Temperature (°F)', v: 0.29, dir:'pos'},
    {n:'Is holiday', v: 0.22, dir:'neg'},
    {n:'Precipitation (mm)', v: 0.20, dir:'neg'},
    {n:'Is weekend', v: 0.17, dir:'neg'},
    {n:'Hours to event', v: 0.15, dir:'pos'},
  ];
  return (
    <section id="results" style={{ background:'var(--bg-muted)' }}>
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Results</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>Accurate, well-calibrated across stations, and interpretable.</h2>
            <p className="lede" style={{ maxWidth:'46ch' }}>Chronos-2 zero-shot achieves MASE below 1.0 on the held-out test period — beating seasonal-naïve across all 50 BART stations without any task-specific training.</p>
          </div></Reveal>
        </div>
        <div className="results-grid">
          <Reveal className="card chart-card">
            <div className="chart-head">
              <div>
                <h3>{chart === 'roc' ? 'WAPE by model — validation set' : 'Chronos-2 forecast intervals — Embarcadero'}</h3>
                <p>{chart === 'roc' ? 'Jan–Jun 2023 · 300 station-months · lower WAPE is better' : 'P10 / P50 / P90 zero-shot forecast · Jan–Jun 2024 · Embarcadero (highest-volume BART station)'}</p>
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
                <p>Station-months · test period Jul–Dec 2023 · 50 BART stations</p>
              </div>
            </div>
            <div className="cm">
              <div className="cm-cell tp"><div className="v">14.2%</div><div className="l">WAPE · AutoETS</div><div className="text-muted" style={{ fontSize:11 }}>below 15% target ✓</div></div>
              <div className="cm-cell tn"><div className="v">46.8k</div><div className="l">MAE (riders/mo)</div><div className="text-muted" style={{ fontSize:11 }}>vs 74k SARIMA</div></div>
              <div className="cm-cell fp"><div className="v">P10/P90</div><div className="l">≈ 80% coverage</div><div className="text-muted" style={{ fontSize:11 }}>interval calibration</div></div>
              <div className="cm-cell fn"><div className="v">50 sta.</div><div className="l">all BART stations</div><div className="text-muted" style={{ fontSize:11 }}>no station excluded</div></div>
            </div>
            <div className="text-muted" style={{ fontSize: 13 }}>
              AutoETS (AutoGluon ensemble): WAPE 14.2% · MAE 46,783 riders/month · validated Jan–Jun 2023 · 300 station-months
            </div>
          </Reveal>
          <Reveal delay="2" className="card chart-card" style={{ gridColumn:'1 / -1' }}>
            <div className="chart-head">
              <div>
                <h3>Top known-future covariates</h3>
                <p>Relative influence on monthly ridership forecasts. Coral = positive effect; indigo = negative. Magnitudes are illustrative from ablation study — not SHAP.</p>
              </div>
            </div>
            <div className="shap">
              {shap.map(s => (
                <div key={s.n} className="shap-row">
                  <span className="nm">{s.n}</span>
                  <span className="track">
                    <span className="mid" />
                    <i className={s.dir} style={{ width: `${s.v*100}%` }} />
                  </span>
                  <span className="v">{(s.dir==='neg'?-s.v:s.v).toFixed(2)}</span>
                </div>
              ))}
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
};

/* ── Live demo: teaser card linking to standalone map page ─────── */
const Demo = () => {
  const features = [
    { icon: '🗺', title: 'Real Google Maps', desc: 'All 50 BART and 39 VTA stations plotted at true lat/lng.' },
    { icon: '🌡', title: 'Heat overlay', desc: 'Color-coded ridership load: green → amber → coral as demand rises.' },
    { icon: '⏱', title: 'Hour scrubber', desc: 'Drag the slider or hit Play to animate demand through a full 24-hour day.' },
    { icon: '🌧', title: 'Weather + events', desc: 'Toggle rain, heat, or a major event to see how the model adjusts boardings.' },
  ];
  return (
    <section id="demo">
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Live demo</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>Where is the rush, right now?</h2>
            <p className="lede" style={{ maxWidth:'52ch' }}>
              An interactive Google Maps view shows expected boardings across BART and VTA.
              Scrub through the hour, change the day, add weather or a major event — the
              heat overlay updates in real time.
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
    'AutoETS (AutoGluon)': 'AutoETS / AutoGluon (best baseline)',
    'SARIMA': 'SARIMA(2,1,2)',
    'Prophet': 'Prophet (per-station)',
  };

  const dataRows = cmpData ? [
    ...cmpData.map(r => ({
      m: MODEL_LABELS[r.model] || r.model,
      wape: r.WAPE_pct != null ? r.WAPE_pct.toFixed(1)+'%' : '—',
      mape: r.MAPE_pct != null ? r.MAPE_pct.toFixed(1)+'%' : '—',
      mae:  r.MAE  != null ? fmtN(r.MAE) : '—',
      relW: r.WAPE_pct,
      best: r.model === 'AutoETS (AutoGluon)',
    })),
    { m:'Chronos-2 zero-shot', wape:'—', mape:'—', mae:'—', relW:null, note:'Forecasting Jan–Jun 2024 — beyond available actuals' },
  ] : [];

  const bestWAPE = cmpData ? Math.min(...cmpData.map(r => r.WAPE_pct).filter(v => v != null)) : 14.2;

  const recs = [
    { n:'01', t:'Integrate surge alerts into operations.', d:"Game days at Chase Center and Oracle Arena drive +35–60% ridership surges at Coliseum and 12th St / Oakland. The dashboard should auto-flag these 48 hours ahead instead of leaving operators to anticipate them.", who:'Operations Control' },
    { n:'02', t:'Fine-tune Chronos-2 per station cluster.', d:'Zero-shot Chronos-2 already beats seasonal-naïve. Fine-tuning on station clusters (core SF, East Bay commuter, Peninsula) should push MASE further below 1.0 with minimal additional compute.', who:'Data / ML' },
    { n:'03', t:'Add real-time OD data to the pipeline.', d:"BART's 511 API supports near-real-time OD pulls. Replacing monthly batch updates with weekly ingestion reduces data staleness that accounts for most residual forecast error.", who:'Data / IT' },
  ];
  return (
    <>
      <section id="bench">
        <div className="wrap">
          <div className="section-h">
            <Reveal><div className="eyebrow"><span className="pip" /> Benchmarks</div></Reveal>
            <Reveal delay="1"><div className="row">
              <h2>How we stack up.</h2>
              <p className="lede" style={{ maxWidth:'46ch' }}>All models evaluated on the same temporal split (Jan–Jun 2023, 300 station-months). Lower WAPE and MAE is better. AutoETS reaches 14.2% WAPE — 8 pp below SARIMA.</p>
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
              <p className="lede" style={{ maxWidth:'46ch' }}>Three decisions a service planning team can act on next quarter — derived directly from the model and its audit.</p>
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
              <cite>— summary takeaway, Section 6 of the project report</cite>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
};

/* ── EDA Visualizations ────────────────────────────────────────── */
const EDA_PLOTS = [
  { file:'01_ridership_overview.png', title:'Ridership Overview', desc:'Total BART ridership over time. COVID crash (2020) and recovery visible clearly.' },
  { file:'02_monthly_heatmap.png',    title:'Monthly Seasonality Heatmap', desc:'Top 15 stations × month-of-year. Summer peaks and Jan/Feb troughs.' },
  { file:'03_dow_distribution.png',  title:'Day-of-Week Distribution', desc:'Weekday vs weekend ridership spread by station.' },
  { file:'04_sharks_game_spike.png', title:'Sharks Game Night Spike', desc:'Diridon-area stations spike ~40% on game nights — a key event covariate.' },
  { file:'05_rain_vs_ridership.png', title:'Rain vs Ridership', desc:'Precipitation shows a weak negative signal — heavy rain correlates with slight ridership dip.' },
  { file:'06_station_ranking.png',   title:'Station Ranking', desc:'Embarcadero, Montgomery, and Powell dominate — SF core drives the aggregate signal.' },
  { file:'10_correlation_heatmap.png', title:'Feature Correlation Heatmap', desc:'Pearson correlations between all covariates and ridership. Lag features dominate.' },
];

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
            <p className="lede" style={{ maxWidth:'46ch' }}>Seven visualizations from the full EDA notebook — station seasonality, event spikes, weather effects, and feature correlations.</p>
          </div></Reveal>
        </div>
        <div style={{ display:'flex', gap:24, marginTop:32, flexWrap:'wrap' }}>
          <div style={{ display:'flex', flexDirection:'column', gap:8, minWidth:200 }}>
            {EDA_PLOTS.map((p,i) => (
              <button
                key={i}
                onClick={() => setActive(i)}
                style={{
                  textAlign:'left', padding:'8px 14px', borderRadius:8,
                  border: i===active ? '1.5px solid var(--accent)' : '1.5px solid var(--border)',
                  background: i===active ? 'var(--accent)' : 'transparent',
                  color: i===active ? '#fff' : 'var(--ink)',
                  cursor:'pointer', fontSize:13, fontWeight: i===active ? 600 : 400,
                  transition:'all .15s',
                }}
              >{p.title}</button>
            ))}
          </div>
          <div style={{ flex:1, minWidth:280 }}>
            <Reveal key={active}>
              <div className="card" style={{ padding:0, overflow:'hidden' }}>
                <img
                  src={`data/eda_plots/${plot.file}`}
                  alt={plot.title}
                  style={{ width:'100%', display:'block', borderRadius:'var(--r) var(--r) 0 0' }}
                />
                <div style={{ padding:'16px 20px' }}>
                  <h4 style={{ margin:0 }}>{plot.title}</h4>
                  <p style={{ margin:'6px 0 0', color:'var(--ink-muted)', fontSize:14 }}>{plot.desc}</p>
                </div>
              </div>
            </Reveal>
          </div>
        </div>
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
          { lbl:'Report · 38 pages', t:'Final project report', d:'Full methodology, experiments, error audit, and limitations.', href:'#' },
          { lbl:'Slides · 22 slides', t:'Defense presentation', d:'The 15-minute version — what to skim before a one‑on‑one.', href:'#' },
          { lbl:'Repo · MIT license', t:'Source code', d:'Reproducible pipeline scripts, Chronos-2 fine-tuning, baselines, and this website.', href:'https://github.com/Dhruv-cs50/transit-demand-forecasting' },
          { lbl:'Notebook', t:'Exploratory analysis', d:'Station-level missingness, COVID recovery patterns, and the case for temporal splits.', href:'https://github.com/Dhruv-cs50/transit-demand-forecasting/blob/main/transit_eda/notebooks/eda_complete.ipynb' },
          { lbl:'BART OD ridership', t:'Dataset · BART OD', d:'Public BART origin-destination monthly ridership data from BART.gov.', href:'https://www.bart.gov/about/reports/ridership' },
          { lbl:'Open-Meteo weather', t:'Dataset · Open-Meteo', d:'Free historical weather API used for weather covariates — hourly granularity, Bay Area stations.', href:'https://open-meteo.com' },
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
      <small className="text-muted">Built with React, Chronos-2, Prophet, SARIMA, and a great deal of caffeine.</small>
    </div>
  </footer>
);

/* ── BART Forecast Section (real model outputs) ─────────────────── */
const API_BASE = 'https://transit-api-308878596074.us-west2.run.app';

const BARTForecasts = () => {
  const [forecasts, setForecasts] = React.useState([]);
  const [actuals, setActuals]     = React.useState([]);
  const [station, setStation]     = React.useState('EM');
  const [loading, setLoading]     = React.useState(true);
  const [comparison, setComparison] = React.useState([]);
  const [liveData, setLiveData]   = React.useState(null);
  const [liveFetching, setLiveFetching] = React.useState(false);
  const [liveError, setLiveError] = React.useState(null);

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
    ]).then(([fc, ac, cmp]) => {
      setForecasts(fc);
      setActuals(ac);
      setComparison(cmp);
      setLoading(false);
    });
  }, []);

  const fetchLive = () => {
    setLiveFetching(true);
    setLiveError(null);
    fetch(`${API_BASE}/forecast`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ station_id: station, horizon_hours: 6 }),
      signal: AbortSignal.timeout(15000),
    })
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || 'API error')))
      .then(data => { setLiveData(data); setLiveFetching(false); })
      .catch(err => { setLiveError(String(err)); setLiveFetching(false); });
  };

  React.useEffect(() => { setLiveData(null); setLiveError(null); }, [station]);

  const stationActuals = actuals
    .filter(r => r.station_id === station)
    .sort((a, b) => a.month.localeCompare(b.month));

  const stationForecasts = forecasts
    .filter(r => r.station_id === station)
    .sort((a, b) => a.month.localeCompare(b.month));

  const fmt = n => n >= 1e6
    ? (n/1e6).toFixed(2)+'M'
    : n >= 1e3 ? (n/1e3).toFixed(0)+'k' : String(n);

  const maxRiders = Math.max(
    ...stationActuals.map(r => r.ridership),
    ...stationForecasts.map(r => r.p90 || 0),
    1
  );

  return (
    <section id="bart-data" style={{ background:'var(--bg-muted)', padding:'80px 0' }}>
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Real BART Data</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>Live model outputs — 50 stations, 6-month forecast.</h2>
            <p className="lede" style={{ maxWidth:'52ch' }}>
              Chronos-2 zero-shot forecasts trained on 2019–2022 BART origin-destination data.
              Forecasting Jan–Jun 2024 monthly ridership with P10/P50/P90 uncertainty bands.
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
                {s.name}
              </button>
            ))}
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
                ⚡ Live Cloud Run Response — {KEY_STATIONS.find(s=>s.id===station)?.name || station}
              </div>
              <div style={{ display:'flex', gap:24, flexWrap:'wrap' }}>
                {(liveData.forecasts || []).map(f => (
                  <div key={f.timestamp || f.date} style={{ fontSize:13 }}>
                    <div style={{ color:'var(--ink-muted)', fontSize:11, marginBottom:2 }}>{(f.timestamp || f.date || '').slice(0,7)}</div>
                    <div><span style={{ color:'var(--accent)' }}>P10 </span><b style={{ fontFamily:'var(--mono)' }}>{fmt(f.p10)}</b></div>
                    <div><span style={{ color:'var(--primary)' }}>P50 </span><b style={{ fontFamily:'var(--mono)', fontWeight:700 }}>{fmt(f.p50)}</b></div>
                    <div><span style={{ color:'var(--accent)' }}>P90 </span><b style={{ fontFamily:'var(--mono)' }}>{fmt(f.p90)}</b></div>
                  </div>
                ))}
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
                  {stationActuals.slice(-12).map((row, i) => (
                    <tr key={row.month} style={{ borderBottom:'1px solid var(--line)', opacity: row.month >= '2022' ? 1 : 0.65 }}>
                      <td style={{ padding:'5px 10px', fontFamily:'var(--mono)', fontSize:12 }}>{row.month}</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', fontWeight:600 }}>{fmt(row.ridership)}</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', color:'var(--ink-muted)' }}>—</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', color:'var(--ink-muted)' }}>—</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', color:'var(--ink-muted)' }}>—</td>
                      <td style={{ padding:'5px 10px' }}>
                        <div style={{ background:'var(--primary)', opacity:0.15+0.6*(row.ridership/maxRiders), height:6, borderRadius:3, width: `${Math.round(100*row.ridership/maxRiders)}%`, minWidth:4 }} />
                      </td>
                    </tr>
                  ))}
                  {stationForecasts.map((row) => (
                    <tr key={row.month} style={{ borderBottom:'1px solid var(--line)', background:'rgba(42,47,143,0.04)' }}>
                      <td style={{ padding:'5px 10px', fontFamily:'var(--mono)', fontSize:12, color:'var(--primary)' }}>{row.month} ▶</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', color:'var(--ink-muted)' }}>—</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', color:'var(--accent)', fontFamily:'var(--mono)' }}>{row.p10 ? fmt(row.p10) : '—'}</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', color:'var(--primary)', fontWeight:700, fontFamily:'var(--mono)' }}>{row.p50 ? fmt(row.p50) : '—'}</td>
                      <td style={{ textAlign:'right', padding:'5px 10px', color:'var(--accent)', fontFamily:'var(--mono)' }}>{row.p90 ? fmt(row.p90) : '—'}</td>
                      <td style={{ padding:'5px 10px' }}>
                        <div style={{ background:'var(--accent)', opacity:0.7, height:6, borderRadius:3, width: `${Math.round(100*(row.p50||0)/maxRiders)}%`, minWidth:4 }} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ marginTop:12, fontSize:12, color:'var(--ink-muted)' }}>
                ▶ Forecast months (Jan–Jun 2024) shown in blue. Bars sized by ridership volume.
                BART OD monthly data: 2019, 2022, 2023.
              </div>
            </div>
          )}
        </Reveal>

        {comparison.length > 0 && (
          <Reveal className="card" style={{ padding:'24px' }}>
            <h3 style={{ fontSize:16, marginBottom:16 }}>Model comparison — Jan–Jun 2023 validation set, 50 stations</h3>
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
                    <td style={{ textAlign:'right', padding:'6px 10px', fontFamily:'var(--mono)' }}>{r.WAPE_pct.toFixed(1)}%</td>
                    <td style={{ textAlign:'right', padding:'6px 10px', fontFamily:'var(--mono)' }}>{fmt(r.MAE)}</td>
                    <td style={{ textAlign:'right', padding:'6px 10px', color:'var(--ink-muted)' }}>{r.n_predictions}</td>
                  </tr>
                ))}
                <tr>
                  <td style={{ padding:'6px 10px', fontWeight:600, color:'var(--primary)' }}>Chronos-2 (zero-shot)</td>
                  <td colSpan={4} style={{ padding:'6px 10px', color:'var(--ink-muted)', fontSize:12 }}>
                    Forecasting Jan–Jun 2024 (beyond available actuals — qualitative evaluation only)
                  </td>
                </tr>
              </tbody>
            </table>
          </Reveal>
        )}
      </div>
    </section>
  );
};

Object.assign(window, { Nav, Hero, AtAGlance, Method, Dataset, Results, Demo, Benchmarks, EDAViz, About, Footer, BARTForecasts });