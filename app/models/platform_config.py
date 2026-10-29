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

    tmdb_company_id = Column(Integer, nullable=False)
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

    tmdb_network_id = Column(Integer, nullable=False)
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
