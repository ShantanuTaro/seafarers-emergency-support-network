/* Shared between all three portals: websocket plumbing, the map layers, and the
   handful of formatters. Kept deliberately small: three pages do not justify a
   framework, and a build step is one more thing to break at 3am. */

const SESN = (() => {
  const KINDS = ["container", "bulker", "tanker", "gas", "general", "roro",
                 "passenger", "fishing", "tug", "naval", "coastguard", "research"];
  const SEV = ["", "LOW", "MODERATE", "HIGH", "CRITICAL"];
  const NAV = {0: "under way (engine)", 1: "at anchor", 2: "not under command",
               5: "moored", 6: "AGROUND", 7: "fishing", 15: "undefined"};

  /* One vocabulary for the five recipient classes, shared by the operations console
     and the bridge terminal.

     `plain` is written for someone who has never seen this system. It sits under the
     packet header ashore and inside the crew's own view of what was done, and those
     two readings must not drift apart: a master asking "who is MRCC SIM-TASMAN and
     will they come" has to get the same answer the operator releasing the message
     was looking at. */
  const RECIPIENTS = {
    mrcc: {
      label: "Rescue coordination centre",
      plain: "The shore authority legally responsible for this stretch of ocean. It "
           + "decides who sails and directs the whole response. It is an office with a "
           + "24-hour watch, not a ship, and it usually owns no vessels of its own.",
    },
    naval: {
      label: "SAR asset",
      plain: "A rescue-capable vessel near enough to reach the casualty: coastguard, "
           + "navy, or a tug. This asks it to come. The rescue centre does the actual "
           + "tasking, so it is a request and says so.",
    },
    merchant: {
      label: "Nearest merchant",
      plain: "An ordinary cargo ship passing nearby. Under SOLAS every master must help "
           + "a vessel in distress if they can do so safely, and this is that request. A "
           + "master may decline, and a declined request is still information.",
    },
    manager: {
      label: "Company / DPA",
      plain: "The Designated Person Ashore: the 24-hour emergency contact every ship "
           + "operator is required to have. Gets the complete picture, including the raw "
           + "report and the crew detail, because they answer for the ship.",
    },
    next_of_kin: {
      label: "Next of kin",
      plain: "A draft letter to families. This system never sends it. A named person in "
           + "the company's welfare team reads it, edits it, and makes the call, because "
           + "no one should hear this from a machine.",
    },
  };

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  /* Repaint a panel without throwing away where the reader was.

     Every portal re-renders whole panels when a tick lands, and innerHTML resets the
     scroll of the box the panel lives in. A master reading the bottom of an incident
     got yanked back to the top every four seconds, which on a bridge reads as the
     terminal crashing and recovering. Pass `inner` when the scrolling box is itself
     inside the repainted element and so is destroyed by the repaint. */
  function repaint(el, html, inner, key = "") {
    if (!el) return;
    const find = () => inner ? el.querySelector(inner) : el.closest(".scroll");
    // Hold the scroll only when this is the same view being repainted under the
    // reader. Navigating to a different packet is not a repaint, and restoring the
    // previous one's offset would drop the operator into the middle of a draft they
    // have not started reading. Callers that only ever show one view pass no key.
    const same = el.dataset.view === key;
    const before = same ? find()?.scrollTop : 0;
    // Same for a "more" section the reader opened: a tick must not snap it shut.
    const open = same ? [...el.querySelectorAll("details[open][data-k]")].map(d => d.dataset.k) : [];
    el.innerHTML = html;
    el.dataset.view = key;
    for (const k of open) el.querySelector(`details[data-k="${k}"]`)?.setAttribute("open", "");
    const box = find();
    if (box && before) box.scrollTop = before;
  }

  const esc = s => String(s ?? "").replace(/[<>&]/g, c => ({"<": "&lt;", ">": "&gt;", "&": "&amp;"}[c]));
  const num = n => Number(n).toLocaleString();

  /* Range between two contacts, for panels that have both positions in hand and
     no reason to ask the server for the arithmetic. */
  function distanceNm(a, b) {
    const R = 3440.065, r = d => d * Math.PI / 180;
    const dp = r(b.lat - a.lat), dl = r(b.lon - a.lon);
    const x = Math.sin(dp / 2) ** 2
            + Math.cos(r(a.lat)) * Math.cos(r(b.lat)) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(x)));
  }

  function position(lat, lon) {
    const d = (v, p, n) => `${Math.abs(v).toFixed(3)}°${v >= 0 ? p : n}`;
    return `${d(lat, "N", "S")} ${d(lon, "E", "W")}`;
  }

  /* Websocket with viewport push and automatic reconnect. The server culls to the
     bounds we send, so a portal that never sends bounds gets the whole world capped. */
  function connect({ onFrame, onIncident, onMessage, onState }) {
    let ws, bounds = null, cap = 2500;
    const open = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      ws.onopen = () => { onState?.(true); push(); };
      ws.onclose = () => { onState?.(false); setTimeout(open, 1500); };
      ws.onmessage = e => {
        const m = JSON.parse(e.data);
        if (m.type === "frame") onFrame?.(m);
        if (m.type === "incident") onIncident?.(m.incident);
        if (m.type === "message") onMessage?.(m);
      };
    };
    const push = () => {
      if (ws?.readyState === 1) ws.send(JSON.stringify({ bounds, cap }));
    };
    open();
    return {
      setBounds(b) { bounds = b; push(); },
      setCap(c) { cap = c; push(); },
    };
  }

  /* One map configuration, used by all three portals at different zooms. The basemap
     follows the page: OpenFreeMap's dark style under a dark page, positron under a
     light one. The ops console pins itself dark; the others follow the system. */
  function map(container, { center = [20, 25], zoom = 1.6 } = {}) {
    const theme = document.documentElement.dataset.theme;
    const dark = theme ? theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const m = new maplibregl.Map({
      container,
      style: `https://tiles.openfreemap.org/styles/${dark ? "dark" : "positron"}`,
      center, zoom, attributionControl: { compact: true },
      maxZoom: 13, renderWorldCopies: true,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", () => {
      m.addSource("fleet", { type: "geojson", data: fc([]) });

      /* Distress halo underneath everything, so a casualty is findable at world
         zoom where a 3px dot is not. */
      m.addLayer({
        id: "halo", type: "circle", source: "fleet",
        filter: ["==", ["get", "d"], 1],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 11, 6, 26, 12, 60],
          "circle-color": "#ff2d55", "circle-opacity": 0.2,
          "circle-blur": 0.45,
        },
      });
      /* Two rings rippling off every casualty, half a cycle apart. On a world map a
         moving thing is found before a red one. Driven from JS with plain numbers, not
         a zoom expression, so each frame is a uniform update rather than a re-layout,
         and it stops touching the map entirely while nothing is in distress. */
      const RINGS = ["pulse-a", "pulse-b"];
      for (const id of RINGS) m.addLayer({
        id, type: "circle", source: "fleet", filter: ["==", ["get", "d"], 1],
        paint: { "circle-opacity": 0, "circle-stroke-color": "#ff2d55",
                 "circle-stroke-width": 2, "circle-stroke-opacity": 0 },
      });
      let was = false;
      if (!matchMedia("(prefers-reduced-motion: reduce)").matches) requestAnimationFrame(function pulse(now) {
        if (pulsing || was) {
          const base = 4 + m.getZoom();   // about the casualty dot's own radius
          RINGS.forEach((id, n) => {
            const t = (now / 4000 + n / 2) % 1;   // one ripple every 4 s, per ring
            m.setPaintProperty(id, "circle-radius", base + t * 34);
            m.setPaintProperty(id, "circle-stroke-opacity", pulsing ? 0.9 * (1 - t) : 0);
          });
          was = pulsing;
        }
        requestAnimationFrame(pulse);
      });
      /* Every symbol is drawn once per colour onto a canvas at load: an arrow for
         world zoom, a hull silhouette close in, a circle for a hull that is stopped
         and so has no heading worth drawing. 27 small bitmaps, no sprite sheet to
         host, and the outline is baked in so a contact reads on either basemap. */
      const shapes = {
        arrow: c => { c.moveTo(12, 2); c.lineTo(19, 21); c.lineTo(12, 17); c.lineTo(5, 21); },
        hull: c => { c.moveTo(12, 1); c.bezierCurveTo(15.5, 5, 16, 8, 16, 11); c.lineTo(16, 21);
                     c.quadraticCurveTo(16, 23, 14, 23); c.lineTo(10, 23);
                     c.quadraticCurveTo(8, 23, 8, 21); c.lineTo(8, 11);
                     c.bezierCurveTo(8, 8, 8.5, 5, 12, 1); },
        dot: c => c.arc(12, 12, 5, 0, 2 * Math.PI),
      };
      for (const [g, color] of Object.entries(GROUP_COLORS)) {
        for (const [shape, path] of Object.entries(shapes)) {
          const cv = document.createElement("canvas");
          cv.width = cv.height = 48;
          const c = cv.getContext("2d");
          c.scale(2, 2);
          c.beginPath(); path(c); c.closePath();
          c.fillStyle = color; c.fill();
          c.lineWidth = 1.5; c.lineJoin = "round";
          c.strokeStyle = g === "distress" || g === "own" || !dark ? "#ffffff" : "#0d0d0d";
          c.stroke();
          if (shape === "hull") {   // superstructure aft, so it reads as a ship
            c.fillStyle = "rgba(0,0,0,.35)"; c.fillRect(10, 16, 4, 3);
          }
          m.addImage(`${shape}-${g}`, c.getImageData(0, 0, 48, 48), { pixelRatio: 2 });
        }
      }
      const stopped = ["==", ["get", "st"], 1];
      const icon = moving => ["concat", ["case", stopped, "dot", moving], "-", ["get", "g"]];
      m.addLayer({
        id: "ships", type: "symbol", source: "fleet",
        layout: {
          // Arrows until zoom 8, hulls after: a silhouette at world zoom is a blob.
          "icon-image": ["step", ["zoom"], icon("arrow"), 8, icon("hull")],
          // One zoom interpolation only: maplibre rejects a `case` wrapping two of
          // them, so the casualty/normal choice goes inside each stop. A casualty
          // has to be findable at world zoom.
          "icon-size": ["interpolate", ["linear"], ["zoom"],
            1, ["case", ["==", ["get", "d"], 1], 0.5, 0.28],
            4, ["case", ["==", ["get", "d"], 1], 0.65, 0.42],
            8, ["case", ["==", ["get", "d"], 1], 1, 0.75],
            12, ["case", ["==", ["get", "d"], 1], 1.5, 1.25]],
          "icon-rotate": ["get", "c"],
          "icon-rotation-alignment": "map",
          // Never hide a contact to avoid a collision. A picture that drops ships
          // in a dense lane is lying about the traffic.
          "icon-allow-overlap": true, "icon-ignore-placement": true,
          // Casualties paint last. In a dense lane a red contact drawn in feed order
          // ends up underneath the merchant traffic around it, which is the one
          // contact on the screen that may never be covered.
          "symbol-sort-key": ["get", "d"],
        },
        paint: { "icon-opacity": ["interpolate", ["linear"], ["zoom"], 1, 0.8, 6, 1] },
      });
    });
    return m;
  }

  const fc = features => ({ type: "FeatureCollection", features });
  let pulsing = false;   // ponytail: one map per page; set by the last frame drawn

  /* Map colour per vessel group, indexed like KINDS. Mid-luminance and saturated so
     each reads on positron's grey water and the dark style's near-black. Red is
     distress and orange is AIS dark; no vessel type may use either. The ops and
     bridge legends repeat these hexes, so change them together. */
  const GROUP = ["cargo", "cargo", "tanker", "tanker", "cargo", "cargo", "passenger",
                 "fishing", "tug", "state", "state", "research"];
  const GROUP_COLORS = {
    distress: "#ff2d55", dark: "#ff8705", cargo: "#1e9bd7", tanker: "#8b5cf6",
    passenger: "#eab308", fishing: "#9ca3af", tug: "#c2845a", state: "#10b981",
    research: "#5b6b8c",
    own: "#4285f4",   // the bridge portal's own ship only; never assigned from a frame
  };

  /* A frame -> GeoJSON. Row is [mmsi, lat, lon, course, kindIdx, flags] and flags
     packs distressed/dark/sar-capable/stopped.

     Casualties are merged in from the frame's own `distressed` list rather than
     taken only from the culled rows. The server culls to the viewport, so a ship in
     distress outside it would vanish from the map at exactly the moment an operator
     needs to see it. Every portal draws every casualty, always. */
  function frameToGeoJSON(f) {
    const feature = (m, lat, lon, c, t, d, k, st) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [lon, lat] },
      properties: { m, c, d, st, g: d ? "distress" : k ? "dark" : GROUP[t] || "research" },
    });
    const out = (f.rows || []).map(r => feature(
      r[0], r[1], r[2], r[3], r[4],
      r[5] & 1 ? 1 : 0, r[5] & 2 ? 1 : 0, r[5] & 8 ? 1 : 0));
    const seen = new Set((f.rows || []).map(r => r[0]));
    for (const v of f.distressed || []) {
      if (seen.has(v.mmsi)) continue;
      out.push(feature(v.mmsi, v.lat, v.lon, v.course, KINDS.indexOf(v.kind),
                       1, v.dark ? 1 : 0, v.speed < 0.5 ? 1 : 0));
    }
    pulsing = out.some(x => x.properties.d);
    return fc(out);
  }

  /* Our own dialog. The browser's confirm() box is the only piece of UI in these
     portals drawn by the browser vendor, and on a bridge terminal it reads as a
     malfunction rather than a decision. Returns a promise of true/false. */
  function dialog({ title, body = "", confirm = "Confirm", cancel = "Cancel", tone = "primary" }) {
    return new Promise(resolve => {
      const el = document.createElement("div");
      el.className = "modal";
      el.innerHTML = `<div class="box" role="alertdialog" aria-modal="true">
        <h2>${esc(title)}</h2>
        <div class="text">${esc(body)}</div>
        <div class="row" style="margin-top:17px">
          ${cancel ? `<button class="btn ghost" data-ok="0">${esc(cancel)}</button>` : ""}
          <button class="btn ${tone}" data-ok="1">${esc(confirm)}</button>
        </div></div>`;
      const close = v => { el.remove(); document.removeEventListener("keydown", key); resolve(v); };
      const key = e => { if (e.key === "Escape") close(false); };
      el.onclick = e => { if (e.target === el) close(false); };
      el.querySelectorAll("[data-ok]").forEach(b => b.onclick = () => close(b.dataset.ok === "1"));
      document.addEventListener("keydown", key);
      document.body.appendChild(el);
      el.querySelector('[data-ok="1"]').focus();
    });
  }

  const say = (title, body) => dialog({ title, body, confirm: "Understood", cancel: "" });
  const clock = ts => String(ts || "").slice(11, 16) + "Z";

  const boundsOf = m => {
    const b = m.getBounds();
    return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
  };

  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  }
  const post = (path, body) => api(path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  return { $, $$, esc, num, position, clock, distanceNm, connect, map, fc, frameToGeoJSON,
           boundsOf, api, post, dialog, say, repaint, KINDS, SEV, NAV, RECIPIENTS };
})();
