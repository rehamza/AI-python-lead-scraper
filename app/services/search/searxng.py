"""SearXNG — self-hosted metasearch (free, unlimited).

Run one locally with:
    docker run -d -p 8888:8080 searxng/searxng
then set SEARXNG_URL=http://localhost:8888 and enable the JSON format in
searxng settings.yml (search.formats: [html, json]).
"""
import httpx

from app.config import get_settings
from app.services.search.base import SearchProvider, SearchResult


class SearxngProvider(SearchProvider):
    name = "searxng"

    def available(self) -> bool:
        return bool(get_settings().searxng_url)

    async def search(self, query: str, *, region: str = "", max_results: int = 10) -> list[SearchResult]:
        base = get_settings().searxng_url.rstrip("/")
        params = {"q": query, "format": "json", "categories": "general"}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{base}/search", params=params)
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                provider=self.name,
            )
            for item in data.get("results", [])[:max_results]
            if item.get("url")
        ]
