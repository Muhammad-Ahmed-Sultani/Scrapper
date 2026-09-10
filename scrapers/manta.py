"""
Manta.com (US).

Heads-up: Manta sits behind an interactive Cloudflare challenge that does
not clear for automated browsers even with stealth applied (verified
July 2026). robots.txt allows /search and /c/ profile pages, so this
scraper is implemented and will work if Manta relaxes the wall - until
then runs will retry, log the URLs to failed_urls.csv, and mark the
directory "blocked - review separately" in the summary, as designed.

Extraction is JSON-LD-first: search results link to /c/<id>/<slug>
profile pages whose LocalBusiness block carries phone/address/description.
"""
import json
import urllib.parse

from core.models import Listing
from core.retry import DirectoryBlocked
from scrapers.base import DirectoryScraper


class MantaScraper(DirectoryScraper):
    key = "manta"
    label = "Manta (US)"
    base_url = "https://www.manta.com"
    countries = {"us"}
    tos_note = ("robots.txt allows search/profile pages, but an interactive "
                "Cloudflare wall currently blocks automation; expect "
                "'blocked' until Manta changes it.")

    # Manta blocks hard; don't burn time on many profile visits
    max_listings = 60

    def robots_paths(self, keyword, location):
        return ["/search", "/c/example"]

    def _search_url(self, keyword, location):
        q = f"{keyword} {location}".strip()
        return f"{self.base_url}/search?" + urllib.parse.urlencode({"search": q})

    def collect(self, context, keyword, location, geo, stats, failures, report):
        page = context.new_page()
        results = []
        try:
            url = self._search_url(keyword, location)
            report(f"[{self.label}] loading search results...")
            if not self.visit(page, url, stats, failures, report, settle_ms=4000):
                return results

            profiles = self._profile_links(page)
            stats.found = len(profiles)
            report(f"[{self.label}] {len(profiles)} profiles found; visiting each...")

            for i, (name, href) in enumerate(profiles[: self.max_listings], start=1):
                report(f"[{self.label}] profile {i}/{min(len(profiles), self.max_listings)}: {name or href}")
                listing = self._profile_details(page, name, href, keyword,
                                                stats, failures, report)
                if listing:
                    results.append(listing)
                self.pause()
        except DirectoryBlocked:
            raise
        finally:
            page.close()
        return results

    def _profile_links(self, page):
        """Company profiles live under /c/<id>/<slug>."""
        seen = set()
        links = []
        for a in page.locator('a[href^="/c/"]').all():
            try:
                href = a.get_attribute("href") or ""
                path = href.split("?")[0]
                if path in seen or path.count("/") < 2:
                    continue
                seen.add(path)
                name = " ".join((a.inner_text() or "").split())
                links.append((name, self.base_url + path))
            except Exception:
                continue
        return links

    def _profile_details(self, page, name, url, keyword, stats, failures, report):
        if not self.visit(page, url, stats, failures, report, settle_ms=3000):
            return None

        listing = Listing(source=self.key, name=name, category=keyword,
                          profile_url=url)
        for el in page.locator('script[type="application/ld+json"]').all():
            try:
                data = json.loads(el.inner_text())
            except (json.JSONDecodeError, ValueError):
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not (isinstance(item, dict) and item.get("@type") in
                        ("LocalBusiness", "Organization")):
                    continue
                listing.name = listing.name or (item.get("name") or "").strip()
                listing.phone = (item.get("telephone") or "").strip()
                listing.description = (item.get("description") or "").strip()[:400]
                site = (item.get("url") or "").strip()
                if site and "manta.com" not in site:
                    listing.website = site
                addr = item.get("address") or {}
                if isinstance(addr, dict):
                    parts = [str(addr.get(k) or "").strip()
                             for k in ("streetAddress", "addressLocality",
                                       "addressRegion", "postalCode")]
                    listing.address = ", ".join(p for p in parts if p)
                break

        if not listing.website:
            # visit-website style outbound link, if the profile shows one
            web = page.locator('a[href*="ExternalUrl"], a[data-test="website"]').first
            if web.count():
                listing.website = (web.get_attribute("href") or "").strip()

        return listing if listing.name else None
