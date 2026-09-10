"""
Run orchestrator. One call = one run:

1. geocode the location (country code + bounding box, one free call);
2. gate each enabled directory: in-region? robots.txt allows?
3. collect listings from the allowed directories, a couple in parallel,
   each in its own stealth browser at human pace;
4. dedupe across directories by website domain / phone number;
5. OPTIONAL email enrichment (find_emails=True): visit each business's
   website looking for a contact address. Off by default - it is by far
   the slowest stage, and no business is ever dropped for lacking an
   email either way;
6. export EVERY unique business to a timestamped Excel file with a
   per-directory summary sheet.

Every mutation of the shared RunState happens under its lock so the
Flask thread can snapshot it safely at any moment.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from playwright.sync_api import sync_playwright

from config import DIRECTORY_CONCURRENCY, ENRICH_CONCURRENCY, OUTPUT_DIR
from core.dedupe import dedupe
from core.email_finder import find_email
from core.geocode import geocode
from core.humanize import RateLimiter, enrich_delay
from core.models import DirectoryStats, RunState
from core.retry import DirectoryBlocked, FailureLog
from core.robots import check_allowed, make_browser_fetcher
from core.stealth import launch_browser, new_stealth_context
from excel_writer import build_filename, write_excel
from scrapers import REGISTRY


def run_scrape(keyword, location, enabled_keys, state: RunState,
               find_emails=False):
    """Fills `state` as it goes; returns the list of exported rows."""
    scrapers = [REGISTRY[k]() for k in enabled_keys if k in REGISTRY]
    with state._lock:
        state.keyword, state.location = keyword, location
        state.directories = {
            s.key: DirectoryStats(key=s.key, label=s.label) for s in scrapers
        }

    failures = FailureLog()
    limiter = RateLimiter()

    def set_message(message, dstats=None):
        with state._lock:
            state.message = message
            if dstats is not None:
                dstats.message = message

    set_message(f"Looking up '{location}'...")
    geo = geocode(location)

    # ---------------------------------------------------------- collect ---
    with state._lock:
        state.phase = "collect"
    all_listings = []
    listings_lock = threading.Lock()

    def collect_one(scraper):
        dstats = state.directories[scraper.key]

        def report(message):
            set_message(message, dstats)

        # region gate
        if scraper.countries is not None:
            cc = (geo or {}).get("country_code", "")
            if cc and cc not in scraper.countries:
                with state._lock:
                    dstats.status = "out_of_region"
                    dstats.note = f"covers {'/'.join(sorted(scraper.countries)).upper()} only"
                    dstats.message = "Skipped - location is outside this directory's region."
                return

        base = scraper.resolve_base_url(geo)
        scraper.limiter = limiter

        try:
            with sync_playwright() as p:
                browser = launch_browser(p)
                context = scraper.make_context(browser)
                try:
                    # robots.txt gate, checked live with the SAME browser
                    # (some sites drop non-browser TLS connections, which a
                    # plain-HTTP check misreads as "unreachable").
                    if scraper.respects_robots:
                        gate_page = context.new_page()
                        try:
                            allowed, note = check_allowed(
                                base, scraper.robots_paths(keyword, location),
                                make_browser_fetcher(gate_page))
                        finally:
                            gate_page.close()
                        if not allowed:
                            with state._lock:
                                dstats.status = "skipped_robots"
                                dstats.note = note
                                dstats.message = f"Skipped - {note}."
                            failures.log(scraper.key, base, f"robots: {note}")
                            return

                    with state._lock:
                        dstats.status = "running"
                        dstats.note = scraper.tos_note
                    found = scraper.collect(context, keyword, location, geo,
                                            dstats, failures, report)
                finally:
                    browser.close()
            with listings_lock:
                all_listings.extend(found)
            with state._lock:
                # A directory that collected nothing but hit block walls is
                # blocked, not "ok" - report it honestly (the consecutive
                # breaker only trips mid-run, not on a blocked entry page).
                if not found and dstats.blocked_pages:
                    dstats.status = "blocked"
                    dstats.note = ("search/profile pages returned bot-block "
                                   "challenges - review this directory separately")
                    dstats.message = "Blocked by the site - logged and skipped."
                else:
                    dstats.status = "ok"
                    dstats.found = max(dstats.found, len(found))
                    dstats.message = f"Collected {len(found)} listings."
        except DirectoryBlocked as e:
            with state._lock:
                dstats.status = "blocked"
                dstats.note = str(e)
                dstats.message = "Blocked by the site - logged and skipped."
        except Exception as e:
            with state._lock:
                dstats.status = "error"
                dstats.note = f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"
                dstats.message = "Failed - see note."
            failures.log(scraper.key, base, dstats.note)

    with ThreadPoolExecutor(max_workers=DIRECTORY_CONCURRENCY) as pool:
        list(pool.map(collect_one, scrapers))

    # ----------------------------------------------------------- dedupe ---
    with state._lock:
        state.phase = "dedupe"
    set_message(f"Collected {len(all_listings)} listings; removing duplicates...")
    unique, dup_counts = dedupe(all_listings)
    with state._lock:
        for key, count in dup_counts.items():
            if key in state.directories:
                state.directories[key].duplicates = count

    # ----------------------------------------------------------- emails ---
    # Enrichment only ever ADDS an email to a row. Nothing is filtered out
    # here: every unique business is exported, with or without an address.
    if find_emails:
        with state._lock:
            state.phase = "emails"
        progress_lock = threading.Lock()
        progress = {"done": 0, "found": 0}
        # A site with no website can't be visited; one that already has an
        # email from the directory needs no visit.
        candidates = [l for l in unique if l.website and not l.email]

        def enrich_batch(batch):
            if not batch:
                return
            with sync_playwright() as p:
                browser = launch_browser(p)
                # Enrichment visits arbitrary business sites, not a
                # directory, so it uses the standard context.
                context = new_stealth_context(browser)
                try:
                    for listing in batch:
                        limiter.wait(listing.website)
                        listing.email = find_email(context, listing.website)
                        enrich_delay()
                        with progress_lock:
                            progress["done"] += 1
                            if listing.email:
                                progress["found"] += 1
                            done, found = progress["done"], progress["found"]
                        set_message(f"Finding emails... {done}/{len(candidates)} "
                                    f"websites checked, {found} emails found")
                finally:
                    browser.close()

        batches = [candidates[i::ENRICH_CONCURRENCY] for i in range(ENRICH_CONCURRENCY)]
        with ThreadPoolExecutor(max_workers=ENRICH_CONCURRENCY) as pool:
            list(pool.map(enrich_batch, batches))

    kept = unique
    for listing in kept:
        with state._lock:
            dstats = state.directories[listing.source]
            dstats.kept += 1
            if not listing.email:
                dstats.no_email += 1

    # ----------------------------------------------------------- export ---
    with state._lock:
        state.phase = "export"
    set_message(f"Writing Excel file ({len(kept)} businesses)...")

    OUTPUT_DIR.mkdir(exist_ok=True)
    filename = build_filename(keyword, location)
    write_excel(kept, state, OUTPUT_DIR / filename)

    with state._lock:
        state.phase = "done"
        state.done = True
        state.filename = filename
        with_phone = sum(1 for l in kept if l.phone)
        with_email = sum(1 for l in kept if l.email)
        state.message = (f"Finished. {len(kept)} businesses exported "
                         f"({with_phone} with a phone number, "
                         f"{with_email} with an email).")
    return kept
