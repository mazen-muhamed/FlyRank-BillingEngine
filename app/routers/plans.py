from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas import PlanResponse
from app.repositories import usage_repository as repo

router = APIRouter(prefix="/api/v1", tags=["plans"])


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(db: AsyncSession = Depends(get_db)):
    return await repo.list_active_plans(db)
