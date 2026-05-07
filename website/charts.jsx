/* SVG chart primitives — ROC, Calibration, Confusion mini, Distribution. */

const ROCCurve = ({ width = 460, height = 300, animate = true }) => {
  const ours = [
    [0,0],[0.02,0.18],[0.05,0.36],[0.08,0.5],[0.12,0.62],[0.18,0.73],
    [0.25,0.81],[0.34,0.86],[0.45,0.9],[0.58,0.93],[0.72,0.96],[0.86,0.98],[1,1]
  ];
  const baseline = [
    [0,0],[0.05,0.12],[0.12,0.25],[0.22,0.4],[0.34,0.55],[0.46,0.66],
    [0.58,0.74],[0.7,0.82],[0.82,0.9],[0.92,0.96],[1,1]
  ];
  const pad = { l: 44, r: 16, t: 14, b: 36 };
  const W = width - pad.l - pad.r;
  const H = height - pad.t - pad.b;
  const sx = (x) => pad.l + x * W;
  const sy = (y) => pad.t + (1 - y) * H;
  const path = (pts) => pts.map(([x,y], i) => `${i?'L':'M'}${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join(' ');
  const areaPath = path(ours) + ` L${sx(1)},${sy(0)} L${sx(0)},${sy(0)} Z`;
  const oursLen = React.useRef(0);
  const oursRef = React.useRef(null);
  React.useEffect(() => {
    if (!animate || !oursRef.current) return;
    const len = oursRef.current.getTotalLength();
    oursLen.current = len;
    oursRef.current.style.strokeDasharray = len;
    oursRef.current.style.strokeDashoffset = len;
    requestAnimationFrame(() => {
      oursRef.current.style.transition = 'stroke-dashoffset 1.4s cubic-bezier(.2,.7,.2,1)';
      oursRef.current.style.strokeDashoffset = 0;
    });
  }, [animate]);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display:'block' }}>
      <defs>
        <linearGradient id="rocFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.22" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0,0.25,0.5,0.75,1].map(t => (
        <g key={t}>
          <line x1={sx(0)} x2={sx(1)} y1={sy(t)} y2={sy(t)} stroke="var(--line)" strokeDasharray={t===0||t===1?'':'2 4'} />
          <text x={pad.l - 8} y={sy(t) + 4} textAnchor="end" fontSize="10" fill="var(--ink-soft)" fontFamily="var(--mono)">{t.toFixed(2)}</text>
        </g>
      ))}
      {[0,0.25,0.5,0.75,1].map(t => (
        <text key={t} x={sx(t)} y={height - pad.b + 18} textAnchor="middle" fontSize="10" fill="var(--ink-soft)" fontFamily="var(--mono)">{t.toFixed(2)}</text>
      ))}
      <text x={pad.l + W/2} y={height - 4} textAnchor="middle" fontSize="11" fill="var(--ink-muted)">False Positive Rate</text>
      <text transform={`translate(12 ${pad.t + H/2}) rotate(-90)`} textAnchor="middle" fontSize="11" fill="var(--ink-muted)">True Positive Rate</text>
      <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} stroke="var(--line-strong)" strokeDasharray="3 4" />
      <path d={path(baseline)} fill="none" stroke="var(--ink-soft)" strokeWidth="1.6" strokeDasharray="5 4" />
      <path d={areaPath} fill="url(#rocFill)" />
      <path ref={oursRef} d={path(ours)} fill="none" stroke="var(--accent)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <g>
        <circle cx={sx(0.18)} cy={sy(0.73)} r="5" fill="var(--bg-elev)" stroke="var(--accent)" strokeWidth="2" />
        <circle cx={sx(0.18)} cy={sy(0.73)} r="2" fill="var(--accent)" />
      </g>
      <g transform={`translate(${pad.l + W - 178}, ${pad.t + 8})`}>
        <rect x="0" y="0" width="170" height="46" rx="8" fill="var(--bg-elev)" stroke="var(--line)" />
        <line x1="10" y1="16" x2="28" y2="16" stroke="var(--accent)" strokeWidth="2.4" />
        <text x="34" y="19" fontSize="11" fill="var(--ink)" fontFamily="var(--body)">XGBoost · AUC 0.912</text>
        <line x1="10" y1="34" x2="28" y2="34" stroke="var(--ink-soft)" strokeWidth="1.6" strokeDasharray="5 4" />
        <text x="34" y="37" fontSize="11" fill="var(--ink-muted)" fontFamily="var(--body)">LogReg · AUC 0.823</text>
      </g>
    </svg>
  );
};

const Calibration = ({ width = 460, height = 260 }) => {
  const pts = [
    [0.05,0.06],[0.15,0.14],[0.25,0.27],[0.35,0.33],[0.45,0.46],
    [0.55,0.58],[0.65,0.66],[0.75,0.72],[0.85,0.83],[0.95,0.94]
  ];
  const pad = { l: 40, r: 14, t: 14, b: 32 };
  const W = width - pad.l - pad.r;
  const H = height - pad.t - pad.b;
  const sx = (x) => pad.l + x * W;
  const sy = (y) => pad.t + (1 - y) * H;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display:'block' }}>
      {[0,0.25,0.5,0.75,1].map(t => (
        <line key={t} x1={sx(0)} x2={sx(1)} y1={sy(t)} y2={sy(t)} stroke="var(--line)" strokeDasharray={t===0?'':'2 4'} />
      ))}
      <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} stroke="var(--line-strong)" strokeDasharray="3 4" />
      <path
        d={pts.map(([x,y],i)=>`${i?'L':'M'}${sx(x)},${sy(y)}`).join(' ')}
        fill="none" stroke="var(--primary)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
      />
      {pts.map(([x,y],i)=>(
        <circle key={i} cx={sx(x)} cy={sy(y)} r="3" fill="var(--bg-elev)" stroke="var(--primary)" strokeWidth="1.6" />
      ))}
      <text x={pad.l + W/2} y={height - 4} textAnchor="middle" fontSize="11" fill="var(--ink-muted)">Predicted probability</text>
      <text transform={`translate(10 ${pad.t + H/2}) rotate(-90)`} textAnchor="middle" fontSize="11" fill="var(--ink-muted)">Observed frequency</text>
      <text x={pad.l + 8} y={pad.t + 14} fontSize="10.5" fill="var(--ink-soft)" fontFamily="var(--mono)">Brier 0.078 · ECE 0.024</text>
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
        <text textAnchor="middle" y="-6" fontFamily="var(--mono)" fontSize="11" fill="var(--ink-muted)">PROB · 30D</text>
        <text textAnchor="middle" y="22" fontFamily="var(--display)" fontWeight="600" fontSize="34" fill="var(--ink)" letterSpacing="-1">0.74</text>
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