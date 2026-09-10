"""
FreeIndex.co.uk (UK).

Search results live on one page that grows via a "Show More Results"
button (JavaScript pagination). Each listing's profile page embeds clean
JSON-LD (phone, address, description) plus a website link next to a
"Website" icon.
"""
import json
import urllib.parse

from core.models import Listing
from scrapers.base import DirectoryScraper


class FreeIndexScraper(DirectoryScraper):
    key = "freeindex"
    label = "FreeIndex (UK)"
    base_url = "https://www.freeindex.co.uk"
    countries = {"gb"}
    tos_note = "Publicly browsable listings; no bot wall seen in practice."

    def robots_paths(self, keyword, location):
        return ["/searchresults.htm"]

    def _search_url(self, keyword, location):
        # The "v=a!b" parameter must stay literal - FreeIndex 404s if the
        # "!" gets percent-encoded.
        k = urllib.parse.quote_plus(keyword)
        l = urllib.parse.quote_plus(location)
        return f"{self.base_url}/searchresults.htm?k={k}&l={l}&v=a!b"

    def collect(self, context, keyword, location, geo, stats, failures, report):
        page = context.new_page()
        results = []
        try:
            url = self._search_url(keyword, location)
            report(f"[{self.label}] loading search results...")
            if not self.visit(page, url, stats, failures, report):
                return results

            self._expand_all(page, report)
            cards = self._listing_cards(page)
            stats.found = len(cards)
            report(f"[{self.label}] {len(cards)} listings found; visiting profiles...")

            for i, card in enumerate(cards[: self.max_listings], start=1):
                report(f"[{self.label}] profile {i}/{min(len(cards), self.max_listings)}: {card['name']}")
                listing = self._profile_details(page, card, keyword, stats, failures, report)
                if listing:
                    results.append(listing)
                self.pause()
        finally:
            page.close()
        return results

    def _expand_all(self, page, report):
        """Click 'Show More Results' until it disappears."""
        for _ in range(self.max_pages):
            more = page.locator("#load-more-btn")
            if more.count() == 0 or not more.is_visible():
                break
            count = page.locator("div.listing").count()
            report(f"[{self.label}] loading more results... {count} so far")
            try:
                more.click()
            except Exception:
                break
            page.wait_for_timeout(2000)
            for _ in range(10):
                if page.locator("div.listing").count() > count:
                    break
                page.wait_for_timeout(500)
            self.pause()

    def _listing_cards(self, page):
        cards = []
        for el in page.locator("div.listing").all():
            try:
                link = el.locator(".listing_name a").first
                name = link.inner_text().strip()
                href = link.get_attribute("href") or ""
                if href.startswith("/"):
                    href = self.base_url + href
                locality = ""
                loc_el = el.locator(".listing_locality")
                if loc_el.count():
                    locality = loc_el.inner_text().strip()
                if name and href:
                    cards.append({"name": name, "locality": locality, "url": href})
            except Exception:
                continue
        return cards

    def _profile_details(self, page, card, keyword, stats, failures, report):
        if not self.visit(page, card["url"], stats, failures, report, settle_ms=1500):
            return None

        phone = address = description = website = category = ""
        for el in page.locator('script[type="application/ld+json"]').all():
            try:
                data = json.loads(el.inner_text())
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(data, dict) and data.get("@type") == "LocalBusiness":
                phone = data.get("telephone", "") or ""
                description = (data.get("description", "") or "").strip()
                addr = data.get("address", {}) or {}
                parts = []
                for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode"):
                    v = (addr.get(k) or "").strip()
                    if v and v not in parts and not any(v in p for p in parts):
                        parts.append(v)
                address = ", ".join(parts)
                break

        website_el = page.locator('i[title="Website"]').locator("xpath=following-sibling::a[1]")
        if website_el.count():
            website = website_el.first.get_attribute("href") or ""

        crumbs = page.locator(".breadcrumb a").all()
        if crumbs:
            try:
                category = crumbs[-1].inner_text().strip()
            except Exception:
                category = ""

        return Listing(
            source=self.key, name=card["name"], website=website, phone=phone,
            description=description, address=address or card["locality"],
            category=category or keyword, profile_url=card["url"],
        )
