/* Shared interaction primitives for the page (S11-06).
   Loaded before charts.jsx and sections.jsx; every name here is prefixed or
   specific enough not to clash with theirs (all .jsx files share one global
   scope), and each is read only inside component bodies, at render time.

   - Model highlight: one page-wide "highlighted model" (a modelKey() value or
     null) behind React.useSyncExternalStore, so no Provider is needed.
   - useSort / SortTh: sortable table columns with aria-sort.
   - Disclosure: a button with aria-expanded whose panel opens by animating
     grid-template-rows; the closed panel is visibility:hidden (out of the tab
     order and the accessibility tree).
   - usePeek: hover (mouse only) or keyboard focus previews a panel; a click or
     tap pins it open, a second one closes it; Escape closes it.
   Reduced motion is handled in styles.css (prefers-reduced-motion). */

/* ── Page-wide model highlight ───────────────────────────────────── */
const __mhl = { key: null, subs: new Set() };
const __mhlSubscribe = cb => { __mhl.subs.add(cb); return () => { __mhl.subs.delete(cb); }; };
const __mhlGet = () => __mhl.key;
const setModelHighlight = k => {
  __mhl.key = k || null;
  __mhl.subs.forEach(f => f());
};
// [highlightedKey, toggle(key)]: toggling the highlighted key clears it.
const useModelHighlight = () => {
  const key = React.useSyncExternalStore(__mhlSubscribe, __mhlGet, __mhlGet);
  return [key, k => setModelHighlight(__mhl.key === k ? null : k)];
};

// A model name in a table: toggles that model's highlight across the page.
const ModelBtn = ({ k, children }) => {
  const [hl, toggle] = useModelHighlight();
  if (!k) return <>{children}</>;
  const on = hl === k;
  return (
    <button type="button" className="model-btn" aria-pressed={on} onClick={() => toggle(k)}
      title={on ? 'Click to clear the highlight' : 'Click to highlight this model in every table and chart'}>
      {children}
    </button>
  );
};

// Fixed chip naming the highlighted model, with a clear button.
const ModelHighlightChip = () => {
  const [hl] = useModelHighlight();
  const m = hl && typeof FC_MODELS !== 'undefined' ? FC_MODELS[hl] : null;
  return (
    <div className="hl-chip-wrap" aria-live="polite">
      {m && (
        <div className="hl-chip">
          <span className="sw" style={{ background: m.color }} aria-hidden="true" />
          <span>Highlighting <b>{m.short}</b></span>
          <button type="button" onClick={() => setModelHighlight(null)}>Clear</button>
        </div>
      )}
    </div>
  );
};

/* ── Sortable columns ─────────────────────────────────────────────
   useSort(): { sort:{key,dir}, onSort(key), apply(rows, getters) }. Rows keep
   their original order until a header is clicked; the first click sorts
   ascending, the next flips it. Getters return raw values; null/undefined/NaN
   sort last in either direction; strings compare with localeCompare. */
const useSort = () => {
  const [sort, setSort] = React.useState({ key: null, dir: 'asc' });
  const onSort = key => setSort(p => (p.key === key ? { key, dir: p.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }));
  const apply = (rows, getters) => {
    const g = sort.key && getters[sort.key];
    if (!g) return rows;
    const bad = v => v == null || (typeof v === 'number' && !isFinite(v));
    const sgn = sort.dir === 'asc' ? 1 : -1;
    return rows.map((r, i) => ({ r, i })).sort((a, b) => {
      const x = g(a.r), y = g(b.r);
      if (bad(x) || bad(y)) return bad(x) && bad(y) ? a.i - b.i : bad(x) ? 1 : -1;
      const c = typeof x === 'string' ? x.localeCompare(y) : x - y;
      return c ? c * sgn : a.i - b.i;
    }).map(o => o.r);
  };
  return { sort, onSort, apply };
};

// `sub` renders after the sort icon (e.g. a second header line).
const SortTh = ({ k, s, children, sub, className, style, title }) => {
  const active = s.sort.key === k;
  return (
    <th className={className} style={style} title={title}
      aria-sort={active ? (s.sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}>
      <button type="button" className={`sort-btn${active ? ' on' : ''}`} onClick={() => s.onSort(k)}>
        {children}
        <span className="sort-ic" aria-hidden="true">{active ? (s.sort.dir === 'asc' ? '▲' : '▼') : '↕'}</span>
        {sub}
      </button>
    </th>
  );
};

/* ── Disclosure: button + animated panel ─────────────────────────── */
let __discSeq = 0;
const useUid = prefix => {
  const ref = React.useRef(null);
  if (ref.current == null) ref.current = `${prefix}-${++__discSeq}`;
  return ref.current;
};

const Disclosure = ({ label, openLabel, className = '', children, defaultOpen = false }) => {
  const [open, setOpen] = React.useState(defaultOpen);
  const id = useUid('disc');
  return (
    <div className={`disc ${open ? 'open' : ''} ${className}`}>
      <button type="button" className="disc-btn" aria-expanded={open} aria-controls={id} onClick={() => setOpen(o => !o)}>
        <span className="chev" aria-hidden="true">▸</span>{open && openLabel ? openLabel : label}
      </button>
      <div className="collapse" id={id}>
        <div className="collapse-in">{children}</div>
      </div>
    </div>
  );
};

/* ── usePeek: hover / keyboard focus preview, click or tap pins ──────
   open = pinned (true/false) when set, else hovered (mouse) or focused by
   keyboard. Spread `bind` on the wrapper and call `toggle` from its button. */
const __focusVisible = el => { try { return el.matches(':focus-visible'); } catch (e) { return true; } };
const usePeek = () => {
  const [hover, setHover] = React.useState(false);
  const [kbd, setKbd] = React.useState(false);
  const [pinned, setPinned] = React.useState(null);
  const open = pinned != null ? pinned : (hover || kbd);
  const unpinClosed = () => setPinned(p => (p === false ? null : p));
  const bind = {
    onPointerEnter: e => { if (e.pointerType === 'mouse') setHover(true); },
    onPointerLeave: e => { if (e.pointerType === 'mouse') { setHover(false); unpinClosed(); } },
    onFocus: e => { if (__focusVisible(e.target)) setKbd(true); },
    onBlur: e => { if (!e.currentTarget.contains(e.relatedTarget)) { setKbd(false); unpinClosed(); } },
    onKeyDown: e => {
      if (e.key !== 'Escape' || !open) return;
      e.stopPropagation();
      setPinned(false);
      // Focus inside the closing panel would be lost; return it to the toggle.
      const btn = e.currentTarget.querySelector('[aria-expanded]');
      if (btn && e.target !== btn) btn.focus();
    },
  };
  const toggle = () => setPinned(p => (p === true ? false : true));
  return { open, pinned: pinned === true, bind, toggle };
};

Object.assign(window, {
  setModelHighlight, useModelHighlight, ModelBtn, ModelHighlightChip,
  useSort, SortTh, Disclosure, useUid, usePeek,
});
