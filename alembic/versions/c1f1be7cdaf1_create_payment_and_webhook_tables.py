
"""create payment and webhook tables

Revision ID: c1f1be7cdaf1
Revises: 7ede45840ad8
Create Date: 2026-11-10 08:01:02.484430

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c1f1be7cdaf1'
down_revision: Union[str, Sequence[str], None] = '7ede45840ad8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create payment and PayPal webhook tables."""

    # ---------------------------------------------------------
    # 1. PAYMENT METHODS
    # ---------------------------------------------------------

    op.create_table(
        'payment_methods',

        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),

        sa.Column(
            'account_id',
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),

        sa.Column(
            'provider',
            sa.String(length=50),
            nullable=False,
        ),

        sa.Column(
            'provider_customer_id',
            sa.String(length=200),
            nullable=True,
        ),

        sa.Column(
            'encrypted_payment_token',
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            'token_fingerprint',
            sa.String(length=64),
            nullable=False,
        ),

        sa.Column(
            'card_brand',
            sa.String(length=40),
            nullable=True,
        ),

        sa.Column(
            'last_four',
            sa.String(length=4),
            nullable=True,
        ),

        sa.Column(
            'expiry_month',
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            'expiry_year',
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            'status',
            sa.String(length=30),
            nullable=False,
        ),

        sa.Column(
            'is_default',
            sa.Boolean(),
            nullable=False,
        ),

        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),

        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(
            ['account_id'],
            ['accounts.id'],
            ondelete='CASCADE',
        ),

        sa.PrimaryKeyConstraint('id'),

        sa.UniqueConstraint(
            'account_id',
            'provider',
            'token_fingerprint',
            name='uq_payment_method_account_provider_fingerprint',
        ),

        sa.CheckConstraint(
            'last_four IS NULL OR length(last_four) = 4',
            name='check_payment_method_last_four',
        ),

        sa.CheckConstraint(
            'expiry_month IS NULL OR (expiry_month >= 1 AND expiry_month <= 12)',
            name='check_payment_method_expiry_month',
        ),

        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'deleted')",
            name='check_payment_method_status',
        ),
    )

    op.create_index(
        'ix_payment_methods_account_id',
        'payment_methods',
        ['account_id'],
        unique=False,
    )

    # ---------------------------------------------------------
    # 2. PAYMENT TRANSACTIONS
    # ---------------------------------------------------------

    op.create_table(
        'payment_transactions',

        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),

        sa.Column(
            'account_id',
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),

        sa.Column(
            'subscription_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),

        sa.Column(
            'payment_method_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),

        sa.Column(
            'provider',
            sa.String(length=50),
            nullable=False,
        ),

        sa.Column(
            'provider_order_id',
            sa.String(length=200),
            nullable=True,
        ),

        sa.Column(
            'provider_capture_id',
            sa.String(length=200),
            nullable=True,
        ),

        sa.Column(
            'provider_transaction_id',
            sa.String(length=200),
            nullable=True,
        ),

        sa.Column(
            'transaction_type',
            sa.String(length=30),
            nullable=False,
        ),

        sa.Column(
            'amount',
            sa.Numeric(precision=12, scale=2),
            nullable=False,
        ),

        sa.Column(
            'currency',
            sa.String(length=3),
            nullable=False,
        ),

        sa.Column(
            'status',
            sa.String(length=30),
            nullable=False,
        ),

        sa.Column(
            'billing_period_start',
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.Column(
            'billing_period_end',
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.Column(
            'failure_code',
            sa.String(length=100),
            nullable=True,
        ),

        sa.Column(
            'failure_message',
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            'webhook_event_id',
            sa.String(length=200),
            nullable=True,
        ),

        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),

        sa.Column(
            'completed_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(
            ['account_id'],
            ['accounts.id'],
            ondelete='CASCADE',
        ),

        sa.ForeignKeyConstraint(
            ['subscription_id'],
            ['subscriptions.id'],
            ondelete='SET NULL',
        ),

        sa.ForeignKeyConstraint(
            ['payment_method_id'],
            ['payment_methods.id'],
            ondelete='SET NULL',
        ),

        sa.PrimaryKeyConstraint('id'),

        sa.UniqueConstraint(
            'provider_capture_id',
            name='uq_payment_transaction_capture_id',
        ),

        sa.UniqueConstraint(
            'webhook_event_id',
            name='uq_payment_transaction_webhook_event',
        ),

        sa.CheckConstraint(
            'amount >= 0',
            name='check_payment_transaction_amount',
        ),

        sa.CheckConstraint(
            "transaction_type IN ('initial', 'renewal', 'plan_change', 'refund')",
            name='check_payment_transaction_type',
        ),

        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'cancelled', 'refunded')",
            name='check_payment_transaction_status',
        ),
    )

    op.create_index(
        'ix_payment_transactions_account_id',
        'payment_transactions',
        ['account_id'],
        unique=False,
    )

    op.create_index(
        'ix_payment_transactions_subscription_id',
        'payment_transactions',
        ['subscription_id'],
        unique=False,
    )

    # ---------------------------------------------------------
    # 3. PAYPAL WEBHOOK EVENTS
    # ---------------------------------------------------------

    op.create_table(
        'paypal_webhook_events',

        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),

        sa.Column(
            'provider_event_id',
            sa.String(length=200),
            nullable=False,
        ),

        sa.Column(
            'event_type',
            sa.String(length=150),
            nullable=False,
        ),

        sa.Column(
            'resource_type',
            sa.String(length=100),
            nullable=True,
        ),

        sa.Column(
            'resource_id',
            sa.String(length=200),
            nullable=True,
        ),

        sa.Column(
            'payload',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),

        sa.Column(
            'status',
            sa.String(length=30),
            nullable=False,
        ),

        sa.Column(
            'processing_attempts',
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            'last_error',
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            'received_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),

        sa.Column(
            'processed_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),

        sa.PrimaryKeyConstraint('id'),

        sa.UniqueConstraint(
            'provider_event_id',
            name='uq_paypal_webhook_event_provider_id',
        ),

        sa.CheckConstraint(
            "status IN ('received', 'processing', 'processed', 'failed')",
            name='check_paypal_webhook_event_status',
        ),

        sa.CheckConstraint(
            'processing_attempts >= 0',
            name='check_paypal_webhook_event_attempts',
        ),
    )

    op.create_index(
        'ix_paypal_webhook_events_event_type',
        'paypal_webhook_events',
        ['event_type'],
        unique=False,
    )


def downgrade() -> None:
    """Remove payment and PayPal webhook tables."""

    op.drop_table('paypal_webhook_events')
    op.drop_table('payment_transactions')
    op.drop_table('payment_methods')
