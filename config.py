"""
Central configuration for the scraper: pacing, limits, and the pool of
realistic browser profiles rotated across contexts.

Everything here is tunable without touching the scraper logic.
"""
from pathlib import Path

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "outputs"
FAILED_URLS_CSV = OUTPUT_DIR / "failed_urls.csv"

# ---------------------------------------------------------------- pacing ---
# Randomized human-like delay between directory page loads / actions.
DIRECTORY_DELAY_RANGE = (3.0, 8.0)
# Delay between visits to *different* business websites during email
# enrichment. These are all different hosts, so shorter is still polite;
# the per-host rate limiter below is the real guarantee.
ENRICH_DELAY_RANGE = (1.5, 4.0)
# Minimum gap between two requests to the SAME host, whoever makes them.
PER_HOST_MIN_INTERVAL = 3.0

# ----------------------------------------------------------------- retry ---
RETRY_ATTEMPTS = 3          # per URL, on block / captcha / timeout
RETRY_BASE_DELAY = 8.0      # seconds; doubles each attempt (+ jitter)
# After this many consecutive blocked pages a directory is abandoned for
# the run and marked "blocked - review separately" in the summary.
CONSECUTIVE_BLOCK_LIMIT = 3

# ---------------------------------------------------------------- limits ---
MAX_PAGES_PER_DIRECTORY = 50     # pagination safety cap
MAX_LISTINGS_PER_DIRECTORY = 200  # profile-visit safety cap per directory
DIRECTORY_CONCURRENCY = 2        # directories scraped in parallel
ENRICH_CONCURRENCY = 3           # business websites visited in parallel

# --------------------------------------------------------- google maps ---
# A single Maps search stops returning results at roughly 60, whatever the
# real total is, so a town or city is covered by searching a grid of map
# tiles across its bounding box and merging the results.
GOOGLE_MAPS_TILE_ZOOM = 14        # map zoom each tile search is centred at
GOOGLE_MAPS_TILE_DEGREES = 0.045  # target tile size in degrees (~5km)
GOOGLE_MAPS_MAX_TILES = 9         # cap on searches per run - raise for more
#                                   coverage of a big city, at more requests
GOOGLE_MAPS_MAX_SCROLLS = 40      # scrolls of the results panel per search

# ------------------------------------------------------------- browsers ---
# Launch preference: real installed Chrome has the most convincing
# fingerprint, then Edge, then Playwright's bundled Chromium.
BROWSER_CHANNELS = ["chrome", "msedge", None]
LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]

# Pool of realistic browser profiles. All Chromium-family UAs on purpose:
# we drive a Chromium engine, and a Firefox/Safari UA on a Chromium
# fingerprint is itself a bot signal. Viewports are common real sizes.
BROWSER_PROFILES = [
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
        "locale": "en-US",
        "accept_language": "en-US,en;q=0.9",
    },
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "viewport": {"width": 1366, "height": 768},
        "locale": "en-GB",
        "accept_language": "en-GB,en;q=0.9",
    },
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0",
        "viewport": {"width": 1536, "height": 864},
        "locale": "en-US",
        "accept_language": "en-US,en;q=0.9",
    },
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "viewport": {"width": 1440, "height": 900},
        "locale": "en-US",
        "accept_language": "en-US,en;q=0.9",
    },
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "viewport": {"width": 1600, "height": 900},
        "locale": "en-US",
        "accept_language": "en-US,en;q=0.8",
    },
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0",
        "viewport": {"width": 1920, "height": 1200},
        "locale": "en-GB",
        "accept_language": "en-GB,en-US;q=0.9,en;q=0.8",
    },
]

COMMON_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

# Identifying UA for plain-HTTP calls to free APIs that ask for one
# (Nominatim geocoding, Overpass). Not used for directory pages.
API_USER_AGENT = "business-directory-scraper/2.0 (personal lead research)"
