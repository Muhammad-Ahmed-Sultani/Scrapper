"""
Failure handling: block/CAPTCHA detection, retry with backoff, and the
failed_urls.csv log.

Policy (as specified for this project):
- a blocked page, CAPTCHA wall, or timeout is retried with exponential
  backoff up to RETRY_ATTEMPTS;
- CAPTCHAs are never solved - a challenge page is just a failure;
- after the retries a URL is logged to outputs/failed_urls.csv
  (timestamp, directory, url, reason) and the run moves on;
- several consecutive blocks abandon the whole directory for the run
  ("review that directory separately, don't force past it").
"""
import csv
import random
import threading
import time

from config import (CONSECUTIVE_BLOCK_LIMIT, FAILED_URLS_CSV, RETRY_ATTEMPTS,
                    RETRY_BASE_DELAY)


class DirectoryBlocked(Exception):
    """Raised when a directory has blocked us persistently this run."""


class PageBlocked(Exception):
    """One page came back as a bot-block / challenge / CAPTCHA."""


# Phrases that appear in the TITLE of challenge/block pages. Titles are
# checked rather than the body: real pages often reference Cloudflare's
# scripts in passing, which made body-matching false-positive.
BLOCK_TITLE_MARKERS = (
    "just a moment", "attention required", "access denied",
    "verifying you are human", "are you a robot", "pardon our interruption",
    "security check", "captcha",
)
# Body markers only trusted when the page is suspiciously small.
BLOCK_BODY_MARKERS = ("cf-chl", "challenge-platform", "g-recaptcha", "h-captcha",
                      "turnstile", "verifying you are human")
SMALL_PAGE_BYTES = 40_000
BLOCK_STATUSES = (403, 429, 503)


def looks_blocked(status, title, html):
    if status in BLOCK_STATUSES:
        return f"HTTP {status}"
    t = (title or "").lower()
    for m in BLOCK_TITLE_MARKERS:
        if m in t:
            return f"challenge page ({m!r})"
    if html and len(html) < SMALL_PAGE_BYTES:
        h = html.lower()
        for m in BLOCK_BODY_MARKERS:
            if m in h:
                return f"challenge markers in page ({m!r})"
    return ""


def goto_checked(page, url, timeout_ms=45000, settle_ms=2500):
    """Navigate and classify the result. Raises PageBlocked on a block wall,
    lets navigation errors (timeouts, DNS) propagate as-is."""
    response = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
    page.wait_for_timeout(settle_ms)
    status = response.status if response else 0
    reason = looks_blocked(status, page.title(), page.content())
    if reason:
        raise PageBlocked(reason)


def with_retries(action, describe, report=None):
    """Run `action()` with backoff. Returns (True, None) on success or
    (False, reason) after the last attempt. Never raises PageBlocked out."""
    delay = RETRY_BASE_DELAY
    reason = "unknown"
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            action()
            return True, None
        except PageBlocked as e:
            reason = f"blocked: {e}"
        except Exception as e:
            reason = f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"
        if attempt < RETRY_ATTEMPTS:
            if report:
                report(f"{describe}: {reason} - retrying in ~{int(delay)}s "
                       f"(attempt {attempt + 1}/{RETRY_ATTEMPTS})")
            time.sleep(delay + random.uniform(0, 3))
            delay *= 2
    return False, reason


class FailureLog:
    """Thread-safe appender for outputs/failed_urls.csv."""

    _lock = threading.Lock()

    def __init__(self, path=FAILED_URLS_CSV):
        self.path = path

    def log(self, directory, url, reason):
        with self._lock:
            self.path.parent.mkdir(exist_ok=True)
            new_file = not self.path.exists()
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if new_file:
                    writer.writerow(["timestamp", "directory", "url", "reason"])
                writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), directory, url, reason])


def record_block(stats, failures, url, reason):
    """Common bookkeeping when a page is given up on: count it, log it,
    and abandon the directory after too many blocks in a row."""
    stats.failed_pages += 1
    failures.log(stats.key, url, reason)
    if reason and reason.startswith("blocked"):
        stats.blocked_pages += 1
        stats.consecutive_blocks += 1
        if stats.consecutive_blocks >= CONSECUTIVE_BLOCK_LIMIT:
            raise DirectoryBlocked(
                f"{stats.consecutive_blocks} blocked pages in a row - "
                "this directory is actively blocking automation; review it separately")
    # a non-block failure (timeout on one page) breaks the streak
    else:
        stats.consecutive_blocks = 0
