"""Synthetic vessel and owner names, in the house styles real fleets actually use.

A carrier names its ships brand-plus-city, a Greek owner uses family names, a
Japanese owner a Maru, a Chinese fishing fleet a registry number. Copying the pattern
is what makes a traffic picture read as real; copying the names would not be
acceptable. Every brand here is invented. A generic combination ("Ocean Harmony")
may coincide with some real hull somewhere, but nothing else attached to it (MMSI,
flag, position, cargo) is that ship's.
"""

from __future__ import annotations

import random

CITIES = ["Halifax", "Lisbon", "Genoa", "Valparaiso", "Durban", "Mombasa", "Colombo",
          "Kobe", "Osaka", "Manila", "Surabaya", "Darwin", "Fremantle", "Lyttelton",
          "Oslo", "Gdansk", "Riga", "Tallinn", "Bilbao", "Marseille", "Naples", "Izmir",
          "Haifa", "Aqaba", "Muscat", "Karachi", "Kochi", "Chittagong", "Yangon", "Penang",
          "Danang", "Haiphong", "Xiamen", "Dalian", "Incheon", "Yokohama", "Hakodate",
          "Seattle", "Oakland", "Charleston", "Baltimore", "Montreal", "Veracruz",
          "Manzanillo", "Guayaquil", "Buenaventura", "Montevideo", "Recife", "Salvador",
          "Luanda", "Tema", "Abidjan", "Dakar", "Casablanca", "Tangier", "Tunis",
          "Valletta", "Limassol", "Constanta", "Odesa", "Batumi", "Aarhus", "Gothenburg",
          "Bergen", "Reykjavik", "Belfast", "Cork", "Bordeaux", "Porto", "Cadiz",
          "Livorno", "Trieste", "Rijeka", "Thessaloniki", "Mersin", "Port Said", "Djibouti",
          "Berbera", "Dar es Salaam", "Maputo", "Port Louis", "Toamasina", "Chennai",
          "Visakhapatnam", "Kolkata", "Belawan", "Makassar", "Cebu", "Davao", "Keelung",
          "Nagasaki", "Niigata", "Vladivostok", "Tauranga", "Noumea", "Suva", "Apia",
          "Honolulu", "Anchorage", "Callao", "Arica", "Iquique", "Punta Arenas"]
WOMEN = ["Aurora", "Clara", "Giulia", "Sofia", "Isabella", "Chiara", "Valentina",
         "Beatrice", "Lucia", "Francesca", "Elena", "Marta", "Paola", "Carla", "Silvia",
         "Rosa", "Teresa", "Irene", "Alessia", "Martina", "Camilla", "Serena", "Livia",
         "Ottavia", "Viola", "Aurelia", "Noemi", "Greta", "Ilaria", "Vittoria", "Adele",
         "Bianca", "Carolina", "Daniela", "Emma", "Federica", "Gloria", "Ines", "Julia",
         "Laura", "Maya", "Nadia", "Olga", "Petra", "Rita", "Sara", "Tania", "Vera",
         "Yasmin", "Zoe", "Amelie", "Charlotte", "Helena", "Ingrid", "Johanna", "Katrin",
         "Lena", "Mirella", "Nina", "Renata"]
STARS = ["Vega", "Rigel", "Altair", "Deneb", "Sirius", "Capella", "Antares", "Arcturus",
         "Aldebaran", "Spica", "Pollux", "Castor", "Procyon", "Regulus", "Canopus",
         "Achernar", "Bellatrix", "Mira", "Alcor", "Mizar", "Polaris", "Electra", "Maia",
         "Alcyone", "Merope", "Taygeta", "Hadar", "Mimosa", "Shaula", "Nunki", "Kochab",
         "Alnair", "Diphda", "Hamal", "Menkar", "Algol", "Enif", "Markab", "Scheat",
         "Sabik", "Rasalhague", "Eltanin", "Sadr", "Albireo", "Tarazed", "Fomalhaut",
         "Acrux", "Gacrux", "Avior", "Miaplacidus", "Atria", "Peacock", "Ankaa", "Suhail"]
