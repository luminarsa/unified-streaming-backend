
"""add platform original sources

Revision ID: deef1bd1d424
Revises: 8aab6ae37f2c
Create Date: 2026-11-22 15:38:10.907386
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "deef1bd1d424"
down_revision: Union[str, Sequence[str], None] = "8aab6ae37f2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create platform original sources table."""

    op.create_table(
        "platform_original_sources",

        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "platform_id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "source_type",
            sa.String(length=30),
            nullable=False,
        ),

        sa.Column(
            "tmdb_id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
        ),

        sa.Column(
            "media_type",
            sa.String(length=20),
            nullable=True,
        ),

        sa.Column(
            "include_in_discovery",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),

        sa.Column(
            "confidence",
            sa.String(length=20),
            server_default="verified",
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),

        sa.CheckConstraint(
            "source_type IN "
            "('production_company', 'network', 'keyword', 'curated_title')",
            name="ck_platform_original_source_type",
        ),

        sa.CheckConstraint(
            "(source_type = 'curated_title' AND media_type IN ('movie', 'tv')) "
            "OR (source_type != 'curated_title' AND media_type IS NULL)",
            name="ck_platform_original_media_type",
        ),

        sa.ForeignKeyConstraint(
            ["platform_id"],
            ["streaming_platforms.id"],
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint("id"),

        sa.UniqueConstraint(
            "platform_id",
            "source_type",
            "tmdb_id",
            "media_type",
            name="uq_platform_original_source",
        ),
    )

    op.create_index(
        "ix_platform_original_sources_platform_id",
        "platform_original_sources",
        ["platform_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove platform original sources table."""

    op.drop_index(
        "ix_platform_original_sources_platform_id",
        table_name="platform_original_sources",
    )

    op.drop_table("platform_original_sources")
