"""
Browser and context factory with anti-detection applied.

Every context this module hands out:
- runs through playwright-stealth (masks navigator.webdriver, headless
  fingerprints, chrome.runtime absence, plugin/codec anomalies, etc.);
- gets a randomly chosen realistic profile (user-agent + viewport +
  locale + Accept-Language) from the pool in config.py;
- carries realistic navigation headers.

Launching prefers the machine's real Chrome, then Edge, then Playwright's
bundled Chromium - a genuine branded browser build leaks far fewer
automation tells than the stock bundled one.
"""
import random

from playwright_stealth import Stealth

from config import BROWSER_CHANNELS, BROWSER_PROFILES, COMMON_HEADERS, LAUNCH_ARGS

_stealth = Stealth()


def launch_browser(playwright, headless=True):
    last_error = None
    for channel in BROWSER_CHANNELS:
        try:
            kwargs = {"headless": headless, "args": LAUNCH_ARGS}
            if channel:
                kwargs["channel"] = channel
            return playwright.chromium.launch(**kwargs)
        except Exception as e:
            last_error = e
    raise RuntimeError(f"No Chromium-family browser could be launched: {last_error}")


def new_stealth_context(browser, profile=None, common_headers=True):
    """A fresh context with stealth patches and a rotated real-browser profile.

    `common_headers=False` omits the fixed navigation headers from
    config.COMMON_HEADERS. Those headers describe a top-level document
    request, so a single-page app that fetches its own results over XHR
    sees "Sec-Fetch-Site: none" on every call and can refuse to render.
    Google Maps does exactly that, so its scraper opts out. The stealth
    patches and the rotated profile still apply either way.
    """
    profile = profile or random.choice(BROWSER_PROFILES)
    headers = {"Accept-Language": profile["accept_language"]}
    if common_headers:
        headers = {**COMMON_HEADERS, **headers}
    context = browser.new_context(
        user_agent=profile["user_agent"],
        viewport=profile["viewport"],
        locale=profile["locale"],
        extra_http_headers=headers,
    )
    _stealth.apply_stealth_sync(context)
    return context
