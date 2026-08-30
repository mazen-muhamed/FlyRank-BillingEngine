from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# native Postgres; brief says native install, not Docker
engine = create_engine("postgresql://user:pass@localhost/billing")
SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
