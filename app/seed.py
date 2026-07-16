"""Seed default campaigns on first boot.

Ships with one generic example campaign so the app is immediately usable out
of the box. Your own campaigns — real targeting strategy, unannounced
products — belong in app/local_seed.py (gitignored, loaded automatically if
present; see app/local_seed.py.example for the shape).
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Campaign

SEED_CAMPAIGNS: list[dict] = [
    {
        "slug": "example-b2b-saas",
        "name": "Example — B2B SaaS Outsourcing Partner",
        "company_name": "Acme Dev Studio",
        "company_url": "https://example.com",
        "product_description": (
            "Acme Dev Studio is an example software development partner. Replace this with your "
            "own product/service description — this campaign exists to show the shape of a "
            "configuration, not as a real targeting strategy."
        ),
        "icp_description": (
            "Founders and startups across the USA, Canada, and Europe that are likely to "
            "outsource software or MVP development to an external partner. Sweet spot: pre-seed "
            "to Series A companies with 1-50 employees and a non-technical founder."
        ),
        "regions": ["USA", "Canada", "UK", "Germany"],
        "sectors": ["B2B SaaS", "FinTech", "HealthTech"],
        "positive_signals": [
            "recently raised pre-seed, seed, or Series A funding",
            "non-technical founder or no technical co-founder",
            "publicly looking for a development partner or dev agency",
            "small team (1-50 employees), early stage",
        ],
        "negative_signals": [
            "is itself a software development agency or competitor",
            "large enterprise (200+ employees) with in-house engineering",
            "news site, directory, listicle, or job board rather than a company",
        ],
        "services": ["MVP Development", "SaaS Development", "Dedicated Development Team"],
        "min_score": 60,
        "target_leads_per_run": 50,
        "max_iterations": 3,
        "queries_per_iteration": 12,
        "results_per_query": 10,
    },
]


def _load_local_campaigns() -> list[dict]:
    """Optional private campaigns from app/local_seed.py (gitignored)."""
    try:
        from app.local_seed import SEED_CAMPAIGNS as LOCAL_CAMPAIGNS  # type: ignore[import-not-found]
    except ImportError:
        return []
    return LOCAL_CAMPAIGNS


async def seed_campaigns(db: AsyncSession) -> int:
    created = 0
    for data in SEED_CAMPAIGNS + _load_local_campaigns():
        exists = await db.execute(select(Campaign.id).where(Campaign.slug == data["slug"]))
        if exists.scalar_one_or_none() is None:
            db.add(Campaign(**data))
            created += 1
    if created:
        await db.commit()
    return created
