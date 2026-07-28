/* SVG chart primitives — WAPE comparison, Forecast bands, HeroOrbit, Gauge. */

/* ── WAPE comparison bar chart (real data from model_comparison.json) ── */
const ROCCurve = ({ width = 460, height = 280 }) => {
  const [data, setData] = React.useState(null);
  React.useEffect(() => {
    fetch('data/model_comparison.json').then(r => r.json()).catch(() => []).then(setData);
  }, []);

  if (!data) return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display:'block' }}>
      <text x="50%" y="50%" textAnchor="middle" fontSize="13" fill="var(--ink-muted)">Loading…</text>
    </svg>
  );

  const DISPLAY_CAP = 30; // cap x-axis at 30% — Prophet 176% shown as overflow
  const pad = { l: 170, r: 70, t: 20, b: 38 };
  const W = width - pad.l - pad.r;
  const H = height - pad.t - pad.b;
  const rowH = H / data.length;

  const gridLines = [0, 10, 20, 30];

  const labelFor = m => ({
    'AutoGluon_Ensemble': 'AutoETS / AutoGluon',
    'SARIMA': 'SARIMA(2,1,2)',
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
        const isBest = r.model === 'AutoGluon_Ensemble';
        const disp = Math.min(r.WAPE_pct, DISPLAY_CAP);
        const barW = (disp / DISPLAY_CAP) * W;
        const overflow = r.WAPE_pct > DISPLAY_CAP;
        const y = pad.t + i * rowH + rowH * 0.18;
        const bH = rowH * 0.56;
        return (
          <g key={i}>
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
            >{r.WAPE_pct.toFixed(1)}%{overflow ? ' ▶' : ''}</text>
          </g>
        );
      })}

      <text
        x={pad.l + W / 2} y={height - 4}
        textAnchor="middle" fontSize="11" fill="var(--ink-muted)"
      >WAPE % on Jan–Jun 2023 validation set · lower is better</text>
    </svg>
  );
};

/* ── Forecast interval chart — P10/P50/P90 for Embarcadero (real data) ── */
const Calibration = ({ width = 460, height = 260 }) => {
  const [pts, setPts] = React.useState(null);
  React.useEffect(() => {
    fetch('data/forecasts.json')
      .then(r => r.json()).catch(() => [])
      .then(d => {
        const em = d.filter(r => r.station_id === 'EMBR')
                    .sort((a, b) => a.month.localeCompare(b.month));
        setPts(em);
      });
  }, []);

  if (!pts) return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display:'block' }}>
      <text x="50%" y="50%" textAnchor="middle" fontSize="13" fill="var(--ink-muted)">Loading…</text>
    </svg>
  );
  if (pts.length === 0) return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display:'block' }}>
      <text x="50%" y="50%" textAnchor="middle" fontSize="13" fill="var(--ink-muted)">No forecast data</text>
    </svg>
  );

  const pad = { l: 58, r: 20, t: 24, b: 38 };
  const W = width - pad.l - pad.r;
  const H = height - pad.t - pad.b;
  const n = pts.length;

  const allVals = pts.flatMap(r => [r.p10, r.p50, r.p90]).filter(v => v != null);
  const minV = Math.min(...allVals) * 0.92;
  const maxV = Math.max(...allVals) * 1.05;

  const sx = i => pad.l + (n === 1 ? W / 2 : (i / (n - 1)) * W);
  const sy = v => pad.t + (1 - (v - minV) / (maxV - minV)) * H;
  const fmtK = v => v >= 1e6 ? (v / 1e6).toFixed(2) + 'M' : (v / 1e3).toFixed(0) + 'k';
  const monthLabel = s => { const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']; return mo[parseInt(s.slice(5,7),10)-1]; };

  const bandPath = [
    ...pts.map((r, i) => `${i === 0 ? 'M' : 'L'}${sx(i).toFixed(1)},${sy(r.p90).toFixed(1)}`),
    ...pts.slice().reverse().map((r, i) => `L${sx(n - 1 - i).toFixed(1)},${sy(r.p10).toFixed(1)}`),
    'Z',
  ].join(' ');
  const p50Path = pts.map((r, i) => `${i === 0 ? 'M' : 'L'}${sx(i).toFixed(1)},${sy(r.p50).toFixed(1)}`).join(' ');
  const p10Path = pts.map((r, i) => `${i === 0 ? 'M' : 'L'}${sx(i).toFixed(1)},${sy(r.p10).toFixed(1)}`).join(' ');
  const p90Path = pts.map((r, i) => `${i === 0 ? 'M' : 'L'}${sx(i).toFixed(1)},${sy(r.p90).toFixed(1)}`).join(' ');

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
      {pts.map((r, i) => (
        <circle key={i} cx={sx(i)} cy={sy(r.p50)} r="3.5" fill="var(--bg-elev)" stroke="var(--primary)" strokeWidth="1.8" />
      ))}

      {/* x labels */}
      {pts.map((r, i) => (
        <text key={i} x={sx(i)} y={pad.t + H + 16} textAnchor="middle" fontSize="10" fill="var(--ink-soft)" fontFamily="var(--mono)">{monthLabel(r.month)}</text>
      ))}

      {/* annotations */}
      <text x={pad.l + 8} y={pad.t + 13} fontSize="10" fill="var(--ink-soft)" fontFamily="var(--mono)">Embarcadero · Chronos-2 zero-shot forecast</text>
      <text x={pad.l + W} y={pad.t + H + 30} textAnchor="end" fontSize="10" fill="var(--ink-muted)">2024</text>

      {/* legend */}
      <g transform={`translate(${pad.l + W - 160}, ${pad.t + 22})`}>
        <rect x="0" y="-14" width="155" height="46" rx="6" fill="var(--bg-elev)" stroke="var(--line)" />
        <line x1="8" y1="0" x2="26" y2="0" stroke="var(--primary)" strokeWidth="2.4" />
        <circle cx="17" cy="0" r="3" fill="var(--bg-elev)" stroke="var(--primary)" strokeWidth="1.8" />
        <text x="32" y="4" fontSize="10.5" fill="var(--ink)" fontFamily="var(--body)">P50 median</text>
        <rect x="8" y="14" width="18" height="8" rx="2" fill="var(--primary)" opacity="0.16" />
        <line x1="8" y1="14" x2="26" y2="14" stroke="var(--primary)" strokeWidth="1" strokeDasharray="3 2" opacity="0.5" />
        <line x1="8" y1="22" x2="26" y2="22" stroke="var(--primary)" strokeWidth="1" strokeDasharray="3 2" opacity="0.5" />
        <text x="32" y="22" fontSize="10.5" fill="var(--ink)" fontFamily="var(--body)">P10–P90 band</text>
      </g>
    </svg>
  );
};

const HeroOrbit = () => {
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
        <text textAnchor="middle" y="-6" fontFamily="var(--mono)" fontSize="11" fill="var(--ink-muted)">WAPE · val</text>
        <text textAnchor="middle" y="22" fontFamily="var(--display)" fontWeight="600" fontSize="30" fill="var(--ink)" letterSpacing="-1">14.2%</text>
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

Object.assign(window, { ROCCurve, Calibration, HeroOrbit, Gauge });
