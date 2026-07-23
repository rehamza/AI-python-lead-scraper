"""LLM abstraction supporting Gemini, Groq, and Anthropic Claude with Pydantic structured outputs."""
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

    Routes dynamically to Gemini, Groq, or Anthropic based on LLM_PROVIDER in settings.
    """
    settings = get_settings()
    provider = settings.llm_provider.lower().strip()

    # 1. Google Gemini
    if provider == "gemini":
        api_key = settings.gemini_api_key.strip()
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set or empty in .env. Please set GEMINI_API_KEY=... in your .env file."
            )

        schema_dict = output_format.model_json_schema()
        gemini_system = (
            f"{system}\n\n"
            f"CRITICAL REQUIREMENT: You MUST output a single valid JSON object adhering strictly to the JSON schema below.\n"
            f"Do not include any Markdown text formatting or extra text outside of the JSON object.\n"
            f"JSON Schema:\n{schema_dict}"
        )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent?key={api_key}"
        payload = {
            "system_instruction": {
                "parts": [{"text": gemini_system}]
            },
            "contents": [
                {"role": "user", "parts": [{"text": prompt}]}
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2,
                "maxOutputTokens": min(max_tokens, 8192),
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as http_client:
            resp = await http_client.post(url, json=payload)
            if resp.status_code != 200:
                log.error("Gemini API error (%d): %s", resp.status_code, resp.text)
                resp.raise_for_status()
            data = resp.json()
            try:
                raw_content = data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as err:
                log.error("Gemini response missing content: %s", data)
                raise RuntimeError(f"Invalid response structure from Gemini API: {data}") from err
            return output_format.model_validate_json(raw_content)

    # 2. Groq
    if provider == "groq":
        schema_dict = output_format.model_json_schema()
        groq_system = (
            f"{system}\n\n"
            f"CRITICAL REQUIREMENT: You MUST output a single valid JSON object adhering strictly to the JSON schema below.\n"
            f"Do not include any conversational commentary, introductory text, or markdown code block formatting.\n"
            f"JSON Schema:\n{schema_dict}"
        )

        api_key = settings.groq_api_key.strip()
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY is not set or empty in .env. Please set GROQ_API_KEY=gsk_... in your .env file."
            )

        tokens = min(max_tokens, 4096)
        headers = {
            "Authorization": f"Bearer {api_key}",
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
            if resp.status_code != 200:
                log.error("Groq API error (%d): %s", resp.status_code, resp.text)
                resp.raise_for_status()
            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"] or "{}"
            return output_format.model_validate_json(raw_content)

    # 3. Default: Anthropic Claude
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
