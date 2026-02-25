"""
定时任务调度器
每天收盘后自动刷新数据和评级
"""

import asyncio
import logging
import random
from datetime import date

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import Stock, StockPrice, Rating
from app.stock_list import REAL_ESTATE_STOCKS
from app.data_fetcher import fetch_stock_hist
from app.rating_engine import rate_stock

logger = logging.getLogger(__name__)


async def init_stock_list():
    """初始化股票列表到数据库"""
    async with async_session() as session:
        result = await session.execute(select(Stock).limit(1))
        if result.scalar():
            return  # 已初始化
        for s in REAL_ESTATE_STOCKS:
            stock = Stock(code=s["code"], name=s["name"], market=s["market"])
            session.add(stock)
        await session.commit()
        logger.info(f"初始化 {len(REAL_ESTATE_STOCKS)} 只股票")


async def refresh_all_data():
    """刷新所有股票数据和评级（核心定时任务）"""
    logger.info("开始刷新股票数据和评级...")
    async with async_session() as session:
        result = await session.execute(select(Stock).where(Stock.is_active == 1))
        stocks = result.scalars().all()

    today = date.today()
    success_count = 0

    for stock in stocks:
        try:
            df = await asyncio.to_thread(fetch_stock_hist, stock.code, stock.market, 120)
            if df is None or df.empty:
                logger.warning(f"跳过 {stock.name}({stock.code}): 无数据")
                continue

            # 保存最近价格数据
            async with async_session() as session:
                # 删除该股票旧价格数据，重新写入
                await session.execute(
                    delete(StockPrice).where(StockPrice.code == stock.code)
                )
                for _, row in df.iterrows():
                    price = StockPrice(
                        code=stock.code,
                        date=row["date"],
                        open=float(row["open"]) if row["open"] else None,
                        high=float(row["high"]) if row["high"] else None,
                        low=float(row["low"]) if row["low"] else None,
                        close=float(row["close"]) if row["close"] else None,
                        volume=float(row["volume"]) if row["volume"] else None,
                        turnover=float(row.get("turnover", 0)) if row.get("turnover") else None,
                        change_pct=float(row.get("change_pct", 0)) if row.get("change_pct") else None,
                    )
                    session.add(price)
                await session.commit()

            # 评级（量化+AI混合）
            rating_result = await rate_stock(df, stock.name, stock.code, stock.market)
            if rating_result:
                async with async_session() as session:
                    # 删除今日已有评级
                    await session.execute(
                        delete(Rating).where(
                            Rating.code == stock.code, Rating.date == today
                        )
                    )
                    rating = Rating(
                        code=stock.code,
                        name=stock.name,
                        market=stock.market,
                        date=today,
                        **rating_result,
                    )
                    session.add(rating)
                    await session.commit()
                success_count += 1
                logger.info(f"✓ {stock.name}({stock.code}) - {rating_result['rating']} ({rating_result['total_score']})")

            # 避免请求过快，随机间隔 2~4 秒
            await asyncio.sleep(random.uniform(2.0, 4.0))

        except Exception as e:
            logger.error(f"处理 {stock.name}({stock.code}) 失败: {e}")

    logger.info(f"刷新完成: {success_count}/{len(stocks)} 成功")
    return success_count
