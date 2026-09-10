# Business Directory Scraper

A local web app that searches business directories for a **keyword + location**,
collects every business it finds, removes duplicates, and saves the results
to an Excel file. Everything runs on your own machine — **no paid proxies, no
paid CAPTCHA solvers, no paid APIs**. Free and open-source only.

> **Every business is exported**, whether or not it has an email — the file is
> built for SMS as much as for email outreach. Emails that a directory publishes
> on the listing itself are always collected.
>
> **Optional email lookup:** directories rarely publish emails directly, so the
> app can also visit each business's *own website* (and its Contact page) and
> extract a real email there. This is **off by default** — it is by far the
> slowest stage, since it opens one or two pages per business. Tick *Also look
> for emails on each business website* on the form to enable it for a run. It
> only ever **adds** an email to a row; nothing is ever dropped for lacking one.

## What it does

- **Inputs:** a keyword (category/service) and a location (worldwide).
- Searches **every ticked directory**, paginating fully.
- **Dedupes** across directories by website domain and phone number.
- **Exports every unique business**, with whatever details the directory
  published — no email required.
- **Output columns:** Business Name, Website, Email, Description, Contact Number,
  Address, Category, Source.
- **Export:** one timestamped Excel file per run
  (`<keyword>_<location>_<timestamp>.xlsx`) with a **Listings** sheet and a
  **Summary** sheet (found / exported / of-those-no-email / duplicates /
  blocked, per directory).

## Directories

| Key | Directory | Region | Notes |
|-----|-----------|--------|-------|
| `osm` | OpenStreetMap (Overpass API) | Worldwide | Open data (ODbL). Cleanest, most reliable source. |
| `google_maps` | Google Maps / Google Business Profile | Worldwide | Best phone coverage, but see the warning below. **Off by default — tick it deliberately.** |
| `freeindex` | FreeIndex | UK | Publicly browsable; good website coverage. |
| `scoot` | Scoot | UK | Only premium listings show websites, so the optional email lookup yields little here. |
| `yellowpages` | Yellow Pages | US | Good website coverage. Behind Cloudflare that *intermittently* blocks; the retry/skip logic handles it. |
| `hotfrog` | Hotfrog | Worldwide | Auto-selects the country site (`.com`, `.co.uk`, `.com.au`, …) from the location. |
| `manta` | Manta | US | robots.txt allows it, but an interactive Cloudflare wall currently blocks automation — expect it to report **blocked** (logged and skipped, never forced). |

> **About the Google Maps source.** Google's `robots.txt` disallows
> `/maps/search` and their Terms of Service prohibit automated extraction, so
> this scraper skips the robots gate rather than pretending to pass it. Running
> it is your decision, and the summary sheet says so on every run. It uses the
> same politeness the rest of the project does — human-paced delays, retries,
> and a circuit breaker that gives up rather than fighting a block. No CAPTCHA
> solving and no attempt to defeat Google's bot detection.
>
> One Maps search stops at roughly 60 results however far you scroll, so a town
> is covered by searching a grid of map tiles across its bounding box and
> merging them, working outwards from the centre. Tune the grid in `config.py`
> via `GOOGLE_MAPS_MAX_TILES` (more tiles means better coverage and more
> requests), `GOOGLE_MAPS_TILE_DEGREES`, and `GOOGLE_MAPS_TILE_ZOOM`.

Directories are **pluggable**: each is a subclass of
`scrapers.base.DirectoryScraper`. Adding one is a single class plus one line in
`scrapers/__init__.py`; everything else (robots gate, stealth, retries, rate
limiting, dedupe, export) is shared.

## Anti-detection (all free)

- **playwright-stealth** applied to every browser context (masks
  `navigator.webdriver`, headless fingerprints, plugin/codec anomalies, etc.).
- Launches your **real installed Chrome** (then Edge, then bundled Chromium) —
  a genuine browser build leaks far fewer automation tells.
- **Rotated real-browser profiles** — user-agent + viewport + locale +
  Accept-Language chosen from a pool of realistic combinations (`config.py`).
- **Human-like delays** (3–8s) between actions and pages.
- **Per-host rate limiting** so no site is ever hit faster than normal browsing.
- **robots.txt checked live per directory** before scraping; a directory that
  disallows the pages we need is auto-skipped and logged.
- **On block / CAPTCHA / timeout:** retry with exponential backoff up to a
  limit, then log to `outputs/failed_urls.csv` (timestamp, directory, url,
  reason) and move on. **CAPTCHAs are never solved** — a challenge page is just
  a logged failure. Several blocks in a row abandon that directory for the run
  and flag it for separate review rather than forcing past it.

## How to start it

1. Double-click **`start.bat`** (starts the app and opens your browser).
2. In the page: type a **Keyword** and a **Location**, tick the directories you
   want (all ticked by default), and click **Start Scraping**.
3. Watch the live per-directory progress table. When it finishes, a **Download
   Excel File** button appears.
4. To stop the app, close the command window.

## First-time setup (once per machine)

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

Installing Google Chrome is recommended (best fingerprint); the bundled
Chromium is used automatically as a fallback if Chrome isn't present.

## Project layout

| Path | What it does |
|------|--------------|
| `app.py` | Flask server: serves the page, runs a job per request, reports progress. |
| `config.py` | All tunables: pacing, retry limits, caps, and the browser-profile pool. |
| `core/pipeline.py` | Orchestrates a run: geocode → gate → collect → dedupe → optional emails → export. |
| `core/stealth.py` | Browser/context factory with playwright-stealth + profile rotation. |
| `core/humanize.py` | Human-pace delays and the per-host rate limiter. |
| `core/robots.py` | Live robots.txt check per directory. |
| `core/retry.py` | Block/CAPTCHA detection, backoff retries, `failed_urls.csv`. |
| `core/dedupe.py` | Cross-directory dedupe by domain / phone. |
| `core/email_finder.py` | Optional stage: visits a business site + Contact page and extracts a real email. |
| `core/geocode.py` | One free Nominatim lookup → country code + bounding box. |
| `core/models.py` | Shared data shapes (`Listing`, per-directory stats, run state). |
| `scrapers/base.py` | The pluggable scraper interface. |
| `scrapers/*.py` | One scraper per directory. |
| `excel_writer.py` | Writes the Listings + Summary Excel file. |
| `templates/index.html` | The single web page. |

## Notes

- With the email lookup off (the default), a run is only as slow as the
  directory pages themselves. OpenStreetMap answers in seconds; the browser-based
  directories are paced deliberately slowly to stay human-like.
- Ticking the email lookup adds one or two page visits *per business*, so a
  search with 100+ businesses can take many extra minutes. The progress table
  keeps you updated throughout.
- The email finder is deliberately cautious — it prefers `mailto:` links and
  emails on the business's own domain, so it avoids junk like library-author or
  font-designer addresses buried in page code.
- Respect each directory's Terms of Service. Manta and Yellow Pages restrict
  automated access in their ToS even where robots.txt permits the pages; they're
  included because you asked for them, and enabling them is your call — untick
  them to leave them out.
