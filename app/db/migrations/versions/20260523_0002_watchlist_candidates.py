"""add watchlist candidates

Revision ID: 20260523_0002
Revises: 20260520_0001
Create Date: 2026-05-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260523_0002"
down_revision: str | None = "20260520_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watchlist_candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("destination", sa.String(length=3), nullable=False),
        sa.Column("depart_date", sa.Date(), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=False),
        sa.Column("trip_length_days", sa.Integer(), nullable=False),
        sa.Column("calendar_price_cad", sa.Integer(), nullable=False),
        sa.Column("fli_exact_price_cad", sa.Integer(), nullable=True),
        sa.Column("lowest_exact_price_cad", sa.Integer(), nullable=True),
        sa.Column("airline", sa.String(length=120), nullable=True),
        sa.Column("stops", sa.Integer(), nullable=True),
        sa.Column("total_travel_minutes", sa.Integer(), nullable=True),
        sa.Column("layover_summary", sa.Text(), nullable=True),
        sa.Column("baggage_summary", sa.Text(), nullable=True),
        sa.Column("google_flights_link", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("exact_check_completed", sa.Boolean(), nullable=False),
        sa.Column("deal_score", sa.Float(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "category",
            "origin",
            "destination",
            "depart_date",
            "return_date",
            "trip_length_days",
            name="uq_watchlist_candidate_route_dates",
        ),
    )
    op.create_index(
        "ix_watchlist_candidates_category",
        "watchlist_candidates",
        ["category"],
    )
    op.create_index(
        "ix_watchlist_candidates_active",
        "watchlist_candidates",
        ["active"],
    )
    op.create_index(
        "ix_watchlist_candidates_category_active",
        "watchlist_candidates",
        ["category", "active"],
    )
    op.create_index(
        "ix_watchlist_candidates_dates",
        "watchlist_candidates",
        ["depart_date", "return_date"],
    )
    op.create_index(
        "ix_watchlist_candidates_last_checked_at",
        "watchlist_candidates",
        ["last_checked_at"],
    )


def downgrade() -> None:
    op.drop_table("watchlist_candidates")
