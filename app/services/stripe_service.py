import uuid
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.repositories import usage_repository as repo


def verify_signature(payload: bytes, signature: str) -> bool:
    """Cryptographically prove the event really came from Stripe. Forged → False."""
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        stripe.Webhook.construct_event(
            payload=payload,
            sig_header=signature,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
        return True
    except Exception:
        return False


async def create_checkout_session(db: AsyncSession, body) -> dict:
    """Create a Stripe Checkout session and record a Subscription stub."""
    import stripe

    tenant = await repo.get_tenant_by_id(db, body.tenant_id)
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    plan = await repo.get_plan_by_id(db, body.plan_id)
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": plan.stripe_price_id or "price_test", "quantity": 1}],
            mode="subscription",
            success_url=f"{settings.BASE_URL}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.BASE_URL}/checkout/cancel",
            metadata={"tenant_id": str(tenant.id), "plan_id": str(plan.id)},
        )
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Stripe error: {str(e)}")

    from app.models import Subscription
    from datetime import datetime, timedelta

    sub = Subscription(
        tenant_id=tenant.id,
        plan_id=plan.id,
        stripe_checkout_session_id=session.id,
        status="active",
        current_period_start=datetime.utcnow(),
        current_period_end=datetime.utcnow() + timedelta(days=30),
    )
    db.add(sub)
    await db.commit()

    return {"session_id": session.id, "url": session.url or settings.BASE_URL}


async def process_stripe_event(
    db: AsyncSession, event_id: str, event_type: str, payload: dict
) -> dict:
    """Worker-side: dedupe by Stripe event id, then sync tenant plan/status.

    Called by Celery, NOT by the webhook router. Replay of an already-processed
    event is a no-op (the UNIQUE(stripe_event_id) guard below is the real check)."""
    data = payload.get("data", {}).get("object", {})

    # Dedup: already handled this Stripe event id → skip (idempotent webhook)
    if await repo.get_payment_by_event(db, event_id):
        return {"status": "already_processed", "event_id": event_id}

    if event_type == "checkout.session.completed":
        result = await _activate_pro(db, event_id, event_type, data)
        await db.commit()
        return result

    if event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        result = await _sync_subscription(db, event_id, event_type, data)
        await db.commit()
        return result

    # unhandled event types are recorded but not acted on
    await repo.insert_payment(db, None, event_id, event_type, data)
    await db.commit()
    return {"status": "unhandled", "event_type": event_type}


async def _activate_pro(db, event_id, event_type, session) -> dict:
    tenant_id_str = session.get("metadata", {}).get("tenant_id")
    if not tenant_id_str:
        return {"error": "Missing tenant_id in metadata", "status": 400}
    tenant = await repo.get_tenant_by_id(db, uuid.UUID(tenant_id_str))
    pro_plan = await repo.get_plan_by_name(db, "pro")
    if tenant and pro_plan:
        tenant.plan_id = pro_plan.id
        tenant.plan_status = "pro"
        if session.get("subscription"):
            tenant.stripe_subscription_id = session["subscription"]
    await repo.insert_payment(
        db, tenant.id if tenant else None, event_id, event_type, session
    )
    return {"status": "subscription_updated", "tenant_id": tenant_id_str}


async def _sync_subscription(db, event_id, event_type, sub_obj) -> dict:
    sub = await repo.get_subscription_by_id(db, sub_obj.get("id"))
    if sub:
        sub.status = "canceled" if event_type.endswith("deleted") else sub_obj.get("status", sub.status)
    await repo.insert_payment(db, None, event_id, event_type, sub_obj)
    return {"status": "subscription_synced", "event_id": event_id}
