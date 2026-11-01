/* Route assistant chat panel (BART, VTA, Caltrain).

   window.TransitAssistant.mount(el, { apiBase, onRoute })
     apiBase  the transit-assistant service; defaults to ASSISTANT_URL below,
              overridable with ?assistant=<url> for local testing.
     onRoute  called with { option, path } when an option is shown or picked;
              path is [[lat, lng], ...] decoded from Google's encoded polyline
              (a straight origin -> destination line when there is none).

   POST {apiBase}/chat streams NDJSON: follow_up | form | options, text*,
   replace?, caveats, done. Options paint first; text deltas follow into an
   aria-live region. Rider text and service text are set with textContent only. */
(function () {
  'use strict';

  /* The one place the service URL lives. Empty until Task 8 deploys it. */
  var ASSISTANT_URL = 'https://transit-assistant-308878596074.us-west2.run.app';
  var MAX_CHARS = 500;
  var WAKING_MS = 1500;

  function h(tag, attrs, kids) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'text') el.textContent = attrs[k];
      else if (k === 'cls') el.className = attrs[k];
      else el.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return el;
  }

  /* Google encoded polyline -> [[lat, lng], ...] */
  function decodePolyline(str) {
    var pts = [], i = 0, lat = 0, lng = 0;
    while (str && i < str.length) {
      var vals = [0, 0];
      for (var k = 0; k < 2; k++) {
        var shift = 0, result = 0, b;
        do { b = str.charCodeAt(i++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20 && i < str.length);
        vals[k] = (result & 1) ? ~(result >> 1) : (result >> 1);
      }
      lat += vals[0]; lng += vals[1];
      pts.push([lat / 1e5, lng / 1e5]);
    }
    return pts;
  }

  function pathOf(opt) {
    var p = opt.polyline ? decodePolyline(opt.polyline) : [];
    if (p.length < 2 && opt.origin_latlng && opt.dest_latlng) p = [opt.origin_latlng, opt.dest_latlng];
    return p;
  }

  function apiBaseFrom(opts) {
    var q = null;
    try { q = new URLSearchParams(location.search).get('assistant'); } catch (e) { /* old browser */ }
    var base = q || (opts && opts.apiBase) || ASSISTANT_URL;
    return (base || '').replace(/\/+$/, '');
  }

  function localIso() {
    var d = new Date(), off = -d.getTimezoneOffset(), s = off >= 0 ? '+' : '-', a = Math.abs(off);
    var p = function (n) { return String(n).padStart(2, '0'); };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + 'T' + p(d.getHours()) + ':' +
      p(d.getMinutes()) + ':' + p(d.getSeconds()) + s + p(Math.floor(a / 60)) + ':' + p(a % 60);
  }

  function mount(root, opts) {
    opts = opts || {};
    var api = apiBaseFrom(opts);
    var onRoute = typeof opts.onRoute === 'function' ? opts.onRoute : null;
    var uid = 'ta' + Math.random().toString(36).slice(2, 8);
    var busy = false, ctrl = null;

    root.classList.add('ta');
    var input = h('input', { type: 'text', id: uid + '-q', maxlength: String(MAX_CHARS), autocomplete: 'off',
      placeholder: 'e.g. From Mountain View to SAP Center at 6 pm', 'aria-describedby': uid + '-hint' });
    var send = h('button', { type: 'submit', cls: 'ta-send', text: 'Ask' });
    var form = h('form', { cls: 'ta-ask', role: 'search' }, [
      h('label', { for: uid + '-q', cls: 'ta-label', text: 'Ask for a transit route' }),
      h('div', { cls: 'ta-row' }, [input, send]),
      h('div', { cls: 'ta-hint', id: uid + '-hint', text: 'BART, VTA and Caltrain trips in the Bay Area. Up to ' + MAX_CHARS + ' characters.' })
    ]);
    var status = h('div', { cls: 'ta-status', role: 'status', 'aria-live': 'polite' });
    var cards = h('ol', { cls: 'ta-cards', 'aria-label': 'Route options' });
    var text = h('div', { cls: 'ta-text', 'aria-live': 'polite', 'aria-atomic': 'false' });
    var extra = h('div', { cls: 'ta-extra' });
    var out = h('div', { cls: 'ta-out', 'aria-busy': 'false' }, [status, cards, text, extra]);
    root.appendChild(form);
    root.appendChild(out);

    if (!api) {
      status.textContent = 'The route assistant is not connected yet.';
    }

    form.addEventListener('submit', function (e) { e.preventDefault(); ask(input.value); });

    function reset() {
      status.textContent = ''; status.className = 'ta-status';
      cards.textContent = ''; text.textContent = ''; extra.textContent = '';
    }

    function note(msg, kind) { status.textContent = msg; status.className = 'ta-status' + (kind ? ' ta-' + kind : ''); }

    function select(btns, i, opt) {
      btns.forEach(function (b, j) { b.setAttribute('aria-pressed', j === i ? 'true' : 'false'); });
      if (onRoute) { try { onRoute({ option: opt, path: pathOf(opt) }); } catch (e) { /* the map is optional */ } }
    }

    function renderOptions(ev) {
      var list = ev.options || [];
      if (!list.length) {
        var msg = ev.error === 'routing_unavailable'
          ? 'Route planning is unavailable right now.'
          : 'No BART, VTA or Caltrain route was found for that trip.';
        note(msg, 'warn');
        if (ev.maps_link && /^https:\/\/www\.google\.com\/maps\//.test(ev.maps_link)) {
          extra.appendChild(h('p', { cls: 'ta-link' }, [
            h('a', { href: ev.maps_link, target: '_blank', rel: 'noopener noreferrer', text: 'Open this trip in Google Maps' })
          ]));
        }
        return;
      }
      note('');
      var btns = [];
      list.forEach(function (o, i) {
        var chips = h('span', { cls: 'ta-chips' }, (o.agencies || []).map(function (a) {
          return h('span', { cls: 'ta-chip ta-ag-' + String(a).toLowerCase().replace(/[^a-z]/g, ''), text: a });
        }));
        var meta = [];
        meta.push(o.transfers === 0 ? 'No transfers' : o.transfers + (o.transfers === 1 ? ' transfer' : ' transfers'));
        if (o.walk_minutes != null) meta.push(o.walk_minutes + ' min walk');
        var btn = h('button', { type: 'button', cls: 'ta-card', 'aria-pressed': 'false' }, [
          h('span', { cls: 'ta-rank', text: '#' + (o.rank || i + 1) }),
          h('span', { cls: 'ta-mins' }, [h('b', { text: String(o.minutes != null ? o.minutes : Math.round(o.duration_s / 60)) }), ' min']),
          h('span', { cls: 'ta-times', text: (o.depart_display || '') + ' → ' + (o.arrive_display || '') }),
          chips,
          h('span', { cls: 'ta-meta', text: meta.join(' · ') })
        ]);
        btn.addEventListener('click', function () { select(btns, i, o); });
        btns.push(btn);
        cards.appendChild(h('li', null, [btn]));
      });
      if (ev.attribution) extra.appendChild(h('p', { cls: 'ta-attr', text: ev.attribution }));
      select(btns, 0, list[0]);
    }

    function renderCaveats(ev) {
      var items = (ev.notes || []).slice();
      if (ev.missing && ev.missing.length) items.push('Some live details were unavailable: ' + ev.missing.join(', ') + '.');
      if (!items.length) return;
      var ul = h('ul', { cls: 'ta-caveats', 'aria-label': 'Notes' });
      items.forEach(function (t) { ul.appendChild(h('li', { text: t })); });
      extra.insertBefore(ul, extra.firstChild);
    }

    function renderForm() {
      note('I could not read a trip from that. Fill in where you are going:', 'warn');
      var f = h('form', { cls: 'ta-form' });
      function field(name, label, type, ph) {
        var id = uid + '-' + name;
        var inp = h('input', { id: id, name: name, type: type, maxlength: '120', placeholder: ph || '' });
        f.appendChild(h('div', { cls: 'ta-field' }, [h('label', { for: id, text: label }), inp]));
        return inp;
      }
      var from = field('from', 'From', 'text', 'Station or place');
      var to = field('to', 'To', 'text', 'Station or place');
      var at = field('at', 'Leave at (optional)', 'time');
      from.required = true; to.required = true;
      f.appendChild(h('button', { type: 'submit', cls: 'ta-send', text: 'Find routes' }));
      f.addEventListener('submit', function (e) {
        e.preventDefault();
        var msg = 'From ' + from.value.trim() + ' to ' + to.value.trim() + (at.value ? ' at ' + at.value : '');
        input.value = msg.slice(0, MAX_CHARS);
        ask(input.value);
      });
      extra.appendChild(f);
      from.focus();
    }

    function handle(ev) {
      switch (ev.type) {
        case 'options': renderOptions(ev); break;
        case 'text': text.appendChild(document.createTextNode(ev.delta || '')); break;
        case 'replace': text.textContent = ev.text || ''; break;
        case 'caveats': renderCaveats(ev); break;
        case 'follow_up': note(ev.question || 'Could you tell me more about the trip?', 'ask'); input.focus(); break;
        case 'form': renderForm(); break;
        default: break; /* done, and anything newer */
      }
    }

    function friendly(status, body, retry) {
      if (status === 429) {
        var m = parseInt(retry, 10);
        return 'You have asked a lot of questions this hour. Please try again' +
          (m > 0 ? ' in about ' + Math.max(1, Math.ceil(m / 60)) + ' min.' : ' a little later.');
      }
      if (status === 400) {
        if (body && body.error === 'message_too_long') return 'Please keep your question under ' + MAX_CHARS + ' characters.';
        return 'Please type a question, for example “From Berkeley to SFO at 8 am”.';
      }
      if (status === 503) return 'The assistant is starting up. Please try again in a few seconds.';
      return 'Something went wrong on our side. Please try again.';
    }

    async function ask(raw) {
      var message = (raw || '').trim();
      if (!message) { note('Please type a question first.', 'warn'); input.focus(); return; }
      if (!api) { note('The route assistant is not connected yet.', 'warn'); return; }
      if (busy && ctrl) ctrl.abort();
      reset();
      busy = true; ctrl = new AbortController();
      var mine = ctrl;
      out.setAttribute('aria-busy', 'true'); send.disabled = true;
      var got = false;
      var waking = setTimeout(function () { if (!got) note('Waking the assistant up…'); }, WAKING_MS);
      note('Finding routes…');
      try {
        var resp = await fetch(api + '/chat', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: message, client_time: localIso() }), signal: mine.signal
        });
        if (!resp.ok) {
          var body = null;
          try { body = await resp.json(); } catch (e) { /* not JSON */ }
          got = true; note(friendly(resp.status, body, resp.headers.get('Retry-After')), 'err');
          return;
        }
        var reader = resp.body.getReader(), dec = new TextDecoder(), buf = '';
        for (;;) {
          var r = await reader.read();
          if (r.done) break;
          buf += dec.decode(r.value, { stream: true });
          var lines = buf.split('\n'); buf = lines.pop();
          lines.forEach(function (line) {
            if (!line.trim()) return;
            var ev; try { ev = JSON.parse(line); } catch (e) { return; }
            if (!got) { got = true; note(''); }
            handle(ev);
          });
        }
        buf += dec.decode();
        if (buf.trim()) { try { got = true; handle(JSON.parse(buf)); } catch (e) { /* partial line */ } }
        if (!got) note('No answer came back. Please try again.', 'err');
      } catch (e) {
        if (e && e.name === 'AbortError') return;
        note('Could not reach the route assistant. Check your connection and try again.', 'err');
      } finally {
        clearTimeout(waking);
        if (ctrl === mine) { busy = false; out.setAttribute('aria-busy', 'false'); send.disabled = false; }
      }
    }

    return { ask: ask };
  }

  window.TransitAssistant = { mount: mount, decodePolyline: decodePolyline };
})();
