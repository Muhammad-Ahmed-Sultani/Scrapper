"""Shared data shapes passed between the scrapers, pipeline, and exporter."""
import threading
from dataclasses import dataclass, field


@dataclass
class Listing:
    """One business as collected from a directory (before email enrichment)."""
    source: str            # scraper key, e.g. "yellowpages"
    name: str
    website: str = ""
    email: str = ""        # some sources (OSM) carry an email directly
    phone: str = ""
    description: str = ""
    address: str = ""
    category: str = ""
    profile_url: str = ""  # the directory's own page for this business

    def merge_from(self, other):
        """Fill any blank fields from a duplicate found on another site."""
        for f in ("website", "email", "phone", "description", "address", "category"):
            if not getattr(self, f) and getattr(other, f):
                setattr(self, f, getattr(other, f))


@dataclass
class DirectoryStats:
    """Per-directory counters for the run summary. Mutated from the scraper
    thread; snapshot() is what the UI reads."""
    key: str
    label: str
    status: str = "pending"   # pending|running|ok|blocked|skipped_robots|out_of_region|error
    message: str = ""
    found: int = 0            # listings collected from the directory
    kept: int = 0             # rows in the final file from this directory
    no_email: int = 0         # exported, but with no email address
    duplicates: int = 0       # dropped: same domain/phone seen elsewhere
    failed_pages: int = 0     # pages given up on after retries
    blocked_pages: int = 0    # subset of failed_pages that were block/CAPTCHA walls
    consecutive_blocks: int = 0
    note: str = ""

    def snapshot(self):
        return {
            "key": self.key, "label": self.label, "status": self.status,
            "message": self.message, "found": self.found, "kept": self.kept,
            "no_email": self.no_email, "duplicates": self.duplicates,
            "failed_pages": self.failed_pages, "note": self.note,
        }


@dataclass
class RunState:
    """Everything the UI needs to render live progress for one job."""
    keyword: str = ""
    location: str = ""
    phase: str = "starting"   # starting|collect|dedupe|emails|export|done
    message: str = "Starting..."
    directories: dict = field(default_factory=dict)  # key -> DirectoryStats
    done: bool = False
    error: str = ""
    filename: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self):
        with self._lock:
            return {
                "keyword": self.keyword,
                "location": self.location,
                "phase": self.phase,
                "message": self.message,
                "directories": [d.snapshot() for d in self.directories.values()],
                "done": self.done,
                "error": self.error,
                "filename": self.filename,
            }
