
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import QueuePool

from app.config import settings

# Database URL from settings (which loads from .env)
database_url = settings.database_url

# Check if using Neon (SSL required) or local PostgreSQL
is_neon = "neon.tech" in database_url

# Pool dimensionado para ambiente multi-worker (ex.: 4 workers x 10 max = 40 conexões < max_connections=100)
_pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
_max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "5"))

# SSL and connection arguments for PostgreSQL - aggressive keepalive for Neon
connect_args = (
    {
        "sslmode": "require" if is_neon else "prefer",
        "channel_binding": "require" if is_neon else "prefer",
        "connect_timeout": 30,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
        "application_name": "vende360",
        "tcp_user_timeout": 30000,
    }
    if database_url.startswith("postgresql")
    else {}
)

# Engine configuration with robust connection pooling and SSL handling
engine = create_engine(
    database_url,
    poolclass=QueuePool,
    pool_pre_ping=True,           # CRITICAL: validates connections before use
    pool_recycle=180,             # Recycle connections every 3 minutes (Neon closes idle at 5min)
    pool_size=_pool_size,         # Base pool size per worker
    max_overflow=_max_overflow,   # Additional overflow connections per worker
    pool_timeout=30,              # Timeout for getting connection from pool
    connect_args=connect_args,    # SSL and keepalive settings
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()