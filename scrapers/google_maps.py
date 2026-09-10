"""
Google Maps / Google Business Profile.

The most restricted source in the set, and the one to understand before
enabling. Three facts about it, measured rather than assumed:

1. Google's robots.txt disallows /maps/search, and their Terms of Service
   prohibit automated extraction. `respects_robots` is False here so the
   gate doesn't silently skip the directory - the choice to run it is
   yours, and the ToS note says so in the UI and the summary sheet.
2. One search returns about 60 results and then stops, showing "you're
   seeing a limited view". No amount of scrolling gets past that, so
   covering a city means splitting its bounding box into a grid and
   searching each tile separately. That's what _tiles() does.
3. Maps loads its results over XHR, and the fixed navigation headers in
   config.COMMON_HEADERS make every one of those look like a top-level
   document request, which stops the app rendering at all. Hence
   `sends_common_headers = False`.

No detection evasion beyond what the rest of the project already does:
the shared stealth context, human-paced delays, and the standard retry
and circuit-breaker logic. A block is recorded and skipped, never fought.
Expect a lower yield here than from the open directories.
"""
import math
import re
import urllib.parse

from config import (GOOGLE_MAPS_MAX_SCROLLS, GOOGLE_MAPS_MAX_TILES,
                    GOOGLE_MAPS_TILE_DEGREES, GOOGLE_MAPS_TILE_ZOOM)
from core.models import Listing
from scrapers.base import DirectoryScraper

