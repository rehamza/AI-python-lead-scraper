"""Free multi-engine metasearch via the `ddgs` library (no API key).

`ddgs` federates DuckDuckGo/Google/Bing/Brave HTML endpoints. It is sync, so
calls run in a worker thread. Rate-limit friendly: small jittered delay per
call and a process-wide lock so we never hammer one backend concurrently.
"""
import asyncio
import random

from ddgs import DDGS

from app.services.search.base import SearchProvider, SearchResult

# Map campaign region hints to ddgs region codes
_REGION_MAP = {
    "usa": "us-en", "united states": "us-en", "us": "us-en",
    "canada": "ca-en", "uk": "uk-en", "united kingdom": "uk-en",
    "germany": "de-de", "netherlands": "nl-nl", "sweden": "se-sv",
    "switzerland": "ch-de", "ireland": "ie-en", "uae": "xa-en",
    "australia": "au-en", "france": "fr-fr", "spain": "es-es",
}

_lock = asyncio.Lock()


class DDGProvider(SearchProvider):
    name = "ddg"

    async def search(self, query: str, *, region: str = "", max_results: int = 10) -> list[SearchResult]:
        ddg_region = _REGION_MAP.get(region.lower().strip(), "us-en")

        def _run() -> list[dict]:
            with DDGS() as ddgs:
                return list(ddgs.text(query, region=ddg_region, max_results=max_results))

        async with _lock:  # serialize free-engine calls to avoid bans
            await asyncio.sleep(random.uniform(0.5, 1.5))
            raw = await asyncio.to_thread(_run)

        results = []
        for item in raw:
            url = item.get("href") or item.get("url") or ""
            if not url:
                continue
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("body") or item.get("description") or "",
                    provider=self.name,
                )
            )
        return results
