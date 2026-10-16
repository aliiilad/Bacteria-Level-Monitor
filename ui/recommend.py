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
