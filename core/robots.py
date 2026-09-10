"""
robots.txt gate, checked live per directory before any scraping starts.

The file is fetched with the SAME browser that does the scraping, not a
plain HTTP client: some directories (e.g. Scoot) drop non-browser TLS
connections, which would make a urllib fetch fail and wrongly skip a
directory whose robots.txt actually permits us. A urllib fallback is
kept for callers that don't supply a browser fetcher.

Rules follow RFC 9309 practice:
- 200: parse the file and honour it for our generic user-agent;
- 401/403/404/410 (robots file unavailable): crawling is not restricted;
- unreachable / server error: treated as disallowed for safety (and NOT
  cached, so a transient failure doesn't stick for the whole session).

A directory whose search or profile paths are disallowed is auto-skipped
and shows up in the run summary as "skipped (robots.txt)".
"""
import urllib.error
import urllib.request
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from config import API_USER_AGENT

# What we identify as when *checking* the rules. "*" rules apply to us.
ROBOTS_AGENT = "business-directory-scraper"

# base_url -> (parser_or_None, note). Only definitive answers are cached;
# transient fetch failures are not, so they can recover on a later run.
_cache = {}


def urllib_fetcher(robots_url):
    req = urllib.request.Request(robots_url, headers={"User-Agent": API_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return res.status, res.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return None, ""


def make_browser_fetcher(page):
    """A robots.txt fetcher backed by an open Playwright page, so the check
    uses the same client (and TLS fingerprint) as the scrape itself."""
    def fetch(robots_url):
        try:
            resp = page.goto(robots_url, timeout=25000, wait_until="domcontentloaded")
            status = resp.status if resp else None
            if status and status >= 400:
                return status, ""
            # robots.txt is text/plain; the browser wraps it, inner_text
            # gives back the raw rules.
            try:
                text = page.inner_text("body")
            except Exception:
                text = page.content()
            return status or 200, text
        except Exception:
            return None, ""
    return fetch


def check_allowed(base_url, paths, fetcher=urllib_fetcher):
    """Return (allowed: bool, note: str) for the given site paths."""
    if base_url in _cache:
        parser, note = _cache[base_url]
    else:
        status, text = fetcher(urljoin(base_url, "/robots.txt"))
        if status == 200 and text.strip():
            parser = RobotFileParser()
            parser.parse(text.splitlines())
            note = ""
            _cache[base_url] = (parser, note)
        elif status in (401, 403, 404, 410):
            parser, note = None, "no robots.txt restrictions published"
            _cache[base_url] = (parser, note)
        else:
            # transient/unreachable: skip to be safe, but do NOT cache
            return False, "robots.txt could not be fetched - skipping to be safe"

    if parser is None:
        return True, note

    for path in paths:
        url = urljoin(base_url, path)
        if not (parser.can_fetch(ROBOTS_AGENT, url) or parser.can_fetch("*", url)):
            return False, f"robots.txt disallows {path}"
    return True, "robots.txt permits the pages we need"
