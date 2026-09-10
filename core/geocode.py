"""
One free Nominatim lookup per run: turns the location text into a
bounding box (used by the OpenStreetMap scraper) and a country code
(used to pick the right Hotfrog country site and to skip US-only
directories for non-US searches).
"""
import json
import urllib.parse
import urllib.request

from config import API_USER_AGENT

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def geocode(location):
    """Return {"bbox": (s, w, n, e), "point": (lat, lng), "country_code":
    "us", "display": str} or None if the location can't be found.

    `point` is the place's own centre, which is not the middle of the
    bounding box: Bristol's box reaches out over the Severn estuary, so
    its midpoint sits several miles west of the actual city.
    """
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode(
        {"q": location, "format": "json", "limit": 1, "addressdetails": 1}
    )
    req = urllib.request.Request(url, headers={"User-Agent": API_USER_AGENT})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=25).read())
    except Exception:
        return None
    if not data:
        return None
    hit = data[0]
    s, n, w, e = hit["boundingbox"]  # Nominatim order: S, N, W, E
    try:
        point = (float(hit["lat"]), float(hit["lon"]))
    except (KeyError, TypeError, ValueError):
        point = None
    return {
        "bbox": (s, w, n, e),
        "point": point,
        "country_code": (hit.get("address", {}).get("country_code") or "").lower(),
        "display": hit.get("display_name", location),
    }
