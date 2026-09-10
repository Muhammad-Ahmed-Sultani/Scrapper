"""
Hotfrog (per-country sites, picked from the search location's country).

Search results are .hf-box cards with name, phone and a description, but
the business website only appears on the /company/<id> profile page
(JSON-LD LocalBusiness block + an a[data-click="website"] link), so each
profile is visited at a human pace. Pagination is /search/<loc>/<kw>/2.
Verified loading through the stealth browser.
"""
import json
import re

from core.models import Listing
from scrapers.base import DirectoryScraper

# Hotfrog country sites. Anything not listed falls back to hotfrog.com.
COUNTRY_DOMAINS = {
    "us": "www.hotfrog.com",
    "gb": "www.hotfrog.co.uk",
    "ca": "www.hotfrog.ca",
    "au": "www.hotfrog.com.au",
    "nz": "www.hotfrog.co.nz",
    "ie": "www.hotfrog.ie",
    "in": "www.hotfrog.in",
    "sg": "www.hotfrog.sg",
    "my": "www.hotfrog.com.my",
    "ph": "www.hotfrog.ph",
    "za": "www.hotfrog.co.za",
    "de": "www.hotfrog.de",
    "fr": "www.hotfrog.fr",
    "it": "www.hotfrog.it",
    "es": "www.hotfrog.es",
    "nl": "www.hotfrog.nl",
    "be": "www.hotfrog.be",
    "at": "www.hotfrog.at",
    "ch": "www.hotfrog.ch",
    "pl": "www.hotfrog.pl",
    "se": "www.hotfrog.se",
    "no": "www.hotfrog.no",
    "dk": "www.hotfrog.dk",
    "fi": "www.hotfrog.fi",
    "pt": "www.hotfrog.pt",
    "br": "www.hotfrog.com.br",
    "mx": "www.hotfrog.com.mx",
    "ar": "www.hotfrog.com.ar",
    "cl": "www.hotfrog.cl",
}


class HotfrogScraper(DirectoryScraper):
    key = "hotfrog"
    label = "Hotfrog (worldwide)"
    base_url = "https://www.hotfrog.com"
    countries = None  # per-country domains handled in resolve_base_url
    tos_note = ("ToS restricts automated access; robots.txt currently "
                "permits it. Enabled at your discretion.")

    def resolve_base_url(self, geo):
        cc = (geo or {}).get("country_code", "")
        domain = COUNTRY_DOMAINS.get(cc, "www.hotfrog.com")
        return f"https://{domain}"

    def robots_paths(self, keyword, location):
        return [f"/search/{self._slug(location)}/{self._slug(keyword)}"]

    @staticmethod
    def _slug(text):
        return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")

    def _page_url(self, base, keyword, location, page_num):
        url = f"{base}/search/{self._slug(location)}/{self._slug(keyword)}"
        return url if page_num == 1 else f"{url}/{page_num}"

    def collect(self, context, keyword, location, geo, stats, failures, report):
        base = self.resolve_base_url(geo)
        page = context.new_page()
        cards = []
        try:
            for page_num in range(1, self.max_pages + 1):
                url = self._page_url(base, keyword, location, page_num)
                report(f"[{self.label}] results page {page_num} "
                       f"({len(cards)} listings so far)")
                if not self.visit(page, url, stats, failures, report):
                    break
                found = self._extract_cards(page, base)
                # last real page repeats when you walk past the end
                new = [c for c in found if c["profile"] not in {x["profile"] for x in cards}]
                if not new:
                    break
                cards.extend(new)
                stats.found = len(cards)
                if len(cards) >= self.max_listings:
                    cards = cards[: self.max_listings]
                    break
                if not self._has_next_page(page, page_num):
                    break
                self.pause()

            report(f"[{self.label}] {len(cards)} listings; visiting profiles for websites...")
            results = []
            for i, card in enumerate(cards, start=1):
                report(f"[{self.label}] profile {i}/{len(cards)}: {card['name']}")
                listing = self._profile_details(page, card, keyword, stats, failures, report)
                if listing:
                    results.append(listing)
                self.pause()
            return results
        finally:
            page.close()

    def _extract_cards(self, page, base):
        cards = []
        for el in page.locator(".hf-box").all():
            try:
                link = el.locator('h3 a[href^="/company/"]').first
                if link.count() == 0:
                    continue
                name = link.inner_text().strip()
                href = link.get_attribute("href") or ""
                if not name or not href:
                    continue
                phone = ""
                tel = el.locator('a[href^="tel:"]').first
                if tel.count():
                    phone = tel.inner_text().strip()
                description = ""
                for p in el.locator("p.mb-0").all():
                    text = p.inner_text().strip()
                    # skip the "Message business | Review now" action row
                    if len(text) > 40 and "Review now" not in text:
                        description = " ".join(text.split())[:400]
                        break
                cards.append({"name": name, "phone": phone,
                              "description": description, "profile": base + href})
            except Exception:
                continue
        return cards

    @staticmethod
    def _has_next_page(page, current):
        for a in page.locator("a.page-link").all():
            href = a.get_attribute("href") or ""
            if href.rstrip("/").endswith(f"/{current + 1}"):
                return True
        return False

    def _profile_details(self, page, card, keyword, stats, failures, report):
        listing = Listing(
            source=self.key, name=card["name"], phone=card["phone"],
            description=card["description"], category=keyword,
            profile_url=card["profile"],
        )
        if not self.visit(page, card["profile"], stats, failures, report, settle_ms=2000):
            return listing  # keep the card data even if the profile failed

        # JSON-LD block: {"success":true,"msg":"OK","data":{...LocalBusiness}}
        for el in page.locator('script[type="application/ld+json"]').all():
            try:
                data = json.loads(el.inner_text())
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            if not (isinstance(data, dict) and data.get("@type") == "LocalBusiness"):
                continue
            listing.phone = listing.phone or (data.get("telephone") or "").strip()
            listing.description = listing.description or (data.get("description") or "").strip()[:400]
            addr = data.get("address") or {}
            if isinstance(addr, dict):
                parts = [str(addr.get(k) or "").strip()
                         for k in ("streetAddress", "addressLocality",
                                   "addressRegion", "postalCode")]
                listing.address = ", ".join(p for p in parts if p)
            break

        web = page.locator('a[data-click="website"]').first
        if web.count():
            listing.website = (web.get_attribute("href") or "").strip()
        return listing
