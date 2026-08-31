import asyncio
from app.workers.celery_app import celery_app


@celery_app.task(name="billing.process_stripe_event", bind=True, max_retries=3)
def process_stripe_event(self, event_id: str, event_type: str, payload: dict):
    """Verify-based dedupe + plan sync, in its own worker DB session."""
    from app.database import async_session
    from app.services.stripe_service import process_stripe_event as _process

    async def _run():
        async with async_session() as db:
            return await _process(db, event_id, event_type, payload)

    try:
        return asyncio.run(_run())
    except Exception as exc:
        # Transient DB/broker failure → retry with backoff; billing is worth it.
        raise self.retry(exc=exc, countdown=5 * (self.request.retries + 1))