MYTH = ["Athena", "Artemis", "Hermes", "Apollo", "Poseidon", "Triton", "Nereus", "Thetis",
        "Calypso", "Ariadne", "Penelope", "Andromeda", "Perseus", "Orion", "Atlas",
        "Prometheus", "Hyperion", "Theia", "Rhea", "Leto", "Selene", "Helios", "Eos",
        "Iris", "Nike", "Tyche", "Hebe", "Phoebe", "Dione", "Galatea", "Amphitrite",
        "Proteus", "Oceanus", "Tethys", "Electra", "Cassandra", "Hector", "Achilles",
        "Ajax", "Jason", "Medea", "Theseus", "Icarus", "Daedalus", "Pegasus", "Castalia",
        "Arethusa", "Echo", "Daphne", "Europa"]
VIRTUES = ["Harmony", "Prosperity", "Fortune", "Unity", "Loyalty", "Integrity", "Grace",
           "Courage", "Endurance", "Resolve", "Promise", "Liberty", "Serenity", "Triumph",
           "Victory", "Honour", "Wisdom", "Radiance", "Brilliance", "Excellence",
           "Diligence", "Fidelity", "Concord", "Patience", "Vitality", "Clarity",
           "Constancy", "Devotion", "Glory", "Merit", "Valour", "Vision", "Spirit",
           "Ambition", "Dignity", "Tenacity", "Trust", "Venture", "Destiny", "Legacy"]
GEMS = ["Sapphire", "Emerald", "Ruby", "Topaz", "Opal", "Garnet", "Amber", "Jade",
        "Onyx", "Pearl", "Coral", "Agate", "Beryl", "Jasper", "Citrine", "Peridot",
        "Tourmaline", "Zircon", "Spinel", "Amethyst", "Aquamarine", "Moonstone",
        "Obsidian", "Turquoise", "Lapis", "Malachite", "Carnelian", "Diamond", "Tanzanite"]
BIRDS = ["Osprey", "Kestrel", "Albatross", "Petrel", "Gannet", "Cormorant", "Tern",
         "Heron", "Egret", "Kingfisher", "Shearwater", "Skua", "Fulmar", "Puffin",
         "Pelican", "Frigatebird", "Harrier", "Merlin", "Peregrine", "Condor", "Kite",
         "Swift", "Swallow", "Curlew", "Plover", "Sandpiper", "Avocet", "Crane", "Ibis",
         "Stork", "Hawk", "Eagle", "Falcon", "Goshawk", "Buzzard", "Lark", "Oriole",
         "Robin", "Wren", "Starling"]
RIVERS = ["Amazon", "Orinoco", "Parana", "Congo", "Niger", "Zambezi", "Nile", "Volga",
          "Danube", "Rhine", "Elbe", "Loire", "Tagus", "Ebro", "Po", "Thames", "Shannon",
          "Mekong", "Irrawaddy", "Ganges", "Indus", "Brahmaputra", "Yangtze", "Amur",
          "Lena", "Yenisei", "Ob", "Mackenzie", "Yukon", "Columbia", "Fraser", "Hudson",
          "Mississippi", "Missouri", "Colorado", "Murray", "Darling", "Limpopo", "Orange",
          "Senegal", "Tigris", "Euphrates", "Jordan", "Dnieper", "Vistula", "Oder"]
TUG_WORDS = ["Titan", "Hercules", "Samson", "Goliath", "Bison", "Buffalo", "Rhino",
             "Grizzly", "Mammoth", "Colossus", "Mustang", "Stallion", "Bulldog", "Mastiff",
             "Warrior", "Champion", "Gladiator", "Centurion", "Spartan", "Viking",
             "Typhoon", "Cyclone", "Tornado", "Thunder", "Granite", "Anvil", "Hammer",
             "Forge", "Piston", "Torque", "Capstan", "Bollard", "Hawser", "Winch", "Keel",
             "Rudder", "Tiller", "Sentinel", "Guardian", "Defender"]
SCIENTISTS = ["Nansen", "Humboldt", "Darwin", "Cousteau", "Maury", "Ekman", "Sverdrup",
              "Bjerknes", "Wegener", "Carson", "Beebe", "Piccard", "Tharp", "Heezen",
              "Munk", "Stommel", "Agassiz", "Hjort", "Forbes", "Thomson", "Buchanan",
              "Helland", "Defant", "Bigelow", "Iselin", "Hensen", "Knudsen", "Rossby",
              "Sars", "Mohn", "Raman", "Saha", "Sagan", "Hubble", "Kepler", "Halley"]

