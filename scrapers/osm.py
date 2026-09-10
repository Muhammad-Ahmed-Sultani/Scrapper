"""
OpenStreetMap (worldwide) via the free Overpass API.

Not a scrape at all - OSM is an openly licensed database (ODbL, needs
attribution only), so this is the cleanest source in the set. The
pipeline's geocode step supplies the bounding box; common category words
are mapped to proper OSM tags, anything unmapped falls back to a
name-contains query. Some entries carry an email directly.
"""
import json
import re
import time
import urllib.parse
import urllib.request

from config import API_USER_AGENT
from core.models import Listing
from scrapers.base import DirectoryScraper

# Public Overpass instances, tried in order. They share the same data and
# API; a busy one answers 429/504, so we fail over instead of losing the
# whole directory for the run.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
# The [timeout:] Overpass is allowed to spend building the result, and the
# HTTP read budget, which must be the longer of the two.
OVERPASS_QUERY_TIMEOUT = 90
OVERPASS_HTTP_TIMEOUT = 120
OVERPASS_RETRY_DELAY = 3.0   # breather before failing over to the next mirror

# Tag keys that classify a business in OSM. Used to guess a tag for a
# keyword that CATEGORY_TAGS doesn't cover.
GUESSABLE_TAG_KEYS = ("shop", "amenity", "craft", "office", "leisure",
                      "healthcare", "tourism")

CATEGORY_TAGS = {
    "restaurants": [("amenity", "restaurant")],
    "cafes": [("amenity", "cafe")],
    "coffee shops": [("amenity", "cafe")],
    "pubs": [("amenity", "pub")],
    "bars": [("amenity", "bar")],
    "hotels": [("tourism", "hotel")],
    "guest houses": [("tourism", "guest_house")],
    "takeaways": [("amenity", "fast_food")],
    "fast food": [("amenity", "fast_food")],
    "hairdressers": [("shop", "hairdresser")],
    "salons": [("shop", "hairdresser"), ("shop", "beauty")],
    "beauty salons": [("shop", "beauty")],
    "barbers": [("shop", "hairdresser")],
    "dentists": [("amenity", "dentist")],
    "doctors": [("amenity", "doctors")],
    "pharmacies": [("amenity", "pharmacy")],
    "opticians": [("shop", "optician")],
    "vets": [("amenity", "veterinary")],
    "veterinary": [("amenity", "veterinary")],
    "gyms": [("leisure", "fitness_centre")],
    "plumbers": [("craft", "plumber")],
    "electricians": [("craft", "electrician")],
    "builders": [("craft", "builder")],
    "carpenters": [("craft", "carpenter")],
    "estate agents": [("office", "estate_agent")],
    "accountants": [("office", "accountant")],
    "solicitors": [("office", "lawyer")],
    "lawyers": [("office", "lawyer")],
    "florists": [("shop", "florist")],
    "bakeries": [("shop", "bakery")],
    "butchers": [("shop", "butcher")],
    "supermarkets": [("shop", "supermarket")],
    "car repair": [("shop", "car_repair")],
    "garages": [("shop", "car_repair")],
    "car dealers": [("shop", "car")],
    "travel agents": [("shop", "travel_agency")],
    "jewellers": [("shop", "jewelry")],
    "pet shops": [("shop", "pet")],
    "tattoo parlours": [("shop", "tattoo")],
    "tattoo studios": [("shop", "tattoo")],
    "nail salons": [("shop", "beauty")],
    "spas": [("leisure", "spa"), ("shop", "beauty")],
    "driving schools": [("amenity", "driving_school")],
    "driving instructors": [("amenity", "driving_school")],
    "nurseries": [("amenity", "kindergarten")],
    "childcare": [("amenity", "childcare")],
    "schools": [("amenity", "school")],
    "physiotherapists": [("healthcare", "physiotherapist")],
    "chiropractors": [("healthcare", "chiropractor")],
    "care homes": [("amenity", "social_facility")],
    "dry cleaners": [("shop", "dry_cleaning"), ("shop", "laundry")],
    "laundrettes": [("shop", "laundry")],
    "locksmiths": [("craft", "locksmith")],
    "roofers": [("craft", "roofer")],
    "painters": [("craft", "painter")],
    "decorators": [("craft", "painter")],
    "gardeners": [("craft", "gardener")],
    "photographers": [("craft", "photographer")],
    "removals": [("shop", "storage_rental"), ("office", "moving_company")],
    "insurance": [("office", "insurance")],
    "financial advisers": [("office", "financial_advisor")],
    "recruitment agencies": [("office", "employment_agency")],
    "printers": [("shop", "copyshop"), ("craft", "printer")],
    "phone shops": [("shop", "mobile_phone")],
    "computer repair": [("shop", "computer")],
    "furniture shops": [("shop", "furniture")],
    "hardware stores": [("shop", "hardware"), ("shop", "doityourself")],
    "clothing shops": [("shop", "clothes")],
    "convenience stores": [("shop", "convenience")],
    "off licences": [("shop", "alcohol")],
    "newsagents": [("shop", "newsagent")],
    "charity shops": [("shop", "charity")],
    "banks": [("amenity", "bank")],
    "nightclubs": [("amenity", "nightclub")],
    "cinemas": [("amenity", "cinema")],
    "theatres": [("amenity", "theatre")],
    "churches": [("amenity", "place_of_worship")],
    "funeral directors": [("shop", "funeral_directors")],
    "bed and breakfasts": [("tourism", "guest_house")],
    "campsites": [("tourism", "camp_site")],
    "car parks": [("amenity", "parking")],
    "petrol stations": [("amenity", "fuel")],
    "gas stations": [("amenity", "fuel")],
    "car washes": [("amenity", "car_wash")],
    "bike shops": [("shop", "bicycle")],
    "book shops": [("shop", "books")],
    "toy shops": [("shop", "toys")],
    "garden centres": [("shop", "garden_centre")],
    "kitchens": [("shop", "kitchen")],
    "tyre shops": [("shop", "tyres")],
}


