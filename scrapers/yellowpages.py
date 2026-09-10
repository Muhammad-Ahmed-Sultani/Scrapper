"""
YellowPages.com (US).

Search results are server-rendered div.result cards carrying everything
we need directly: business name, an external website link
(a.track-visit-website), phone, address, categories, and a snippet.
Pagination is plain &page=N. Verified loading through the stealth
browser (Cloudflare present but passive as of mid-2026).
"""
import urllib.parse

from core.models import Listing
from scrapers.base import DirectoryScraper


class YellowPagesScraper(DirectoryScraper):
    key = "yellowpages"
    label = "Yellow Pages (US)"
    base_url = "https://www.yellowpages.com"
    countries = {"us"}
    tos_note = ("ToS restricts automated access; robots.txt currently "
                "permits it. Enabled at your discretion.")

    def robots_paths(self, keyword, location):
        return ["/search"]

    def _page_url(self, keyword, location, page_num):
        params = {"search_terms": keyword, "geo_location_terms": location}
        if page_num > 1:
            params["page"] = page_num
        return f"{self.base_url}/search?" + urllib.parse.urlencode(params)

    def collect(self, context, keyword, location, geo, stats, failures, report):
        page = context.new_page()
        results = []
        try:
            for page_num in range(1, self.max_pages + 1):
                url = self._page_url(keyword, location, page_num)
                report(f"[{self.label}] results page {page_num} "
                       f"({len(results)} listings so far)")
                if not self.visit(page, url, stats, failures, report):
                    break
                found = self._extract(page, keyword)
                if not found:
                    break
                results.extend(found)
                stats.found = len(results)
                if len(results) >= self.max_listings:
                    results = results[: self.max_listings]
                    break
                # stop when there's no "next" link instead of loading a
                # page that would just repeat results
                if page.locator(".pagination a.next").count() == 0:
                    break
                self.pause()
        finally:
            page.close()
        return results

    def _external_website(self, el):
        """First real external site link on a card, skipping internal
        yellowpages.com profile/directions links."""
        anchors = el.locator(".links a, a.track-visit-website")
        for i in range(anchors.count()):
            href = (anchors.nth(i).get_attribute("href") or "").strip()
            if href.startswith("http") and "yellowpages.com" not in href.lower():
                return href
        return ""

    def _extract(self, page, keyword):
        found = []
        for el in page.locator("div.result").all():
            try:
                name_el = el.locator("a.business-name").first
                if name_el.count() == 0:
                    continue
                name = name_el.inner_text().strip()
                if not name:
                    continue
                profile = name_el.get_attribute("href") or ""
                if profile.startswith("/"):
                    profile = self.base_url + profile

                website = phone = address = category = description = ""
                # YP has two card layouts: organic cards use
                # a.track-visit-website; paid/ad cards use a plain
                # .links a whose text is "Website". Both point to the real
                # site, but some cards' "website" link is just an internal
                # yellowpages.com profile link - filter those out.
                website = self._external_website(el)
                # Phone: organic cards use "phones phone primary", ad cards
                # a bare "phone" - ".phone" matches both.
                phone_el = el.locator(".phone").first
                if phone_el.count():
                    phone = " ".join(phone_el.inner_text().split())
                addr_el = el.locator(".adr, .street-address").first
                if addr_el.count():
                    address = " ".join(addr_el.inner_text().split())
                cat_el = el.locator(".categories a").first
                if cat_el.count():
                    category = cat_el.inner_text().strip()
                snip_el = el.locator(".snippet").first
                if snip_el.count():
                    description = " ".join(snip_el.inner_text().split())[:400]

                found.append(Listing(
                    source=self.key, name=name, website=website, phone=phone,
                    description=description, address=address,
                    category=category or keyword, profile_url=profile,
                ))
            except Exception:
                continue
        return found
