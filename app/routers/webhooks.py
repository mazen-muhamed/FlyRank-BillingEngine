from fastapi import APIRouter, Depends, HTTPException, Request, status
from app.database import get_db
from app.services import stripe_service
from app.workers.tasks import process_stripe_event

router = APIRouter(tags=["stripe"])

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db=Depends(get_db)):
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    if not stripe_service.verify_signature(payload, signature):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Stripe signature")
    import json
    event = json.loads(payload.decode())
    process_stripe_event.delay(
        event_id=event.get("id"),
        event_type=event.get("type"),
        payload=event,  # full event — service reads payload["data"]["object"]
    )
    return {"status": "ok", "enqueued": event.get("id")}