# The stable part of a place URL: !1s<hex>:<hex> is Google's own id for
# the place, so it survives the rest of the URL changing shape.
PLACE_ID_RE = re.compile(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", re.I)
# Private-use codepoints: Maps renders its icons as ligature glyphs inside
# ordinary text nodes, so they land in innerText as junk characters.
ICON_GLYPH_RE = re.compile("[\uE000-\uF8FF]")

FEED = 'div[role="feed"]'
PLACE_LINK = 'a[href*="/maps/place/"]'


class GoogleMapsScraper(DirectoryScraper):
    key = "google_maps"
    label = "Google Maps (worldwide)"
    base_url = "https://www.google.com"
    countries = None
    tos_note = ("Google's robots.txt disallows /maps/search and their ToS "
                "prohibits automated extraction - enabling this is your call")
    respects_robots = False
    sends_common_headers = False
    enabled_by_default = False

    def robots_paths(self, keyword, location):
        return ["/maps/search/"]

    # -------------------------------------------------------------- tiles
    @staticmethod
    def _tiles(geo):
        """Split the location's bounding box into search tiles.

        Returns a list of (lat, lng) centres, or [None] when there's no
        bounding box to work from (the caller then does a plain text
        search). One search caps out around 60 results, so a city needs
        several overlapping searches to be covered at all.
        """
        if not geo or not geo.get("bbox"):
            return [None]
        try:
            s, w, n, e = (float(v) for v in geo["bbox"])
        except (TypeError, ValueError):
            return [None]

        lat_span, lng_span = abs(n - s), abs(e - w)
        # A degree of longitude shrinks towards the poles; comparing it to
        # a degree of latitude without this makes tiles the wrong shape.
        squeeze = max(0.1, math.cos(math.radians((s + n) / 2)))
        rows = max(1, math.ceil(lat_span / GOOGLE_MAPS_TILE_DEGREES))
        cols = max(1, math.ceil(lng_span * squeeze / GOOGLE_MAPS_TILE_DEGREES))
        # Trim the longer side first so a long thin region stays covered.
        while rows * cols > GOOGLE_MAPS_MAX_TILES:
            if rows >= cols:
                rows -= 1
            else:
                cols -= 1

        centres = [
            (s + lat_span * (r + 0.5) / rows, w + lng_span * (c + 0.5) / cols)
            for r in range(rows)
            for c in range(cols)
        ]
        # Search outwards from the town centre. A bounding box for a city
        # is generous, so its edges are usually outlying villages; when a
        # run stops at the listing cap it should have spent that budget on
        # the centre rather than on whichever edge came first. Anchor on
        # the geocoder's own point, since the middle of the box can be
        # somewhere else entirely - Bristol's lands out in the estuary.
        mid_lat, mid_lng = geo.get("point") or ((s + n) / 2, (w + e) / 2)
        centres.sort(key=lambda p: ((p[0] - mid_lat) ** 2
                                    + ((p[1] - mid_lng) * squeeze) ** 2))
        return centres

    def _search_url(self, keyword, location, tile):
        term = urllib.parse.quote(keyword if tile else f"{keyword} in {location}")
        url = f"{self.base_url}/maps/search/{term}"
        if tile:
            lat, lng = tile
            url += f"/@{lat:.6f},{lng:.6f},{GOOGLE_MAPS_TILE_ZOOM}z"
        return url + "?hl=en"

    # ------------------------------------------------------------ collect
    def collect(self, context, keyword, location, geo, stats, failures, report):
        page = context.new_page()
        cards = {}
        try:
            tiles = self._tiles(geo)
            report(f"[{self.label}] searching {len(tiles)} map "
                   f"{'area' if len(tiles) == 1 else 'areas'}...")

            for index, tile in enumerate(tiles, start=1):
                url = self._search_url(keyword, location, tile)
                report(f"[{self.label}] area {index}/{len(tiles)}: searching...")
                if not self.visit(page, url, stats, failures, report, settle_ms=4000):
                    continue
                self._dismiss_consent(page, report)
                found = self._scroll_results(page, index, len(tiles), report)
                for card in found:
                    cards.setdefault(card["place_id"], card)
                report(f"[{self.label}] area {index}/{len(tiles)}: "
                       f"{len(found)} results, {len(cards)} unique so far")
                if len(cards) >= self.max_listings:
                    report(f"[{self.label}] listing cap reached - stopping search")
                    break
                self.pause()

            ordered = list(cards.values())[: self.max_listings]
            stats.found = len(ordered)
            if not ordered:
                return []

            report(f"[{self.label}] {len(ordered)} places found; opening profiles...")
            results = []
            for i, card in enumerate(ordered, start=1):
                report(f"[{self.label}] profile {i}/{len(ordered)}: {card['name']}")
                results.append(self._place_details(page, card, keyword,
                                                   stats, failures, report))
                self.pause()
            return results
        finally:
            page.close()

    def _dismiss_consent(self, page, report):
        """Decline Google's cookie consent wall if it appears.

        Rejecting rather than accepting: it's the privacy-preserving
        answer and it clears the interstitial just the same.
        """
        if "consent.google" not in page.url and "/consent" not in page.url:
            return
        for label in ("Reject all", "Reject All", "Decline all"):
            button = page.get_by_role("button", name=label)
            try:
                if button.count():
                    report(f"[{self.label}] declining cookie consent...")
                    button.first.click()
                    page.wait_for_timeout(3000)
                    return
            except Exception:
                continue

    def _scroll_results(self, page, index, total, report):
        """Scroll the results panel until Google stops adding to it."""
        try:
            page.wait_for_selector(FEED, timeout=25000)
        except Exception:
            return []

        previous = -1
        for step in range(GOOGLE_MAPS_MAX_SCROLLS):
            try:
                page.eval_on_selector(FEED, "el => el.scrollTop = el.scrollHeight")
            except Exception:
                break
            page.wait_for_timeout(2200)
            count = page.locator(PLACE_LINK).count()
            if page.get_by_text("You've reached the end of the list").count():
                break
            if count == previous:
                # Google caps a single search well before the real total;
                # the tile grid is what compensates for that.
                break
            previous = count
            if step and step % 5 == 0:
                report(f"[{self.label}] area {index}/{total}: "
                       f"loading results... {count} so far")

        return self._read_cards(page)

    @staticmethod
    def _read_cards(page):
        """Name, profile URL and the card's own summary text, per result."""
        try:
            raw = page.evaluate(
                """() => [...document.querySelectorAll('div[role="feed"] > div')]
                    .map(row => {
                        const a = row.querySelector('a[href*="/maps/place/"]');
                        if (!a) return null;
                        return {name: (a.getAttribute('aria-label') || '').trim(),
                                url: a.href,
                                text: row.innerText || ''};
                    })
                    .filter(Boolean)""")
        except Exception:
            return []

        cards = []
        for item in raw:
            match = PLACE_ID_RE.search(item["url"])
            if not item["name"] or not match:
                continue
            item["place_id"] = match.group(1).lower()
            item["text"] = ICON_GLYPH_RE.sub("", item["text"])
            cards.append(item)
        return cards

    # ------------------------------------------------------------ details
    def _place_details(self, page, card, keyword, stats, failures, report):
        """Open one place and read its panel.

        Falls back to the search card's own text when the profile won't
        load, so a failed page costs the extra fields rather than the
        whole business.
        """
        fallback = self._from_card(card, keyword)
        if not self.visit(page, card["url"], stats, failures, report, settle_ms=3500):
            return fallback

        try:
            data = page.evaluate(
                """() => {
                    const el = s => document.querySelector(s);
                    const label = (e, prefix) => {
                        if (!e) return '';
                        let v = (e.getAttribute('aria-label') || e.innerText || '').trim();
                        if (prefix && v.toLowerCase().startsWith(prefix)) {
                            v = v.slice(prefix.length).trim();
                        }
                        return v;
                    };
                    const phoneButton = el('button[data-item-id^="phone:tel:"]');
                    const categoryButton = el('button[jsaction*="category"]')
                        || el('button[jsaction*="Category"]');
                    return {
                        name: label(el('h1')),
                        address: label(el('button[data-item-id="address"]'), 'address:'),
                        // data-item-id carries the number already normalised
                        phone: (phoneButton?.getAttribute('data-item-id') || '')
                            .replace('phone:tel:', ''),
                        website: el('a[data-item-id="authority"]')?.href || '',
                        category: label(categoryButton)
                    };
                }""")
        except Exception:
            return fallback

        return Listing(
            source=self.key,
            name=(data.get("name") or card["name"]).strip(),
            website=data.get("website") or "",
            phone=data.get("phone") or fallback.phone,
            description=fallback.description,
            address=data.get("address") or fallback.address,
            category=data.get("category") or keyword,
            profile_url=card["url"],
        )

    def _from_card(self, card, keyword):
        """Whatever the search card alone can tell us about a business.

        Card text runs: name, name again, rating, then a line of
        "Category . price . street", then an optional one-line summary.
        Only the parts that are unambiguous are trusted.
        """
        lines = [l.strip() for l in card["text"].splitlines() if l.strip()]
        name = card["name"]
        lines = [l for l in lines if l != name]
        # Drop the rating line. It renders either as "4.7" on its own or
        # with the review count attached, as "4.7(439)".
        lines = [l for l in lines
                 if not re.fullmatch(r"\d(?:\.\d)?(?:\(\d[\d,]*\))?", l)]

        address = description = category = ""
        for line in lines:
            if "·" in line and not address:
                parts = [p.strip() for p in line.split("·") if p.strip()]
                if parts:
                    category = parts[0]
                    address = parts[-1] if len(parts) > 1 else ""
            elif not description and not re.match(r"(open|closed|opens|closes)\b",
                                                  line, re.I):
                description = line

        return Listing(
            source=self.key, name=name, phone="", website="",
            description=description, address=address,
            category=category or keyword, profile_url=card["url"],
        )
