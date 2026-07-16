"""Serper.dev — paid Google SERP API (most accurate provider)."""
import httpx

from app.config import get_settings
from app.services.search.base import SearchProvider, SearchResult

_GL_MAP = {
    "usa": "us", "united states": "us", "us": "us",
    "canada": "ca", "uk": "gb", "united kingdom": "gb",
    "germany": "de", "netherlands": "nl", "sweden": "se",
    "switzerland": "ch", "ireland": "ie", "uae": "ae",
    "australia": "au", "france": "fr", "spain": "es",
}


class SerperProvider(SearchProvider):
    name = "serper"

    def available(self) -> bool:
        return bool(get_settings().serper_api_key)

    async def search(self, query: str, *, region: str = "", max_results: int = 10) -> list[SearchResult]:
        settings = get_settings()
        payload = {"q": query, "num": max_results, "gl": _GL_MAP.get(region.lower().strip(), "us")}
        headers = {"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post("https://google.serper.dev/search", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                provider=self.name,
            )
            for item in data.get("organic", [])
            if item.get("link")
        ]
