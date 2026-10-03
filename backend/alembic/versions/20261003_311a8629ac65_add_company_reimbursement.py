"""add company reimbursement

Adds a per-user reimbursement rule and a reimbursable flag on transactions.
Existing weekday rides (Uber / Ola / Rapido) are flagged using the default rule.

Revision ID: 311a8629ac65
Revises: 667cd0a21fec
Create Date: 2026-10-04 00:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "311a8629ac65"
down_revision: Union[str, None] = "667cd0a21fec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same defaults as app/services/reimbursement.py at the time of writing.
DEFAULT_RIDE_PATTERN = r"\m(uber|ola|rapido|ani technologies|roppen)\M"


def upgrade() -> None:
    op.create_table(
        "reimbursement_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("weekdays", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.add_column(
        "transactions", sa.Column("is_reimbursable", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column("transactions", sa.Column("reimbursable_set_by", sa.String(length=10), nullable=True))

    if op.get_bind().dialect.name == "postgresql":
        # Block Supabase's auto-generated REST API, like the other tables.
        op.execute('ALTER TABLE "reimbursement_settings" ENABLE ROW LEVEL SECURITY')
        # Apply the default rule to existing data: rides on Monday-Friday.
        op.execute(
            f"""
            UPDATE transactions
               SET is_reimbursable = true, reimbursable_set_by = 'rule'
             WHERE EXTRACT(ISODOW FROM transaction_date) BETWEEN 1 AND 5
               AND merchant_name ~* '{DEFAULT_RIDE_PATTERN}'
            """
        )


def downgrade() -> None:
    op.drop_column("transactions", "reimbursable_set_by")
    op.drop_column("transactions", "is_reimbursable")
    op.drop_table("reimbursement_settings")
