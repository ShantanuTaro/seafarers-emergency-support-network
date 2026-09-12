/* Shared between all three portals: websocket plumbing, the map layers, and the
   handful of formatters. Kept deliberately small: three pages do not justify a
   framework, and a build step is one more thing to break at 3am. */

const SESN = (() => {
  const KINDS = ["container", "bulker", "tanker", "gas", "general", "roro",
                 "passenger", "fishing", "tug", "naval", "coastguard", "research"];
  const SEV = ["", "LOW", "MODERATE", "HIGH", "CRITICAL"];
  const NAV = {0: "under way (engine)", 1: "at anchor", 2: "not under command",
               5: "moored", 6: "AGROUND", 7: "fishing", 15: "undefined"};

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = s => String(s ?? "").replace(/[<>&]/g, c => ({"<": "&lt;", ">": "&gt;", "&": "&amp;"}[c]));
  const num = n => Number(n).toLocaleString();

  function position(lat, lon) {
    const d = (v, p, n) => `${Math.abs(v).toFixed(3)}°${v >= 0 ? p : n}`;
    return `${d(lat, "N", "S")} ${d(lon, "E", "W")}`;
  }

  /* Websocket with viewport push and automatic reconnect. The server culls to the
     bounds we send, so a portal that never sends bounds gets the whole world capped. */
  function connect({ onFrame, onIncident, onState }) {
    let ws, bounds = null, cap = 2500;
    const open = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      ws.onopen = () => { onState?.(true); push(); };
      ws.onclose = () => { onState?.(false); setTimeout(open, 1500); };
      ws.onmessage = e => {
        const m = JSON.parse(e.data);
        if (m.type === "frame") onFrame?.(m);
        if (m.type === "incident") onIncident?.(m.incident);
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

  /* One map configuration, used by all three portals at different zooms. */
  function map(container, { center = [20, 25], zoom = 1.6, style = "positron" } = {}) {
    const m = new maplibregl.Map({
      container,
      style: `https://tiles.openfreemap.org/styles/${style}`,
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
          "circle-color": "#fb5570", "circle-opacity": 0.2,
          "circle-blur": 0.45,
        },
      });
      m.addLayer({
        id: "ships", type: "circle", source: "fleet",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 1.7, 4, 3, 8, 6, 12, 9],
          "circle-color": [
            "case",
            ["==", ["get", "d"], 1], "#fb5570",
            ["==", ["get", "k"], 1], "#fbbf24",
            ["==", ["get", "s"], 1], "#34d399",
            ["==", ["get", "t"], 7], "#94a3b8",
            ["==", ["get", "t"], 2], "#c084fc",
            ["==", ["get", "t"], 0], "#38bdf8",
            "#5b8fc7",
          ],
          "circle-opacity": ["interpolate", ["linear"], ["zoom"], 1, 0.75, 6, 0.95],
          "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 4, 0, 7, 1],
          "circle-stroke-color": "#070b10",
        },
      });
    });
    return m;
  }

  const fc = features => ({ type: "FeatureCollection", features });

  /* Compact wire rows -> GeoJSON. Row is [mmsi, lat, lon, course, kindIdx, flags]
     and flags packs distressed/dark/sar-capable. */
  function rowsToGeoJSON(rows) {
    return fc(rows.map(r => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [r[2], r[1]] },
      properties: {
        m: r[0], c: r[3], t: r[4],
        d: r[5] & 1 ? 1 : 0, k: r[5] & 2 ? 1 : 0, s: r[5] & 4 ? 1 : 0,
      },
    })));
  }

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

  return { $, $$, esc, num, position, connect, map, fc, rowsToGeoJSON, boundsOf,
           api, post, KINDS, SEV, NAV };
})();
