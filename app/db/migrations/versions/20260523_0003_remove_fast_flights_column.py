"""remove fast flights watchlist column

Revision ID: 20260523_0003
Revises: 20260523_0002
Create Date: 2026-05-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260523_0003"
down_revision: str | None = "20260523_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "alter table watchlist_candidates drop column if exists fast_flights_exact_price_cad"
    )


def downgrade() -> None:
    op.execute(
        "alter table watchlist_candidates "
        "add column if not exists fast_flights_exact_price_cad integer"
    )
