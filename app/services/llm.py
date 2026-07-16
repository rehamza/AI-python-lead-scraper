"""Anthropic Claude wrapper with Pydantic structured outputs."""
from functools import lru_cache
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)


@lru_cache
def get_client() -> anthropic.AsyncAnthropic:
    settings = get_settings()
    # With no explicit key the SDK falls back to ANTHROPIC_API_KEY env var or
    # an `ant auth login` profile.
    if settings.anthropic_api_key:
        return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return anthropic.AsyncAnthropic()


async def structured(
    *,
    system: str,
    prompt: str,
    output_format: type[T],
    max_tokens: int = 16000,
) -> T:
    """One structured-output call: returns a validated instance of output_format."""
    client = get_client()
    response = await client.messages.parse(
        model=get_settings().anthropic_model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=output_format,
    )
    return response.parsed_output
