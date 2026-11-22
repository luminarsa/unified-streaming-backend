
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import Profile

from app.models.platform_config import (
    StreamingPlatform,
    PlatformProfile,
    PlatformProvider,
    PlatformCompany,
    PlatformNetwork,
    PlatformOriginalSource,
    PlatformLiveChannel,
)


def _get_platform(db: Session, platform_id: UUID):
    platform = db.scalar(
        select(StreamingPlatform).where(
            StreamingPlatform.id == platform_id
        )
    )

    if not platform:
        raise HTTPException(
            status_code=404,
            detail="Platform not found.",
        )

    return platform


def _get_platform_profile(db: Session, platform_id: UUID):
    return db.scalar(
        select(PlatformProfile).where(
            PlatformProfile.platform_id == platform_id
        )
    )


def _base_response(platform, profile: Profile):
    preferences = profile.preferences or {}

    return {
        "success": True,

        "platform": {
            "id": str(platform.id),
            "name": platform.name,
            "slug": platform.slug,
        },

        "profile_id": str(profile.id),

        "profile_preferences": {
            "genre_preferences": preferences.get(
                "genre_preferences", []
            ),
            "keyword_preferences": preferences.get(
                "keyword_preferences", []
            ),
        },
    }


def _build_discovery_strategy(
    media_type: str,
    profile_preferences: dict,
    content_sources: dict,
):
    """
    Build TMDB discovery instructions for the frontend.

    This function does not retrieve or return movie or TV titles.
    It only returns filters and discovery instructions.
    """

    genre_preferences = profile_preferences.get(
        "genre_preferences", []
    )

    keyword_preferences = profile_preferences.get(
        "keyword_preferences", []
    )

    preferred_genre_ids = [
        item["genre_id"]
        for item in genre_preferences
        if isinstance(item, dict) and item.get("genre_id") is not None
    ]

    preferred_keyword_ids = [
        item["keyword_id"]
        for item in keyword_preferences
        if isinstance(item, dict) and item.get("keyword_id") is not None
    ]

    excluded_genre_ids = []
    excluded_keyword_ids = []

    strategy = {
        "strategy_version": 1,
        "media_type": media_type,
        "personalization_enabled": bool(
            preferred_genre_ids or preferred_keyword_ids
        ),

        "discovery_priorities": [
            "profile_preferences",
            "platform_content_sources",
            "popular_content",
            "trending_content",
            "highly_rated_content",
            "new_releases",
        ],

        "recommended_queries": [],

        "content_exclusions": {
            "exclude_adult": True,
            "exclude_genre_ids": excluded_genre_ids,
            "exclude_keyword_ids": excluded_keyword_ids,
        },

        "default_sorting": {
            "popular": "popularity.desc",
            "trending": "popularity.desc",
            "highly_rated": "vote_average.desc",
            "new_releases": (
                "primary_release_date.desc"
                if media_type == "movie"
                else "first_air_date.desc"
            ),
        },

        "suggested_page_size": 20,
    }

    if preferred_genre_ids:
        strategy["recommended_queries"].append({
            "query_key": "profile_preferred_genres",
            "description": (
                "Discover content matching the profile's preferred genres."
            ),
            "with_genres": preferred_genre_ids,
            "sort_by": "popularity.desc",
        })

    if preferred_keyword_ids:
        strategy["recommended_queries"].append({
            "query_key": "profile_preferred_keywords",
            "description": (
                "Discover content matching the profile's preferred keywords."
            ),
            "with_keywords": preferred_keyword_ids,
            "sort_by": "popularity.desc",
        })

    if preferred_genre_ids and preferred_keyword_ids:
        strategy["recommended_queries"].append({
            "query_key": "profile_combined_preferences",
            "description": (
                "Discover content matching both preferred genres "
                "and keywords."
            ),
            "with_genres": preferred_genre_ids,
            "with_keywords": preferred_keyword_ids,
            "sort_by": "vote_average.desc",
            "vote_count_gte": 100,
        })

    strategy["recommended_queries"].append({
        "query_key": "popular_content",
        "description": "Discover currently popular content.",
        "sort_by": "popularity.desc",
    })

    strategy["recommended_queries"].append({
        "query_key": "highly_rated_content",
        "description": "Discover highly rated content.",
        "sort_by": "vote_average.desc",
        "vote_count_gte": 100,
    })

    if media_type == "movie":
        strategy["recommended_queries"].append({
            "query_key": "new_releases",
            "description": "Discover recently released movies.",
            "sort_by": "primary_release_date.desc",
        })

        company_ids = [
            item["tmdb_company_id"]
            for item in content_sources.get(
                "production_companies", []
            )
            if item.get("tmdb_company_id") is not None
        ]

        if company_ids:
            strategy["recommended_queries"].append({
                "query_key": "platform_originals",
                "description": (
                    "Discover movies associated with the platform's "
                    "configured production companies."
                ),
                "with_companies": company_ids,
                "sort_by": "popularity.desc",
            })

    elif media_type == "tv":
        strategy["recommended_queries"].append({
            "query_key": "new_releases",
            "description": "Discover recently aired TV shows.",
            "sort_by": "first_air_date.desc",
        })

        network_ids = [
            item["tmdb_network_id"]
            for item in content_sources.get("networks", [])
            if item.get("tmdb_network_id") is not None
        ]

        if network_ids:
            strategy["recommended_queries"].append({
                "query_key": "platform_network_content",
                "description": (
                    "Discover TV shows associated with the platform's "
                    "configured networks."
                ),
                "with_networks": network_ids,
                "sort_by": "popularity.desc",
            })

        provider_ids = [
            item["tmdb_provider_id"]
            for item in content_sources.get("watch_providers", [])
            if item.get("tmdb_provider_id") is not None
        ]

        if provider_ids:
            strategy["recommended_queries"].append({
                "query_key": "platform_available_content",
                "description": (
                    "Discover TV shows available through the platform's "
                    "configured watch providers."
                ),
                "with_watch_providers": provider_ids,
                "sort_by": "popularity.desc",
            })

    return strategy


