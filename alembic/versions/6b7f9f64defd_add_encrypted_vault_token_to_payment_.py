"""add encrypted vault token to payment transactions

Revision ID: 6b7f9f64defd
Revises: c1f1be7cdaf1
Create Date: 2026-11-10 08:21:07.941530

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b7f9f64defd'
down_revision: Union[str, Sequence[str], None] = 'c1f1be7cdaf1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_transactions",
        sa.Column(
            "encrypted_vault_token",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "payment_transactions",
        "encrypted_vault_token",
    )