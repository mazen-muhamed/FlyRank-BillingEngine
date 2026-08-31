from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas import UsageSummary
from app.services import cost_service

router = APIRouter(prefix="/api/v1", tags=["usage"])


@router.get("/usage/{tenant_id}", response_model=UsageSummary)
async def get_usage(tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    summary = await cost_service.get_tenant_usage_summary(db, tenant_id)
    if not summary:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    return UsageSummary(**summary)
