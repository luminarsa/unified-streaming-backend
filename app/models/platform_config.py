import uuid
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class StreamingPlatform(Base):
    __tablename__ = "streaming_platforms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name = Column(String(120), nullable=False, unique=True)
    slug = Column(String(120), nullable=False, unique=True)
    description = Column(Text)
    logo_url = Column(Text)
    icon = Column(String(100), nullable=False)
    # TMDB content capabilities
    supports_movies = Column(Boolean, default=True, nullable=False)
    supports_tv_shows = Column(Boolean, default=True, nullable=False)

    # Platform-level capability, not subscriber permission
    supports_live_tv = Column(Boolean, default=False, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PlatformProfile(Base):
    __tablename__ = "platform_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    platform_id = Column(
        UUID(as_uuid=True),
        ForeignKey("streaming_platforms.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    config_version = Column(Integer, default=1, nullable=False)
    region_code = Column(String(2), default="ZA", nullable=False)
    language = Column(String(10), default="en-US", nullable=False)
    default_row_count = Column(Integer, default=12, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    fallback_policy = Column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "config_version >= 1",
            name="check_config_version_positive",
        ),
        CheckConstraint(
            "default_row_count > 0",
            name="check_default_row_count_positive",
        ),
    )


class PlatformProvider(Base):
    __tablename__ = "platform_providers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    platform_id = Column(
        UUID(as_uuid=True),
        ForeignKey("streaming_platforms.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform_name = Column(String, nullable=False)

    # Example: TMDB watch-provider ID
    provider_kind = Column(String(20), nullable=False)
    external_id = Column(Integer, nullable=False)
    region_code = Column(String(2))
    is_primary = Column(Boolean, default=False, nullable=False)
    source = Column(String(40), default="manual", nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "platform_id",
            "provider_kind",
            "external_id",
            "region_code",
            name="uq_platform_provider_mapping",
        ),
        CheckConstraint(
            "external_id > 0",
            name="check_external_provider_id_positive",
        ),
    )


class PlatformCompany(Base):
    __tablename__ = "platform_companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    platform_id = Column(
        UUID(as_uuid=True),
        ForeignKey("streaming_platforms.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform_name = Column(String, nullable=False)

    tmdb_company_id = Column(Integer, nullable=False)
    company_name = Column(String, nullable=False)
    relation_type = Column(String(40), default="produced_by", nullable=False)
    include_in_discovery = Column(Boolean, default=True, nullable=False)
    confidence = Column(String(20), default="verified", nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "platform_id",
            "tmdb_company_id",
            "relation_type",
            name="uq_platform_company_relation",
        ),
        CheckConstraint(
            "tmdb_company_id > 0",
            name="check_tmdb_company_id_positive",
        ),
    )


class PlatformNetwork(Base):
    __tablename__ = "platform_networks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    platform_id = Column(
        UUID(as_uuid=True),
        ForeignKey("streaming_platforms.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform_name = Column(String)

    tmdb_network_id = Column(Integer, nullable=False)
    network_name = Column(String, nullable=False)
    include_in_discovery = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "platform_id",
            "tmdb_network_id",
            name="uq_platform_network",
        ),
        CheckConstraint(
            "tmdb_network_id > 0",
            name="check_tmdb_network_id_positive",
        ),
    )

class PlatformOriginalSource(Base):
    """
    Platform-level configuration for identifying curated platform originals.

    source_type:
        production_company = TMDB production company
        network = TMDB TV network
        keyword = TMDB keyword
        curated_title = individually selected movie or TV show
    """

    __tablename__ = "platform_original_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    platform_id = Column(
        UUID(as_uuid=True),
        ForeignKey("streaming_platforms.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    source_type = Column(String(30), nullable=False)

    # TMDB company, network, keyword, movie or TV show ID.
    tmdb_id = Column(Integer, nullable=False)

    # Human-readable company, network, keyword or title name.
    name = Column(String(255), nullable=False)

    # Only used for curated_title: movie or tv.
    media_type = Column(String(20), nullable=True)

    # Allows a source to be retained but temporarily excluded from results.
    include_in_discovery = Column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    # Useful for tracking how confidently an original source was verified.
    confidence = Column(
        String(20),
        default="verified",
        server_default="verified",
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "source_type IN "
            "('production_company', 'network', 'keyword', 'curated_title')",
            name="ck_platform_original_source_type",
        ),
        CheckConstraint(
            "(source_type = 'curated_title' AND media_type IN ('movie', 'tv')) "
            "OR (source_type != 'curated_title' AND media_type IS NULL)",
            name="ck_platform_original_media_type",
        ),
        UniqueConstraint(
            "platform_id",
            "source_type",
            "tmdb_id",
            "media_type",
            name="uq_platform_original_source",
        ),
    )


