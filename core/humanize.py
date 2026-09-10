"""
Human-pace controls: randomized delays and a per-host rate limiter.

Two layers, on purpose:
- human_delay() adds a random pause between successive actions so the
  request pattern never looks machine-regular;
- RateLimiter guarantees a minimum gap between any two requests to the
  SAME host, across all threads, so no site ever sees us faster than a
  person clicking around.
"""
import random
import threading
import time
from urllib.parse import urlparse

from config import DIRECTORY_DELAY_RANGE, ENRICH_DELAY_RANGE, PER_HOST_MIN_INTERVAL


def human_delay(delay_range=DIRECTORY_DELAY_RANGE):
    time.sleep(random.uniform(*delay_range))


def enrich_delay():
    time.sleep(random.uniform(*ENRICH_DELAY_RANGE))


class RateLimiter:
    """Blocks until at least `min_interval` seconds have passed since the
    last request to the same host. Shared by every thread in a run."""

    def __init__(self, min_interval=PER_HOST_MIN_INTERVAL):
        self.min_interval = min_interval
        self._last = {}
        self._lock = threading.Lock()

    def wait(self, url):
        host = urlparse(url).netloc.lower()
        if not host:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                last = self._last.get(host, 0)
                remaining = self.min_interval - (now - last)
                if remaining <= 0:
                    self._last[host] = now
                    return
            # add jitter so parallel workers don't wake in lockstep
            time.sleep(min(remaining, 0.5) + random.uniform(0, 0.2))