# The first word of each operator is its hull prefix: "Marslev Line" names its ships
# "Marslev <city>". Operators only run the kind of tonnage their name says they run.
BRANDS: dict[str, list[tuple[str, list[str]]]] = {
    "container": [("Marslev Line", CITIES), ("Medterra Shipping", WOMEN),
                  ("CGA Atlantique", MYTH + CITIES), ("Cosmos Ocean", STARS),
                  ("Hapag-Nord Container", CITIES + RIVERS), ("Evergale Marine", VIRTUES + GEMS),
                  ("Yanghai Lines", VIRTUES + CITIES), ("Meridian ONE", STARS + BIRDS),
                  ("Zamir Line", GEMS + CITIES), ("HYM Global", CITIES + RIVERS),
                  ("Interocean Pacific", BIRDS + STARS), ("Wansea Carriers", RIVERS + GEMS)],
    "bulker": [("Nordkap Bulk", RIVERS + BIRDS), ("Ironbay Bulk Carriers", BIRDS + GEMS),
               ("Granvik Shipping", WOMEN + STARS), ("Tessaly Dry Cargo", MYTH + VIRTUES)],
    "tanker": [("Auralis Tankers", STARS + GEMS), ("Petromar Shipping", CITIES + VIRTUES),
               ("Delvari Tankers", MYTH + RIVERS)],
    "gas": [("Kestrel Gas Transport", RIVERS + STARS), ("Arcterra LNG", BIRDS + MYTH)],
    "general": [("Hanselund Feeder", CITIES), ("Coralia Coasters", GEMS + BIRDS)],
    "roro": [("Silverline Ro-Ro", MYTH + STARS), ("Carmona Car Carriers", CITIES + VIRTUES)],
    "passenger": [("Stellamar Cruises", VIRTUES + GEMS + STARS),
                  ("Northstraits Ferries", CITIES + MYTH)],
    "tug": [("Brandvik Towage", TUG_WORDS), ("Oceanhaul Salvage", TUG_WORDS)],
}
ANY_WORD = CITIES + WOMEN + STARS + MYTH + VIRTUES + GEMS + BIRDS + RIVERS
# Share of each kind that sails under a liner brand; the rest are independent owners.
BRANDED_SHARE = {"container": 0.6, "roro": 0.7, "passenger": 0.9, "gas": 0.4,
                 "tanker": 0.3, "bulker": 0.25, "general": 0.15, "tug": 0.5}
STATE_PREFIX = {"naval": ("NS", MYTH + VIRTUES + RIVERS + CITIES + STARS),
                "coastguard": ("CGS", CITIES + BIRDS + VIRTUES + RIVERS + GEMS),
                "research": ("RV", SCIENTISTS + STARS + BIRDS)}

ADJ = ["Ocean", "Pacific", "Atlantic", "Golden", "Silver", "Star", "Cape", "Nord",
       "Sea", "Blue", "Royal", "Grand", "Eastern", "Western", "Southern", "Northern",
       "Great", "Bright", "New", "Lucky", "Coral", "Island", "Harbour", "Global",
       "Orient", "Asian", "Crystal", "Emerald", "Sunny", "Morning", "Evening", "Polar",
       "Tropical", "Baltic", "Aegean", "Caspian", "Summit", "Crown", "Noble", "Pearl"]
NOUN = ["Pride", "Glory", "Spirit", "Venture", "Fortune", "Harmony", "Unity", "Dawn",
        "Crown", "Eagle", "Falcon", "Breeze", "Wave", "Horizon", "Voyager", "Pioneer",
        "Trader", "Carrier", "Express", "Navigator", "Explorer", "Mariner", "Endeavour",
        "Frontier", "Legend", "Jewel", "Treasure", "Beacon", "Compass", "Anchor", "Crest",
        "Tide", "Current", "Wind", "Sun", "Moon", "Light", "Hope", "Faith", "Promise"]
GREEK_REGIONS = ["Aegean", "Ionian", "Hellenic", "Cretan", "Thalassa", "Nissos", "Kyma",
                 "Cycladic", "Saronic", "Kythira", "Chios", "Andros", "Kefalonia", "Lesvos"]
GREEK_NAMES = ["Eleni", "Maria", "Katerina", "Despina", "Anastasia", "Vasiliki", "Georgia",
               "Dimitra", "Sofia", "Ioanna", "Nikolaos", "Georgios", "Dimitrios", "Ioannis",
               "Konstantinos", "Panagiotis", "Vasilis", "Christos", "Michalis", "Stavros",
               "Spyros", "Theodoros", "Angelos", "Evangelos", "Kostas", "Yannis", "Manolis",
               "Antonis", "Petros", "Stelios"]
