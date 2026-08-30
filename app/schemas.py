from pydantic import BaseModel, Field

class GenerateRequest(BaseModel):
    prompt: str
    idempotency_key: str

class GenerateResponse(BaseModel):
    used: int
    limit: int
    cost_cents: int
    message: str

class UsageResponse(BaseModel):
    api_used: int
    api_limit: int
    tokens_used: int
    token_limit: int
    cost_cents: int
