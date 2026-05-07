/* Schematic transit maps with rush-heat overlays for BART + VTA.
   Self-contained SVG (no external map API). Stations are positioned
   to evoke the real network shape but are stylized, not GIS-accurate. */

const { useMemo, useState, useEffect } = React;

const BART_STATIONS = [
  { id:'rich', nm:'Richmond', x: 215, y: 60, type:'commuter', baseAM:1.4, basePM:1.1, eventBoost:0 },
  { id:'elc',  nm:'El Cerrito', x: 230, y: 95, type:'commuter', baseAM:1.2, basePM:1.0, eventBoost:0 },
  { id:'nbk',  nm:'N. Berkeley', x: 250, y: 130, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'bky',  nm:'Berkeley', x: 270, y: 165, type:'urban', baseAM:1.6, basePM:1.5, eventBoost:0 },
  { id:'mac',  nm:'MacArthur', x: 295, y: 220, type:'transfer', baseAM:1.7, basePM:1.6, eventBoost:0 },
  { id:'ant',  nm:'Antioch', x: 470, y: 50, type:'commuter', baseAM:1.6, basePM:0.6, eventBoost:0 },
  { id:'pit',  nm:'Pittsburg', x: 425, y: 80, type:'commuter', baseAM:1.5, basePM:0.7, eventBoost:0 },
  { id:'ccd',  nm:'Concord', x: 390, y: 115, type:'commuter', baseAM:1.4, basePM:0.8, eventBoost:0 },
  { id:'plh',  nm:'Pleasant Hill', x: 365, y: 150, type:'commuter', baseAM:1.3, basePM:0.9, eventBoost:0 },
  { id:'lfy',  nm:'Lafayette', x: 345, y: 185, type:'commuter', baseAM:1.2, basePM:0.9, eventBoost:0 },
  { id:'orn',  nm:'Orinda', x: 325, y: 215, type:'commuter', baseAM:1.1, basePM:0.9, eventBoost:0 },
  { id:'rkr',  nm:'Rockridge', x: 312, y: 240, type:'commuter', baseAM:1.0, basePM:0.95, eventBoost:0 },
  { id:'12th', nm:'12th St / Oakland', x: 305, y: 270, type:'transfer', baseAM:1.9, basePM:1.9, eventBoost:0.4 },
  { id:'19th', nm:'19th St / Oakland', x: 295, y: 250, type:'transfer', baseAM:1.7, basePM:1.7, eventBoost:0 },
  { id:'lkm',  nm:'Lake Merritt', x: 320, y: 295, type:'urban', baseAM:1.4, basePM:1.4, eventBoost:0 },
  { id:'fvw',  nm:'Fruitvale', x: 360, y: 320, type:'urban', baseAM:1.3, basePM:1.3, eventBoost:0 },
  { id:'col',  nm:'Coliseum', x: 395, y: 345, type:'transfer', baseAM:1.0, basePM:1.0, eventBoost:0.9 },
  { id:'sl',   nm:'San Leandro', x: 425, y: 375, type:'commuter', baseAM:1.1, basePM:1.0, eventBoost:0 },
  { id:'bayp', nm:'Bay Fair', x: 455, y: 405, type:'transfer', baseAM:1.0, basePM:0.95, eventBoost:0 },
  { id:'hyw',  nm:'Hayward', x: 485, y: 425, type:'commuter', baseAM:1.0, basePM:0.95, eventBoost:0 },
  { id:'unc',  nm:'Union City', x: 515, y: 450, type:'commuter', baseAM:1.0, basePM:0.95, eventBoost:0 },
  { id:'frm',  nm:'Fremont', x: 540, y: 478, type:'commuter', baseAM:1.05, basePM:0.95, eventBoost:0 },
  { id:'brb',  nm:'Berryessa', x: 555, y: 498, type:'commuter', baseAM:1.0, basePM:0.95, eventBoost:0 },
  { id:'wo',   nm:'West Oakland', x: 260, y: 285, type:'urban', baseAM:1.3, basePM:1.5, eventBoost:0 },
  { id:'emb',  nm:'Embarcadero', x: 175, y: 305, type:'core', baseAM:2.4, basePM:2.5, eventBoost:0.2 },
  { id:'mtg',  nm:'Montgomery', x: 150, y: 320, type:'core', baseAM:2.6, basePM:2.7, eventBoost:0.2 },
  { id:'pwl',  nm:'Powell', x: 130, y: 340, type:'core', baseAM:2.3, basePM:2.4, eventBoost:0.3 },
  { id:'cvc',  nm:'Civic Center', x: 115, y: 360, type:'core', baseAM:2.0, basePM:2.1, eventBoost:0.2 },
  { id:'16th', nm:'16th St Mission', x: 105, y: 385, type:'urban', baseAM:1.5, basePM:1.7, eventBoost:0 },
  { id:'24th', nm:'24th St Mission', x: 100, y: 410, type:'urban', baseAM:1.4, basePM:1.6, eventBoost:0 },
  { id:'gln',  nm:'Glen Park', x: 105, y: 435, type:'urban', baseAM:1.1, basePM:1.2, eventBoost:0 },
  { id:'bls',  nm:'Balboa Park', x: 115, y: 458, type:'urban', baseAM:1.1, basePM:1.2, eventBoost:0 },
  { id:'daly', nm:'Daly City', x: 130, y: 480, type:'transfer', baseAM:1.2, basePM:1.1, eventBoost:0 },
  { id:'colm', nm:'Colma', x: 150, y: 500, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'ssf',  nm:'S. San Francisco', x: 175, y: 510, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'sbr',  nm:'San Bruno', x: 200, y: 510, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'mil',  nm:'Millbrae', x: 235, y: 510, type:'transfer', baseAM:1.2, basePM:1.0, eventBoost:0 },
  { id:'sfo',  nm:'SFO Airport', x: 220, y: 488, type:'airport', baseAM:1.5, basePM:1.5, eventBoost:0 },
  { id:'cas',  nm:'Castro Valley', x: 510, y: 380, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'dub',  nm:'Dublin/Pleasanton', x: 555, y: 360, type:'commuter', baseAM:1.3, basePM:0.7, eventBoost:0 },
  { id:'wdb',  nm:'W. Dublin', x: 530, y: 370, type:'commuter', baseAM:1.1, basePM:0.8, eventBoost:0 },
];
const BART_LINES = [
  { c: '#f04e23', ids: ['rich','elc','nbk','bky','mac','19th','12th','wo','emb','mtg','pwl','cvc','16th','24th','gln','bls','daly','colm','ssf','sbr','mil'] },
  { c: '#fdb62a', ids: ['ant','pit','ccd','plh','lfy','orn','rkr','mac','19th','12th','wo','emb','mtg','pwl','cvc','16th','24th','gln','bls','daly','colm','ssf','sbr','sfo','mil'] },
  { c: '#0099d8', ids: ['dub','wdb','cas','bayp','sl','col','fvw','lkm','12th','19th','mac','rkr','orn','lfy','plh','ccd','pit','ant'] },
  { c: '#1a8a3f', ids: ['brb','frm','unc','hyw','bayp','sl','col','fvw','lkm','12th','wo','emb','mtg','pwl','cvc','daly'] },
];