def get_platform_movies(
    db: Session,
    platform_id: UUID,
    profile: Profile,
):
    platform = _get_platform(db, platform_id)
    platform_profile = _get_platform_profile(db, platform_id)

    companies = db.scalars(
        select(PlatformCompany)
        .where(
            PlatformCompany.platform_id == platform_id,
            PlatformCompany.include_in_discovery.is_(True),
        )
        .order_by(PlatformCompany.company_name.asc())
    ).all()

    response = _base_response(platform, profile)

    content_sources = {
        "production_companies": [
            {
                "tmdb_company_id": company.tmdb_company_id,
                "company_name": company.company_name,
                "relation_type": company.relation_type,
                "confidence": company.confidence,
            }
            for company in companies
        ],

        "region_code": (
            platform_profile.region_code
            if platform_profile
            else None
        ),

        "language": (
            platform_profile.language
            if platform_profile
            else None
        ),
    }

    response["content_sources"] = content_sources

    response["discovery_strategy"] = _build_discovery_strategy(
        media_type="movie",
        profile_preferences=response["profile_preferences"],
        content_sources=content_sources,
    )

    return response


def get_platform_shows(
    db: Session,
    platform_id: UUID,
    profile: Profile,
):
    platform = _get_platform(db, platform_id)
    platform_profile = _get_platform_profile(db, platform_id)

    providers = db.scalars(
        select(PlatformProvider)
        .where(
            PlatformProvider.platform_id == platform_id,
        )
        .order_by(
            PlatformProvider.region_code.asc(),
            PlatformProvider.external_id.asc(),
        )
    ).all()

    networks = db.scalars(
        select(PlatformNetwork)
        .where(
            PlatformNetwork.platform_id == platform_id,
            PlatformNetwork.include_in_discovery.is_(True),
        )
        .order_by(PlatformNetwork.network_name.asc())
    ).all()

    response = _base_response(platform, profile)

    content_sources = {
        "watch_providers": [
            {
                "tmdb_provider_id": provider.external_id,
                "provider_kind": provider.provider_kind,
                "region_code": provider.region_code,
                "is_primary": provider.is_primary,
                "source": provider.source,
            }
            for provider in providers
        ],

        "networks": [
            {
                "tmdb_network_id": network.tmdb_network_id,
                "network_name": network.network_name,
            }
            for network in networks
        ],

        "region_code": (
            platform_profile.region_code
            if platform_profile
            else None
        ),

        "language": (
            platform_profile.language
            if platform_profile
            else None
        ),
    }

    response["content_sources"] = content_sources

    response["discovery_strategy"] = _build_discovery_strategy(
        media_type="tv",
        profile_preferences=response["profile_preferences"],
        content_sources=content_sources,
    )

    return response


