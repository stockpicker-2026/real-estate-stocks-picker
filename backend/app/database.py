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
    """为ratings表添加新字段（SQLite不支持批量ALTER，逐列添加）"""
    new_columns = [
        ("pe_ttm", "FLOAT"),
        ("pb_mrq", "FLOAT"),
        ("roe", "FLOAT"),
        ("eps", "FLOAT"),
        ("market_value", "FLOAT"),
        ("debt_ratio", "FLOAT"),
        ("fundamental_score", "FLOAT"),
        ("main_net_inflow", "FLOAT"),
        ("retail_net_inflow", "FLOAT"),
        ("large_net_inflow", "FLOAT"),
        ("rise_day_count", "INTEGER"),
        ("vol_ratio", "FLOAT"),
        ("swing", "FLOAT"),
        ("committee", "FLOAT"),
        ("turnover_ratio", "FLOAT"),
        ("chg_5d", "FLOAT"),
        ("chg_10d", "FLOAT"),
        ("chg_20d", "FLOAT"),
        ("chg_60d", "FLOAT"),
        ("chg_120d", "FLOAT"),
        ("chg_year", "FLOAT"),
        ("model_type", "VARCHAR(20) DEFAULT 'quant_ai'"),
    ]
    for col_name, col_type in new_columns:
        try:
            await conn.execute(text(f"ALTER TABLE ratings ADD COLUMN {col_name} {col_type}"))
            logger.info(f"Added column ratings.{col_name}")
        except Exception:
            pass  # 列已存在，忽略

    # 为已有数据补填 model_type
    try:
        await conn.execute(text("UPDATE ratings SET model_type = 'quant_ai' WHERE model_type IS NULL"))
    except Exception:
        pass

    # 创建新索引（忽略已存在）
    try:
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rating_code_date_model ON ratings (code, date, model_type)"))
    except Exception:
        pass


async def _migrate_watchlists_table(conn):
    """创建 watchlists 表（如已存在则忽略）"""
    try:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS watchlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                stock_code VARCHAR(20) NOT NULL,
                stock_name VARCHAR(100) NOT NULL,
                market VARCHAR(10) NOT NULL,
                note VARCHAR(500) DEFAULT '',
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, stock_code)
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_watchlist_user_id ON watchlists (user_id)"))
        logger.info("watchlists table ready")
    except Exception:
        pass


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_ratings_table(conn)
        await _migrate_watchlists_table(conn)


async def get_db():
    async with async_session() as session:
        yield session
