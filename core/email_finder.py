"""
Email finder: given a business's website, visit it (and its Contact page)
and extract a real contact email.

Deliberately cautious about false positives - pages are full of junk
"emails" (font-licence authors, tracking libraries, image filenames).
Order of trust:
1. mailto: links - an author writing <a href="mailto:..."> means it;
2. emails on the business's own domain (info@acme.com on acme.com);
3. plain-text emails with a business-style prefix (info@, sales@, ...).
Anything else is ignored. Returns "" when nothing trustworthy is found;
never raises - dead sites, bot-blocks and SSL errors just yield "".
"""
import re
from urllib.parse import urljoin, urlparse

from core.dedupe import registrable_domain

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

JUNK_SUBSTRINGS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", "@2x", "@3x",
    "sentry", "wixpress", "example.com", "example.org", "googlefonts",
    "googleapis", "gstatic", "cloudflare", "schema.org", "sentry.io",
    "domain.com", "yourdomain", "email.com", "test.com", "@example",
    "fontawesome", "jquery", "bootstrap", "no-reply", "noreply",
)

BUSINESS_PREFIXES = (
    "info", "contact", "enquiries", "enquiry", "sales", "hello", "admin",
    "office", "mail", "reception", "bookings", "booking", "support",
    "hi", "team", "ask", "shop", "orders",
)


def _is_junk(email):
    e = email.lower()
    return any(j in e for j in JUNK_SUBSTRINGS) or len(email) > 60


def _normalise_url(url):
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # things like "http://." slip through some directories' data
    host = urlparse(url).netloc
    if len(host.replace(".", "")) < 3:
        return ""
    return url


def _emails_from_page(page):
    """Return (mailto_emails, text_emails) found on the current page."""
    mailto = set()
    for a in page.locator('a[href^="mailto:"]').all():
        href = a.get_attribute("href") or ""
        addr = href.split("mailto:", 1)[-1].split("?")[0].strip()
        for m in EMAIL_RE.findall(addr):
            if not _is_junk(m):
                mailto.add(m)
    text = set()
    try:
        html = page.content()
    except Exception:
        html = ""
    for m in EMAIL_RE.findall(html):
        if not _is_junk(m):
            text.add(m)
    return mailto, text


def _find_contact_link(page, base_url):
    try:
        anchors = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({href: e.getAttribute('href'), text: e.innerText}))",
        )
    except Exception:
        return None
    base_host = urlparse(base_url).netloc
    for a in anchors:
        href = a.get("href") or ""
        text = (a.get("text") or "").lower()
        if "contact" in href.lower() or "contact" in text:
            full = urljoin(base_url, href)
            if urlparse(full).netloc in ("", base_host):
                return full
    return None


def _pick_best(mailto, text, site_domain):
    def domain_matches(email):
        return registrable_domain(email.split("@")[-1]) == site_domain

    def has_business_prefix(email):
        local = email.split("@")[0].lower()
        return any(local == p or local.startswith(p) for p in BUSINESS_PREFIXES)

    for pred in (domain_matches, has_business_prefix, lambda e: True):
        picks = sorted(e for e in mailto if pred(e))
        if picks:
            return picks[0]

    for pred in (domain_matches, has_business_prefix):
        picks = sorted(e for e in text if pred(e))
        if picks:
            return picks[0]

    return ""


def _load_and_read(page, url, timeout_ms):
    """Load a URL, let JS-injected content settle, read the emails."""
    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        page.wait_for_timeout(2500)
    return _emails_from_page(page)


def find_email(context, website_url, timeout_ms=20000):
    url = _normalise_url(website_url)
    if not url:
        return ""
    site_domain = registrable_domain(urlparse(url).netloc)

    page = context.new_page()
    try:
        try:
            mailto, text = _load_and_read(page, url, timeout_ms)
        except Exception:
            return ""

        if not mailto:
            contact_url = _find_contact_link(page, page.url)
            if contact_url and contact_url != page.url:
                try:
                    m2, t2 = _load_and_read(page, contact_url, timeout_ms)
                    mailto |= m2
                    text |= t2
                except Exception:
                    pass

        return _pick_best(mailto, text, site_domain)
    finally:
        page.close()