def get_platform_originals(
    db: Session,
    platform_id: UUID,
    profile: Profile,
):
    platform = _get_platform(db, platform_id)
    platform_profile = _get_platform_profile(db, platform_id)

    sources = db.scalars(
        select(PlatformOriginalSource)
        .where(
            PlatformOriginalSource.platform_id == platform_id,
            PlatformOriginalSource.include_in_discovery.is_(True),
        )
        .order_by(
            PlatformOriginalSource.source_type.asc(),
            PlatformOriginalSource.name.asc(),
        )
    ).all()

    content_sources = {
        "production_companies": [],
        "networks": [],
        "keywords": [],
    }

    source_key_map = {
        "production_company": "production_companies",
        "network": "networks",
        "keyword": "keywords",
    }

    for source in sources:
        key = source_key_map.get(source.source_type)

        if not key:
            continue

        content_sources[key].append({
            "tmdb_id": source.tmdb_id,
            "name": source.name,
            "confidence": source.confidence,
        })

    content_sources["region_code"] = (
        platform_profile.region_code
        if platform_profile
        else None
    )

    content_sources["language"] = (
        platform_profile.language
        if platform_profile
        else None
    )

    response = _base_response(platform, profile)

    response["content_sources"] = content_sources

    response["discovery_strategy"] = {
        "strategy_version": 1,
        "personalization_enabled": bool(
            response["profile_preferences"]["genre_preferences"]
            or response["profile_preferences"]["keyword_preferences"]
        ),

        "movies": _build_discovery_strategy(
            media_type="movie",
            profile_preferences=response["profile_preferences"],
            content_sources=content_sources,
        ),

        "tv_shows": _build_discovery_strategy(
            media_type="tv",
            profile_preferences=response["profile_preferences"],
            content_sources=content_sources,
        ),

        "content_exclusions": {
            "exclude_adult": True,
        },

        "suggested_page_size": 20,
    }

    return response


def get_platform_channels(
    db: Session,
    platform_id: UUID,
    profile: Profile,
):
    platform = _get_platform(db, platform_id)

    channels = db.scalars(
        select(PlatformLiveChannel)
        .where(
            PlatformLiveChannel.platform_id == platform_id,
            PlatformLiveChannel.is_active.is_(True),
        )
        .order_by(
            PlatformLiveChannel.display_order.asc(),
            PlatformLiveChannel.channel_number.asc(),
            PlatformLiveChannel.name.asc(),
        )
    ).all()

    response = _base_response(platform, profile)

    response["live_channels"] = [
        {
            "id": str(channel.id),
            "channel_key": channel.channel_key,
            "name": channel.name,
            "logo_url": channel.logo_url,
            "stream_url": channel.stream_url,
            "channel_number": channel.channel_number,
            "display_order": channel.display_order,
            "category": channel.category,
            "is_news_channel": channel.is_news_channel,
            "metadata": channel.metadata_json or {},
        }
        for channel in channels
    ]

    response["total_channels"] = len(channels)

    return response
