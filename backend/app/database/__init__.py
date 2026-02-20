from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from backend.app.config import get_settings

settings = get_settings()

# Create SQLAlchemy engine with Neon
# Neon requires SSL, which is handled by sslmode=require in the URL
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # Verify connections before using them
    pool_size=5,         # Connection pool size
    max_overflow=10,     # Max overflow connections
    echo=settings.debug  # Log SQL queries in debug mode
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for declarative models
Base = declarative_base()


def get_db():
    """Dependency for getting database sessions in FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()