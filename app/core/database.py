from collections.abc import Iterator
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.core.config import get_settings

class Base(DeclarativeBase):
    pass

def database_url() -> URL:
    s = get_settings()
    return URL.create("mysql+pymysql", username=s.db_user, password=s.db_password,
                      host=s.db_host, port=s.db_port, database=s.db_name,
                      query={"charset":"utf8mb4"})

engine = create_engine(database_url(), pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
