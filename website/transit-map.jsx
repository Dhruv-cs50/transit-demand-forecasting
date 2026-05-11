/* Leaflet-based transit maps with rush-heat overlays for BART + VTA.
   Requires Leaflet CSS+JS loaded in <head> before this file. */

const { useMemo, useState, useEffect, useRef } = React;

/* ── BART stations — real lat/lng + SVG x,y kept for data compatibility ─── */
const BART_STATIONS = [
  { id:'rich', nm:'Richmond',          lat:37.9372, lng:-122.3531, x:215, y:60,  type:'commuter', baseAM:1.4, basePM:1.1, eventBoost:0 },
  { id:'elc',  nm:'El Cerrito',        lat:37.9252, lng:-122.3170, x:230, y:95,  type:'commuter', baseAM:1.2, basePM:1.0, eventBoost:0 },
  { id:'nbk',  nm:'N. Berkeley',       lat:37.8741, lng:-122.2832, x:250, y:130, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'bky',  nm:'Berkeley',          lat:37.8699, lng:-122.2681, x:270, y:165, type:'urban',    baseAM:1.6, basePM:1.5, eventBoost:0 },
  { id:'mac',  nm:'MacArthur',         lat:37.8286, lng:-122.2672, x:295, y:220, type:'transfer', baseAM:1.7, basePM:1.6, eventBoost:0 },
  { id:'ant',  nm:'Antioch',           lat:37.9959, lng:-121.7806, x:470, y:50,  type:'commuter', baseAM:1.6, basePM:0.6, eventBoost:0 },
  { id:'pit',  nm:'Pittsburg',         lat:38.0183, lng:-121.9456, x:425, y:80,  type:'commuter', baseAM:1.5, basePM:0.7, eventBoost:0 },
  { id:'ccd',  nm:'Concord',           lat:37.9732, lng:-122.0290, x:390, y:115, type:'commuter', baseAM:1.4, basePM:0.8, eventBoost:0 },
  { id:'plh',  nm:'Pleasant Hill',     lat:37.9279, lng:-122.0571, x:365, y:150, type:'commuter', baseAM:1.3, basePM:0.9, eventBoost:0 },
  { id:'lfy',  nm:'Lafayette',         lat:37.8934, lng:-122.1238, x:345, y:185, type:'commuter', baseAM:1.2, basePM:0.9, eventBoost:0 },
  { id:'orn',  nm:'Orinda',            lat:37.8784, lng:-122.1834, x:325, y:215, type:'commuter', baseAM:1.1, basePM:0.9, eventBoost:0 },
  { id:'rkr',  nm:'Rockridge',         lat:37.8445, lng:-122.2512, x:312, y:240, type:'commuter', baseAM:1.0, basePM:0.95,eventBoost:0 },
  { id:'12th', nm:'12th St / Oakland', lat:37.8031, lng:-122.2716, x:305, y:270, type:'transfer', baseAM:1.9, basePM:1.9, eventBoost:0.4 },
  { id:'19th', nm:'19th St / Oakland', lat:37.8083, lng:-122.2693, x:295, y:250, type:'transfer', baseAM:1.7, basePM:1.7, eventBoost:0 },
  { id:'lkm',  nm:'Lake Merritt',      lat:37.7979, lng:-122.2651, x:320, y:295, type:'urban',    baseAM:1.4, basePM:1.4, eventBoost:0 },
  { id:'fvw',  nm:'Fruitvale',         lat:37.7750, lng:-122.2242, x:360, y:320, type:'urban',    baseAM:1.3, basePM:1.3, eventBoost:0 },
  { id:'col',  nm:'Coliseum',          lat:37.7539, lng:-122.1977, x:395, y:345, type:'transfer', baseAM:1.0, basePM:1.0, eventBoost:0.9 },
  { id:'sl',   nm:'San Leandro',       lat:37.7222, lng:-122.1609, x:425, y:375, type:'commuter', baseAM:1.1, basePM:1.0, eventBoost:0 },
  { id:'bayp', nm:'Bay Fair',          lat:37.6970, lng:-122.1272, x:455, y:405, type:'transfer', baseAM:1.0, basePM:0.95,eventBoost:0 },
  { id:'hyw',  nm:'Hayward',           lat:37.6695, lng:-122.0872, x:485, y:425, type:'commuter', baseAM:1.0, basePM:0.95,eventBoost:0 },
  { id:'unc',  nm:'Union City',        lat:37.5908, lng:-122.0174, x:515, y:450, type:'commuter', baseAM:1.0, basePM:0.95,eventBoost:0 },
  { id:'frm',  nm:'Fremont',           lat:37.5574, lng:-121.9763, x:540, y:478, type:'commuter', baseAM:1.05,basePM:0.95,eventBoost:0 },
  { id:'brb',  nm:'Berryessa',         lat:37.4479, lng:-121.9007, x:555, y:498, type:'commuter', baseAM:1.0, basePM:0.95,eventBoost:0 },
  { id:'wo',   nm:'West Oakland',      lat:37.8046, lng:-122.2949, x:260, y:285, type:'urban',    baseAM:1.3, basePM:1.5, eventBoost:0 },
  { id:'emb',  nm:'Embarcadero',       lat:37.7930, lng:-122.3969, x:175, y:305, type:'core',     baseAM:2.4, basePM:2.5, eventBoost:0.2 },
  { id:'mtg',  nm:'Montgomery',        lat:37.7892, lng:-122.4014, x:150, y:320, type:'core',     baseAM:2.6, basePM:2.7, eventBoost:0.2 },
  { id:'pwl',  nm:'Powell',            lat:37.7844, lng:-122.4080, x:130, y:340, type:'core',     baseAM:2.3, basePM:2.4, eventBoost:0.3 },
  { id:'cvc',  nm:'Civic Center',      lat:37.7796, lng:-122.4137, x:115, y:360, type:'core',     baseAM:2.0, basePM:2.1, eventBoost:0.2 },
  { id:'16th', nm:'16th St Mission',   lat:37.7650, lng:-122.4194, x:105, y:385, type:'urban',    baseAM:1.5, basePM:1.7, eventBoost:0 },
  { id:'24th', nm:'24th St Mission',   lat:37.7524, lng:-122.4181, x:100, y:410, type:'urban',    baseAM:1.4, basePM:1.6, eventBoost:0 },
  { id:'gln',  nm:'Glen Park',         lat:37.7328, lng:-122.4345, x:105, y:435, type:'urban',    baseAM:1.1, basePM:1.2, eventBoost:0 },
  { id:'bls',  nm:'Balboa Park',       lat:37.7219, lng:-122.4475, x:115, y:458, type:'urban',    baseAM:1.1, basePM:1.2, eventBoost:0 },
  { id:'daly', nm:'Daly City',         lat:37.7061, lng:-122.4690, x:130, y:480, type:'transfer', baseAM:1.2, basePM:1.1, eventBoost:0 },
  { id:'colm', nm:'Colma',             lat:37.6844, lng:-122.4669, x:150, y:500, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'ssf',  nm:'S. San Francisco',  lat:37.6547, lng:-122.4437, x:175, y:510, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'sbr',  nm:'San Bruno',         lat:37.6302, lng:-122.4120, x:200, y:510, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'mil',  nm:'Millbrae',          lat:37.5995, lng:-122.3869, x:235, y:510, type:'transfer', baseAM:1.2, basePM:1.0, eventBoost:0 },
  { id:'sfo',  nm:'SFO Airport',       lat:37.6162, lng:-122.3924, x:220, y:488, type:'airport',  baseAM:1.5, basePM:1.5, eventBoost:0 },
  { id:'cas',  nm:'Castro Valley',     lat:37.6902, lng:-121.9825, x:510, y:380, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'dub',  nm:'Dublin/Pleasanton', lat:37.7016, lng:-121.8998, x:555, y:360, type:'commuter', baseAM:1.3, basePM:0.7, eventBoost:0 },
  { id:'wdb',  nm:'W. Dublin',         lat:37.6995, lng:-121.9287, x:530, y:370, type:'commuter', baseAM:1.1, basePM:0.8, eventBoost:0 },
];

