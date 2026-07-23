"""LLM abstraction supporting Anthropic Claude and Groq with Pydantic structured outputs."""
from functools import lru_cache
import logging
from typing import TypeVar

import anthropic
import httpx
from pydantic import BaseModel

from app.config import get_settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@lru_cache
def get_anthropic_client() -> anthropic.AsyncAnthropic:
    settings = get_settings()
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
    """One structured-output call: returns a validated instance of output_format.

    Routes dynamically to Anthropic or Groq based on LLM_PROVIDER in settings.
    """
    settings = get_settings()
    provider = settings.llm_provider.lower().strip()

    if provider == "groq":
        schema_dict = output_format.model_json_schema()
        groq_system = (
            f"{system}\n\n"
            f"CRITICAL REQUIREMENT: You MUST output a single valid JSON object adhering strictly to the JSON schema below.\n"
            f"Do not include any conversational commentary, introductory text, or markdown code block formatting.\n"
            f"JSON Schema:\n{schema_dict}"
        )

        tokens = min(max_tokens, 8192)
        headers = {
            "Authorization": f"Bearer {settings.groq_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.groq_model,
            "messages": [
                {"role": "system", "content": groq_system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": tokens,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=60.0) as http_client:
            resp = await http_client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"] or "{}"
            return output_format.model_validate_json(raw_content)

    # Default: Anthropic Claude
    client = get_anthropic_client()
    response = await client.messages.parse(
        model=settings.anthropic_model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=output_format,
    )
    return response.parsed_output
