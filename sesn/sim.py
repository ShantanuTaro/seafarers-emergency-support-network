"""In-process vessel simulator at world-fleet scale.

Ticks ~60,000 vessels, which is roughly the size of the real merchant fleet over
100 GT. A full tick costs about 20 ms, so the simulator is never the bottleneck.
the websocket payload is, which is why `frame()` culls to the client's viewport and
sends compact arrays rather than objects.

Ships are a slots dataclass, not a pydantic model. At sixty thousand instances that
is the difference between a simulator and a memory problem; pydantic stays at the
API boundary where validation actually buys something.

Deterministic under a fixed seed, so a scenario replays exactly.

Every operator brand, vessel name and MMSI here is invented. None of them refer to a
real company or a real ship.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .models import Telemetry

EARTH_NM = 3440.065
TIME_SCALE = 120.0  # simulated seconds per wall-clock second
SEED = 20260912
FLEET_SIZE = 60_000


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_NM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def step_position(lat: float, lon: float, course: float, nm: float) -> tuple[float, float]:
    p1, brg, d = math.radians(lat), math.radians(course), nm / EARTH_NM
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(brg))
    dl = math.atan2(math.sin(brg) * math.sin(d) * math.cos(p1),
                    math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(math.radians(lon) + dl) + 540) % 360 - 180


# Sea lanes as polylines that follow navigable water. Hand-placed rather than
# great-circle generated, because a great circle between two ports cheerfully sails
# a container ship across Kazakhstan.
CORRIDORS: dict[str, list[tuple[float, float]]] = {
    "Gulf of Aden": [(12.6, 43.4), (12.0, 45.5), (11.9, 48.5), (12.5, 51.5), (13.5, 55.0)],
    "Bab el-Mandeb": [(14.6, 42.4), (13.2, 43.0), (12.6, 43.4)],
    "Red Sea": [(29.9, 32.5), (27.2, 34.2), (23.0, 36.8), (20.5, 38.4), (16.5, 41.0), (14.6, 42.4)],
    "Suez-Gibraltar": [(31.5, 32.3), (33.5, 28.0), (35.0, 20.0), (36.8, 12.0), (36.5, 3.0), (36.0, -5.4)],
    "Gibraltar-Channel": [(36.0, -5.6), (38.5, -9.8), (43.5, -9.5), (47.5, -6.0), (49.5, -2.0)],
    "English Channel": [(49.5, -2.0), (50.4, 0.5), (51.0, 1.6), (51.9, 3.2), (53.5, 5.0)],
    "North Sea": [(53.5, 5.0), (55.5, 6.5), (57.5, 8.5), (57.8, 11.0)],
    "Baltic Approaches": [(57.8, 11.0), (55.8, 12.7), (54.8, 15.0), (59.4, 24.0)],
    "North Atlantic": [(51.9, 3.9), (49.5, -8.0), (47.0, -20.0), (43.0, -40.0), (40.6, -70.0)],
    "US East Coast": [(40.6, -73.9), (36.9, -75.3), (32.7, -79.5), (25.8, -80.0)],
    "Gulf of Mexico": [(25.8, -80.5), (24.5, -84.0), (27.5, -90.0), (29.3, -94.7)],
    "Panama Approaches": [(9.4, -79.9), (11.0, -77.0), (14.0, -72.0), (18.0, -68.0)],
    "Panama Pacific": [(8.9, -79.5), (7.0, -82.0), (10.0, -90.0), (15.0, -100.0)],
    "US West Coast": [(33.7, -118.2), (36.6, -122.5), (40.5, -124.8), (46.2, -124.5), (48.4, -124.8)],
    "Trans-Pacific North": [(48.4, -125.0), (50.0, -145.0), (48.0, -170.0), (43.0, 165.0), (35.5, 140.5)],
    "Trans-Pacific Central": [(33.7, -118.5), (28.0, -140.0), (25.0, -165.0), (24.0, 175.0), (25.0, 140.0), (31.2, 122.0)],
    "East China Sea": [(31.2, 122.0), (29.0, 123.5), (25.0, 122.0), (22.5, 118.5), (22.3, 114.2)],
    "South China Sea": [(22.3, 114.2), (18.0, 112.0), (12.0, 110.0), (6.0, 106.0), (1.3, 104.0)],
    "Singapore Strait": [(1.3, 104.6), (1.2, 103.8), (1.4, 103.2)],
    "Malacca Strait": [(1.4, 103.2), (2.5, 101.0), (4.2, 99.0), (5.9, 96.5)],
    "Bay of Bengal": [(5.9, 95.5), (10.0, 92.0), (14.0, 86.0), (18.0, 85.0), (21.6, 88.2)],
    "India West Coast": [(8.0, 77.0), (11.0, 74.5), (15.5, 72.0), (19.0, 72.5), (22.5, 69.0)],
    "Arabian Sea": [(22.5, 68.5), (20.0, 65.0), (17.0, 60.0), (14.0, 55.0), (13.5, 52.0)],
    "Strait of Hormuz": [(26.6, 56.4), (25.8, 55.0), (26.5, 52.5), (28.5, 50.0), (29.5, 48.5)],
    "Cape of Good Hope": [(-33.9, 18.2), (-35.0, 20.5), (-34.5, 26.0), (-32.0, 31.0), (-28.0, 34.0)],
    "West Africa": [(-8.0, 12.0), (-4.0, 8.0), (0.5, 5.0), (5.0, 2.0), (6.3, 3.3)],
    "South Atlantic": [(-34.0, -52.0), (-30.0, -40.0), (-25.0, -25.0), (-25.0, -10.0), (-33.9, 17.8)],
    "Brazil Coast": [(-23.0, -43.1), (-26.0, -47.0), (-30.0, -49.5), (-34.0, -53.0)],
    "Australia East": [(-33.9, 151.3), (-30.0, 153.8), (-25.0, 154.0), (-19.0, 148.5)],
    "Australia-Asia": [(-32.0, 115.7), (-20.0, 114.0), (-10.0, 116.0), (-6.0, 112.0), (1.3, 104.6)],
    "Mediterranean": [(36.0, -5.4), (37.5, 3.0), (38.0, 10.0), (35.5, 16.0), (34.5, 25.0), (36.8, 28.0)],
    "Black Sea": [(40.5, 27.5), (41.2, 29.2), (43.5, 32.0), (45.3, 36.5)],
    "Japan-Korea": [(35.5, 140.0), (34.0, 132.0), (34.5, 128.5), (37.5, 126.0)],
    "Northern Sea Route": [(69.7, 33.0), (73.0, 55.0), (75.5, 90.0), (74.0, 140.0), (66.0, -169.0)],
}

# Anchorage clusters. These are what make a world AIS map look like a world AIS map:
# dense knots of stationary tonnage off every major port.
PORTS: list[tuple[str, float, float]] = [
    ("Shanghai", 31.0, 122.3), ("Singapore", 1.22, 103.85), ("Ningbo", 29.8, 122.1),
    ("Shenzhen", 22.5, 114.0), ("Guangzhou", 22.6, 113.6), ("Busan", 35.05, 129.1),
    ("Qingdao", 36.0, 120.5), ("Hong Kong", 22.28, 114.15), ("Tianjin", 38.9, 117.8),
    ("Rotterdam", 51.95, 4.05), ("Antwerp", 51.3, 4.3), ("Hamburg", 53.9, 8.7),
    ("Port Klang", 3.0, 101.35), ("Dubai", 25.0, 55.05), ("Los Angeles", 33.7, -118.25),
    ("Long Beach", 33.72, -118.2), ("New York", 40.5, -74.0), ("Savannah", 32.0, -80.9),
    ("Houston", 29.3, -94.8), ("Santos", -24.0, -46.3), ("Piraeus", 37.9, 23.6),
    ("Valencia", 39.4, -0.3), ("Algeciras", 36.1, -5.4), ("Colombo", 6.9, 79.8),
    ("Mumbai", 18.9, 72.8), ("Mundra", 22.7, 69.7), ("Chennai", 13.1, 80.3),
    ("Jakarta", -6.1, 106.9), ("Manila", 14.6, 120.9), ("Kaohsiung", 22.6, 120.3),
    ("Tokyo Bay", 35.5, 139.8), ("Nagoya", 34.9, 136.8), ("Vancouver", 49.3, -123.2),
    ("Panama Balboa", 8.9, -79.55), ("Cartagena", 10.4, -75.5), ("Lagos", 6.4, 3.4),
    ("Durban", -29.9, 31.05), ("Alexandria", 31.2, 29.9), ("Istanbul", 40.9, 28.9),
    ("Jeddah", 21.5, 39.1), ("Salalah", 17.0, 54.0), ("Melbourne", -37.9, 144.9),
    ("Auckland", -36.8, 174.8), ("Callao", -12.05, -77.2), ("Hamburg Elbe", 54.1, 8.3),
]

FISHING_GROUNDS: list[tuple[float, float, float]] = [
    (57.0, -3.0, 3.0), (44.0, -60.0, 4.0), (-42.0, -60.0, 4.0), (60.0, 5.0, 3.0),
    (10.0, -20.0, 5.0), (-8.0, 80.0, 5.0), (38.0, 128.0, 3.0), (54.0, 165.0, 4.0),
    (-35.0, 20.0, 3.0), (5.0, 120.0, 4.0), (20.0, -110.0, 4.0), (-20.0, -80.0, 4.0),
    (65.0, -20.0, 3.0), (12.0, 45.0, 2.5), (-10.0, 150.0, 4.0),
]

# Invented operator brands. Any resemblance to a real carrier is the point of a
# simulation and the limit of it. None of these companies exist.
OPERATORS = [
    "Marslev Line", "Medterra Shipping", "CGA Atlantique", "Cosmos Ocean",
    "Hapag-Nord", "Evergale Marine", "Yanghai Lines", "Meridian ONE",
    "Zamir Line", "HYM Global", "Pacific Interocean", "Wansea Carriers",
    "Nordkap Bulk", "Auralis Tankers", "Kestrel Gas Transport", "Silverline Ro-Ro",
]
_NAMES = ["Sentinel", "Voyager", "Pioneer", "Mariner", "Spirit", "Endeavour", "Star",
          "Horizon", "Provider", "Runner", "Crest", "Beacon", "Warden", "Trader",
          "Harrier", "Osprey", "Meridian", "Aurora", "Pegasus", "Corona", "Zenith",
          "Falcon", "Lantern", "Compass", "Anchor", "Tempest", "Cascade", "Summit"]
FLAGS = ["Panama", "Liberia", "Marshall Islands", "Singapore", "Malta", "Bahamas",
         "Hong Kong", "Cyprus", "Greece", "India", "China", "Japan", "Norway", "UK"]
MIDS = ["636", "538", "371", "477", "249", "309", "563", "215", "241", "419",
        "412", "431", "257", "232"]

# Index order is the wire format for `kind`; append only, never reorder.
KINDS = ["container", "bulker", "tanker", "gas", "general", "roro", "passenger",
         "fishing", "tug", "naval", "coastguard", "research"]
SAR_CAPABLE = {"tug", "naval", "coastguard"}


@dataclass(slots=True)
class Ship:
    mmsi: str
    name: str
    operator: str
    kind: str
    flag: str
    pob: int
    lat: float
    lon: float
    course: float
    speed_kn: float
    nav_status: int = 0
    corridor: str = ""
    route: list[tuple[float, float]] = field(default_factory=list)
    leg: int = 0
    distressed: bool = False
    ais_dark: bool = False
    injected_fault: str | None = None
    destination: str = ""

    @property
    def can_assist(self) -> bool:
        return self.kind in SAR_CAPABLE

    def telemetry(self) -> Telemetry:
        return Telemetry(mmsi=self.mmsi, lat=self.lat, lon=self.lon,
                         speedKn=self.speed_kn, navStatus=self.nav_status)


@dataclass
class Fault:
    """One injectable emergency. `text` is what a human would have phoned in, and it
    may be empty, because plenty of real incidents announce themselves only as
    telemetry."""
    label: str
    text: str
    speed_kn: float | None = None
    nav_status: int | None = None
    ais_dark: bool = False
    beacon_prefix: str | None = None


FAULTS: dict[str, Fault] = {
    "piracy": Fault("Piracy / armed robbery",
        "Two skiffs closing from the port quarter at high speed, six persons visible in "
        "each, one carrying a ladder. Increasing to full sea speed, commencing evasive "
        "steering, crew mustering at the citadel.", speed_kn=18.5),
    "attack": Fault("Drone / missile attack",
        "We have taken an impact on the port side above the waterline, believed to be an "
        "aerial drone. Fire in the accommodation block. Three crew with burns. Requesting "
        "immediate assistance.", speed_kn=6.0),
    "fire": Fault("Fire",
        "Fire in the main engine room. Space evacuated and sealed, CO2 released, boundary "
        "cooling in progress. All crew accounted for. Vessel without propulsion.",
        speed_kn=0.4, nav_status=2),
    "flooding": Fault("Flooding",
        "Breach in the hull below the waterline. Pumps cannot keep up with the rate of "
        "ingress. List has increased from three to eleven degrees in twenty minutes.",
        speed_kn=2.0),
    "collision": Fault("Collision",
        "We have struck a fishing vessel in fog. Damage to our bow above the waterline. "
        "The other vessel is going down by the stern. Rescue boat launched, recovering "
        "persons from the water.", speed_kn=0.5, nav_status=2),
    "grounding": Fault("Grounding", "", speed_kn=0.0, nav_status=6),
    "machinery_failure": Fault("Machinery failure",
        "Main engine has shut down and cannot be restarted. We are not under command and "
        "setting toward the traffic separation scheme. Wind thirty-five knots on the beam. "
        "Requesting a tug.", speed_kn=1.5, nav_status=2),
    "medical_evacuation": Fault("Medical evacuation",
        "Chief engineer, male, fifty-four, severe central chest pain radiating to the left "
        "arm, cold and sweating, no cardiac history. Given aspirin and oxygen. Requesting "
        "medical advice and evacuation."),
    "man_overboard": Fault("Man overboard",
        "A crew member went over the side from the main deck. Lifebuoy released, Williamson "
        "turn commenced, all hands to lookout stations.", speed_kn=5.0, beacon_prefix="972"),
    "crew_abandonment": Fault("Crew abandonment",
        "The master has given the order to abandon. Two liferafts are in the water and the "
        "free-fall boat has been launched. All persons accounted for at the rafts. EPIRB "
        "activated.", speed_kn=0.2, nav_status=15, beacon_prefix="974"),
    "sart_only": Fault("AIS-SART, no voice contact", "",
        speed_kn=0.6, nav_status=15, beacon_prefix="970"),
    "ais_blackout": Fault("AIS blackout", "", ais_dark=True),
}


class Simulator:
    def __init__(self, seed: int = SEED, size: int = FLEET_SIZE) -> None:
        self.rng = random.Random(seed)
        self.ships: dict[str, Ship] = {}
        self.paused = False
        self._seed_fleet(size)
        # Rebuilt each tick: the flat frame every viewport is culled from. Built once
        # per tick rather than once per client.
        self._frame: list[list] = []
        self._rebuild_frame()

    # ---- fleet generation -------------------------------------------------

    def _seed_fleet(self, size: int) -> None:
        rng = self.rng
        used: set[str] = set()
        n_corridor = int(size * 0.62)
        n_port = int(size * 0.22)
        n_fishing = size - n_corridor - n_port

        lanes = list(CORRIDORS.items())
        for _ in range(n_corridor):
            corridor, waypoints = lanes[rng.randrange(len(lanes))]
            leg = rng.randrange(len(waypoints) - 1)
            a, b = waypoints[leg], waypoints[leg + 1]
            f = rng.random()
            # Scatter off the lane centreline so traffic reads as a band, not a wire.
            lat = a[0] + (b[0] - a[0]) * f + rng.gauss(0, 0.25)
            lon = a[1] + (b[1] - a[1]) * f + rng.gauss(0, 0.25)
            kind = self._weighted_kind(rng)
            self._add(used, kind, lat, lon, rng.uniform(8.0, 21.0), 0,
                      corridor, list(waypoints), leg,
                      destination=PORTS[rng.randrange(len(PORTS))][0])

        for _ in range(n_port):
            name, plat, plon = PORTS[rng.randrange(len(PORTS))]
            lat = plat + rng.gauss(0, 0.22)
            lon = plon + rng.gauss(0, 0.22)
            kind = self._weighted_kind(rng)
            moored = rng.random() < 0.45
            self._add(used, kind, lat, lon, 0.0, 5 if moored else 1,
                      f"{name} anchorage", [], 0, destination=name)

        for _ in range(n_fishing):
            lat0, lon0, spread = FISHING_GROUNDS[rng.randrange(len(FISHING_GROUNDS))]
            lat = lat0 + rng.gauss(0, spread)
            lon = lon0 + rng.gauss(0, spread)
            self._add(used, "fishing", lat, lon, rng.uniform(0.0, 6.0), 7,
                      "fishing grounds", [], 0)

    def _weighted_kind(self, rng: random.Random) -> str:
        # Roughly the shape of the real merchant fleet: bulkers and tankers dominate
        # by hull count, passenger and naval are rare.
        r = rng.random()
        if r < 0.26: return "bulker"
        if r < 0.48: return "tanker"
        if r < 0.66: return "container"
        if r < 0.78: return "general"
        if r < 0.84: return "gas"
        if r < 0.89: return "roro"
        if r < 0.92: return "tug"
        if r < 0.95: return "fishing"
        if r < 0.97: return "passenger"
        if r < 0.985: return "coastguard"
        if r < 0.995: return "naval"
        return "research"

    def _add(self, used: set[str], kind: str, lat: float, lon: float, speed: float,
             nav: int, corridor: str, route: list, leg: int, destination: str = "") -> Ship:
        rng = self.rng
        while True:
            mmsi = MIDS[rng.randrange(len(MIDS))] + f"{rng.randrange(1000000):06d}"
            if mmsi not in used:
                used.add(mmsi)
                break
        operator = OPERATORS[rng.randrange(len(OPERATORS))] if kind not in (
            "fishing", "naval", "coastguard", "research") else ""
        stem = _NAMES[rng.randrange(len(_NAMES))]
        prefix = operator.split()[0] if operator else {
            "fishing": "FV", "naval": "NS", "coastguard": "CGS", "research": "RV"}[kind]
        pob = (rng.randint(180, 3200) if kind == "passenger"
               else rng.randint(4, 9) if kind == "fishing"
               else rng.randint(14, 28))
        ship = Ship(
            mmsi=mmsi, name=f"{prefix} {stem}", operator=operator, kind=kind,
            flag=FLAGS[rng.randrange(len(FLAGS))], pob=pob,
            lat=max(-85.0, min(85.0, lat)), lon=(lon + 540) % 360 - 180,
            course=rng.uniform(0, 360), speed_kn=speed, nav_status=nav,
            corridor=corridor, route=route, leg=leg, destination=destination)
        if route:
            nxt = route[(leg + 1) % len(route)]
            ship.course = bearing_deg(ship.lat, ship.lon, *nxt)
        self.ships[mmsi] = ship
        return ship

    # ---- tick -------------------------------------------------------------

    def tick(self, dt_seconds: float) -> None:
        if self.paused:
            return
        hours = (dt_seconds * TIME_SCALE) / 3600.0
        for s in self.ships.values():
            if s.speed_kn <= 0.05:
                continue
            if s.route:
                target = s.route[(s.leg + 1) % len(s.route)]
                if haversine_nm(s.lat, s.lon, *target) < 25.0:
                    s.leg = (s.leg + 1) % len(s.route)
                    target = s.route[(s.leg + 1) % len(s.route)]
                s.course = bearing_deg(s.lat, s.lon, *target)
            s.lat, s.lon = step_position(s.lat, s.lon, s.course, s.speed_kn * hours)
        self._rebuild_frame()

    def _rebuild_frame(self) -> None:
        """Compact wire rows, built once per tick and shared by every client.

        [mmsi, lat, lon, course, kind_index, flags]
        flags: bit0 distressed, bit1 AIS dark, bit2 SAR capable

        Names, flag states, POB and destination are deliberately absent. They are
        fetched per vessel on click. Sending them for every hull on screen would be
        most of the payload and none of the picture.
        """
        rows = []
        for s in self.ships.values():
            flags = (1 if s.distressed else 0) | (2 if s.ais_dark else 0) | (
                4 if s.can_assist else 0)
            rows.append([s.mmsi, round(s.lat, 4), round(s.lon, 4),
                         round(s.course), KINDS.index(s.kind), flags])
        self._frame = rows

    def frame(self, bounds: tuple[float, float, float, float] | None,
              cap: int = 2500) -> tuple[list[list], int]:
        """Cull the frame to a viewport and cap it. Returns (rows, total_in_view).

        ponytail: linear scan over the fleet per client per tick, about 15 ms at
        60k hulls. Fine for a handful of operators; build a spatial grid if the
        console ever has many concurrent viewers.
        """
        if bounds is None:
            rows = self._frame
        else:
            w, s_, e, n = bounds
            if w <= e:
                rows = [r for r in self._frame if s_ <= r[1] <= n and w <= r[2] <= e]
            else:  # viewport crosses the antimeridian
                rows = [r for r in self._frame
                        if s_ <= r[1] <= n and (r[2] >= w or r[2] <= e)]

        total = len(rows)
        if total <= cap:
            return rows, total
        # Always keep every distressed contact, then thin the rest evenly. An
        # operator must never lose a casualty to a rendering budget.
        distressed = [r for r in rows if r[5] & 1]
        others = [r for r in rows if not (r[5] & 1)]
        stride = max(1, len(others) // max(1, cap - len(distressed)))
        return distressed + others[::stride][:cap - len(distressed)], total

    # ---- incidents --------------------------------------------------------

    def inject(self, mmsi: str, fault_key: str) -> tuple[Ship, Fault, Ship | None]:
        ship = self.ships[mmsi]
        fault = FAULTS[fault_key]
        if fault.speed_kn is not None:
            ship.speed_kn = fault.speed_kn
        if fault.nav_status is not None:
            ship.nav_status = fault.nav_status
        ship.ais_dark = fault.ais_dark
        ship.distressed = True
        ship.injected_fault = fault.label
        beacon = self._spawn_beacon(ship, fault.beacon_prefix) if fault.beacon_prefix else None
        self._rebuild_frame()
        return ship, fault, beacon

    def _spawn_beacon(self, near: Ship, prefix: str) -> Ship:
        """A dedicated distress transmitter appears as its own contact, drifting.
        This is what makes the Unknown path real: 970 and 974 confirm that something
        is very wrong and refuse to say what."""
        label = {"970": "AIS-SART", "972": "MOB BEACON", "974": "AIS-EPIRB"}[prefix]
        mmsi = prefix + f"{self.rng.randrange(1000000):06d}"
        beacon = Ship(
            mmsi=mmsi, name=f"{label} ({near.name})", operator="", kind="research",
            flag="-", pob=0,
            lat=near.lat + self.rng.uniform(-0.02, 0.02),
            lon=near.lon + self.rng.uniform(-0.02, 0.02),
            course=self.rng.uniform(0, 360), speed_kn=0.6, nav_status=15,
            corridor="distress beacon", distressed=True)
        self.ships[mmsi] = beacon
        return beacon

    def clear(self, mmsi: str) -> None:
        s = self.ships.get(mmsi)
        if not s:
            return
        s.distressed = False
        s.ais_dark = False
        s.injected_fault = None
        s.nav_status = 0
        if s.speed_kn < 6.0 and s.route:
            s.speed_kn = round(self.rng.uniform(9.0, 16.0), 1)
        self._rebuild_frame()

    def distressed(self) -> list[Ship]:
        return [s for s in self.ships.values() if s.distressed]

    def stats(self) -> dict:
        under_way = sum(1 for s in self.ships.values() if s.speed_kn > 0.5)
        return {
            "fleet": len(self.ships),
            "under_way": under_way,
            "moored_or_anchored": len(self.ships) - under_way,
            "distressed": sum(1 for s in self.ships.values() if s.distressed),
            "dark": sum(1 for s in self.ships.values() if s.ais_dark),
            "paused": self.paused,
        }
