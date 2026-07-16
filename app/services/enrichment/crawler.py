"""Async website crawler: find real published emails on a company's site.

Checks the homepage + common contact/about/team paths for mailto: links and
raw email addresses. No paid APIs.
"""
import asyncio
import logging
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

CONTACT_PATHS = ["", "/contact", "/contact-us", "/about", "/about-us", "/team", "/company"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Substrings that mark false-positive matches (asset names, tracker domains…)
_JUNK = ("example.com", "sentry.io", "wixpress.com", ".png", ".jpg", ".jpeg", ".svg",
         ".webp", ".gif", "schema.org", "yourdomain", "domain.com", "email.com")

GENERIC_PREFIXES = {
    "info", "contact", "support", "hello", "admin", "sales", "help", "team",
    "press", "media", "careers", "jobs", "no-reply", "noreply", "office", "mail",
}


def extract_domain(url_or_domain: str) -> str:
    value = (url_or_domain or "").strip().lower()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    netloc = urlparse(value).netloc
    return netloc.removeprefix("www.")


def _emails_from_html(html: str, domain: str) -> set[str]:
    found: set[str] = set()
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            addr = href[7:].split("?")[0].strip()
            if EMAIL_RE.fullmatch(addr):
                found.add(addr.lower())
    for match in EMAIL_RE.findall(html):
        lower = match.lower()
        if not any(junk in lower for junk in _JUNK):
            found.add(lower)
    # Prefer emails on the company's own domain
    own = {e for e in found if e.endswith(f"@{domain}")}
    return own or found


async def crawl_site_for_emails(domain: str, *, max_pages: int = 5, timeout: float = 8.0) -> set[str]:
    """Fetch a handful of likely pages and return any published emails."""
    domain = extract_domain(domain)
    if not domain:
        return set()

    found: set[str] = set()
    async with httpx.AsyncClient(
        headers=HEADERS, timeout=timeout, follow_redirects=True, verify=False
    ) as client:
        for path in CONTACT_PATHS[:max_pages]:
            url = f"https://{domain}{path}"
            try:
                resp = await client.get(url)
                if resp.status_code != 200 or "text/html" not in resp.headers.get("content-type", ""):
                    continue
                found |= _emails_from_html(resp.text[:500_000], domain)
                if found:
                    break
            except (httpx.HTTPError, asyncio.TimeoutError) as exc:
                log.debug("crawl %s failed: %s", url, exc)
                continue
    return found


def rank_emails(emails: set[str]) -> list[str]:
    """Personal-looking inboxes first, generic inboxes last."""
    return sorted(emails, key=lambda e: (e.split("@")[0] in GENERIC_PREFIXES, e))


def generate_pattern_candidates(full_name: str, domain: str) -> list[str]:
    """Ranked common B2B email patterns for a person at a domain."""
    domain = extract_domain(domain)
    parts = [p for p in re.sub(r"[^a-z\s'-]", "", full_name.lower()).split() if p]
    if not parts or not domain:
        return []
    first = parts[0]
    last = parts[-1] if len(parts) > 1 else ""
    if last and last != first:
        return [
            f"{first}.{last}@{domain}",
            f"{first}@{domain}",
            f"{first[0]}{last}@{domain}",
            f"{first}{last}@{domain}",
            f"{first[0]}.{last}@{domain}",
        ]
    return [f"{first}@{domain}"]
