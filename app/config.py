from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    APP_NAME: str = "flyrank-capstone-metering-billing"
    DEBUG: bool = False
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/billing"
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_FREE_ID: str = ""
    STRIPE_PRICE_PRO_ID: str = ""  # .env uses STRIPE_PRICE_ID_PRO; pydantic aliases below
    STRIPE_PRICE_ID_PRO: str = ""  # compatibility with existing .env key
    # Celery broker/backend — single Redis instance
    REDIS_URL: str = "redis://localhost:6379/0"
    BASE_URL: str = "http://localhost:8000"
    PORT: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
