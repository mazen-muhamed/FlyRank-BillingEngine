from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas import StripeCheckoutRequest, StripeCheckoutResponse
from app.services import stripe_service

router = APIRouter(prefix="/api/v1", tags=["stripe"])


@router.post("/checkout", response_model=StripeCheckoutResponse)
async def create_checkout(body: StripeCheckoutRequest, db: AsyncSession = Depends(get_db)):
    result = await stripe_service.create_checkout_session(db, body)
    return StripeCheckoutResponse(session_id=result["session_id"], url=result["url"])
