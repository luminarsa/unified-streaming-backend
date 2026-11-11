
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.identity import Profile
from app.core.config import settings

from app.models.commercial import (
    Plan,
    PlanEntitlement,
    Subscription,
)

from app.models.platform_config import (
    StreamingPlatform,
    PlatformProfile,
    PlatformProvider,
    PlatformNetwork,
    PlatformCompany,
)


def get_platform_search_entitlements(
    db: Session,
    account_id: UUID,
    platform_id: UUID,
    profile: Profile,
):
    # ---------------------------------------------------------
    # 1. GET PLATFORM
    # ---------------------------------------------------------

    platform = db.query(StreamingPlatform).filter(
        StreamingPlatform.id == platform_id,
        StreamingPlatform.is_active == True,
    ).first()

    if platform is None:
        raise HTTPException(
            status_code=404,
            detail="Platform not found or inactive.",
        )

    # ---------------------------------------------------------
    # PROFILE CONTENT RESTRICTIONS
    # ---------------------------------------------------------

    is_kids_profile = profile.is_kids_profile

    profile_type = "kids" if is_kids_profile else "adult"

    allow_adult_content = not is_kids_profile

    content_rating_policy = (
        "kids_only"
        if is_kids_profile
        else "all"
    )

    # ---------------------------------------------------------
    # 2. GET ACTIVE SUBSCRIPTION
    # ---------------------------------------------------------

    now = datetime.now(timezone.utc)

    subscription = (
        db.query(Subscription)
        .join(
            Plan,
            Subscription.plan_id == Plan.id,
        )
        .filter(
            Subscription.account_id == account_id,
            Subscription.status == "active",
            Plan.is_active == True,
            (
                Subscription.current_period_end.is_(None)
                |
                (Subscription.current_period_end > now)
            ),
        )
        .order_by(Subscription.created_at.desc())
        .first()
    )

    if subscription is None:
        raise HTTPException(
            status_code=403,
            detail="An active subscription is required.",
        )

    # ---------------------------------------------------------
    # 3. CHECK PLATFORM ENTITLEMENT
    # ---------------------------------------------------------

    entitlement = db.query(PlanEntitlement).filter(
        PlanEntitlement.plan_id == subscription.plan_id,
        PlanEntitlement.platform_id == platform_id,
    ).first()

    if entitlement is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PLATFORM_NOT_ENTITLED",
                "message": "Your subscription does not include this platform.",
            },
        )

    # ---------------------------------------------------------
    # 4. GET PLATFORM PROFILE CONFIGURATION
    # ---------------------------------------------------------

    profile_config = db.query(PlatformProfile).filter(
        PlatformProfile.platform_id == platform_id,
    ).first()

    if profile_config is not None and not profile_config.enabled:
        raise HTTPException(
            status_code=403,
            detail="Search is currently disabled for this platform.",
        )

    if profile_config is None:
        region_code = settings.tmdb_region.upper()
        language = settings.tmdb_language
    else:
        region_code = profile_config.region_code.upper()
        language = profile_config.language

    # ---------------------------------------------------------
    # 5. GET WATCH PROVIDERS
    # ---------------------------------------------------------

    provider_query = db.query(PlatformProvider).filter(
        PlatformProvider.platform_id == platform_id,
    )

    # Include global mappings and mappings for this region.
    providers = provider_query.filter(
        (
            PlatformProvider.region_code.is_(None)
        )
        |
        (
            PlatformProvider.region_code == region_code
        )
    ).order_by(
        PlatformProvider.is_primary.desc(),
        PlatformProvider.external_id.asc(),
    ).all()

    watch_providers = [
        {
            "tmdb_id": provider.external_id,
            "provider_kind": provider.provider_kind,
            "region_code": provider.region_code,
            "is_primary": provider.is_primary,
        }
        for provider in providers
    ]

    # ---------------------------------------------------------
    # 6. GET TV NETWORKS
    # ---------------------------------------------------------

    networks = db.query(PlatformNetwork).filter(
        PlatformNetwork.platform_id == platform_id,
        PlatformNetwork.include_in_discovery == True,
    ).order_by(
        PlatformNetwork.network_name.asc(),
    ).all()

    network_data = [
        {
            "tmdb_id": network.tmdb_network_id,
            "name": network.network_name,
        }
        for network in networks
    ]

    # ---------------------------------------------------------
    # 7. GET PRODUCTION COMPANIES
    # ---------------------------------------------------------

    companies = db.query(PlatformCompany).filter(
        PlatformCompany.platform_id == platform_id,
        PlatformCompany.include_in_discovery == True,
    ).order_by(
        PlatformCompany.company_name.asc(),
    ).all()

    company_data = [
        {
            "tmdb_id": company.tmdb_company_id,
            "name": company.company_name,
            "relation_type": company.relation_type,
        }
        for company in companies
    ]

    # ---------------------------------------------------------
    # 8. GET ALLOWED CONTENT TYPES
    # ---------------------------------------------------------

    allowed_content_types = []

    if platform.supports_movies:
        allowed_content_types.append("movie")

    if platform.supports_tv_shows:
        allowed_content_types.append("tv")

    # ---------------------------------------------------------
    # 9. BUILD RESPONSE
    # ---------------------------------------------------------

    return {
        "profile": {
            "profile_id": str(profile.id),
            "profile_type": profile_type,
            "is_kids_profile": is_kids_profile,
            "allow_adult_content": allow_adult_content,
            "content_rating_policy": content_rating_policy,
        },
        "platform_id": str(platform.id),
        "platform_name": platform.name,
        "platform_slug": platform.slug,

        "region_code": region_code,
        "language": language,

        "supports_movies": platform.supports_movies,
        "supports_tv_shows": platform.supports_tv_shows,

        "allowed_content_types": allowed_content_types,

        "search_entitlements": {
            "watch_providers": watch_providers,
            "networks": network_data,
            "production_companies": company_data,
        },

        "watch_providers": watch_providers,
        "networks": network_data,
        "production_companies": company_data,
    }