const VTA_STATIONS = [
  { id:'mtv', nm:'Mountain View', x: 70, y: 90, type:'transfer', baseAM:1.4, basePM:1.2, eventBoost:0 },
  { id:'evv', nm:'Evelyn', x: 110, y: 95, type:'urban', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'win', nm:'Whisman', x: 145, y: 102, type:'urban', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'msv', nm:'Middlefield', x: 180, y: 110, type:'urban', baseAM:0.95, basePM:0.85, eventBoost:0 },
  { id:'baytm', nm:'Bayshore/NASA', x: 215, y: 118, type:'commuter', baseAM:1.4, basePM:0.7, eventBoost:0 },
  { id:'rmt', nm:'Reamwood', x: 250, y: 125, type:'urban', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'old', nm:'Old Ironsides', x: 290, y: 132, type:'transfer', baseAM:1.3, basePM:1.0, eventBoost:1.4 },
  { id:'lck', nm:'Lick Mill', x: 320, y: 145, type:'urban', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'gsh', nm:'Great America', x: 350, y: 158, type:'urban', baseAM:1.0, basePM:0.9, eventBoost:1.5 },
  { id:'tas', nm:'Tasman', x: 400, y: 175, type:'transfer', baseAM:1.2, basePM:1.0, eventBoost:0 },
  { id:'rvr', nm:'River Oaks', x: 425, y: 200, type:'urban', baseAM:0.95, basePM:0.85, eventBoost:0 },
  { id:'orc', nm:'Orchard', x: 440, y: 230, type:'urban', baseAM:0.95, basePM:0.85, eventBoost:0 },
  { id:'bry', nm:'Bonaventura', x: 450, y: 260, type:'urban', baseAM:0.95, basePM:0.85, eventBoost:0 },
  { id:'cnv', nm:'Component', x: 460, y: 295, type:'urban', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'krn', nm:'Karina', x: 470, y: 325, type:'urban', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'mtfair', nm:'Metro/Airport', x: 460, y: 350, type:'transfer', baseAM:1.4, basePM:1.3, eventBoost:0 },
  { id:'gish', nm:'Gish', x: 445, y: 375, type:'urban', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'cvc',  nm:'Civic Center', x: 425, y: 400, type:'transfer', baseAM:1.4, basePM:1.3, eventBoost:0 },
  { id:'jpsq', nm:'Japantown', x: 405, y: 420, type:'urban', baseAM:1.1, basePM:1.0, eventBoost:0 },
  { id:'shc',  nm:'St James', x: 385, y: 440, type:'urban', baseAM:1.2, basePM:1.1, eventBoost:0.3 },
  { id:'sntc', nm:'Santa Clara', x: 365, y: 458, type:'transfer', baseAM:1.6, basePM:1.5, eventBoost:0.3 },
  { id:'pmd',  nm:'Paseo de S. Antonio', x: 348, y: 478, type:'core', baseAM:1.7, basePM:1.7, eventBoost:0.4 },
  { id:'sjc',  nm:'San Jose Diridon', x: 330, y: 498, type:'core', baseAM:2.2, basePM:2.3, eventBoost:1.6 },
  { id:'cnvc', nm:'Convention Center', x: 360, y: 510, type:'urban', baseAM:1.3, basePM:1.4, eventBoost:0.6 },
  { id:'cit',  nm:"Children's Discovery", x: 388, y: 522, type:'urban', baseAM:1.0, basePM:0.95, eventBoost:0 },
  { id:'tam',  nm:'Tamien', x: 415, y: 540, type:'transfer', baseAM:1.3, basePM:1.2, eventBoost:0 },
  { id:'ctn',  nm:'Curtner', x: 445, y: 555, type:'urban', baseAM:1.0, basePM:0.95, eventBoost:0 },
  { id:'cap',  nm:'Capitol', x: 480, y: 565, type:'urban', baseAM:1.1, basePM:1.0, eventBoost:0 },
  { id:'brh',  nm:'Branham', x: 515, y: 565, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'orh',  nm:'Ohlone/Chynoweth', x: 545, y: 555, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'ble',  nm:'Blossom Hill', x: 570, y: 538, type:'commuter', baseAM:1.05, basePM:0.95, eventBoost:0 },
  { id:'snt',  nm:'Snell', x: 590, y: 515, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'stc',  nm:'Santa Teresa', x: 605, y: 488, type:'commuter', baseAM:1.05, basePM:0.95, eventBoost:0 },
  { id:'race', nm:'Race', x: 295, y: 482, type:'urban', baseAM:1.0, basePM:0.95, eventBoost:0 },
  { id:'fru',  nm:'Fruitdale', x: 265, y: 488, type:'urban', baseAM:0.95, basePM:0.9, eventBoost:0 },
  { id:'bas',  nm:'Bascom', x: 235, y: 495, type:'urban', baseAM:0.95, basePM:0.9, eventBoost:0 },
  { id:'haml', nm:'Hamilton', x: 205, y: 502, type:'urban', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'dws',  nm:'Downtown Campbell', x: 175, y: 510, type:'urban', baseAM:1.05, basePM:1.0, eventBoost:0 },
  { id:'wch',  nm:'Winchester', x: 140, y: 518, type:'commuter', baseAM:1.1, basePM:0.95, eventBoost:0 },
];
const VTA_LINES = [
  { c: '#22a06b', ids: ['mtv','evv','win','msv','baytm','rmt','old','lck','gsh','tas','rvr','orc','bry','cnv','krn','mtfair','gish','cvc','jpsq','shc','sntc','pmd','sjc','cnvc','cit','tam','ctn','cap','brh','orh','ble','snt','stc'] },
  { c: '#f08323', ids: ['mtv','evv','win','msv','baytm','rmt','old','lck','gsh','tas','rvr','orc','bry','cnv','krn','mtfair','gish','cvc','jpsq','shc','sntc','pmd','sjc','race','fru','bas','haml','dws','wch'] },
  { c: '#0099d8', ids: ['old','tas','sjc','tam','ctn','cap','brh','orh','ble','snt','stc'] },
];