const BART_LINES = [
  { c:'#f04e23', ids:['rich','elc','nbk','bky','mac','19th','12th','wo','emb','mtg','pwl','cvc','16th','24th','gln','bls','daly','colm','ssf','sbr','mil'] },
  { c:'#fdb62a', ids:['ant','pit','ccd','plh','lfy','orn','rkr','mac','19th','12th','wo','emb','mtg','pwl','cvc','16th','24th','gln','bls','daly','colm','ssf','sbr','sfo','mil'] },
  { c:'#0099d8', ids:['dub','wdb','cas','bayp','sl','col','fvw','lkm','12th','19th','mac','rkr','orn','lfy','plh','ccd','pit','ant'] },
  { c:'#1a8a3f', ids:['brb','frm','unc','hyw','bayp','sl','col','fvw','lkm','12th','wo','emb','mtg','pwl','cvc','daly'] },
];

/* ── VTA stations — approximate lat/lng for Silicon Valley corridors ─── */
const VTA_STATIONS = [
  { id:'mtv',   nm:'Mountain View',       lat:37.3943, lng:-122.0761, x:70,  y:90,  type:'transfer', baseAM:1.4, basePM:1.2, eventBoost:0 },
  { id:'evv',   nm:'Evelyn',              lat:37.3870, lng:-122.0553, x:110, y:95,  type:'urban',    baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'win',   nm:'Whisman',             lat:37.3838, lng:-122.0327, x:145, y:102, type:'urban',    baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'msv',   nm:'Middlefield',         lat:37.3815, lng:-122.0097, x:180, y:110, type:'urban',    baseAM:0.95,basePM:0.85,eventBoost:0 },
  { id:'baytm', nm:'Bayshore/NASA',       lat:37.3845, lng:-121.9824, x:215, y:118, type:'commuter', baseAM:1.4, basePM:0.7, eventBoost:0 },
  { id:'rmt',   nm:'Reamwood',            lat:37.3787, lng:-121.9618, x:250, y:125, type:'urban',    baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'old',   nm:'Old Ironsides',       lat:37.3504, lng:-121.9525, x:290, y:132, type:'transfer', baseAM:1.3, basePM:1.0, eventBoost:1.4 },
  { id:'lck',   nm:'Lick Mill',           lat:37.3622, lng:-121.9493, x:320, y:145, type:'urban',    baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'gsh',   nm:'Great America',       lat:37.3990, lng:-121.9764, x:350, y:158, type:'urban',    baseAM:1.0, basePM:0.9, eventBoost:1.5 },
  { id:'tas',   nm:'Tasman',              lat:37.4053, lng:-121.9533, x:400, y:175, type:'transfer', baseAM:1.2, basePM:1.0, eventBoost:0 },
  { id:'rvr',   nm:'River Oaks',          lat:37.4100, lng:-121.9350, x:425, y:200, type:'urban',    baseAM:0.95,basePM:0.85,eventBoost:0 },
  { id:'orc',   nm:'Orchard',             lat:37.4135, lng:-121.9200, x:440, y:230, type:'urban',    baseAM:0.95,basePM:0.85,eventBoost:0 },
  { id:'bry',   nm:'Bonaventura',         lat:37.4175, lng:-121.9080, x:450, y:260, type:'urban',    baseAM:0.95,basePM:0.85,eventBoost:0 },
  { id:'cnv',   nm:'Component',           lat:37.4218, lng:-121.8950, x:460, y:295, type:'urban',    baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'krn',   nm:'Karina',              lat:37.4266, lng:-121.8820, x:470, y:325, type:'urban',    baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'mtfair',nm:'Metro/Airport',       lat:37.3685, lng:-121.9280, x:460, y:350, type:'transfer', baseAM:1.4, basePM:1.3, eventBoost:0 },
  { id:'gish',  nm:'Gish',               lat:37.3581, lng:-121.9133, x:445, y:375, type:'urban',    baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'cvc',   nm:'Civic Center',        lat:37.3388, lng:-121.8894, x:425, y:400, type:'transfer', baseAM:1.4, basePM:1.3, eventBoost:0 },
  { id:'jpsq',  nm:'Japantown',          lat:37.3488, lng:-121.9080, x:405, y:420, type:'urban',    baseAM:1.1, basePM:1.0, eventBoost:0 },
  { id:'shc',   nm:'St James',            lat:37.3440, lng:-121.8950, x:385, y:440, type:'urban',    baseAM:1.2, basePM:1.1, eventBoost:0.3 },
  { id:'sntc',  nm:'Santa Clara',         lat:37.3519, lng:-121.9358, x:365, y:458, type:'transfer', baseAM:1.6, basePM:1.5, eventBoost:0.3 },
  { id:'pmd',   nm:'Paseo de S. Antonio', lat:37.3348, lng:-121.8894, x:348, y:478, type:'core',     baseAM:1.7, basePM:1.7, eventBoost:0.4 },
  { id:'sjc',   nm:'San Jose Diridon',    lat:37.3295, lng:-121.9023, x:330, y:498, type:'core',     baseAM:2.2, basePM:2.3, eventBoost:1.6 },
  { id:'cnvc',  nm:'Convention Center',   lat:37.3300, lng:-121.8836, x:360, y:510, type:'urban',    baseAM:1.3, basePM:1.4, eventBoost:0.6 },
  { id:'cit',   nm:"Children's Discovery",lat:37.3244, lng:-121.8750, x:388, y:522, type:'urban',    baseAM:1.0, basePM:0.95,eventBoost:0 },
  { id:'tam',   nm:'Tamien',              lat:37.3131, lng:-121.8771, x:415, y:540, type:'transfer', baseAM:1.3, basePM:1.2, eventBoost:0 },
  { id:'ctn',   nm:'Curtner',             lat:37.2980, lng:-121.8664, x:445, y:555, type:'urban',    baseAM:1.0, basePM:0.95,eventBoost:0 },
  { id:'cap',   nm:'Capitol',             lat:37.2890, lng:-121.8451, x:480, y:565, type:'urban',    baseAM:1.1, basePM:1.0, eventBoost:0 },
  { id:'brh',   nm:'Branham',             lat:37.2740, lng:-121.8281, x:515, y:565, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'orh',   nm:'Ohlone/Chynoweth',    lat:37.2570, lng:-121.8178, x:545, y:555, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'ble',   nm:'Blossom Hill',        lat:37.2430, lng:-121.8234, x:570, y:538, type:'commuter', baseAM:1.05,basePM:0.95,eventBoost:0 },
  { id:'snt',   nm:'Snell',               lat:37.2295, lng:-121.8329, x:590, y:515, type:'commuter', baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'stc',   nm:'Santa Teresa',        lat:37.2144, lng:-121.8260, x:605, y:488, type:'commuter', baseAM:1.05,basePM:0.95,eventBoost:0 },
  { id:'race',  nm:'Race',                lat:37.3296, lng:-121.9157, x:295, y:482, type:'urban',    baseAM:1.0, basePM:0.95,eventBoost:0 },
  { id:'fru',   nm:'Fruitdale',           lat:37.3240, lng:-121.9290, x:265, y:488, type:'urban',    baseAM:0.95,basePM:0.9, eventBoost:0 },
  { id:'bas',   nm:'Bascom',              lat:37.3188, lng:-121.9426, x:235, y:495, type:'urban',    baseAM:0.95,basePM:0.9, eventBoost:0 },
  { id:'haml',  nm:'Hamilton',            lat:37.3110, lng:-121.9553, x:205, y:502, type:'urban',    baseAM:1.0, basePM:0.9, eventBoost:0 },
  { id:'dws',   nm:'Downtown Campbell',   lat:37.2877, lng:-121.9394, x:175, y:510, type:'urban',    baseAM:1.05,basePM:1.0, eventBoost:0 },
  { id:'wch',   nm:'Winchester',          lat:37.2721, lng:-121.9470, x:140, y:518, type:'commuter', baseAM:1.1, basePM:0.95,eventBoost:0 },
];

