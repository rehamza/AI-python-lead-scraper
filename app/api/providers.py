"""Search provider health / configuration status."""
from fastapi import APIRouter

from app.config import get_settings
from app.services.search import get_search_chain

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("")
async def provider_status():
    settings = get_settings()
    return {
        "order": settings.provider_order,
        "providers": get_search_chain().status(),
        "llm_model": settings.anthropic_model,
        "llm_key_configured": bool(settings.anthropic_api_key),
        "smtp_verify_enabled": settings.smtp_verify_enabled,
    }
