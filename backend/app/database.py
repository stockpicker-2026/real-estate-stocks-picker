import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.config import DATABASE_URL, DATA_DIR

logger = logging.getLogger(__name__)

os.makedirs(DATA_DIR, exist_ok=True)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def _migrate_ratings_table(conn):
    """为ratings表添加iFinD基本面字段（SQLite不支持批量ALTER，逐列添加）"""
    new_columns = [
        ("pe_ttm", "FLOAT"),
        ("pb_mrq", "FLOAT"),
        ("roe", "FLOAT"),
        ("eps", "FLOAT"),
        ("market_value", "FLOAT"),
        ("debt_ratio", "FLOAT"),
        ("fundamental_score", "FLOAT"),
        ("main_net_inflow", "FLOAT"),
        ("rise_day_count", "INTEGER"),
    ]
    for col_name, col_type in new_columns:
        try:
            await conn.execute(text(f"ALTER TABLE ratings ADD COLUMN {col_name} {col_type}"))
            logger.info(f"Added column ratings.{col_name}")
        except Exception:
            pass  # 列已存在，忽略


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_ratings_table(conn)


async def get_db():
    async with async_session() as session:
        yield session
