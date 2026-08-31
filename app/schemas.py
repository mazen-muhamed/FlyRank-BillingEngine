import uuid
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    api_call = "api_call"
    input_token = "input_token"
    cached_input_token = "cached_input_token"
    output_token = "output_token"
    reasoning_token = "reasoning_token"


class TenantCreate(BaseModel):
    name: str
    email: str


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    plan_status: str

    model_config = ConfigDict(from_attributes=True)

class PlanCreate(BaseModel):
    name: str
    api_calls_limit: int
    api_tokens_limit: int
    price_per_month_cents: int = 0


class PlanResponse(BaseModel):
    id: uuid.UUID
    name: str
    api_calls_limit: int
    api_tokens_limit: int
    price_per_month_cents: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


#  Metering: POST /api/v1/generate 
class GenerateRequest(BaseModel):
    event_type: EventType
    quantity: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1)


class GenerateResponse(BaseModel):
    event_id: uuid.UUID
    tenant_id: uuid.UUID
    event_type: str
    quantity: int
    cost_cents: int
    within_quota: bool
    is_duplicate: bool = False


class UsageSummary(BaseModel):
    tenant_id: str
    api_calls_used: int
    api_calls_limit: int
    tokens_used: int
    tokens_limit: int
    total_cost_cents: int
    plan_status: str

class StripeCheckoutRequest(BaseModel):
    tenant_id: uuid.UUID
    plan_id: uuid.UUID


class StripeCheckoutResponse(BaseModel):
    session_id: str
    url: str

class CostBreakdown(BaseModel):
    model_config = ConfigDict(extra="allow")

    api_call: int = 0
    input_token: int = 0
    cached_input_token: int = 0
    output_token: int = 0
    reasoning_token: int = 0
    total_cents: int = 0
