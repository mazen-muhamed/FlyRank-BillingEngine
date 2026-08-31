import uuid
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Tenant
from app.schemas import GenerateResponse
from app.repositories import usage_repository as repo
from app.billing import get_plan_limits

_PERIOD = lambda: datetime.utcnow().strftime("%Y-%m")


async def record_usage(
    db: AsyncSession, *, tenant_id: uuid.UUID, event_type: str, quantity: int, idempotency_key: str
) -> GenerateResponse:
    """One idempotent billable action. Duplicate key → original result, no new event."""
    tenant = await repo.get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")

    # Idempotency fast-path: a retry with the same key returns the original event.
    existing = await repo.get_usage_by_key(db, tenant_id, idempotency_key, event_type)
    if existing:
        return _response(existing, tenant_id, event_type, is_dup=True)

    # Quota enforced BEFORE the action (PROBE 2 boundary honesty).
    allowed, reason = await check_quota(db, tenant_id, event_type, quantity)
    if not allowed:
        raise _quota_error(tenant, reason)

    from app.billing import tokens_to_cents
    cost = tokens_to_cents(quantity, event_type)
    event = await repo.insert_usage(db, tenant_id, event_type, quantity, cost, idempotency_key)

    await _bump_rollup(db, tenant, event_type, quantity)
    await db.commit()
    return _response(event, tenant_id, event_type, is_dup=False)


async def check_quota(db, tenant_id, event_type, requested_quantity) -> tuple[bool, str | None]:
    limits = get_plan_limits((await _plan_status(db, tenant_id)))
    limit_key = "api_calls_limit" if event_type == "api_call" else "tokens_limit"
    limit = limits[limit_key]

    current = await repo.sum_usage_this_month(db, tenant_id, event_type, _PERIOD())
    if current + requested_quantity > limit:
        return False, f"Quota exceeded: {current}/{limit} used. Request of {requested_quantity} would exceed limit."
    return True, None


def _quota_error(tenant, reason):
    # 402 → plan is lapsed/unpaid (payment required). 429 → usage quota hit (over limit).
    if getattr(tenant, "plan_status", "free") == "canceled":
        return HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "Payment required: plan is canceled.")
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, reason)


async def _plan_status(db, tenant_id) -> str:
    tenant = await repo.get_tenant_by_id(db, tenant_id)
    return tenant.plan_status if tenant else "free"


async def _bump_rollup(db, tenant, event_type, quantity):
    period = _PERIOD()
    rollup = await repo.get_rollup(db, tenant.id, period)
    if not rollup:
        limits = get_plan_limits(tenant.plan_status)
        rollup = await repo.create_rollup(
            db, tenant.id, tenant.plan_id or uuid.uuid4(), period,
            limits["api_calls_limit"], limits["tokens_limit"],
        )
    if event_type == "api_call":
        rollup.api_calls_used += quantity
    else:
        rollup.tokens_used += quantity


def _response(event, tenant_id, event_type, is_dup):
    return GenerateResponse(
        event_id=event.id,
        tenant_id=tenant_id,
        event_type=event_type,
        quantity=event.quantity,
        cost_cents=event.cost_cents or 0,
        within_quota=True,
        is_duplicate=is_dup,
    )
