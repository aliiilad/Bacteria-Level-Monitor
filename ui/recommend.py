"""Advice and safer-beach logic for feature 2. Plain Python, no Streamlit, so the app,
a future back end, or an alert job can all import it.
"""
import math

EARTH_RADIUS_KM = 6371.0

# Sampling points that are really the same beach. Never suggest one for the other, and the
# map draws each group as one pin. Magic Island Bowls (858) and Canoe Launch (859) are two
# points at Ala Moana.
SAME_BEACH = [{"858", "859"}]


def same_beach(site_a, site_b):
    """True when two site ids are the same place (or the same id)."""
    a, b = str(site_a), str(site_b)
    return a == b or any(a in group and b in group for group in SAME_BEACH)


def distance_km(lat1, lon1, lat2, lon2):
    """Straight-line distance between two points on Earth (haversine formula), in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


# What to do in each risk band (the band names match band() in ui/app.py). Worded from the
# Hawaiʻi DOH Clean Water Branch's public guidance: stay out of brown or murky water, avoid
# stream mouths and runoff, wait 48–72 hours after heavy rain, and check DOH's advisories.
ADVICE = {
    "LOWER RISK": [
        "Bacteria are likely under the state limit today.",
        "Still skip water that looks brown or murky, and stay away from where streams or storm drains flow into the ocean.",
    ],
    "CAUTION": [
        "Bacteria may be over the state limit today.",
        "Stay away from where streams or storm drains flow into the ocean, and from brown or murky water.",
        "If you can, swim at a lower-risk beach instead.",
    ],
    "LIKELY UNSAFE": [
        "Bacteria are likely over the state limit today. Stay out of the water.",
        "After heavy rain, DOH suggests waiting 48–72 hours after the rain stops and the beach gets full sun.",
    ],
}


def safer_beaches(site, beaches, risks, below, limit=3):
    """Beaches whose risk today is under `below`, nearest to `site` first (at most `limit`).

    site    : the selected beach's site id
    beaches : rows with site_id, beach_name, region, latitude, longitude (e.g. beaches.csv)
    risks   : {site_id: today's risk} for every beach (the same numbers as the map)
    below   : only beaches under this risk count as safer (the "lower risk" band)
    Each item is {"site_id", "beach_name", "region", "risk", "km"}. Points at the same beach as
    `site` never count, and only one point per beach is listed.
    """
    here = next(b for b in beaches if str(b["site_id"]) == str(site))
    found = []
    for b in beaches:
        sid = str(b["site_id"])
        if same_beach(sid, site) or risks[sid] >= below:
            continue
        km = distance_km(here["latitude"], here["longitude"], b["latitude"], b["longitude"])
        found.append({"site_id": sid, "beach_name": b["beach_name"], "region": b.get("region", ""),
                      "risk": risks[sid], "km": km})
    found.sort(key=lambda b: b["km"])
    unique = []
    for b in found:   # e.g. both Magic Island points safer: keep only the nearer one
        if not any(same_beach(b["site_id"], u["site_id"]) for u in unique):
            unique.append(b)
    return unique[:limit]


def safer_beach(site, beaches, risks, below):
    """The nearest beach whose risk today is under `below`, or None if there isn't one."""
    found = safer_beaches(site, beaches, risks, below, limit=1)
    return found[0] if found else None