const VTA_LINES = [
  { c:'#22a06b', ids:['mtv','evv','win','msv','baytm','rmt','old','lck','gsh','tas','rvr','orc','bry','cnv','krn','mtfair','gish','cvc','jpsq','shc','sntc','pmd','sjc','cnvc','cit','tam','ctn','cap','brh','orh','ble','snt','stc'] },
  { c:'#f08323', ids:['mtv','evv','win','msv','baytm','rmt','old','lck','gsh','tas','rvr','orc','bry','cnv','krn','mtfair','gish','cvc','jpsq','shc','sntc','pmd','sjc','race','fru','bas','haml','dws','wch'] },
  { c:'#0099d8', ids:['old','tas','sjc','tam','ctn','cap','brh','orh','ble','snt','stc'] },
];

/* ── Ridership enrichment hook ─────────────────────────────────────────── */
function useBartRidership(rawStations) {
  const [enriched, setEnriched] = useState(rawStations);
  useEffect(() => {
    if (!rawStations || rawStations.length === 0) { setEnriched(rawStations); return; }
    fetch('data/stations_ridership.json')
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => {
        setEnriched(rawStations.map(s => {
          const d = data[s.id];
          return d ? { ...s, baseAM: d.baseAM, basePM: d.basePM } : s;
        }));
      })
      .catch(() => setEnriched(rawStations));
  }, []);
  return enriched;
}

