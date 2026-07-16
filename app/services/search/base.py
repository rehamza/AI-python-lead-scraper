"""Search provider interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    provider: str = ""

    def as_prompt_dict(self, index: int) -> dict:
        return {"index": index, "title": self.title, "url": self.url, "snippet": self.snippet}


class SearchProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def search(self, query: str, *, region: str = "", max_results: int = 10) -> list[SearchResult]:
        """Run one query. Raise on failure — the chain handles fallback."""

    def available(self) -> bool:
        """Whether this provider is configured/usable."""
        return True
