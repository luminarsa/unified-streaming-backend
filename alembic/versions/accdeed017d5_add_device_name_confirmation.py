from alembic import op
import sqlalchemy as sa


revision = "YOUR_NEW_REVISION_ID"
down_revision = "d3ffd0bec284"
branch_labels = None
depends_on = None


def upgrade():
    # Existing devices already have names, so consider
    # their names confirmed.
    op.add_column(
        "registered_devices",
        sa.Column(
            "is_name_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    # New device registrations must start unconfirmed.
    op.alter_column(
        "registered_devices",
        "is_name_confirmed",
        server_default=sa.false(),
    )


def downgrade():
    op.drop_column(
        "registered_devices",
        "is_name_confirmed",
    )