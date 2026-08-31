from uuid import UUID
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas import GenerateRequest, GenerateResponse
from app.services import meter_service

router = APIRouter(prefix="/api/v1", tags=["metering"])


@router.post("/generate", response_model=GenerateResponse, status_code=status.HTTP_201_CREATED)
async def generate(body: GenerateRequest, db: AsyncSession = Depends(get_db)):
    # Thin handler — all logic (idempotency, quota, rollup) lives in meter_service.
    return await meter_service.record_usage(
        db,
        tenant_id=(await _default_tenant_id(db)),
        event_type=body.event_type.value,
        quantity=body.quantity,
        idempotency_key=body.idempotency_key,
    )


async def _default_tenant_id(db: AsyncSession) -> UUID:
    tenant = await _first_tenant(db)
    if not tenant:
        from fastapi import HTTPException
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No tenant found. Seed the database first.")
    return tenant.id


async def _first_tenant(db: AsyncSession):
    from app.repositories import usage_repository as repo
    return await repo.get_first_tenant(db)
