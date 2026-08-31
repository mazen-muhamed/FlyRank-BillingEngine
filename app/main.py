from fastapi import FastAPI, Depends, HTTPException, status, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta
import uuid
import uuid as _uuid

from app.database import get_db, init_db, async_session
from app.schemas import (
    PlanCreate, PlanResponse, TenantCreate, TenantResponse,
    GenerateRequest, GenerateResponse, UsageSummary, StripeCheckoutRequest,
    StripeCheckoutResponse, EventType, CostBreakdown,
)
from app.models import Tenant, Plan, UsageEvent, MonthlyRollup, Subscription, PaymentRecord
from app.billing import tokens_to_cents, get_plan_limits, compute_total_cost, record_usage, update_rollup_after_event
from app.services import (
    check_quota,
    get_tenant_usage_summary, handle_stripe_webhook,
)
from app.seed import seed

app = FastAPI(title="FlyRank Metering & Billing Engine", version="1.0.0")

@app.on_event("startup")
async def startup():
    await init_db()
    async with async_session() as db:
        await seed(db)

@app.get("/health")
async def health():
    return {"status": "ok"}

#  Tenants 
@app.post("/api/v1/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    tenant = Tenant(name=body.name, email=body.email)
    db.add(tenant)
    await db.flush()
    return TenantResponse(id=tenant.id, name=tenant.name, email=tenant.email, plan_status=tenant.plan_status)

@app.get("/api/v1/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantResponse(id=tenant.id, name=tenant.name, email=tenant.email, plan_status=tenant.plan_status)

# Plans 
@app.get("/api/v1/plans", response_model=list[PlanResponse])
async def list_plans(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Plan).where(Plan.is_active == True))
    plans = result.scalars().all()
    return [PlanResponse.from_orm(p) for p in plans]

# Core metering: POST /api/v1/generate 
@app.post("/api/v1/generate", response_model=GenerateResponse, status_code=status.HTTP_201_CREATED)
async def generate(body: GenerateRequest, db: AsyncSession = Depends(get_db)):
    # Resolve tenant — use first tenant for demo; production would get from auth
    result = await db.execute(select(Tenant).limit(1))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="No tenant found. Seed the database first.")

    # Idempotency check
    existing = await record_usage(db, tenant.id, body.event_type.value, body.quantity, body.idempotency_key)
    event, is_dup = existing

    if is_dup:
        return GenerateResponse(
            event_id=event.id,
            tenant_id=tenant.id,
            event_type=event.event_type,
            quantity=event.quantity,
            cost_cents=event.cost_cents,
            within_quota=True,
            is_duplicate=True,
        )

    # Quota check
    allowed, reason = await check_quota(db, tenant.id, body.quantity, body.event_type.value)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=reason)

    # Update rollup
    await update_rollup_after_event(db, tenant.id, tenant.plan_id or uuid.uuid4(), body.event_type.value, body.quantity)

    return GenerateResponse(
        event_id=event.id,
        tenant_id=tenant.id,
        event_type=event.event_type,
        quantity=event.quantity,
        cost_cents=event.cost_cents,
        within_quota=True,
    )

#  Usage summary 
@app.get("/api/v1/usage/{tenant_id}", response_model=UsageSummary)
async def get_usage(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    summary = await get_tenant_usage_summary(db, tenant_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return UsageSummary(**summary)

# Stripe Checkout 
@app.post("/api/v1/checkout", response_model=StripeCheckoutResponse)
async def create_checkout(body: StripeCheckoutRequest, db: AsyncSession = Depends(get_db)):
    stripe.api_key = settings.STRIPE_SECRET_KEY if hasattr(settings, 'STRIPE_SECRET_KEY') else ""

    result = await db.execute(select(Tenant).where(Tenant.id == body.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    result2 = await db.execute(select(Plan).where(Plan.id == body.plan_id))
    plan = result2.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    # Create a Stripe Checkout session
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": plan.stripe_price_id or "price_test",
                "quantity": 1,
            }],
            mode="subscription",
            success_url=f"{settings.BASE_URL}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.BASE_URL}/checkout/cancel",
            metadata={
                "tenant_id": str(tenant.id),
                "plan_id": str(plan.id),
            },
        )
    except StripeError as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")

    # Store subscription record
    sub = Subscription(
        tenant_id=tenant.id,
        plan_id=plan.id,
        stripe_checkout_session_id=checkout_session.id,
        status="active",
        current_period_start=datetime.utcnow(),
        current_period_end=datetime.utcnow() + timedelta(days=30),
    )
    db.add(sub)
    await db.flush()

    return StripeCheckoutResponse(session_id=checkout_session.id, url=checkout_session.url or "http://localhost:8000")

# Stripe Webhook
@app.post("/api/v1/webhooks/stripe")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    result = await handle_stripe_webhook(db, payload.decode(), signature)
    if "error" in result:
        raise HTTPException(status_code=result.get("status", 400), detail=result["error"])
    return result

@app.get("/api/v1/cost-breakdown", response_model=CostBreakdown)
async def cost_breakdown(db: AsyncSession = Depends(get_db)):
    # Return current pricing constants
    from app.billing import PRICING
    return CostBreakdown(
        api_call_cost_cents=PRICING.get("api_call", 0),
        input_token_cost_cents=PRICING.get("input_token", 1),
        cached_input_token_cost_cents=PRICING.get("cached_input_token", 0),
        output_token_cost_cents=PRICING.get("output_token", 3),
        reasoning_token_cost_cents=PRICING.get("reasoning_token", 3),
        total_cents=0,
    )

# --- Error handler ---
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

from fastapi.responses import JSONResponse
from app.config import settings