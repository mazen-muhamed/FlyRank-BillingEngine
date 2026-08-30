from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.repositories.usage_repository import UsageRepository
from app.models import UsageEvent

class MeterService:
    def record(self, db: Session, tenant_id: int, event_type: str, qty: int, key: str) -> UsageEvent:
        repo = UsageRepository()
        existing = repo.get_by_key(db, tenant_id, key)
        if existing:
            return existing

        try:
            return repo.insert_event(db, tenant_id, event_type, qty, key)
        except IntegrityError:
            existing = repo.get_by_key(db, tenant_id, key)
            if existing:
                return existing
            raise
