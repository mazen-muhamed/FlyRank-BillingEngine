from sqlalchemy import Column, Integer, String, DateTime, func, UniqueConstraint
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True)
    stripe_customer_id = Column(String, unique=True)
    plan_name = Column(String, nullable=False) 
    status = Column(String, nullable=False)

class Plan(Base):
    __tablename__ = "plans"
    name = Column(String, primary_key=True)  # idempotent by name
    api_limit = Column(Integer, nullable=False)
    token_limit = Column(Integer, nullable=False)

class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, nullable=False)  
    stripe_subscription_id = Column(String, unique=True)  # idempotency
    status = Column(String, nullable=False)

class UsageEvent(Base):
    __tablename__ = "usage_events"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False)  # api | token
    quantity = Column(Integer, nullable=False)  
    timestamp = Column(DateTime, default=datetime.utcnow)
    idempotency_key = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_usage_idempotency"),)

class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    stripe_event_id = Column(String, primary_key=True)  
