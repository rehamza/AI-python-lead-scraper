"""Search provider health / configuration status."""
from fastapi import APIRouter

from app.config import get_settings
from app.services.search import get_search_chain

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("")
async def provider_status():
    settings = get_settings()
    provider = settings.llm_provider.lower().strip()
    if provider == "gemini":
        key_configured = bool(settings.gemini_api_key)
    elif provider == "groq":
        key_configured = bool(settings.groq_api_key)
    else:
        key_configured = bool(settings.anthropic_api_key)
    return {
        "order": settings.provider_order,
        "providers": get_search_chain().status(),
        "llm_provider": settings.llm_provider,
        "llm_model": settings.active_llm_model,
        "llm_key_configured": key_configured,
        "smtp_verify_enabled": settings.smtp_verify_enabled,
    }
