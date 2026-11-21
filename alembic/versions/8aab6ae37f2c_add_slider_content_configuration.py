
"""add slider content configuration

Revision ID: 8aab6ae37f2c
Revises: 1ce4df52d091
Create Date: 2026-11-21 15:42:35.321580

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8aab6ae37f2c'
down_revision: Union[str, Sequence[str], None] = '1ce4df52d091'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create slider content configuration tables."""

    # 1. Slider Collections
    op.create_table(
        'slider_collections',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('slider_id', sa.UUID(), nullable=False),
        sa.Column('tmdb_collection_id', sa.Integer(), nullable=False),
        sa.Column('collection_name', sa.String(length=255), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.CheckConstraint(
            'priority > 0',
            name='check_slider_collection_priority_positive'
        ),
        sa.CheckConstraint(
            'tmdb_collection_id > 0',
            name='check_slider_collection_id_positive'
        ),
        sa.ForeignKeyConstraint(
            ['slider_id'],
            ['slider_definitions.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'slider_id',
            'tmdb_collection_id',
            name='uq_slider_collection'
        )
    )

    # 2. Slider Companies
    op.create_table(
        'slider_companies',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('slider_id', sa.UUID(), nullable=False),
        sa.Column('tmdb_company_id', sa.Integer(), nullable=False),
        sa.Column('company_name', sa.String(length=255), nullable=False),
        sa.Column('relation_type', sa.String(length=40), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.CheckConstraint(
            'priority > 0',
            name='check_slider_company_priority_positive'
        ),
        sa.CheckConstraint(
            'tmdb_company_id > 0',
            name='check_slider_company_id_positive'
        ),
        sa.ForeignKeyConstraint(
            ['slider_id'],
            ['slider_definitions.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'slider_id',
            'tmdb_company_id',
            'relation_type',
            name='uq_slider_company_relation'
        )
    )

    # 3. Slider Curated Titles
    op.create_table(
        'slider_curated_titles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('slider_id', sa.UUID(), nullable=False),
        sa.Column('tmdb_id', sa.Integer(), nullable=False),
        sa.Column('media_type', sa.String(length=10), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.CheckConstraint(
            "media_type IN ('movie', 'tv')",
            name='check_slider_curated_media_type'
        ),
        sa.CheckConstraint(
            'priority > 0',
            name='check_slider_curated_priority_positive'
        ),
        sa.CheckConstraint(
            'tmdb_id > 0',
            name='check_slider_curated_tmdb_id_positive'
        ),
        sa.ForeignKeyConstraint(
            ['slider_id'],
            ['slider_definitions.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'slider_id',
            'tmdb_id',
            'media_type',
            name='uq_slider_curated_title'
        )
    )

    # 4. Slider Excluded Titles
    op.create_table(
        'slider_excluded_titles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('slider_id', sa.UUID(), nullable=False),
        sa.Column('tmdb_id', sa.Integer(), nullable=False),
        sa.Column('media_type', sa.String(length=10), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.CheckConstraint(
            "media_type IN ('movie', 'tv')",
            name='check_slider_excluded_media_type'
        ),
        sa.CheckConstraint(
            'tmdb_id > 0',
            name='check_slider_excluded_tmdb_id_positive'
        ),
        sa.ForeignKeyConstraint(
            ['slider_id'],
            ['slider_definitions.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'slider_id',
            'tmdb_id',
            'media_type',
            name='uq_slider_excluded_title'
        )
    )

    # 5. Slider Keywords
    op.create_table(
        'slider_keywords',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('slider_id', sa.UUID(), nullable=False),
        sa.Column('tmdb_keyword_id', sa.Integer(), nullable=False),
        sa.Column('keyword_name', sa.String(length=150), nullable=False),
        sa.Column('match_type', sa.String(length=20), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.CheckConstraint(
            "match_type IN ('include', 'boost')",
            name='check_slider_keyword_match_type'
        ),
        sa.CheckConstraint(
            'priority > 0',
            name='check_slider_keyword_priority_positive'
        ),
        sa.CheckConstraint(
            'tmdb_keyword_id > 0',
            name='check_slider_keyword_id_positive'
        ),
        sa.ForeignKeyConstraint(
            ['slider_id'],
            ['slider_definitions.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'slider_id',
            'tmdb_keyword_id',
            name='uq_slider_keyword'
        )
    )

    # 6. Slider Networks
    op.create_table(
        'slider_networks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('slider_id', sa.UUID(), nullable=False),
        sa.Column('tmdb_network_id', sa.Integer(), nullable=False),
        sa.Column('network_name', sa.String(length=255), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.CheckConstraint(
            'priority > 0',
            name='check_slider_network_priority_positive'
        ),
        sa.CheckConstraint(
            'tmdb_network_id > 0',
            name='check_slider_network_id_positive'
        ),
        sa.ForeignKeyConstraint(
            ['slider_id'],
            ['slider_definitions.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'slider_id',
            'tmdb_network_id',
            name='uq_slider_network'
        )
    )


def downgrade() -> None:
    """Remove slider content configuration tables."""

    op.drop_table('slider_networks')
    op.drop_table('slider_keywords')
    op.drop_table('slider_excluded_titles')
    op.drop_table('slider_curated_titles')
    op.drop_table('slider_companies')
    op.drop_table('slider_collections')
