from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models import UsageEvent

class UsageRepository:
    # Owns the unique constraint that makes idempotency work
    def insert_event(self, db: Session, tenant_id: int, event_type: str, qty: int, key: str) -> UsageEvent:
        event = UsageEvent(tenant_id=tenant_id, event_type=event_type, quantity=qty, idempotency_key=key)
        db.add(event)
        try:
            db.commit()
            db.refresh(event)
        except IntegrityError:
            db.rollback()
            # Duplicate: return existing; handled at service layer via query-back
            raise
        return event

    def get_by_key(self, db: Session, tenant_id: int, key: str) -> UsageEvent | None:
        return db.query(UsageEvent).filter_by(tenant_id=tenant_id, idempotency_key=key).first()