PINYIN = ["Hai", "Xin", "Tian", "Feng", "Sheng", "Da", "Hua", "Long", "Yuan", "Ming",
          "Heng", "Tai", "Jin", "Fu", "Rong", "Kang", "An", "Shun", "Xiang", "Yang",
          "Hong", "Chang", "Ping", "Xing", "Bao", "De", "Guang", "Hui", "Jia", "Lian"]
PROVINCES = ["Lu", "Zhe", "Min", "Yue", "Liao", "Qiong", "Su", "Gui"]
JP_HEAD = ["Shin", "Kai", "Tai", "Ei", "Ho", "Ko", "Nis", "Sei", "Mei", "Ryu", "To",
           "Fuku", "Haku", "Asa", "Toku", "Sho", "Kyo", "Yu", "Chi", "Hi"]
JP_TAIL = ["yo", "ho", "ei", "wa", "sho", "ju", "toku", "kai", "sei", "ko"]
NORSE_HEAD = ["Nordic", "Polar", "Fjord", "Viking", "Skagen", "Arctic", "Norse",
              "Lofoten", "Hardanger", "Sogn", "Vesteral", "Finnmark"]
NORSE_NAMES = ["Freja", "Sigrid", "Astrid", "Ingrid", "Solveig", "Ragnhild", "Gudrun",
               "Liv", "Tove", "Kari", "Odin", "Tor", "Harald", "Olav", "Leif", "Sigurd",
               "Bjorn", "Erik", "Magnus", "Halvard", "Havbris", "Nordlys", "Sjostjerne"]
IN_HEAD = ["Arya", "Samudra", "Tarang", "Varuna", "Sindhu", "Nav", "Jal", "Megh",
           "Surya", "Chandra"]
IN_NAMES = ["Lakshmi", "Shakti", "Pragati", "Vijay", "Kiran", "Prabha", "Ratna", "Jyoti",
            "Tejas", "Anand", "Kaveri", "Godavari", "Narmada", "Tapti", "Saraswati",
            "Durga", "Ganga", "Yamuna", "Sagarika", "Deepika", "Aarti", "Bhavani",
            "Kalpana", "Nandini", "Pooja", "Rekha", "Sunita", "Usha", "Vasudha", "Madhavi"]
FISH_HEAD = ["Northern", "Southern", "Ocean", "Sea", "Atlantic", "Pacific", "Arctic",
             "Silver", "Morning", "Evening", "Bountiful", "Faithful", "Western", "Coastal"]
KR_FISH = ["Hanbit", "Daeyang", "Sinsung", "Haeyang", "Namhae", "Donghae", "Seohae",
           "Bada", "Hanil", "Samho", "Geumsan", "Jinyang"]
FISH_NOUN = ["Harvest", "Hunter", "Venture", "Provider", "Reward", "Endeavour", "Hope",
             "Star", "Dawn", "Quest", "Bounty", "Challenger", "Enterprise", "Pride",
             "Maid", "Lass", "Rover", "Seeker", "Trawler", "Fisher"]

