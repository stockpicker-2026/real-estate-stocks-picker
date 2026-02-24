"""
房地产股票AI评级Agent - 后端服务
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func

from app.api import router
from app.config import REFRESH_HOUR, REFRESH_MINUTE, ADMIN_USERNAME, ADMIN_PASSWORD, UPLOAD_DIR
from app.database import init_db, async_session
from app.models import Rating, User
from app.auth import hash_password
from app.scheduler import init_stock_list, refresh_all_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def init_admin():
    """首次启动时创建默认管理员账户"""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.username == ADMIN_USERNAME))
        if result.scalar_one_or_none() is None:
            admin = User(
                username=ADMIN_USERNAME,
                hashed_password=hash_password(ADMIN_PASSWORD),
                display_name="管理员",
                is_admin=True,
                is_active=True,
            )
            session.add(admin)
            await session.commit()
            logger.info(f"默认管理员账户已创建: {ADMIN_USERNAME}")
        else:
            logger.info("管理员账户已存在，跳过创建")


async def check_and_refresh():
    """检查今日是否已有评级数据，没有则自动执行刷新"""
    async with async_session() as session:
        latest_date = await session.scalar(select(func.max(Rating.date)))

    today = date.today()
    if latest_date is None or latest_date < today:
        logger.info("今日尚无评级数据，启动自动刷新...")
        await refresh_all_data()
    else:
        logger.info(f"今日({today})评级数据已存在，跳过刷新")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # 启动
    await init_db()
    await init_stock_list()
    await init_admin()
    logger.info("数据库初始化完成")

    # 定时任务: 每天早上9点刷新
    scheduler.add_job(
        refresh_all_data,
        "cron",
        hour=REFRESH_HOUR,
        minute=REFRESH_MINUTE,
        id="daily_refresh",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"定时任务已启动: 每天 {REFRESH_HOUR}:{REFRESH_MINUTE:02d} 自动计算评级")

    # 启动时检查并自动刷新（后台异步执行，不阻塞启动）
    asyncio.create_task(check_and_refresh())

    yield

    # 关闭
    scheduler.shutdown()


app = FastAPI(title="房地产股票AI评级Agent", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


# 挂载前端静态文件 (生产环境)
import os
frontend_dist = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