class SliderDefinition(Base):
    __tablename__ = "slider_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    platform_id = Column(
        UUID(as_uuid=True),
        ForeignKey("streaming_platforms.id", ondelete="CASCADE"),
        nullable=False,
    )

    key = Column(String(80), nullable=False)
    title = Column(String(120), nullable=False)
    strategy = Column(String(40), nullable=False)

    # mixed, movies, tv_shows
    media_scope = Column(String(20), default="mixed", nullable=False)

    genre_ids = Column(JSONB, default=list, nullable=False)
    query_overrides = Column(JSONB, default=dict, nullable=False)

    display_order = Column(Integer, default=0, nullable=False)
    page_size = Column(Integer, default=25, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "platform_id",
            "key",
            name="uq_slider_platform_key",
        ),
        CheckConstraint(
            "page_size > 0",
            name="check_slider_page_size_positive",
        ),
        CheckConstraint(
            "media_scope IN ('mixed', 'movies', 'tv_shows')",
            name="check_slider_media_scope",
        ),
    )


class PlatformNavigationItem(Base):
    __tablename__ = "platform_navigation_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    platform_id = Column(
        UUID(as_uuid=True),
        ForeignKey("streaming_platforms.id", ondelete="CASCADE"),
        nullable=False,
    )

    key = Column(String(40), nullable=False)
    label = Column(String(80), nullable=False)
    route = Column(String(160), nullable=False)
    display_order = Column(Integer, default=0, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)

    # Examples: always, live_tv
    requires_feature = Column(String(40), default="always", nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "platform_id",
            "key",
            name="uq_platform_navigation_key",
        ),
        CheckConstraint(
            "requires_feature IN ('always', 'live_tv')",
            name="check_navigation_requires_feature",
        ),
    )


class PlatformLiveChannel(Base):
    __tablename__ = "platform_live_channels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    platform_id = Column(
        UUID(as_uuid=True),
        ForeignKey("streaming_platforms.id", ondelete="CASCADE"),
        nullable=False,
    )

    channel_key = Column(String(80), nullable=False)
    name = Column(String(120), nullable=False)
    logo_url = Column(Text)
    stream_url = Column(Text)
    channel_number = Column(Integer)
    display_order = Column(Integer, default=0, nullable=False)
    category = Column(String, nullable=True)
    is_news_channel = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Can be used later for EPG/program-guide integration
    metadata_json = Column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "platform_id",
            "channel_key",
            name="uq_platform_live_channel_key",
        ),
        CheckConstraint(
            "channel_number IS NULL OR channel_number > 0",
            name="check_channel_number_positive",
        ),
    )


# =========================================================
# SLIDER-LEVEL CONTENT CONFIGURATION
# These tables configure administrator-defined seed sliders.
# They do not store dynamically generated profile sliders.
# =========================================================


class SliderCuratedTitle(Base):
    """
    Stores manually selected TMDB titles for a slider.

    Priority determines the order in which curated titles
    should be considered by the discovery engine.
    """

    __tablename__ = "slider_curated_titles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    slider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("slider_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    tmdb_id = Column(Integer, nullable=False)
    media_type = Column(String(10), nullable=False)

    title = Column(String(255), nullable=False)

    priority = Column(Integer, default=1, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "slider_id",
            "tmdb_id",
            "media_type",
            name="uq_slider_curated_title",
        ),
        CheckConstraint(
            "tmdb_id > 0",
            name="check_slider_curated_tmdb_id_positive",
        ),
        CheckConstraint(
            "media_type IN ('movie', 'tv')",
            name="check_slider_curated_media_type",
        ),
        CheckConstraint(
            "priority > 0",
            name="check_slider_curated_priority_positive",
        ),
    )


