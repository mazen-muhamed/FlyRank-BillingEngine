"""Usage summary service: aggregate the month's usage into {used, limit, cost}."""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import get_plan_limits
from app.repositories import usage_repository as repo

_PERIOD = lambda: datetime.utcnow().strftime("%Y-%m")


async def get_tenant_usage_summary(db: AsyncSession, tenant_id) -> dict | None:
    tenant = await repo.get_tenant_by_id(db, tenant_id)
    if not tenant:
        return None

    plan_name = tenant.plan_status
    limits = get_plan_limits(plan_name)
    period = _PERIOD()

    api_used, tokens_used = await repo.api_and_token_totals(db, tenant_id, period)

    # Fall back to the monthly rollup when no raw events exist this period.
    if api_used == 0 and tokens_used == 0:
        rollup = await repo.get_rollup(db, tenant_id, period)
        if rollup:
            api_used, tokens_used = rollup.api_calls_used, rollup.tokens_used

    return {
        "tenant_id": str(tenant_id),
        "api_calls_used": api_used,
        "api_calls_limit": limits["api_calls_limit"],
        "tokens_used": tokens_used,
        "tokens_limit": limits["tokens_limit"],
        "total_cost_cents": 0,
        "plan_status": plan_name,
    }
