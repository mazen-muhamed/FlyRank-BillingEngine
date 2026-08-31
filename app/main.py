from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.billing import PRICING
from app.config import settings
from app.database import init_db, async_session
from app.seed import seed
from app.schemas import CostBreakdown
from app.routers import generate, usage, webhooks, checkout, tenants, plans

app = FastAPI(title="FlyRank Metering & Billing Engine", version="1.0.0")


# Serve the admin console at /static 
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.on_event("startup")
async def startup():
    await init_db()
    async with async_session() as db:
        await seed(db)


@app.get("/health")
async def health():
    return {"status": "ok"}


# ----- assemble the layered routers -----
app.include_router(tenants.router)
app.include_router(plans.router)
app.include_router(generate.router)
app.include_router(usage.router)
app.include_router(checkout.router)
app.include_router(webhooks.router)


@app.get("/api/v1/cost-breakdown", response_model=CostBreakdown)
async def cost_breakdown():
    return CostBreakdown(
        api_call=PRICING.get("api_call", 0),
        input_token=PRICING.get("input_token", 1),
        cached_input_token=PRICING.get("cached_input_token", 0),
        output_token=PRICING.get("output_token", 3),
        reasoning_token=PRICING.get("reasoning_token", 3),
        total_cents=0,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