class SliderKeyword(Base):
    """
    Stores TMDB keywords associated with an individual slider.

    match_type:
        include = keyword is a discovery target.
        boost = keyword should increase relevance when present.
    """

    __tablename__ = "slider_keywords"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    slider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("slider_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    tmdb_keyword_id = Column(Integer, nullable=False)
    keyword_name = Column(String(150), nullable=False)

    match_type = Column(String(20), default="include", nullable=False)

    priority = Column(Integer, default=1, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "slider_id",
            "tmdb_keyword_id",
            name="uq_slider_keyword",
        ),
        CheckConstraint(
            "tmdb_keyword_id > 0",
            name="check_slider_keyword_id_positive",
        ),
        CheckConstraint(
            "match_type IN ('include', 'boost')",
            name="check_slider_keyword_match_type",
        ),
        CheckConstraint(
            "priority > 0",
            name="check_slider_keyword_priority_positive",
        ),
    )


class SliderCollection(Base):
    """
    Associates TMDB collections with individual sliders.

    Useful for franchise-based and universe-based sliders.
    """

    __tablename__ = "slider_collections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    slider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("slider_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    tmdb_collection_id = Column(Integer, nullable=False)
    collection_name = Column(String(255), nullable=False)

    priority = Column(Integer, default=1, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "slider_id",
            "tmdb_collection_id",
            name="uq_slider_collection",
        ),
        CheckConstraint(
            "tmdb_collection_id > 0",
            name="check_slider_collection_id_positive",
        ),
        CheckConstraint(
            "priority > 0",
            name="check_slider_collection_priority_positive",
        ),
    )


class SliderCompany(Base):
    """
    Stores production-company associations for an individual slider.

    These mappings help discover relevant content.
    They do not establish streaming availability.
    """

    __tablename__ = "slider_companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    slider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("slider_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    tmdb_company_id = Column(Integer, nullable=False)
    company_name = Column(String(255), nullable=False)

    relation_type = Column(
        String(40),
        default="produced_by",
        nullable=False,
    )

    priority = Column(Integer, default=1, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "slider_id",
            "tmdb_company_id",
            "relation_type",
            name="uq_slider_company_relation",
        ),
        CheckConstraint(
            "tmdb_company_id > 0",
            name="check_slider_company_id_positive",
        ),
        CheckConstraint(
            "priority > 0",
            name="check_slider_company_priority_positive",
        ),
    )


class SliderNetwork(Base):
    """
    Stores TV network associations for an individual slider.

    These mappings are discovery signals, not proof of
    regional streaming availability.
    """

    __tablename__ = "slider_networks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    slider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("slider_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    tmdb_network_id = Column(Integer, nullable=False)
    network_name = Column(String(255), nullable=False)

    priority = Column(Integer, default=1, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "slider_id",
            "tmdb_network_id",
            name="uq_slider_network",
        ),
        CheckConstraint(
            "tmdb_network_id > 0",
            name="check_slider_network_id_positive",
        ),
        CheckConstraint(
            "priority > 0",
            name="check_slider_network_priority_positive",
        ),
    )


class SliderExcludedTitle(Base):
    """
    Stores titles that must be excluded from an individual slider.

    This allows administrators to prevent irrelevant or
    unwanted titles from appearing in a generated collection.
    """

    __tablename__ = "slider_excluded_titles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    slider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("slider_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    tmdb_id = Column(Integer, nullable=False)
    media_type = Column(String(10), nullable=False)

    title = Column(String(255), nullable=False)
    reason = Column(Text, nullable=True)

    enabled = Column(Boolean, default=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "slider_id",
            "tmdb_id",
            "media_type",
            name="uq_slider_excluded_title",
        ),
        CheckConstraint(
            "tmdb_id > 0",
            name="check_slider_excluded_tmdb_id_positive",
        ),
        CheckConstraint(
            "media_type IN ('movie', 'tv')",
            name="check_slider_excluded_media_type",
        ),
    )
