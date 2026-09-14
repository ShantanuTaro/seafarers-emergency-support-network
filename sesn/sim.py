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

from .land import is_land, is_open_water
from .models import Telemetry
from .names import vessel_name

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
# a container ship across Kazakhstan. Every leg is checked against the land mask by
# test_the_fleet_is_at_sea; a waypoint moved by eye has to pass it.
CORRIDORS: dict[str, list[tuple[float, float]]] = {
    "Gulf of Aden": [(12.6, 43.4), (12.0, 45.5), (11.9, 48.5), (12.5, 51.5), (13.5, 55.0)],
    "Bab el-Mandeb": [(14.6, 42.4), (13.2, 43.0), (12.6, 43.4)],
    "Red Sea": [(29.8, 32.58), (28.9, 33.05), (27.8, 33.75), (27.2, 34.2), (23.0, 36.8),
                (20.5, 38.4), (16.5, 41.0), (14.6, 42.4)],
    "Suez-Gibraltar": [(31.5, 32.3), (33.5, 28.0), (35.0, 20.0), (37.35, 11.6), (37.7, 9.0),
                       (37.4, 3.0), (36.4, -1.5), (36.0, -3.5), (35.97, -5.45)],
    "Gibraltar-Channel": [(35.95, -5.8), (36.6, -8.5), (36.9, -9.4), (38.5, -9.8), (43.5, -9.5),
                          (48.0, -5.8), (48.7, -5.6), (50.1, -2.5)],
    "English Channel": [(50.1, -2.5), (50.4, 0.4), (51.0, 1.55), (51.9, 3.0), (53.5, 4.6)],
    "North Sea": [(53.5, 4.6), (55.5, 6.5), (57.5, 8.3), (58.0, 10.5), (57.8, 11.2)],
    "Baltic Approaches": [(57.8, 11.2), (56.9, 11.5), (56.1, 12.55), (55.3, 12.75), (55.1, 13.5),
                          (54.75, 15.2), (56.0, 18.0), (57.5, 20.0), (58.8, 21.0), (59.55, 22.8),
                          (59.6, 24.2)],
    "North Atlantic": [(51.9, 3.3), (51.05, 1.6), (50.4, 0.4), (50.05, -2.5), (49.6, -5.3),
                       (49.2, -7.0), (47.0, -20.0), (43.0, -40.0), (40.3, -70.0)],
    "US East Coast": [(40.35, -73.75), (39.3, -73.9), (37.5, -75.0), (36.9, -75.4), (35.1, -75.2),
                      (34.3, -76.3), (33.6, -77.8), (32.6, -79.4), (28.3, -80.0), (27.0, -79.8),
                      (25.8, -79.95)],
    "Gulf of Mexico": [(25.6, -79.95), (25.0, -80.2), (24.55, -80.9), (24.35, -81.5), (24.3, -82.5),
                       (24.5, -84.0), (27.5, -90.0), (29.0, -94.5)],
    "Panama Approaches": [(9.6, -80.0), (10.0, -79.3), (11.0, -77.0), (14.0, -72.0), (18.0, -68.0)],
    "Panama Pacific": [(8.8, -79.5), (8.0, -79.3), (7.2, -79.7), (6.9, -80.8), (7.0, -82.0),
                       (10.0, -90.0), (15.0, -100.0)],
    "US West Coast": [(33.6, -118.3), (34.15, -119.5), (34.3, -120.6), (34.9, -121.0), (35.6, -121.6),
                      (36.6, -122.2), (38.9, -124.0), (40.5, -124.8), (42.8, -125.0), (46.2, -124.5),
                      (48.3, -125.0)],
    "Trans-Pacific North": [(48.4, -125.0), (50.0, -145.0), (48.0, -170.0), (43.0, 165.0), (35.5, 140.5)],
    "Trans-Pacific Central": [(33.7, -118.5), (28.0, -140.0), (25.0, -165.0), (24.0, 175.0), (25.0, 140.0), (31.2, 122.0)],
    "East China Sea": [(31.2, 122.0), (29.0, 123.5), (25.5, 121.5), (24.5, 119.8), (23.0, 118.8),
                       (22.05, 114.3)],
    "South China Sea": [(22.05, 114.3), (18.0, 112.0), (12.0, 110.0), (6.0, 106.0), (2.0, 105.0),
                        (1.35, 104.5)],
    "Singapore Strait": [(1.3, 104.6), (1.2, 103.8), (1.4, 103.2)],
    "Malacca Strait": [(1.4, 103.2), (2.5, 101.0), (4.2, 99.0), (5.3, 98.0), (5.95, 96.5)],
    "Bay of Bengal": [(5.95, 95.6), (10.0, 91.5), (14.0, 86.0), (18.0, 85.0), (19.5, 87.3), (21.4, 88.25)],
    "India West Coast": [(8.0, 77.0), (11.0, 74.5), (15.5, 72.0), (19.0, 72.3), (20.4, 71.0),
                         (20.9, 69.6), (22.4, 68.7)],
    "Arabian Sea": [(22.5, 68.5), (20.0, 65.0), (17.0, 60.0), (14.0, 55.0), (13.5, 52.0)],
    "Strait of Hormuz": [(26.6, 56.4), (25.8, 55.0), (26.5, 52.5), (28.5, 50.0), (29.5, 48.5)],
    "Cape of Good Hope": [(-33.9, 18.2), (-34.6, 18.2), (-35.1, 20.0), (-34.5, 26.0), (-32.0, 31.0),
                          (-28.0, 34.0)],
    "West Africa": [(-8.0, 12.0), (-4.0, 8.0), (0.5, 5.0), (5.0, 2.0), (6.3, 3.3)],
    "South Atlantic": [(-34.0, -52.0), (-30.0, -40.0), (-25.0, -25.0), (-25.0, -10.0), (-33.9, 17.8)],
    "Brazil Coast": [(-23.0, -43.1), (-26.0, -47.0), (-30.0, -49.5), (-34.0, -53.0)],
    "Australia East": [(-33.9, 151.45), (-32.5, 152.9), (-30.9, 153.4), (-30.0, 153.8), (-25.0, 154.0),
                       (-19.0, 148.5)],
    "Australia-Asia": [(-32.1, 115.25), (-29.0, 114.3), (-26.0, 112.6), (-22.0, 113.2), (-20.0, 114.0),
                       (-10.0, 116.0), (-9.0, 115.8), (-8.3, 115.85), (-6.5, 114.5), (-6.0, 112.0),
                       (1.3, 104.6)],
    "Mediterranean": [(36.0, -5.4), (37.5, 3.0), (38.0, 10.0), (35.5, 16.0), (34.5, 25.0), (34.8, 26.6),
                      (35.8, 28.2)],
    "Black Sea": [(40.8, 28.0), (40.95, 28.95), (41.3, 29.15), (43.5, 32.0), (44.5, 37.6)],
    "Japan-Korea": [(35.2, 139.75), (35.0, 139.6), (34.8, 139.2), (34.4, 138.95), (33.3, 136.0),
                    (32.5, 133.0), (31.4, 131.8), (30.9, 130.8), (31.3, 129.9), (31.5, 129.45),
                    (32.3, 129.4), (32.9, 129.35), (34.0, 129.0), (34.8, 129.0), (33.8, 126.5),
                    (34.2, 125.6), (35.5, 125.6), (37.3, 125.9)],
    "Northern Sea Route": [(69.8, 33.5), (70.5, 40.0), (71.0, 50.0), (70.2, 55.0), (70.5, 58.0),
                           (70.9, 61.0), (72.0, 66.0), (74.0, 70.0), (74.5, 78.0), (76.3, 88.0),
                           (77.9, 104.5), (77.0, 115.0), (74.3, 128.0), (73.6, 136.0), (73.05, 141.5),
                           (72.5, 150.0), (71.3, 163.0), (70.2, 178.0), (67.8, -170.5), (66.0, -169.0)],
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

# Centred on water. Hulls are still drawn only where the land mask says open water,
# but a ground centred on Scotland puts its whole fleet on the Scottish coastline.
FISHING_GROUNDS: list[tuple[float, float, float]] = [
    (57.5, 0.5, 2.5), (44.0, -60.0, 4.0), (-42.0, -60.0, 4.0), (60.0, 3.0, 2.5),
    (10.0, -20.0, 5.0), (-8.0, 80.0, 5.0), (38.5, 131.0, 2.5), (54.0, 165.0, 4.0),
    (-36.5, 21.0, 2.0), (5.0, 120.0, 4.0), (20.0, -110.0, 4.0), (-20.0, -80.0, 4.0),
    (62.5, -19.0, 2.0), (12.0, 45.0, 2.5), (-10.0, 150.0, 4.0),
]

# Flag state and the Maritime Identification Digits that open its MMSIs. An MMSI whose
# MID contradicts the flag is exactly the inconsistency a watchkeeper notices.
FLAG_MIDS: dict[str, list[str]] = {
    "Panama": ["351", "352", "353", "354", "355", "356", "357", "370", "371", "372"],
    "Liberia": ["636"], "Marshall Islands": ["538"], "Singapore": ["563", "564", "565", "566"],
    "Malta": ["215", "229", "248", "249", "256"], "Bahamas": ["308", "309", "311"],
    "Hong Kong": ["477"], "Cyprus": ["209", "210", "212"], "Greece": ["237", "239", "240", "241"],
    "India": ["419"], "China": ["412", "413", "414"], "Japan": ["431", "432"],
    "Norway": ["257", "258", "259"], "UK": ["232", "233", "234", "235"],
}
FLAGS = list(FLAG_MIDS)
STATE_FLAGS = ["Singapore", "Greece", "India", "China", "Japan", "Norway", "UK"]

# What each hull is carrying. Operationally this is not decoration: cargo decides
# whether a fire is a fire or a hazmat incident, and it is the first thing a
# responding master asks about before closing.
CARGOES: dict[str, list[str]] = {
    "container": ["mixed containerised freight, 8,400 TEU",
                  "containerised freight incl. 12 IMDG class 3 units, 14,000 TEU",
                  "containerised freight, reefer boxes, 4,200 TEU"],
    "bulker": ["62,000 t iron ore", "45,000 t grain", "70,000 t coal",
               "28,000 t bauxite"],
    "tanker": ["95,000 t crude oil", "38,000 t gasoil", "12,000 t palm oil",
               "30,000 t naphtha, IMDG class 3"],
    "gas": ["68,000 m3 LNG", "22,000 m3 LPG, IMDG class 2.1"],
    "general": ["3,800 t project cargo, steel sections", "6,200 t bagged cement",
                "sawn timber, deck cargo"],
    "roro": ["1,900 vehicles", "trade cars and 180 trailers"],
    "passenger": ["passengers and vehicles, no declared freight"],
    "fishing": ["frozen catch, approx. 40 t"],
    "tug": ["no cargo, towing gear and salvage pumps aboard"],
    "naval": ["no commercial cargo, military stores"],
    "coastguard": ["no cargo, SAR equipment and rescue boat"],
    "research": ["no cargo, scientific equipment"],
}

# Index order is the wire format for `kind`; append only, never reorder.
KINDS = ["container", "bulker", "tanker", "gas", "general", "roro", "passenger",
         "fishing", "tug", "naval", "coastguard", "research"]
SAR_CAPABLE = {"tug", "naval", "coastguard"}
# Armed is a strict subset and the distinction decides a security case: a tug is
# SAR-capable and sorts to the top of a responder list, but it is not a response to
# an active boarding.
ARMED = {"naval", "coastguard"}


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
    cargo: str = ""

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
        self._names: set[str] = set()
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
            # Scatter off the lane centreline so traffic reads as a band, not a wire,
            # but only into open water.
            # Longitude the short way round: interpolating straight from -170 to 165 put
            # Trans-Pacific hulls in the middle of Asia.
            dlon = (b[1] - a[1] + 540.0) % 360.0 - 180.0
            lat, lon = self._at_sea(a[0] + (b[0] - a[0]) * f, a[1] + dlon * f, 0.25)
            kind = self._weighted_kind(rng)
            # Out and back along the same water. Looping from the last waypoint to the
            # first sailed that closing leg straight across whatever continent was between.
            self._add(used, kind, lat, lon, rng.uniform(8.0, 21.0), 0,
                      corridor, waypoints + waypoints[-2:0:-1],
                      # Half the lane sails it homeward: the same segment, entered from
                      # the return half of the route, so traffic runs both ways.
                      leg if rng.random() < 0.5 else 2 * len(waypoints) - 3 - leg,
                      destination=PORTS[rng.randrange(len(PORTS))][0])

        for _ in range(n_port):
            name, plat, plon = PORTS[rng.randrange(len(PORTS))]
            lat, lon = self._at_sea(plat, plon, 0.22)
            kind = self._weighted_kind(rng)
            moored = rng.random() < 0.45
            self._add(used, kind, lat, lon, 0.0, 5 if moored else 1,
                      f"{name} anchorage", [], 0, destination=name)

        for _ in range(n_fishing):
            lat0, lon0, spread = FISHING_GROUNDS[rng.randrange(len(FISHING_GROUNDS))]
            lat, lon = self._at_sea(lat0, lon0, spread)
            self._add(used, "fishing", lat, lon, rng.uniform(0.0, 6.0), 7,
                      "fishing grounds", [], 0)

    def _at_sea(self, lat0: float, lon0: float, sigma: float) -> tuple[float, float]:
        """A point scattered round (lat0, lon0), redrawn until it is open water. The
        spread widens every twenty misses, so a port well up a river still gets an
        anchorage, just further out. Draws from the sim RNG, so it replays exactly."""
        rng = self.rng
        for attempt in range(600):
            spread = sigma * 1.25 ** (attempt // 20)
            lat, lon = lat0 + rng.gauss(0, spread), lon0 + rng.gauss(0, spread)
            if -85.0 < lat < 85.0 and is_open_water(lat, lon):
                return lat, lon
        raise RuntimeError(f"no open water near {lat0}, {lon0}")

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
        # Warships and coastguard cutters fly a state's own flag, never an open registry.
        flags = STATE_FLAGS if kind in ("naval", "coastguard") else FLAGS
        flag = flags[rng.randrange(len(flags))]
        mids = FLAG_MIDS[flag]
        while True:
            mmsi = mids[rng.randrange(len(mids))] + f"{rng.randrange(1000000):06d}"
            if mmsi not in used:
                used.add(mmsi)
                break
        name, operator = vessel_name(rng, kind, flag, self._names)
        pob = (rng.randint(180, 3200) if kind == "passenger"
               else rng.randint(4, 9) if kind == "fishing"
               else rng.randint(14, 28))
        ship = Ship(
            mmsi=mmsi, name=name, operator=operator, kind=kind, flag=flag, pob=pob,
            lat=max(-85.0, min(85.0, lat)), lon=(lon + 540) % 360 - 180,
            course=rng.uniform(0, 360), speed_kn=speed, nav_status=nav,
            corridor=corridor, route=route, leg=leg, destination=destination,
            cargo=CARGOES[kind][rng.randrange(len(CARGOES[kind]))])
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
                # Close enough to follow the lane round its corners (25 nm cut straight
                # across Singapore island), wider than the 3.5 nm a 21 kn hull covers in
                # one tick, so nothing orbits its waypoint.
                if haversine_nm(s.lat, s.lon, *target) < 5.0:
                    s.leg = (s.leg + 1) % len(s.route)
                    target = s.route[(s.leg + 1) % len(s.route)]
                s.course = bearing_deg(s.lat, s.lon, *target)
            lat, lon = step_position(s.lat, s.lon, s.course, s.speed_kn * hours)
            if not s.route and is_land(lat, lon):
                # No lane to follow, so nothing else keeps a fishing boat off the beach.
                s.course = (s.course + 180.0) % 360.0
                continue
            s.lat, s.lon = lat, lon
        self._rebuild_frame()

    def _rebuild_frame(self) -> None:
        """Compact wire rows, built once per tick and shared by every client.

        [mmsi, lat, lon, course, kind_index, flags]
        flags: bit0 distressed, bit1 AIS dark, bit2 SAR capable, bit3 stopped

        Names, flag states, POB and destination are deliberately absent. They are
        fetched per vessel on click. Sending them for every hull on screen would be
        most of the payload and none of the picture. Stopped rides in the flags
        because the map draws a stopped hull as a circle, not a heading arrow: a
        course over ground means nothing at anchor.
        """
        rows = []
        for s in self.ships.values():
            flags = (1 if s.distressed else 0) | (2 if s.ais_dark else 0) | (
                4 if s.can_assist else 0) | (8 if s.speed_kn < 0.5 else 0)
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
            corridor="distress beacon", distressed=True,
            cargo="not applicable, distress transmitter")
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
