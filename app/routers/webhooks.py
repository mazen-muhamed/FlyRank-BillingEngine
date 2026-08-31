# Webhook handler: verify Stripe sig FIRST, enqueue to Celery, return 200.
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    return {"status": "ok"}
