from app.db.base import Base
from app.db.session import engine
import app.models

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("Development tables created. Use Alembic migrations outside local development.")