/* ── Heat color (green→amber→coral) ───────────────────────────────────── */
function heatColor(v) {
  const t = Math.min(1, v / 2.0);
  const a = [47,143,91], b = [212,166,74], c = [238,108,77];
  let r, g, bl;
  if (t < 0.5) {
    const u = t / 0.5;
    r = a[0]+(b[0]-a[0])*u; g = a[1]+(b[1]-a[1])*u; bl = a[2]+(b[2]-a[2])*u;
  } else {
    const u = (t-0.5)/0.5;
    r = b[0]+(c[0]-b[0])*u; g = b[1]+(c[1]-b[1])*u; bl = b[2]+(c[2]-b[2])*u;
  }
  return `rgb(${r|0},${g|0},${bl|0})`;
}

/* ── Heat computation ──────────────────────────────────────────────────── */
function computeHeat(stations, hour, day, weather, event) {
  const hourMul = (h) => {
    if (h>=7 && h<=9)  return { am:1.0, pm:0.0, level:0.95 };
    if (h>=16 && h<=18) return { am:0.0, pm:1.0, level:1.0 };
    if (h>=10 && h<=15) return { am:0.3, pm:0.4, level:0.55 };
    if (h>=19 && h<=21) return { am:0.0, pm:0.55,level:0.6 };
    if (h>=22 || h<=4)  return { am:0.0, pm:0.05,level:0.18 };
    return { am:0.7, pm:0.0, level:0.45 };
  };
  const hM = hourMul(hour);
  const dM = (day===0||day===6) ? 0.55 : 1.0;
  const wM = weather==='rain' ? 0.78 : weather==='hot' ? 0.88 : 1.0;
  const eM = event==='major' ? 1.0 : event==='small' ? 0.4 : 0;
  return stations.map(s => {
    let v = (s.baseAM*hM.am + s.basePM*hM.pm + 0.45*hM.level) * dM * wM + s.eventBoost*eM;
    if (s.type==='core') v = Math.max(v, 0.55);
    if (s.type==='commuter' && (day===0||day===6)) v *= 0.6;
    return Math.max(0.05, Math.min(2.4, v));
  });
}

