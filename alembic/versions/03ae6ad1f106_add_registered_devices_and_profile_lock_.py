
"""add registered devices and profile lock pin

Revision ID: 03ae6ad1f106
Revises: deef1bd1d424
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# Revision identifiers.
revision: str = "03ae6ad1f106"
down_revision: Union[str, Sequence[str], None] = "deef1bd1d424"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # -------------------------------------------------
    # 1. Add Profile Lock PIN fields to accounts
    # -------------------------------------------------

    op.add_column(
        "accounts",
        sa.Column(
            "profile_lock_pin_hash",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "accounts",
        sa.Column(
            "profile_lock_pin_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # -------------------------------------------------
    # 2. Create registered_devices table
    # -------------------------------------------------

    op.create_table(
        "registered_devices",

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
            "device_installation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),

        sa.Column(
            "device_name",
            sa.String(length=120),
            nullable=False,
        ),

        sa.Column(
            "device_type",
            sa.String(length=30),
            nullable=False,
        ),

        sa.Column(
            "locked_profile_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),

        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=True,
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

        sa.PrimaryKeyConstraint(
            "id",
            name="pk_registered_devices",
        ),

        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_registered_devices_account_id",
            ondelete="CASCADE",
        ),

        sa.ForeignKeyConstraint(
            ["locked_profile_id"],
            ["profiles.id"],
            name="fk_registered_devices_locked_profile_id",
            ondelete="SET NULL",
        ),

        sa.UniqueConstraint(
            "account_id",
            "device_installation_id",
            name="uq_registered_device_account_installation",
        ),
    )

    # -------------------------------------------------
    # 3. Create account lookup index
    # -------------------------------------------------

    op.create_index(
        "ix_registered_devices_account_id",
        "registered_devices",
        ["account_id"],
        unique=False,
    )


def downgrade() -> None:

    # Remove registered devices first because they
    # depend on accounts and profiles.

    op.drop_index(
        "ix_registered_devices_account_id",
        table_name="registered_devices",
    )

    op.drop_table("registered_devices")

    # Remove Profile Lock PIN fields.

    op.drop_column(
        "accounts",
        "profile_lock_pin_updated_at",
    )

    op.drop_column(
        "accounts",
        "profile_lock_pin_hash",
    )
