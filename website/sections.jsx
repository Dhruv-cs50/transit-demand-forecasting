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
    ['results','Results'], ['demo','Live demo'], ['recs','Recommendations'], ['about','About']
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
          A machine‑learning pipeline that predicts hourly boardings across 3,184 VTA bus and
          light‑rail stops using two years of automatic passenger counter data, weather, and
          calendar context — built to support smarter service planning, not just better dashboards.
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
          <span className="meta-chip"><b>Advisor</b> · Dr. Genya Ishigaki</span>
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
            <div className="mono" style={{ fontSize: 11, color:'var(--ink-muted)' }}>MODEL · v2.4</div>
            <div className="mono" style={{ fontSize: 13, fontWeight:600 }}>MAPE 11.8%</div>
            <div style={{ fontSize: 11, color:'var(--ink-soft)' }}>24h horizon · n=2.1M obs</div>
          </div>
        </div>
      </Reveal>
    </div>
  </section>
);

/* ── At-a-glance metrics ───────────────────────────────────────── */
const AtAGlance = () => {
  const items = [
    { ic: <I.target />, num: '11.8', unit:'% MAPE', lbl:'24-hour-ahead boarding forecast', delta:'−37% vs seasonal-naïve' },
    { ic: <I.chart />, num: '0.93', unit:'R²', lbl:'On held-out 2024 test period', delta:'+0.18 vs ARIMA baseline' },
    { ic: <I.database />, num: '2.1', unit:'M obs', lbl:'Stop-hour boarding records', delta:'Jan 2022 – Dec 2023' },
    { ic: <I.bus />, num: '3,184', unit:'stops', lbl:'VTA bus + light-rail network', delta:'Full Santa Clara County' },
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
    { ic: <I.database />, n:'01', t:'Data ingestion', d:"Pulled 2.1M stop-hour boardings from VTA's APC feed, joined with GTFS schedules, NOAA hourly weather, and a Bay Area events calendar. Stored as Parquet on S3.", tools:['GTFS','Parquet','DuckDB'] },
    { ic: <I.flask />, n:'02', t:'Feature engineering', d:'Built 87 features: lag windows (1h–24h–7d), rolling means, holiday and school-calendar flags, weather, route-level connectivity, and stop spatial embeddings.', tools:['pandas','tsfresh'] },
    { ic: <I.brain />, n:'03', t:'Modeling', d:'Compared LightGBM with global stop-embedding features against ARIMA, Prophet, and a Temporal Fusion Transformer. Bayesian-tuned over 240 Optuna trials.', tools:['LightGBM','TFT','Optuna'] },
    { ic: <I.shield />, n:'04', t:'Validation', d:'Walk-forward time-series CV with eight expanding folds. Audited error by route, hour-of-day, and quintile of stop volume to surface systematic gaps.', tools:['scikit-learn'] },
    { ic: <I.chart />, n:'05', t:'Deployment', d:'Per-stop forecasts and SHAP attributions exposed via a planner-friendly Streamlit dashboard. Hourly retrain via a scheduled Airflow DAG.', tools:['SHAP','Streamlit','Airflow'] },
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
    { nm:'Train (Jan 22 – Mar 24)', v:1612400, w:0.78 },
    { nm:'Validation (Apr–Jun 24)', v:218600, w:0.105 },
    { nm:'Test (Jul–Dec 24)', v:240800, w:0.115 },
  ];
  const cohort = [
    { nm:'Bus stops', v:84.2, w:0.842 },
    { nm:'Light-rail stations', v:15.8, w:0.158 },
    { nm:'Peak-hour share', v:42.6, w:0.426 },
    { nm:'Weekday share', v:73.4, w:0.734 },
    { nm:'Stops w/ <10 daily ons', v:11.2, w:0.112 },
  ];
  const features = [
    {n:'Boardings lag-1h', p:true}, {n:'Boardings lag-24h', p:true}, {n:'Rolling mean (7d)'}, {n:'Hour-of-week sin/cos'},
    {n:'Holiday flag'}, {n:'School in session', p:true}, {n:'Temperature (°F)'}, {n:'Precipitation (in/h)'},
    {n:'Route headway (min)'}, {n:'Connecting routes'}, {n:'Stop embedding (16d)', p:true}, {n:'Distance to CBD'},
    {n:'Event within 1 mi', p:true}, {n:'Sunset offset'}, {n:'Day-of-month'}, {n:'+ 72 more'}
  ];
  return (
    <section id="data">
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Dataset</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>VTA APC · 2.1M stop‑hour boardings.</h2>
            <p className="lede" style={{ maxWidth:'46ch' }}>Two years of automatic passenger counter records from the Santa Clara Valley Transportation Authority, fused with GTFS, NOAA weather, and a curated events calendar. Splits are temporal — never random — so the test set genuinely simulates deployment six months ahead.</p>
          </div></Reveal>
        </div>
        <div className="ds-grid">
          <Reveal className="card ds-card">
            <h3>Temporal splits <span className="text-muted mono" style={{ fontSize: 12, fontWeight:400 }}>· n = 2.07M</span></h3>
            <div className="flex flex-col gap-md">
              {splits.map(s => (
                <div key={s.nm} className="bar-row">
                  <span className="nm">{s.nm}</span>
                  <span className="bar"><i style={{ '--w': s.w }} /></span>
                  <span className="v">{(s.v/1000).toFixed(0)}K</span>
                </div>
              ))}
            </div>
            <div className="divider" />
            <p className="text-muted" style={{ fontSize: 13 }}>
              Forecast horizon is the 24 hours after each cutoff. No future leakage — features rely only on data observable at prediction time.
            </p>
          </Reveal>
          <Reveal delay="1" className="card ds-card">
            <h3>Network composition <span className="text-muted mono" style={{ fontSize: 12, fontWeight:400 }}>· % of stop-hours</span></h3>
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
              Long-tail of low-volume stops is preserved with weighted loss; we don't drop them just because they're hard to model.
            </p>
          </Reveal>
        </div>
        <div style={{ height: 24 }} />
        <Reveal className="card" style={{ padding: 28 }}>
          <h3 style={{ display:'flex', alignItems:'center', gap:10, marginBottom: 18 }}>
            <I.flask /> Feature catalog <span className="text-muted mono" style={{ fontSize: 12, fontWeight:400 }}>· 87 engineered features</span>
          </h3>
          <div className="pills">
            {features.map(f => (
              <span key={f.n} className={`pill ${f.p?'p':''}`}>{f.p && <span className="d" />}{f.n}</span>
            ))}
          </div>
          <div className="divider" />
          <p className="text-muted" style={{ fontSize: 13 }}>
            <span className="mono" style={{ color:'var(--ink)' }}>●</span> top-5 SHAP contributors. Engineered with leak guards: only data observable at the moment of prediction enters the feature vector.
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
    {n:'Boardings lag-24h', v: 0.46, dir:'pos'},
    {n:'Hour-of-week', v: 0.34, dir:'pos'},
    {n:'Stop embedding', v: 0.29, dir:'pos'},
    {n:'School in session', v: 0.22, dir:'pos'},
    {n:'Precipitation', v: 0.20, dir:'neg'},
    {n:'Holiday flag', v: 0.17, dir:'neg'},
    {n:'Event within 1 mi', v: 0.15, dir:'pos'},
  ];
  return (
    <section id="results" style={{ background:'var(--bg-muted)' }}>
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Results</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>Accurate, well-behaved across hours, and interpretable.</h2>
            <p className="lede" style={{ maxWidth:'46ch' }}>The headline number is 11.8% MAPE — but the per‑hour error curve and the long‑tail audit matter more for actually deploying this in a service planning workflow.</p>
          </div></Reveal>
        </div>
        <div className="results-grid">
          <Reveal className="card chart-card">
            <div className="chart-head">
              <div>
                <h3>{chart === 'roc' ? 'Predicted vs. actual (lift curve)' : 'Reliability plot'}</h3>
                <p>{chart === 'roc' ? 'LightGBM vs. seasonal-naïve baseline · test window, n=240,800' : 'Forecast quantile vs. observed boardings, decile bins'}</p>
              </div>
              <div className="chip-grp">
                <button className={chart==='roc'?'on':''} onClick={()=>setChart('roc')}>Lift</button>
                <button className={chart==='cal'?'on':''} onClick={()=>setChart('cal')}>Reliability</button>
              </div>
            </div>
            <div>{chart === 'roc' ? <ROCCurve /> : <Calibration />}</div>
          </Reveal>
          <Reveal delay="1" className="card chart-card">
            <div className="chart-head">
              <div>
                <h3>Forecast error bands</h3>
                <p>Stop-hours bucketed by absolute % error · n = 240,800</p>
              </div>
            </div>
            <div className="cm">
              <div className="cm-cell tp"><div className="v">{cm.tp.toLocaleString()}</div><div className="l">Within ±10%</div><div className="text-muted" style={{ fontSize:11 }}>69.8% of stop‑hours</div></div>
              <div className="cm-cell tn"><div className="v">{cm.tn.toLocaleString()}</div><div className="l">±10–25%</div><div className="text-muted" style={{ fontSize:11 }}>21.5% of stop‑hours</div></div>
              <div className="cm-cell fp"><div className="v">{cm.fp.toLocaleString()}</div><div className="l">±25–50%</div><div className="text-muted" style={{ fontSize:11 }}>6.0% of stop‑hours</div></div>
              <div className="cm-cell fn"><div className="v">{cm.fn.toLocaleString()}</div><div className="l">&gt;50% off</div><div className="text-muted" style={{ fontSize:11 }}>2.6% — long‑tail stops</div></div>
            </div>
            <div className="text-muted" style={{ fontSize: 13 }}>
              MAPE 11.8% · RMSE 4.2 boardings · sMAPE 9.6% · Pinball-loss (q90) 1.74
            </div>
          </Reveal>
          <Reveal delay="2" className="card chart-card" style={{ gridColumn:'1 / -1' }}>
            <div className="chart-head">
              <div>
                <h3>Top SHAP feature attributions</h3>
                <p>Mean |SHAP| across the test window. Coral pushes the forecast up; indigo pulls it down.</p>
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

/* ── Live demo: rush-heat map ─────────────────────────────────── */
const Demo = () => {
  const [system, setSystem] = useState('bart');
  const [hour, setHour] = useState(8);
  const [dow, setDow] = useState(2);
  const [weather, setWeather] = useState('clear');
  const [event, setEvent] = useState('none');
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(2);

  React.useEffect(() => {
    if (!playing) return;
    const interval = 700 / speed;
    const t = setInterval(() => {
      setHour(h => {
        const next = (h + 1) % 24;
        if (next === 0) setDow(d => (d + 1) % 7);
        return next;
      });
    }, interval);
    return () => clearInterval(t);
  }, [playing, speed]);

  const stations = system === 'bart' ? window.BART_STATIONS : window.VTA_STATIONS;
  const stats = useMemo(() => {
    if (!stations) return { total: 0, peak: 0, peakName: '', meanLoad: 0 };
    const hourMul = (h) => {
      if (h>=7 && h<=9) return { am: 1.0, pm: 0.0, level: 0.95 };
      if (h>=16 && h<=18) return { am: 0.0, pm: 1.0, level: 1.0 };
      if (h>=10 && h<=15) return { am: 0.3, pm: 0.4, level: 0.55 };
      if (h>=19 && h<=21) return { am: 0.0, pm: 0.55, level: 0.6 };
      if (h>=22 || h<=4) return { am: 0.0, pm: 0.05, level: 0.18 };
      return { am: 0.7, pm: 0.0, level: 0.45 };
    };
    const hM = hourMul(hour);
    const dM = (dow===0||dow===6) ? 0.55 : 1.0;
    const wM = weather==='rain'?0.78:weather==='hot'?0.88:1.0;
    const eM = event==='major'?1.0:event==='small'?0.4:0;
    const loads = stations.map(s => {
      let v = (s.baseAM*hM.am + s.basePM*hM.pm + 0.45*hM.level) * dM * wM + s.eventBoost*eM;
      if (s.type==='core') v = Math.max(v, 0.55);
      if (s.type==='commuter' && (dow===0||dow===6)) v *= 0.6;
      return { s, v: Math.max(0.05, Math.min(2.4, v)) };
    });
    loads.sort((a,b)=>b.v-a.v);
    const total = loads.reduce((acc,r)=>acc + r.v*22, 0);
    const meanLoad = loads.reduce((acc,r)=>acc + r.v, 0) / loads.length;
    return { total, peak: loads[0].v*22, peakName: loads[0].s.nm, meanLoad, top3: loads.slice(0,3) };
  }, [stations, hour, dow, weather, event]);

  const dayName = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][dow];
  const hLabel = `${String(hour).padStart(2,'0')}:00`;
  const tier = stats.meanLoad < 0.45 ? 'low' : stats.meanLoad < 0.95 ? 'med' : 'high';
  const tierLabel = tier==='low' ? 'Off-peak' : tier==='med' ? 'Building' : 'Peak crush';

  return (
    <section id="demo">
      <div className="wrap">
        <div className="section-h">
          <Reveal><div className="eyebrow"><span className="pip" /> Live demo</div></Reveal>
          <Reveal delay="1"><div className="row">
            <h2>Where is the rush, right now?</h2>
            <p className="lede" style={{ maxWidth:'52ch' }}>Toggle between BART and VTA, then scrub the hour and weekday to see the model's expected boardings light up across the network. Add weather and an event to test how the system reacts.</p>
          </div></Reveal>
        </div>

        <Reveal className="card map-card">
          <div className="map-toolbar">
            <div className="seg seg-system">
              <button className={system==='bart'?'on':''} onClick={()=>setSystem('bart')}>BART · 50 stations</button>
              <button className={system==='vta'?'on':''} onClick={()=>setSystem('vta')}>VTA · 39 stations</button>
            </div>
            <div className="map-stat">
              <div className="map-stat-num">{stats.total.toFixed(0)}</div>
              <div className="map-stat-lbl">network ons/hr</div>
            </div>
            <div className="map-stat">
              <div className="map-stat-num">{stats.peak.toFixed(0)}</div>
              <div className="map-stat-lbl">peak · {stats.peakName}</div>
            </div>
            <div className={`tier ${tier} map-tier`}>{tierLabel}</div>
          </div>

          <div className="map-grid">
            <div className="map-canvas">
              {window.TransitMap && (
                <TransitMap system={system} hour={hour} day={dow} weather={weather} event={event} />
              )}
            </div>

            <div className="map-controls">
              <div className="field">
                <label>Hour of day <span className="v">{hLabel}</span></label>
                <input type="range" min="0" max="23" value={hour} onChange={e=>setHour(+e.target.value)} />
                <div className="hour-strip">
                  {[0,4,8,12,16,20].map(h => (
                    <span key={h} className={Math.abs(h-hour)<=1?'on':''}>{String(h).padStart(2,'0')}</span>
                  ))}
                </div>
              </div>

              <div className="field">
                <label>Day of week <span className="v">{dayName}</span></label>
                <div className="dow">
                  {['S','M','T','W','T','F','S'].map((d,i)=>(
                    <button key={i} className={dow===i?'on':''} onClick={()=>setDow(i)} aria-label={['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][i]}>{d}</button>
                  ))}
                </div>
              </div>

              <div className="field">
                <label>Weather</label>
                <div className="seg">
                  <button className={weather==='clear'?'on':''} onClick={()=>setWeather('clear')}>Clear</button>
                  <button className={weather==='rain'?'on':''} onClick={()=>setWeather('rain')}>Rain</button>
                  <button className={weather==='hot'?'on':''} onClick={()=>setWeather('hot')}>Heat (95°F+)</button>
                </div>
              </div>

              <div className="field">
                <label>Event near a venue</label>
                <div className="seg">
                  <button className={event==='none'?'on':''} onClick={()=>setEvent('none')}>None</button>
                  <button className={event==='small'?'on':''} onClick={()=>setEvent('small')}>Small</button>
                  <button className={event==='major'?'on':''} onClick={()=>setEvent('major')}>Major</button>
                </div>
                <div className="hint">{system==='bart' ? 'Boosts Coliseum, 12th St / Oakland.' : "Boosts Diridon (SAP), Great America, Old Ironsides (Levi's)."}</div>
              </div>

              <div className="play-row">
                <button className={`btn ${playing?'btn-secondary':'btn-primary'} play-btn`} onClick={()=>setPlaying(p=>!p)}>
                  {playing ? <><I.pause /> Pause</> : <><I.play /> Play week-by-week</>}
                </button>
                <div className="speed-seg">
                  {[1,2,4,8].map(s => (
                    <button key={s} className={speed===s?'on':''} onClick={()=>setSpeed(s)} aria-label={`${s}x speed`}>{s}×</button>
                  ))}
                </div>
              </div>

              <div className="top-stations">
                <div className="text-muted" style={{ fontSize: 11, letterSpacing:'.06em', textTransform:'uppercase', fontFamily:'var(--mono)', marginBottom: 8 }}>Hottest stops · {hLabel} {dayName}</div>
                {(stats.top3 || []).map((r, i) => (
                  <div key={r.s.id} className="hot-row">
                    <span className="rank">{i+1}</span>
                    <span className="nm">{r.s.nm}</span>
                    <span className="v">{(r.v*22).toFixed(0)} <em>ons/hr</em></span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
};

/* ── Benchmarks + Recommendations ──────────────────────────────── */
const Benchmarks = () => {
  const rows = [
    { m:'LightGBM (ours)', auc:0.118, f1:0.93, brier:4.20, ece:9.6, best:true },
    { m:'Temporal Fusion Transformer', auc:0.124, f1:0.92, brier:4.41, ece:10.1 },
    { m:'Prophet (per-stop)', auc:0.171, f1:0.84, brier:6.02, ece:14.4 },
    { m:'ARIMA(2,1,2)', auc:0.183, f1:0.81, brier:6.51, ece:15.8 },
    { m:'Seasonal-naïve (week)', auc:0.187, f1:0.80, brier:6.74, ece:16.2 },
  ];
  const recs = [
    { n:'01', t:'Re-balance peak-hour headways.', d:"On the top‑decile of stops, our forecast is consistently 22% above the published schedule's assumed load between 7–9am. A targeted three-minute headway cut on routes 22, 23, and 522 captures most of that spread.", who:'Service Planning' },
    { n:'02', t:'Surface event-driven surges proactively.', d:"Major events at SAP Center, Levi's Stadium, and PayPal Park drive a +35–60% surge at the four nearest stops. The dashboard should auto-flag these 48 hours ahead instead of leaving operators to anticipate them.", who:'Operations Control' },
    { n:'03', t:'Retrain monthly, recalibrate weekly.', d:'School-calendar drift and route changes cost ~1.4 MAPE points per quarter without retraining. A scheduled monthly refit on the trailing 90 days closes that gap with a 12-minute training run.', who:'Data / IT' },
  ];
  return (
    <>
      <section id="bench">
        <div className="wrap">
          <div className="section-h">
            <Reveal><div className="eyebrow"><span className="pip" /> Benchmarks</div></Reveal>
            <Reveal delay="1"><div className="row">
              <h2>How we stack up.</h2>
              <p className="lede" style={{ maxWidth:'46ch' }}>All models trained on the same temporal split with identical features. Lower is better for MAPE, sMAPE, and RMSE; higher is better for R².</p>
            </div></Reveal>
          </div>
          <Reveal className="card bench">
            <table>
              <thead>
                <tr><th>Model</th><th style={{ textAlign:'right' }}>MAPE</th><th style={{ textAlign:'right' }}>R²</th><th style={{ textAlign:'right' }}>RMSE</th><th style={{ textAlign:'right' }}>sMAPE</th><th>Relative</th></tr>
              </thead>
              <tbody>
                {rows.map((r,i) => (
                  <tr key={i} className={r.best?'best':''}>
                    <td className="model">{r.m}</td>
                    <td className="num">{(r.auc*100).toFixed(1)}%</td>
                    <td className="num">{r.f1.toFixed(2)}</td>
                    <td className="num">{r.brier.toFixed(2)}</td>
                    <td className="num">{r.ece.toFixed(1)}%</td>
                    <td className="barcell"><span className="b"><i style={{ '--w': 1 - (r.auc-0.10)/(0.19-0.10) }} /></span></td>
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
              <h2>What VTA should actually do.</h2>
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
            <a className="btn btn-secondary" href="#"><I.github /> github.com/dhruv-shah</a>
            <a className="btn btn-secondary" href="#">LinkedIn <I.arrowOut /></a>
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
          { lbl:'Report · 38 pages', t:'Final project report', d:'Full methodology, experiments, error audit, and limitations.' },
          { lbl:'Slides · 22 slides', t:'Defense presentation', d:'The 15-minute version — what to skim before a one‑on‑one.' },
          { lbl:'Repo · MIT license', t:'Source code', d:'Reproducible Makefile, training scripts, and the Streamlit demo.' },
          { lbl:'Notebook', t:'Exploratory analysis', d:'Stop-level missingness, headway changes, and the case for temporal splits.' },
          { lbl:'Poster · 36×48"', t:'Showcase poster', d:'Print-ready PDF used at the SJSU CS senior project showcase.' },
          { lbl:'Dataset card', t:'VTA APC + GTFS', d:'Public APC and GTFS feeds — link with attribution.' },
        ].map((r,i) => (
          <Reveal key={i} delay={(i%3)+1}>
            <a href="#">
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
        <small>TransitForecast · CS 163 Senior Project · San José State University · © 2026 Dhruv Punit Shah</small>
      </div>
      <small className="text-muted">Built with React, LightGBM, and a great deal of caffeine.</small>
    </div>
  </footer>
);

Object.assign(window, { Nav, Hero, AtAGlance, Method, Dataset, Results, Demo, Benchmarks, About, Footer });