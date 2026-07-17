"""Provider chain: tries providers in configured order, falls back on failure.

A provider that errors repeatedly is put in a cooldown so a dead/exhausted
provider (e.g. Serper credits used up, DDG rate-limited) doesn't stall runs.

Smart routing: queries that rely on search operators (site:, inurl:, exact
"quoted phrases") only work reliably on a real Google SERP, so those are
routed to serper first when it's configured — free metasearch engines treat
operators as loose hints and return junk for them. Natural keyword queries
keep the configured (free-first) order, so paid credits are only spent where
they actually buy precision.
"""
import logging
import time

from app.config import get_settings
from app.services.search.base import SearchProvider, SearchResult
from app.services.search.brave import BraveProvider
from app.services.search.ddg import DDGProvider
from app.services.search.searxng import SearxngProvider
from app.services.search.serper import SerperProvider

log = logging.getLogger(__name__)

_PROVIDERS: dict[str, type[SearchProvider]] = {
    "serper": SerperProvider,
    "ddg": DDGProvider,
    "searxng": SearxngProvider,
    "brave": BraveProvider,
}

_COOLDOWN_SECONDS = 300
_FAILURES_BEFORE_COOLDOWN = 3

# Operators that free metasearch engines don't honor reliably
_PRECISION_HINTS = ("site:", "inurl:", "intitle:", '"')


def needs_precision_engine(query: str) -> bool:
    return any(hint in query for hint in _PRECISION_HINTS)


class SearchChain:
    def __init__(self, order: list[str]):
        self.providers: list[SearchProvider] = [
            _PROVIDERS[name]() for name in order if name in _PROVIDERS
        ]
        self._failures: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}

    def status(self) -> list[dict]:
        now = time.monotonic()
        return [
            {
                "name": p.name,
                "configured": p.available(),
                "cooling_down": self._cooldown_until.get(p.name, 0) > now,
                "consecutive_failures": self._failures.get(p.name, 0),
            }
            for p in self.providers
        ]

    def _usable(self, provider: SearchProvider) -> bool:
        return provider.available() and self._cooldown_until.get(provider.name, 0) <= time.monotonic()

    def _order_for(self, query: str) -> list[SearchProvider]:
        """Providers to try for this query. Operator-heavy queries go to serper
        first (real Google SERP honors them); everything else keeps the
        configured free-first order."""
        if not needs_precision_engine(query):
            return self.providers
        serper = [p for p in self.providers if p.name == "serper"]
        return serper + [p for p in self.providers if p.name != "serper"]

    async def search(self, query: str, *, region: str = "", max_results: int = 10) -> list[SearchResult]:
        last_error: Exception | None = None
        for provider in self._order_for(query):
            if not self._usable(provider):
                continue
            try:
                results = await provider.search(query, region=region, max_results=max_results)
                self._failures[provider.name] = 0
                return results
            except Exception as exc:  # noqa: BLE001 — any provider failure means "try the next one"
                last_error = exc
                count = self._failures.get(provider.name, 0) + 1
                self._failures[provider.name] = count
                log.warning("search provider %s failed (%d): %s", provider.name, count, exc)
                if count >= _FAILURES_BEFORE_COOLDOWN:
                    self._cooldown_until[provider.name] = time.monotonic() + _COOLDOWN_SECONDS
                    log.warning("search provider %s cooling down for %ds", provider.name, _COOLDOWN_SECONDS)
        if last_error:
            raise last_error
        raise RuntimeError("No search provider is configured/usable. Check SEARCH_PROVIDER_ORDER and keys.")


_chain: SearchChain | None = None


def get_search_chain() -> SearchChain:
    global _chain
    if _chain is None:
        _chain = SearchChain(get_settings().provider_order)
    return _chain
