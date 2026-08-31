import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("plans.id"), nullable=True)
    plan_status = Column(String, nullable=False, default="free")  # free | pro | canceled
    stripe_customer_id = Column(String, unique=True, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Plan(Base):
    __tablename__ = "plans"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, unique=True, nullable=False) 
    api_calls_limit = Column(Integer, nullable=False)
    api_tokens_limit = Column(Integer, nullable=False)
    price_per_month_cents = Column(Integer, nullable=False, default=0)  
    stripe_price_id = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    event_type = Column(String, nullable=False)  # api_call | input_token | cached_input_token | output_token | reasoning_token
    quantity = Column(Integer, nullable=False)   
    cost_cents = Column(Integer, nullable=False, default=0)
    recorded_at = Column(DateTime, default=datetime.utcnow)
    idempotency_key = Column(String, nullable=False)
    # (tenant_id, idempotency_key) unique → the real retry guard, DB-enforced (no race)
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_usage_idempotency"),
    )


class MonthlyRollup(Base):
    __tablename__ = "monthly_rollups"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False)
    period_year_month = Column(String, nullable=False)  
    api_calls_limit = Column(Integer, nullable=False, default=1000)  # limits snapshot at rollup create
    tokens_limit = Column(Integer, nullable=False, default=100000)
    api_calls_used = Column(Integer, nullable=False, default=0)
    tokens_used = Column(Integer, nullable=False, default=0)
    total_cost_cents = Column(Integer, nullable=False, default=0)
    
    # One rollup row per tenant per month per plan → UPSERT target
    __table_args__ = (
        UniqueConstraint("tenant_id", "plan_id", "period_year_month", name="uq_rollup_period"),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False)
    stripe_subscription_id = Column(String, unique=True, nullable=True)  # webhook dedupe anchor
    stripe_checkout_session_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")
    current_period_start = Column(DateTime, nullable=False)
    current_period_end = Column(DateTime, nullable=False)


class PaymentRecord(Base):
    __tablename__ = "payment_records"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True)
    stripe_event_id = Column(String, unique=True, nullable=False)  # idempotent webhook processing
    event_type = Column(String, nullable=False)
    stripe_data = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
