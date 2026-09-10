"""
Cross-directory dedupe by website domain and phone number.

Two listings are the same business if they share a registrable domain
(www.acme.co.uk == acme.co.uk) or the same significant phone digits.
The first-seen listing wins; blank fields are filled in from the
duplicate before it's dropped, so merging loses nothing.
"""
import re

# Country-code and generic second-level labels under which the real
# "company" label sits one level deeper (acme.co.uk, acme.com.au ...).
_SECOND_LEVELS = {"co", "com", "org", "net", "gov", "ac", "ltd", "plc", "me", "edu"}


def registrable_domain(host):
    host = (host or "").strip().lower()
    host = re.sub(r"^https?://", "", host).split("/")[0].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    parts = [p for p in host.split(".") if p]
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVELS:
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def normalize_phone(phone):
    """Comparable form of a phone number: significant trailing digits."""
    digits = re.sub(r"\D", "", phone or "")
    digits = digits.lstrip("0")
    if len(digits) < 7:
        return ""          # too short to identify anything
    return digits[-10:]    # ignore country-code prefixes


def dedupe(listings):
    """Return (unique_listings, per_source_duplicate_counts)."""
    by_domain = {}
    by_phone = {}
    unique = []
    dup_counts = {}

    for listing in listings:
        domain = registrable_domain(listing.website) if listing.website else ""
        phone = normalize_phone(listing.phone)

        existing = (domain and by_domain.get(domain)) or (phone and by_phone.get(phone))
        if existing:
            existing.merge_from(listing)
            dup_counts[listing.source] = dup_counts.get(listing.source, 0) + 1
            continue

        unique.append(listing)
        if domain:
            by_domain[domain] = listing
        if phone:
            by_phone[phone] = listing

    return unique, dup_counts