class OSMScraper(DirectoryScraper):
    key = "osm"
    label = "OpenStreetMap (worldwide)"
    base_url = "https://overpass-api.de"
    countries = None
    tos_note = "Open data (ODbL); explicitly fine to reuse with attribution."
    # Overpass's robots.txt disallows /api/ to keep crawlers out of the
    # query endpoint. That rule is aimed at spiders, not at API clients:
    # /api/interpreter IS the documented public interface, governed by its
    # own usage policy (be light, identify yourself), which we follow via
    # API_USER_AGENT, a result cap, and one query per run.
    respects_robots = False

    def robots_paths(self, keyword, location):
        return ["/api/interpreter"]

    def collect(self, context, keyword, location, geo, stats, failures, report):
        if not geo:
            report(f"[{self.label}] location could not be geocoded - skipping")
            return []

        filters, name_fallback = self._filters(keyword)
        query = self._query(filters, name_fallback, keyword, geo["bbox"],
                            self.max_listings)
        report(f"[{self.label}] querying Overpass for '{keyword}'...")

        res = self._fetch(query, stats, failures, report)
        if res is None:
            return []

        elements = [el for el in res.get("elements", [])
                    if el.get("tags", {}).get("name")]
        # nodes and ways can describe the same place twice
        seen = set()
        listings = []
        for el in elements:
            t = el["tags"]
            key = (t.get("name", ""),
                   t.get("website", "") or t.get("contact:website", ""))
            if key in seen:
                continue
            seen.add(key)
            listings.append(Listing(
                source=self.key,
                name=t.get("name", "").strip(),
                website=self._tag(t, "website", "contact:website"),
                email=self._tag(t, "email", "contact:email"),
                phone=self._tag(t, "phone", "contact:phone"),
                description=self._tag(t, "description"),
                address=self._address(t),
                category=keyword,
            ))
            if len(listings) >= self.max_listings:
                break

        stats.found = len(listings)
        report(f"[{self.label}] {len(listings)} businesses found")
        return listings

    def _fetch(self, query, stats, failures, report):
        """POST the query, failing over across the public mirrors.

        A loaded instance answers 429 (rate limited) or 504 (its own query
        timeout) - both mean "ask someone else", not "no results".
        Returns the decoded JSON, or None when every mirror refused.
        """
        last_error = ""
        for index, url in enumerate(OVERPASS_URLS):
            req = urllib.request.Request(
                url,
                data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"User-Agent": API_USER_AGENT},
            )
            try:
                return json.loads(
                    urllib.request.urlopen(req, timeout=OVERPASS_HTTP_TIMEOUT).read())
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                failures.log(self.key, url, f"overpass: {last_error}")
                if index + 1 < len(OVERPASS_URLS):
                    report(f"[{self.label}] {url} unavailable ({last_error}) "
                           f"- trying the next mirror...")
                    time.sleep(OVERPASS_RETRY_DELAY)

        report(f"[{self.label}] every Overpass mirror failed: {last_error}")
        stats.failed_pages += 1
        return None

    @staticmethod
    def _tag_guesses(keyword):
        """Plausible OSM tag values for a keyword not in CATEGORY_TAGS.

        Both the plural as typed and its singular, since OSM values are
        singular ("driving schools" -> driving_school).
        """
        slug = re.sub(r"[^a-z0-9]+", "_", keyword.strip().lower()).strip("_")
        if not slug:
            return []
        guesses = [slug]
        if slug.endswith("ies"):
            guesses.append(slug[:-3] + "y")
        elif slug.endswith("ses"):
            guesses.append(slug[:-2])
        elif slug.endswith("s"):
            guesses.append(slug[:-1])
        return list(dict.fromkeys(guesses))

    @staticmethod
    def _filters(keyword):
        norm = keyword.strip().lower()
        if norm in CATEGORY_TAGS:
            return CATEGORY_TAGS[norm], False
        if norm.endswith("s") and norm[:-1] in CATEGORY_TAGS:
            return CATEGORY_TAGS[norm[:-1]], False
        if norm + "s" in CATEGORY_TAGS:
            return CATEGORY_TAGS[norm + "s"], False
        return [], True

    @staticmethod
    def _query(filters, name_fallback, keyword, bbox, limit):
        """Build the Overpass QL query.

        Two details matter for it to complete at city scale:
        `nwr` matches nodes, ways and relations in one statement (a big
        shop mapped as a relation was previously invisible), and the
        result cap on `out` is applied server-side - without it a query
        like "restaurants in London" builds ~10k full elements and every
        public instance answers 504.
        """
        s, w, n, e = bbox
        box = f"({s},{w},{n},{e})"
        parts = []
        if name_fallback:
            safe = re.sub(r'["\\]', "", keyword).strip()
            parts.append(f'nwr["name"~"{safe}",i]{box};')
            # OSM's own vocabulary often already matches an unmapped
            # keyword: "driving schools" -> amenity=driving_school. Guessing
            # the tag value costs one indexed lookup each and catches the
            # businesses whose name never spells the category out.
            for slug in OSMScraper._tag_guesses(keyword):
                for key in GUESSABLE_TAG_KEYS:
                    parts.append(f'nwr["{key}"="{slug}"]["name"]{box};')
        else:
            for key, value in filters:
                parts.append(f'nwr["{key}"="{value}"]["name"]{box};')
        return (f"[out:json][timeout:{OVERPASS_QUERY_TIMEOUT}];"
                f"({''.join(parts)});out center tags {limit};")

    @staticmethod
    def _tag(tags, *keys):
        for k in keys:
            if tags.get(k):
                return tags[k].strip()
        return ""

    @staticmethod
    def _address(tags):
        parts = []
        for key in ("addr:housenumber", "addr:street", "addr:city", "addr:postcode"):
            v = (tags.get(key) or "").strip()
            if v:
                parts.append(v)
        return ", ".join(parts)