ROMAN = ["", "", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


CARRIER_NOUN = ["Trader", "Carrier", "Express", "Venture", "Pioneer", "Leader", "Ace",
                "Bay", "Sky", "Hope", "Glory", "Spirit"]


def _english(r: random.Random) -> tuple[str, str]:
    head = r.choice(ADJ)
    if r.random() < 0.7:
        name = f"{head} {r.choice(NOUN + BIRDS + STARS + MYTH + GEMS)}"
    else:
        name = f"{r.choice(BIRDS + STARS + MYTH + GEMS + RIVERS)} {r.choice(CARRIER_NOUN)}"
    suffix = r.choice(["Shipping Ltd", "Maritime Inc.", "Navigation Corp."])
    return name, f"{name.split()[0]} {suffix}"


def _greek(r: random.Random) -> tuple[str, str]:
    if r.random() < 0.5:
        name = f"{r.choice(GREEK_REGIONS)} {r.choice(GREEK_NAMES + MYTH)}"
    else:
        name = f"{r.choice(GREEK_NAMES + MYTH)} {r.choice('ABDGKLMNPST')}."
    return name, f"{name.split()[0]} Maritime S.A."


def _chinese(r: random.Random) -> tuple[str, str]:
    stem = " ".join(r.sample(PINYIN, 2))
    name = f"{stem} {r.randint(1, 99)}" if r.random() < 0.6 else stem
    return name, f"{stem} Shipping Co., Ltd"


def _japanese(r: random.Random) -> tuple[str, str]:
    stem = r.choice(JP_HEAD) + r.choice(JP_TAIL)
    name = f"{stem} Maru No. {r.randint(2, 38)}" if r.random() < 0.5 else f"{stem} Maru"
    return name, f"{stem} Kaiun K.K."


def _nordic(r: random.Random) -> tuple[str, str]:
    head = r.choice(NORSE_HEAD)
    return f"{head} {r.choice(NORSE_NAMES)}", f"{head} Rederi AS"


def _indian(r: random.Random) -> tuple[str, str]:
    head = r.choice(IN_HEAD)
    return f"{head} {r.choice(IN_NAMES)}", f"{head} Shipping Pvt Ltd"


STYLE_BY_FLAG = {"Greece": _greek, "Cyprus": _greek, "China": _chinese,
                 "Hong Kong": _chinese, "Japan": _japanese, "Norway": _nordic,
                 "India": _indian, "UK": _english}
# Open registries fly every owner nationality; weighted roughly by who owns the tonnage.
OPEN_REGISTRY = [_chinese] * 4 + [_greek] * 2 + [_english] * 3 + [_japanese] * 2 + [
    _nordic, _indian]


def _fishing(r: random.Random, flag: str) -> tuple[str, str]:
    roll = r.random()
    if flag in ("China", "Hong Kong") or (flag not in STYLE_BY_FLAG and roll < 0.35):
        prov = r.choice(PROVINCES)
        return f"{prov} {r.choice(PINYIN)} Yu {r.randint(100, 9999)}", ""
    if flag == "Japan":
        return f"{r.choice(JP_HEAD)}{r.choice(JP_TAIL)} Maru No. {r.randint(1, 88)}", ""
    if flag not in STYLE_BY_FLAG and roll < 0.65:
        return f"{r.choice(KR_FISH)} No. {r.randint(1, 999)}", ""
    return f"{r.choice(FISH_HEAD)} {r.choice(FISH_NOUN + BIRDS)}", ""


# Styles with enough combinations to absorb overflow once a brand or a small national
# style has run out of names.
_DEEP = [_chinese, _chinese, _english]


def _candidate(r: random.Random, kind: str, flag: str, overflow: bool) -> tuple[str, str]:
    if kind in STATE_PREFIX:
        prefix, pool = STATE_PREFIX[kind]
        if overflow:  # patrol craft and auxiliaries carry hull numbers, not names
            return f"{prefix} {r.randint(101, 999)}", ""
        return f"{prefix} {r.choice(pool)}", ""
    if kind == "fishing":
        return _fishing(r, "Panama" if overflow else flag)
    if not overflow and kind in BRANDS and r.random() < BRANDED_SHARE[kind]:
        operator, pool = r.choice(BRANDS[kind])
        return f"{operator.split()[0]} {r.choice(pool)}", operator
    if overflow and kind in BRANDS and r.random() < BRANDED_SHARE[kind]:
        # A carrier that has run out of house-style names widens the pool, as real ones do.
        operator, _ = r.choice(BRANDS[kind])
        return f"{operator.split()[0]} {r.choice(ANY_WORD)}", operator
    if overflow:
        return r.choice(_DEEP)(r)
    style = STYLE_BY_FLAG.get(flag) if r.random() < 0.6 else None
    return (style or r.choice(OPEN_REGISTRY))(r)


def vessel_name(r: random.Random, kind: str, flag: str, taken: set[str]) -> tuple[str, str]:
    """(name, operator) for a new hull, unique across the fleet and within the 20
    characters an AIS static report carries. Operator is blank for fishing and state
    vessels."""
    for attempt in range(12):
        name, operator = _candidate(r, kind, flag, overflow=attempt >= 3)
        if name not in taken and len(name) <= 20:
            break
    # ponytail: roman suffix only after twelve misses; grow the pools if it shows up.
    n, base = 1, name
    while name in taken:
        n += 1
        name = f"{base} {ROMAN[n]}" if n < len(ROMAN) else f"{base} {n}"
    taken.add(name)
    return name, operator
