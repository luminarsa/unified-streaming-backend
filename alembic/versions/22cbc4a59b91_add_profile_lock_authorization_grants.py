
"""add profile lock authorization grants

Revision ID: d3ffd0bec284
Revises: 03ae6ad1f106
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d3ffd0bec284"
down_revision: Union[str, Sequence[str], None] = "03ae6ad1f106"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profile_lock_authorization_grants",

        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),

        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),

        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),

        sa.Column(
            "grant_hash",
            sa.String(length=64),
            nullable=False,
        ),

        sa.Column(
            "operation",
            sa.String(length=40),
            nullable=False,
        ),

        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),

        sa.Column(
            "used_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),

        sa.PrimaryKeyConstraint("id"),

        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="CASCADE",
        ),

        sa.ForeignKeyConstraint(
            ["device_id"],
            ["registered_devices.id"],
            ondelete="CASCADE",
        ),

        sa.UniqueConstraint(
            "grant_hash",
            name="uq_profile_lock_grant_hash",
        ),
    )

    op.create_index(
        "ix_profile_lock_authorization_grants_account_id",
        "profile_lock_authorization_grants",
        ["account_id"],
    )

    op.create_index(
        "ix_profile_lock_authorization_grants_device_id",
        "profile_lock_authorization_grants",
        ["device_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_profile_lock_authorization_grants_device_id",
        table_name="profile_lock_authorization_grants",
    )

    op.drop_index(
        "ix_profile_lock_authorization_grants_account_id",
        table_name="profile_lock_authorization_grants",
    )

    op.drop_table("profile_lock_authorization_grants")
