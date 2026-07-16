"""Brave Search API — free tier: 2,000 queries/month, 1 req/sec."""
import asyncio

import httpx

from app.config import get_settings
from app.services.search.base import SearchProvider, SearchResult

_COUNTRY_MAP = {
    "usa": "US", "united states": "US", "us": "US",
    "canada": "CA", "uk": "GB", "united kingdom": "GB",
    "germany": "DE", "netherlands": "NL", "sweden": "SE",
    "switzerland": "CH", "ireland": "IE", "uae": "AE",
}

_lock = asyncio.Lock()  # free tier is 1 req/sec


class BraveProvider(SearchProvider):
    name = "brave"

    def available(self) -> bool:
        return bool(get_settings().brave_api_key)

    async def search(self, query: str, *, region: str = "", max_results: int = 10) -> list[SearchResult]:
        settings = get_settings()
        headers = {"X-Subscription-Token": settings.brave_api_key, "Accept": "application/json"}
        params = {
            "q": query,
            "count": min(max_results, 20),
            "country": _COUNTRY_MAP.get(region.lower().strip(), "US"),
        }
        async with _lock:
            await asyncio.sleep(1.1)
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    "https://api.search.brave.com/res/v1/web/search", params=params, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
                provider=self.name,
            )
            for item in (data.get("web", {}) or {}).get("results", [])
            if item.get("url")
        ]
