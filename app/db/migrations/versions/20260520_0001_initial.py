"""initial schema

Revision ID: 20260520_0001
Revises:
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_scans_source", "scans", ["source"])
    op.create_index("ix_scans_category", "scans", ["category"])
    op.create_index("ix_scans_status", "scans", ["status"])

    op.create_table(
        "raw_api_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scan_id", sa.Integer(), sa.ForeignKey("scans.id"), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_raw_api_results_scan_id", "raw_api_results", ["scan_id"])
    op.create_index("ix_raw_api_results_source", "raw_api_results", ["source"])
    op.create_index("ix_raw_api_results_category", "raw_api_results", ["category"])
    op.create_index("ix_raw_api_results_request_hash", "raw_api_results", ["request_hash"])
    op.create_index("ix_raw_api_results_expires_at", "raw_api_results", ["expires_at"])

    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("destination", sa.String(length=3), nullable=False),
        sa.Column("depart_date", sa.Date(), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=False),
        sa.Column("trip_length_days", sa.Integer(), nullable=False),
        sa.Column("price_cad", sa.Integer(), nullable=False),
        sa.Column("airline", sa.String(length=120), nullable=True),
        sa.Column("stops", sa.Integer(), nullable=True),
        sa.Column("total_travel_minutes", sa.Integer(), nullable=True),
        sa.Column("layover_summary", sa.Text(), nullable=True),
        sa.Column("baggage_summary", sa.Text(), nullable=True),
        sa.Column("exact_check_completed", sa.Boolean(), nullable=False),
        sa.Column("deal_score", sa.Float(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_price_history_source", "price_history", ["source"])
    op.create_index("ix_price_history_category", "price_history", ["category"])
    op.create_index("ix_price_history_depart_date", "price_history", ["depart_date"])
    op.create_index("ix_price_history_return_date", "price_history", ["return_date"])
    op.create_index("ix_price_history_checked_at", "price_history", ["checked_at"])
    op.create_index("ix_price_history_archived_at", "price_history", ["archived_at"])
    op.create_index(
        "ix_price_history_category_checked",
        "price_history",
        ["category", "checked_at"],
    )
    op.create_index(
        "ix_price_history_route_dates",
        "price_history",
        ["origin", "destination", "depart_date", "return_date"],
    )

    op.create_table(
        "active_deals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("deal_type", sa.String(length=50), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("destination", sa.String(length=3), nullable=False),
        sa.Column("depart_date", sa.Date(), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=False),
        sa.Column("trip_length_days", sa.Integer(), nullable=False),
        sa.Column("price_cad", sa.Integer(), nullable=False),
        sa.Column("airline", sa.String(length=120), nullable=True),
        sa.Column("stops", sa.Integer(), nullable=True),
        sa.Column("total_travel_minutes", sa.Integer(), nullable=True),
        sa.Column("layover_summary", sa.Text(), nullable=True),
        sa.Column("baggage_summary", sa.Text(), nullable=True),
        sa.Column("google_flights_link", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("exact_check_completed", sa.Boolean(), nullable=False),
        sa.Column("deal_score", sa.Float(), nullable=True),
        sa.Column("market_label", sa.String(length=50), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_posted_price_cad", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("category", "deal_type", name="uq_active_deals_category_deal_type"),
    )
    op.create_index("ix_active_deals_category", "active_deals", ["category"])
    op.create_index("ix_active_deals_active", "active_deals", ["active"])
    op.create_index("ix_active_deals_category_active", "active_deals", ["category", "active"])

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("post_type", sa.String(length=50), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("active_deal_id", sa.Integer(), sa.ForeignKey("active_deals.id"), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_posts_post_type", "posts", ["post_type"])
    op.create_index("ix_posts_category", "posts", ["category"])

    op.create_table(
        "provider_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("month_key", sa.String(length=7), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("successful_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "month_key", name="uq_provider_usage_source_month"),
    )

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=120), primary_key=True),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("provider_usage")
    op.drop_table("posts")
    op.drop_table("active_deals")
    op.drop_table("price_history")
    op.drop_table("raw_api_results")
    op.drop_table("scans")
