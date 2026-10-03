"""enable row level security

Supabase automatically exposes every table in the `public` schema through its
REST "Data API". Enabling Row Level Security with NO policies blocks that API
completely, so the only way to reach the data is through our FastAPI backend.

The backend connects as the table owner, which bypasses RLS, so the app itself
is unaffected. On non-Supabase PostgreSQL this is harmless.

Revision ID: ea15c0ba980c
Revises: 497dd394c188
Create Date: 2026-10-03 18:55:02.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ea15c0ba980c"
down_revision: Union[str, None] = "497dd394c188"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ["users", "api_tokens", "bank_accounts", "pending_imports", "transactions", "alembic_version"]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
