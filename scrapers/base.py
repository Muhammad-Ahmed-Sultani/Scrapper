"""
The pluggable scraper interface. One subclass per directory site.

A scraper's only job is to COLLECT listings (name, website, phone,
description, address, category) for a keyword + location. It does not
find emails, dedupe, or export - the pipeline does that uniformly.

To add a new directory: subclass DirectoryScraper, implement collect(),
and register the class in scrapers/__init__.py. Everything else
(robots gate, stealth contexts, retries, rate limiting, failure log,
summary stats, export) comes for free.
"""
from abc import ABC, abstractmethod

from config import MAX_LISTINGS_PER_DIRECTORY, MAX_PAGES_PER_DIRECTORY
from core.humanize import human_delay
from core.retry import goto_checked, record_block, with_retries
from core.stealth import new_stealth_context


class DirectoryScraper(ABC):
    key = ""            # short id, used in stats / failed_urls.csv / UI
    label = ""          # human name shown in the UI
    base_url = ""       # scheme+host, used for the robots.txt check
    # ISO country codes the directory covers; None = worldwide.
    countries = None
    # Honest note about the site's terms, surfaced in the UI/summary.
    tos_note = ""
    # Whether the UI ticks this directory on page load. A source that
    # needs a deliberate decision (Google Maps) starts unticked.
    enabled_by_default = True
    # Whether the live robots.txt gate applies. True for every site we
    # scrape by fetching HTML pages. A documented public data API with its
    # own usage policy (OSM's Overpass) can set this False - see that class.
    respects_robots = True
    # Whether the context should carry config.COMMON_HEADERS. A site that
    # renders its results over XHR (Google Maps) breaks on them - see
    # core.stealth.new_stealth_context.
    sends_common_headers = True

    max_pages = MAX_PAGES_PER_DIRECTORY
    max_listings = MAX_LISTINGS_PER_DIRECTORY

    # set by the pipeline: shared per-host rate limiter for the run
    limiter = None

    def robots_paths(self, keyword, location):
        """Paths the scraper will touch, for the robots.txt pre-check."""
        return ["/"]

    def make_context(self, browser):
        """The stealth context this directory runs in. Overridable for sites
        that need different context options."""
        return new_stealth_context(browser,
                                   common_headers=self.sends_common_headers)

    def resolve_base_url(self, geo):
        """Hook for directories with per-country sites (Hotfrog)."""
        return self.base_url

    @abstractmethod
    def collect(self, context, keyword, location, geo, stats, failures, report):
        """Yield/return a list of core.models.Listing. `context` is a
        stealth browser context dedicated to this directory."""

    # ------------------------------------------------------------ helpers
    def visit(self, page, url, stats, failures, report, settle_ms=2500):
        """Load a directory page with block detection, retries with backoff,
        failure logging, and the consecutive-block circuit breaker.
        Returns True when the page is usable."""
        if self.limiter:
            self.limiter.wait(url)
        ok, reason = with_retries(
            lambda: goto_checked(page, url, settle_ms=settle_ms),
            f"[{self.label}] {url}",
            report,
        )
        if ok:
            stats.consecutive_blocks = 0
            return True
        record_block(stats, failures, url, reason)
        report(f"[{self.label}] giving up on {url} ({reason})")
        return False

    def pause(self):
        """Human-like pause between directory actions/pages (3-8s)."""
        human_delay()