/* ── Leaflet TransitMap ────────────────────────────────────────────────── */
function TransitMap({ system, hour, day, weather, event }) {
  const containerRef = useRef(null);
  const mapData = useRef({ map: null, markers: [], polylines: [] });
  const [mapReady, setMapReady] = useState(false);

  const rawBart = system === 'bart' ? BART_STATIONS : null;
  const bartEnriched = useBartRidership(rawBart || []);
  const stations = system === 'bart' ? bartEnriched : VTA_STATIONS;
  const lines = system === 'bart' ? BART_LINES : VTA_LINES;

  const heat = useMemo(
    () => computeHeat(stations, hour, day, weather, event),
    [stations, hour, day, weather, event]
  );

  /* Initialize map once on mount */
  useEffect(() => {
    const L = window.L;
    if (!L || !containerRef.current || mapData.current.map) return;

    const map = L.map(containerRef.current, {
      scrollWheelZoom: false,
      zoomControl: true,
    });

    L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
      {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
        maxZoom: 18,
      }
    ).addTo(map);

    mapData.current.map = map;
    setMapReady(true);

    return () => {
      map.remove();
      mapData.current.map = null;
      mapData.current.markers = [];
      mapData.current.polylines = [];
    };
  }, []);

  /* Recenter when system switches */
  useEffect(() => {
    const { map } = mapData.current;
    if (!map) return;
    if (system === 'bart') {
      map.setView([37.76, -122.27], 10, { animate: true });
    } else {
      map.setView([37.35, -121.92], 11, { animate: true });
    }
  }, [system, mapReady]);

  /* Redraw markers + lines whenever heat changes */
  useEffect(() => {
    const L = window.L;
    const { map } = mapData.current;
    if (!L || !map || !mapReady) return;

    /* clear previous */
    mapData.current.markers.forEach(m => m.remove());
    mapData.current.polylines.forEach(p => p.remove());
    mapData.current.markers = [];
    mapData.current.polylines = [];

    /* draw transit lines */
    const byId = Object.fromEntries(stations.map(s => [s.id, s]));
    lines.forEach(ln => {
      const pts = ln.ids.map(id => byId[id]).filter(s => s && s.lat && s.lng);
      if (pts.length < 2) return;
      const poly = L.polyline(
        pts.map(s => [s.lat, s.lng]),
        { color: ln.c, weight: 4, opacity: 0.7, lineJoin: 'round' }
      ).addTo(map);
      mapData.current.polylines.push(poly);
    });

    /* rank stations */
    const ranked = stations.map((s, i) => ({ s, v: heat[i] })).sort((a,b) => b.v-a.v);
    const hotIds = new Set(ranked.slice(0,3).map(r => r.s.id));

    /* draw station circles */
    stations.forEach((s, i) => {
      if (!s.lat || !s.lng) return;
      const v = heat[i];
      const col = heatColor(v);
      const isHot = hotIds.has(s.id);

      const m = L.circleMarker([s.lat, s.lng], {
        radius: 6 + v * 9,
        fillColor: col,
        fillOpacity: isHot ? 0.92 : 0.75,
        color: '#fff',
        weight: isHot ? 2.5 : 1.5,
      }).addTo(map);

      m.bindPopup(
        `<div style="font-family:system-ui,sans-serif;min-width:170px">
          <div style="font-weight:700;font-size:14px;margin-bottom:4px">${s.nm}</div>
          <div style="color:#555;font-size:12px;margin-bottom:6px">Type: ${s.type}</div>
          <div style="font-size:13px">Est. load: <b style="color:${col}">${(v*22).toFixed(0)}</b> ons/hr</div>
         </div>`,
        { maxWidth: 220 }
      );

      mapData.current.markers.push(m);
    });
  }, [mapReady, system, heat]);

  if (!window.L) {
    return (
      <div style={{ display:'flex', alignItems:'center', justifyContent:'center',
        height:480, color:'var(--ink-muted)', fontSize:14, textAlign:'center' }}>
        Leaflet not loaded — add leaflet.js to index.html
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      style={{ width:'100%', height:480, borderRadius:'var(--radius-sm)', zIndex:0 }}
    />
  );
}

window.TransitMap = TransitMap;
window.BART_STATIONS = BART_STATIONS;
window.VTA_STATIONS = VTA_STATIONS;
window.useBartRidership = useBartRidership;
