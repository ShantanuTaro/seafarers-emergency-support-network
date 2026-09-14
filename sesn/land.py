"""Land mask, so the simulated fleet stays in the water.

A 0.05 degree (about 3 nm) raster of Natural Earth 1:50m land (public domain), one bit
per cell, zlib-compressed into land.bin: about 100 KB on disk, 3.2 MB in memory. A
lookup is two divisions and a bit test, cheap enough for every hull at seed.

ponytail: 1:50m generalises coastlines by a few km and closes straits narrower than a
cell (the Bosporus, the Sound). Right at ops-console zoom; rebuild from ne_10m_land at
a finer RES if a demo ever zooms into a harbour.

Rebuild:
    curl -LO https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson
    python -m sesn.land ne_50m_land.geojson
"""

from __future__ import annotations

import json
import math
import sys
import zlib
from pathlib import Path

RES = 0.05
W, H = int(360 / RES), int(180 / RES)
PATH = Path(__file__).with_name("land.bin")
_MASK = b"" if __name__ == "__main__" else zlib.decompress(PATH.read_bytes())


def is_land(lat: float, lon: float) -> bool:
    r = min(H - 1, max(0, int((90.0 - lat) / RES)))
    i = r * W + int(((lon + 180.0) % 360.0) / RES) % W
    return bool(_MASK[i >> 3] >> (i & 7) & 1)


def is_open_water(lat: float, lon: float) -> bool:
    """Water with water all round it, so a hull placed here is not on a beach that the
    coarse coastline happened to call sea."""
    return not any(is_land(lat + dy * RES, lon + dx * RES)
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1))


def build(geojson: str) -> bytes:
    """Even-odd scanline fill of every ring, sampled at each row's centre latitude."""
    crossings: list[list[float]] = [[] for _ in range(H)]
    for feature in json.loads(Path(geojson).read_text())["features"]:
        g = feature["geometry"]
        polygons = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for ring in (ring for poly in polygons for ring in poly):
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                lo, hi = min(y1, y2), max(y1, y2)
                if lo == hi:
                    continue
                # One row wider than needed each way, so only the comparison below decides.
                # Letting the rounded range decide meant two edges meeting at a vertex on a
                # row centre could disagree, leaving an odd crossing that striped the row.
                for r in range(max(0, math.floor((90 - hi) / RES - 0.5)),
                               min(H - 1, math.ceil((90 - lo) / RES - 0.5)) + 1):
                    lat = 90 - (r + 0.5) * RES
                    if lo <= lat < hi:
                        x = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
                        crossings[r].append((x + 180) / RES - 0.5)
    out = bytearray()
    for xs in crossings:
        row = bytearray(b"0" * W)
        xs.sort()
        for a, b in zip(xs[::2], xs[1::2]):
            c1, c2 = max(0, math.ceil(a)), min(W - 1, math.floor(b))
            if c2 >= c1:
                row[c1:c2 + 1] = b"1" * (c2 - c1 + 1)
        # Cell c becomes bit c of the row, least significant first.
        out += int(bytes(row[::-1]), 2).to_bytes(W // 8, "little")
    return zlib.compress(bytes(out), 9)


if __name__ == "__main__":
    PATH.write_bytes(build(sys.argv[1]))
    print(f"wrote {PATH} ({PATH.stat().st_size // 1000} KB)")
