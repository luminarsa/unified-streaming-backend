
"""add email verification and account registration fields

Revision ID: 1ce4df52d091
Revises: 6b7f9f64defd
Create Date: 2026-11-19 01:43:41.185580
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Revision identifiers
revision: str = "1ce4df52d091"
down_revision: Union[str, Sequence[str], None] = "6b7f9f64defd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add registration fields and email verification storage.
    """

    # -------------------------------------------------
    # 1. Add account registration fields
    # -------------------------------------------------

    op.add_column(
        "accounts",
        sa.Column(
            "phone_number",
            sa.String(length=20),
            nullable=True,
        ),
    )

    # Existing accounts are considered verified.
    # After adding the column, change the default to false
    # so newly created accounts must complete verification.

    op.add_column(
        "accounts",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    op.alter_column(
        "accounts",
        "email_verified",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
        existing_nullable=False,
    )

    op.add_column(
        "accounts",
        sa.Column(
            "referral_code_used",
            sa.String(length=15),
            nullable=True,
        ),
    )

    # -------------------------------------------------
    # 2. Create email verification table
    # -------------------------------------------------

    op.create_table(
        "email_verifications",

        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "account_id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "purpose",
            sa.String(length=30),
            nullable=False,
        ),

        sa.Column(
            "code_hash",
            sa.String(length=64),
            nullable=False,
        ),

        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),

        sa.Column(
            "attempts",
            sa.Integer(),
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

        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_email_verifications_account_id_accounts",
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_email_verifications_account_id",
        "email_verifications",
        ["account_id"],
        unique=False,
    )

    # -------------------------------------------------
    # 3. Increase profile avatar URL storage length
    # -------------------------------------------------

    op.alter_column(
        "profiles",
        "avatar_key",
        existing_type=sa.String(length=120),
        type_=sa.String(length=500),
        existing_nullable=True,
    )


def downgrade() -> None:
    """
    Reverse registration and email verification changes.
    """

    # -------------------------------------------------
    # 1. Remove profile avatar length change
    # -------------------------------------------------

    op.alter_column(
        "profiles",
        "avatar_key",
        existing_type=sa.String(length=500),
        type_=sa.String(length=120),
        existing_nullable=True,
    )

    # -------------------------------------------------
    # 2. Remove email verification table
    # -------------------------------------------------

    op.drop_index(
        "ix_email_verifications_account_id",
        table_name="email_verifications",
    )

    op.drop_table("email_verifications")

    # -------------------------------------------------
    # 3. Remove account registration fields
    # -------------------------------------------------

    op.drop_column("accounts", "referral_code_used")
    op.drop_column("accounts", "email_verified")
    op.drop_column("accounts", "phone_number")
