"""
Scraper registry. The order here is the order directories appear in the
UI and the run summary. Adding a directory = writing one subclass of
scrapers.base.DirectoryScraper and listing it here.
"""
from scrapers.freeindex import FreeIndexScraper
from scrapers.google_maps import GoogleMapsScraper
from scrapers.hotfrog import HotfrogScraper
from scrapers.manta import MantaScraper
from scrapers.osm import OSMScraper
from scrapers.scoot import ScootScraper
from scrapers.yellowpages import YellowPagesScraper

SCRAPER_CLASSES = [
    OSMScraper,
    GoogleMapsScraper,
    FreeIndexScraper,
    ScootScraper,
    YellowPagesScraper,
    HotfrogScraper,
    MantaScraper,
]

REGISTRY = {cls.key: cls for cls in SCRAPER_CLASSES}
