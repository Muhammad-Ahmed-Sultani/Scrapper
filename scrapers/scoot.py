"""
Scoot.co.uk (UK).

Everything needed sits on the search results page itself (name, category,
address, phone, website link), paginated with plain ?page=N URLs. Note:
Scoot only shows websites for premium listings, so email yield is low.
"""
import re

from core.models import Listing
from scrapers.base import DirectoryScraper


class ScootScraper(DirectoryScraper):
    key = "scoot"
    label = "Scoot (UK)"
    base_url = "https://www.scoot.co.uk"
    countries = {"gb"}
    tos_note = ("Publicly browsable; websites shown only for premium "
                "listings, so email yield is low.")

    def robots_paths(self, keyword, location):
        return [f"/find/{self._slug(keyword)}-in-{self._slug(location)}"]

    @staticmethod
    def _slug(text):
        return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")

    def _page_url(self, keyword, location, page_num):
        base = f"{self.base_url}/find/{self._slug(keyword)}-in-{self._slug(location)}"
        return base if page_num == 1 else f"{base}?page={page_num}"

    def collect(self, context, keyword, location, geo, stats, failures, report):
        page = context.new_page()
        results = []
        try:
            for page_num in range(1, self.max_pages + 1):
                url = self._page_url(keyword, location, page_num)
                report(f"[{self.label}] results page {page_num} "
                       f"({len(results)} listings so far)")
                if not self.visit(page, url, stats, failures, report, settle_ms=1500):
                    break
                found = self._extract(page, keyword)
                if not found:
                    break  # walked past the last page
                results.extend(found)
                stats.found = len(results)
                if len(results) >= self.max_listings:
                    results = results[: self.max_listings]
                    break
                self.pause()
        finally:
            page.close()
        return results

    def _extract(self, page, keyword):
        found = []
        for el in page.locator("div.result").all():
            try:
                name_el = el.locator(".result-title a").first
                if name_el.count() == 0:
                    continue
                name = name_el.inner_text().strip()
                if not name:
                    continue

                category = address = phone = website = ""
                cat_el = el.locator(".result-category").first
                if cat_el.count():
                    category = cat_el.inner_text().strip()
                addr_el = el.locator(".result-address").first
                if addr_el.count():
                    address = " ".join(addr_el.inner_text().split())
                # Full phone number lives in a data attribute (visible text
                # is truncated like "020 740...").
                num_link = el.locator(".result-number a").first
                if num_link.count():
                    phone = (num_link.get_attribute("data-link-number")
                             or num_link.get_attribute("data-visible-number") or "").strip()
                web_link = el.locator(
                    ".result-links a[data-web-click], a[data-yext-click='website']").first
                if web_link.count():
                    website = (web_link.get_attribute("href") or "").strip()

                found.append(Listing(
                    source=self.key, name=name, website=website, phone=phone,
                    address=address, category=category or keyword,
                ))
            except Exception:
                continue
        return found