function useBartRidership(rawStations) {
  const [enriched, setEnriched] = useState(rawStations);
  useEffect(() => {
    if (!rawStations || rawStations.length === 0) { setEnriched(rawStations); return; }
    fetch('data/stations_ridership.json')
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => {
        const lookup = {};
        data.forEach(d => { lookup[d.station_id] = d; });
        setEnriched(rawStations.map(s => {
          const d = lookup[s.id];
          return d ? { ...s, baseAM: d.baseAM, basePM: d.basePM } : s;
        }));
      })
      .catch(() => setEnriched(rawStations));
  }, []);
  return enriched;
}

function TransitMap({ system, hour, day, weather, event }) {
  const hourMul = (h) => {
    if (h>=7 && h<=9) return { am: 1.0, pm: 0.0, level: 0.95 };
    if (h>=16 && h<=18) return { am: 0.0, pm: 1.0, level: 1.0 };
    if (h>=10 && h<=15) return { am: 0.3, pm: 0.4, level: 0.55 };
    if (h>=19 && h<=21) return { am: 0.0, pm: 0.55, level: 0.6 };
    if (h>=22 || h<=4) return { am: 0.0, pm: 0.05, level: 0.18 };
    return { am: 0.7, pm: 0.0, level: 0.45 };
  };
  const dowMul = (d) => (d===0||d===6) ? 0.55 : 1.0;
  const wxMul = (w) => w==='rain' ? 0.78 : w==='hot' ? 0.88 : 1.0;
  const evMul = (e) => e==='major' ? 1.0 : e==='small' ? 0.4 : 0;

  const rawBart = system === 'bart' ? BART_STATIONS : null;
  const bartWithRealData = useBartRidership(rawBart || []);
  const stations = system === 'bart' ? bartWithRealData : VTA_STATIONS;
  const lines = system === 'bart' ? BART_LINES : VTA_LINES;
  const stationById = useMemo(() => Object.fromEntries(stations.map(s => [s.id, s])), [stations]);

  const heat = useMemo(() => {
    const h = hourMul(hour);
    const dM = dowMul(day);
    const wM = wxMul(weather);
    const eM = evMul(event);
    return stations.map(s => {
      const baseHr = s.baseAM * h.am + s.basePM * h.pm + 0.45 * h.level;
      let v = baseHr * dM * wM;
      v += s.eventBoost * eM;
      if (s.type === 'core') v = Math.max(v, 0.55);
      if (s.type === 'commuter' && (day===0||day===6)) v *= 0.6;
      return Math.max(0.05, Math.min(2.4, v));
    });
  }, [stations, hour, day, weather, event]);

  const heatColor = (v) => {
    const t = Math.min(1, v / 2.0);
    const a = [47,143,91];
    const b = [212,166,74];
    const c = [238,108,77];
    let r,g,bl;
    if (t < 0.5) {
      const u = t / 0.5;
      r = a[0] + (b[0]-a[0])*u; g = a[1] + (b[1]-a[1])*u; bl = a[2] + (b[2]-a[2])*u;
    } else {
      const u = (t - 0.5)/0.5;
      r = b[0] + (c[0]-b[0])*u; g = b[1] + (c[1]-b[1])*u; bl = b[2] + (c[2]-b[2])*u;
    }
    return `rgb(${r|0},${g|0},${bl|0})`;
  };

  const linePaths = lines.map((ln, idx) => {
    const pts = ln.ids.map(id => stationById[id]).filter(Boolean);
    const d = pts.map((p,i) => `${i?'L':'M'}${p.x},${p.y}`).join(' ');
    return <path key={idx} d={d} fill="none" stroke={ln.c} strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.55" />;
  });

  const vb = system === 'bart' ? '60 30 600 500' : '40 60 620 500';
  const ranked = stations.map((s,i) => ({ s, v: heat[i] })).sort((a,b) => b.v - a.v);
  const hotIds = new Set(ranked.slice(0,3).map(r => r.s.id));

  return (
    <svg viewBox={vb} width="100%" style={{ display:'block', borderRadius: 'var(--radius-sm)' }}>
      <defs>
        <radialGradient id="bg-glow" cx="50%" cy="50%" r="60%">
          <stop offset="0%" stopColor="var(--bg-elev)" />
          <stop offset="100%" stopColor="var(--bg)" />
        </radialGradient>
        <filter id="halo" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="6" />
        </filter>
      </defs>
      <rect x="0" y="0" width="800" height="600" fill="url(#bg-glow)" />
      {Array.from({length:14}).map((_,i)=>(
        <line key={'gv'+i} x1={i*55} x2={i*55} y1="0" y2="600" stroke="var(--line)" strokeWidth="0.5" opacity="0.5" />
      ))}
      {Array.from({length:11}).map((_,i)=>(
        <line key={'gh'+i} x1="0" x2="800" y1={i*55} y2={i*55} stroke="var(--line)" strokeWidth="0.5" opacity="0.5" />
      ))}
      {linePaths}
      {stations.map((s,i)=>{
        const v = heat[i];
        const r = 6 + v * 16;
        return (
          <circle key={'h'+s.id} cx={s.x} cy={s.y} r={r} fill={heatColor(v)} opacity={Math.min(0.55, 0.2 + v*0.18)} filter="url(#halo)" />
        );
      })}
      {stations.map((s,i)=>{
        const v = heat[i];
        const isHot = hotIds.has(s.id);
        return (
          <g key={s.id}>
            <circle cx={s.x} cy={s.y} r={isHot?6:4.2} fill="var(--bg-elev)" stroke={heatColor(v)} strokeWidth={isHot?2.5:2} />
            {isHot && (
              <g>
                <rect x={s.x+8} y={s.y-15} width={s.nm.length*5.4+12} height="18" rx="4" fill="var(--bg-elev)" stroke="var(--line)" />
                <text x={s.x+14} y={s.y-2} fontFamily="var(--mono)" fontSize="10" fill="var(--ink)">{s.nm} · {(v*22).toFixed(0)} ons/hr</text>
              </g>
            )}
          </g>
        );
      })}
      <g transform="translate(70, 540)">
        <rect x="0" y="-22" width="220" height="36" rx="6" fill="var(--bg-elev)" stroke="var(--line)" />
        <text x="10" y="-8" fontSize="9" fontFamily="var(--mono)" fill="var(--ink-muted)" letterSpacing="1">RUSH HEAT</text>
        {[0.1, 0.5, 1.0, 1.5, 2.0].map((v,i) => (
          <g key={i}>
            <rect x={10 + i*40} y={0} width={36} height={10} fill={heatColor(v)} />
          </g>
        ))}
        <text x="10" y="20" fontSize="9" fontFamily="var(--mono)" fill="var(--ink-muted)">light</text>
        <text x="200" y="20" fontSize="9" fontFamily="var(--mono)" fill="var(--ink-muted)" textAnchor="end">heavy</text>
      </g>
    </svg>
  );
}

window.TransitMap = TransitMap;
window.BART_STATIONS = BART_STATIONS;
window.VTA_STATIONS = VTA_STATIONS;
window.useBartRidership = useBartRidership;