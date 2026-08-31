from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas import TenantCreate, TenantResponse
from app.repositories import usage_repository as repo

router = APIRouter(prefix="/api/v1", tags=["tenants"])


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    existing = await repo.get_tenant_by_email(db, body.email)
    if existing:
        return _to_response(existing)
    free_plan = await repo.get_plan_by_name(db, "free")
    tenant = await repo.create_tenant(db, body.name, body.email,
                                    plan_id=free_plan.id if free_plan else None)
    await db.commit()
    return _to_response(tenant)


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id, db: AsyncSession = Depends(get_db)):
    tenant = await repo.get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    return _to_response(tenant)


def _to_response(t):
    return TenantResponse(id=t.id, name=t.name, email=t.email, plan_status=t.plan_status)
