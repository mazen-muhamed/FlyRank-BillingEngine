"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("api_calls_limit", sa.Integer(), nullable=False),
        sa.Column("api_tokens_limit", sa.Integer(), nullable=False),
        sa.Column("price_per_month_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stripe_price_id", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("name", name="uq_plan_name"),
    )

    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id"), nullable=True),
        sa.Column("plan_status", sa.String(), nullable=False, server_default="free"),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("email", name="uq_tenant_email"),
        sa.UniqueConstraint("stripe_customer_id", name="uq_tenant_stripe_customer"),
    )

    op.create_table(
        "usage_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recorded_at", sa.DateTime(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        # The idempotency guarantee, enforced by the DB (no app-level race).
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_usage_idempotency"),
    )

    op.create_table(
        "monthly_rollups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("period_year_month", sa.String(), nullable=False),
        sa.Column("api_calls_limit", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("tokens_limit", sa.Integer(), nullable=False, server_default="100000"),
        sa.Column("api_calls_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("tenant_id", "plan_id", "period_year_month", name="uq_rollup_period"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column("stripe_checkout_session_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("current_period_start", sa.DateTime(), nullable=False),
        sa.Column("current_period_end", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("stripe_subscription_id", name="uq_subscription_stripe_id"),
    )

    op.create_table(
        "payment_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("stripe_event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("stripe_data", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        # Idempotent webhook processing: one row per Stripe event id.
        sa.UniqueConstraint("stripe_event_id", name="uq_payment_event_id"),
    )


def downgrade() -> None:
    op.drop_table("payment_records")
    op.drop_table("subscriptions")
    op.drop_table("monthly_rollups")
    op.drop_table("usage_events")
    op.drop_table("tenants")
    op.drop_table("plans")
