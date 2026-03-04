"""
API路由 - 包含评级、认证、点评、报告模块
"""

import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select, func, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    hash_password, verify_password, create_token,
    get_current_user, require_user, require_admin,
)
from app.config import UPLOAD_DIR
from app.database import get_db
from app.models import Stock, Rating, StockPrice, User, Commentary, Report, Watchlist
from app.news_fetcher import fetch_filtered_news, fetch_stock_news
from app.ifind_client import fetch_recent_announcements, fetch_reports
from app.schemas import (
    StockOut, RatingOut, PriceOut, DashboardStats, RatingHistoryOut,
    LoginRequest, RegisterRequest, TokenResponse, UserOut,
    CommentaryCreate, CommentaryUpdate, CommentaryOut,
    ReportOut,
    WatchlistAdd, WatchlistOut, WatchlistAnalysisItem,
)

router = APIRouter(prefix="/api")

# 确保上传目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ========== 认证接口 ==========

@router.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    token = create_token(user.id, user.username, user.is_admin)
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@router.get("/auth/me", response_model=UserOut)
async def get_me(user: User = Depends(require_user)):
    """获取当前用户信息"""
    return UserOut.model_validate(user)


# ========== 用户管理接口（管理员） ==========

MAX_USERS = 100


@router.get("/users", response_model=list[UserOut])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取用户列表（管理员）"""
    result = await db.execute(select(User).order_by(User.id))
    return result.scalars().all()


@router.post("/users", response_model=UserOut)
async def create_user(
    req: RegisterRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建用户（管理员）"""
    total = await db.scalar(select(func.count(User.id)))
    if total and total >= MAX_USERS:
        raise HTTPException(status_code=400, detail=f"用户数量已达上限({MAX_USERS})")
    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = User(
        username=req.username,
        hashed_password=hash_password(req.password),
        display_name=req.display_name or req.username,
        is_admin=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{uid}")
async def delete_user(
    uid: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除用户（管理员，不能删除自己）"""
    if uid == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    await db.execute(delete(User).where(User.id == uid))
    await db.commit()
    return {"ok": True}


# ========== 仪表盘和评级接口（保持原有） ==========

@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard(
    model_type: str = Query("quant_ai"),
    db: AsyncSession = Depends(get_db),
):
    """仪表盘统计数据"""
    total = await db.scalar(select(func.count(Stock.id)).where(Stock.is_active == 1))
    latest_date = await db.scalar(
        select(func.max(Rating.date)).where(Rating.model_type == model_type)
    )
    if not latest_date:
        return DashboardStats(
            total_stocks=total or 0, rated_today=0, avg_score=0,
            market_distribution={}, rating_distribution={}
        )
    rated_q = select(Rating).where(Rating.date == latest_date, Rating.model_type == model_type)
    result = await db.execute(rated_q)
    ratings = result.scalars().all()
    rated_count = len(ratings)
    avg_score = round(sum(r.total_score for r in ratings) / max(rated_count, 1), 2)
    market_dist = {}
    rating_dist = {}
    ai_success = 0
    quant_only = 0
    latest_time = None
    for r in ratings:
        market_dist[r.market] = market_dist.get(r.market, 0) + 1
        rating_dist[r.rating] = rating_dist.get(r.rating, 0) + 1
        if r.ai_score and r.ai_score > 0:
            ai_success += 1
        else:
            quant_only += 1
        if r.created_at and (latest_time is None or r.created_at > latest_time):
            latest_time = r.created_at
    # 将时间转为北京时间显示（兼容 SQLite UTC 存储和系统时区已设为 Asia/Shanghai 两种情况）
    if latest_time:
        # 如果 latest_time 是 naive datetime，假定为系统本地时间（Docker 已设 TZ=Asia/Shanghai）
        refresh_time_str = latest_time.strftime("%Y-%m-%d %H:%M")
    else:
        refresh_time_str = None
    return DashboardStats(
        total_stocks=total or 0,
        rated_today=rated_count,
        avg_score=avg_score,
        market_distribution=market_dist,
        rating_distribution=rating_dist,
        ai_success_count=ai_success,
        quant_only_count=quant_only,
        refresh_time=refresh_time_str,
    )


@router.get("/news")
async def get_news(
    code: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    limit: int = Query(5, ge=1, le=20),
):
    """获取房地产行业新闻+公告资讯（AI筛选）
    limit: 返回条数（默认5，可扩展到10）
    """
    import asyncio

    # 行业新闻：经过 AI 筛选的 top N
    industry_news = await fetch_filtered_news(limit)

    # 个股新闻
    stock_news = []
    if code and name:
        stock_news = await asyncio.to_thread(fetch_stock_news, code, name, limit)

    # 个股公告（来自iFinD）
    announcements = []
    if code:
        try:
            market = "A"
            # 从数据库查询股票的市场类型
            # 简单判断：5位数字开头为港股
            if code.startswith("0") and len(code) == 5:
                market = "HK"
            elif not code[0].isdigit():
                market = "US"
            raw = await asyncio.to_thread(
                fetch_recent_announcements, code, market, 60
            )
            if raw:
                for line in raw.split("\n"):
                    line = line.strip()
                    if line.startswith("["):
                        # 格式: [2026-02-20] 标题
                        parts = line.split("]", 1)
                        if len(parts) == 2:
                            date_str = parts[0].lstrip("[").strip()
                            title = parts[1].strip()
                            announcements.append({
                                "title": title,
                                "source": "iFinD公告",
                                "time": date_str,
                                "url": "",
                                "type": "announcement",
                            })
        except Exception:
            pass

    return {
        "industry_news": industry_news[:limit],
        "stock_news": stock_news[:limit],
        "announcements": announcements[:limit],
    }


@router.get("/announcements/{code}")
async def get_stock_announcements(
    code: str,
    days: int = Query(90, ge=1, le=365),
    limit: int = Query(10, ge=1, le=30),
):
    """获取单只股票的近期公告与财报（来自iFinD）"""
    import asyncio

    # 判断市场
    market = "A"
    if code.startswith("0") and len(code) == 5:
        market = "HK"
    elif not code[0].isdigit():
        market = "US"

    # 并发获取：全部公告 + 财报类关键词公告
    all_reports, financial_reports = await asyncio.gather(
        asyncio.to_thread(fetch_reports, [code], market, days),
        asyncio.to_thread(fetch_reports, [code], market, min(days, 365), "903", "年度报告,半年度报告,季度报告,业绩预告,业绩快报"),
    )

    # 财报标题集合（用于标记）
    fin_titles = set()
    if financial_reports:
        for r in financial_reports:
            fin_titles.add(r.get("report_title", ""))

    # 关键公告关键词（高亮重点）
    KEY_WORDS = ["年度报告", "半年度报告", "季度报告", "业绩预告", "业绩快报",
                 "利润分配", "分红", "增持", "减持", "回购", "股权激励",
                 "重大合同", "中标", "收购", "出售", "关联交易", "担保",
                 "评级", "信用", "债券"]

    items = []
    if all_reports:
        for r in all_reports:
            title = r.get("report_title", "")
            if not title:
                continue
            is_financial = title in fin_titles or any(kw in title for kw in ["年度报告", "半年度报告", "季度报告", "业绩预告", "业绩快报"])
            is_key = is_financial or any(kw in title for kw in KEY_WORDS)
            items.append({
                "title": title,
                "date": r.get("report_date", ""),
                "pdf_url": r.get("pdf_url", ""),
                "is_financial": is_financial,
                "is_key": is_key,
            })

    # 重点公告排前面，同等级别按日期倒序
    items.sort(key=lambda x: (not x["is_financial"], not x["is_key"], x["date"]), reverse=False)
    # 修正排序：先财报、再重点、再普通，每组内按日期倒序
    items.sort(key=lambda x: (0 if x["is_financial"] else (1 if x["is_key"] else 2), x["date"]), reverse=False)
    items.sort(key=lambda x: (0 if x["is_financial"] else (1 if x["is_key"] else 2)))
    # 每个类别内按日期倒序
    from itertools import groupby
    sorted_items = []
    for _, group in groupby(items, key=lambda x: (0 if x["is_financial"] else (1 if x["is_key"] else 2))):
        g = sorted(list(group), key=lambda x: x["date"], reverse=True)
        sorted_items.extend(g)

    return sorted_items[:limit]


@router.get("/stocks", response_model=list[StockOut])
async def get_stocks(
    market: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """股票列表"""
    q = select(Stock).where(Stock.is_active == 1)
    if market:
        q = q.where(Stock.market == market)
    q = q.order_by(Stock.market, Stock.code)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/ratings/latest", response_model=list[RatingOut])
async def get_latest_ratings(
    market: Optional[str] = Query(None),
    rating: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("total_score"),
    sort_dir: Optional[str] = Query("desc"),
    model_type: str = Query("quant_ai"),
    db: AsyncSession = Depends(get_db),
):
    """获取最新一期评级"""
    latest_date = await db.scalar(
        select(func.max(Rating.date)).where(Rating.model_type == model_type)
    )
    if not latest_date:
        return []
    q = select(Rating).where(Rating.date == latest_date, Rating.model_type == model_type)
    if market:
        q = q.where(Rating.market == market)
    if rating:
        q = q.where(Rating.rating == rating)
    allowed_sort = {"total_score", "trend_score", "momentum_score",
                    "volatility_score", "volume_score", "value_score", "ai_score", "name", "code"}
    if sort_by not in allowed_sort:
        sort_by = "total_score"
    sort_col = getattr(Rating, sort_by, Rating.total_score)
    if sort_dir == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/ratings/history/{code}", response_model=list[RatingOut])
async def get_rating_history(
    code: str,
    days: int = Query(30, ge=1, le=365),
    model_type: str = Query("quant_ai"),
    db: AsyncSession = Depends(get_db),
):
    """获取某只股票的历史评级"""
    since = date.today() - timedelta(days=days)
    q = (
        select(Rating)
        .where(Rating.code == code, Rating.date >= since, Rating.model_type == model_type)
        .order_by(desc(Rating.date))
    )
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/ratings/date/{target_date}", response_model=list[RatingOut])
async def get_ratings_by_date(
    target_date: date,
    market: Optional[str] = Query(None),
    model_type: str = Query("quant_ai"),
    db: AsyncSession = Depends(get_db),
):
    """获取指定日期的评级"""
    q = select(Rating).where(Rating.date == target_date, Rating.model_type == model_type)
    if market:
        q = q.where(Rating.market == market)
    q = q.order_by(desc(Rating.total_score))
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/ratings/dates", response_model=list[date])
async def get_available_dates(
    model_type: str = Query("quant_ai"),
    db: AsyncSession = Depends(get_db),
):
    """获取所有有评级数据的日期"""
    q = (
        select(Rating.date)
        .where(Rating.model_type == model_type)
        .distinct()
        .order_by(desc(Rating.date))
        .limit(90)
    )
    result = await db.execute(q)
    return [row[0] for row in result.all()]


@router.get("/prices/{code}", response_model=list[PriceOut])
async def get_prices(
    code: str,
    days: int = Query(60, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """获取股票价格数据"""
    since = date.today() - timedelta(days=days)
    q = (
        select(StockPrice)
        .where(StockPrice.code == code, StockPrice.date >= since)
        .order_by(StockPrice.date)
    )
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/rating-trend/{code}", response_model=list[RatingHistoryOut])
async def get_rating_trend(
    code: str,
    days: int = Query(30, ge=1, le=365),
    model_type: str = Query("quant_ai"),
    db: AsyncSession = Depends(get_db),
):
    """获取评分趋势"""
    since = date.today() - timedelta(days=days)
    q = (
        select(Rating.date, Rating.total_score, Rating.rating)
        .where(Rating.code == code, Rating.date >= since, Rating.model_type == model_type)
        .order_by(Rating.date)
    )
    result = await db.execute(q)
    return [
        RatingHistoryOut(date=row[0], total_score=row[1], rating=row[2])
        for row in result.all()
    ]


# ========== 市场点评接口 ==========

@router.get("/commentaries", response_model=list[CommentaryOut])
async def list_commentaries(
    category: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取点评列表（公开）"""
    q = select(Commentary).where(Commentary.is_published == True)
    if category:
        q = q.where(Commentary.category == category)
    q = q.order_by(desc(Commentary.publish_date), desc(Commentary.id)).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/commentaries/{cid}", response_model=CommentaryOut)
async def get_commentary(cid: int, db: AsyncSession = Depends(get_db)):
    """获取单条点评"""
    result = await db.execute(select(Commentary).where(Commentary.id == cid))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="点评不存在")
    return item


@router.post("/commentaries", response_model=CommentaryOut)
async def create_commentary(
    req: CommentaryCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建点评（管理员）"""
    item = Commentary(
        title=req.title,
        content=req.content,
        category=req.category,
        stock_codes=req.stock_codes or "",
        author=admin.display_name or admin.username,
        publish_date=req.publish_date or date.today(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.put("/commentaries/{cid}", response_model=CommentaryOut)
async def update_commentary(
    cid: int,
    req: CommentaryUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新点评（管理员）"""
    result = await db.execute(select(Commentary).where(Commentary.id == cid))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="点评不存在")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/commentaries/{cid}")
async def delete_commentary(
    cid: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除点评（管理员）"""
    await db.execute(delete(Commentary).where(Commentary.id == cid))
    await db.commit()
    return {"ok": True}


# ========== 研究报告接口 ==========

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


@router.get("/reports", response_model=list[ReportOut])
async def list_reports(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取报告列表（公开）"""
    q = (
        select(Report)
        .where(Report.is_published == True)
        .order_by(desc(Report.publish_date), desc(Report.id))
        .limit(limit)
    )
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/reports", response_model=ReportOut)
async def upload_report(
    title: str = Form(...),
    summary: str = Form(""),
    institution: str = Form(""),
    publish_date: Optional[str] = Form(None),
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """上传研究报告（管理员）"""
    # 验证文件类型
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型，允许: {', '.join(ALLOWED_EXTENSIONS)}")

    # 读取文件
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小不能超过50MB")

    # 生成唯一文件名
    stored_name = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, stored_name)
    async with aiofiles.open(filepath, "wb") as f:
        await f.write(content)

    p_date = date.today()
    if publish_date:
        try:
            p_date = date.fromisoformat(publish_date)
        except ValueError:
            pass

    report = Report(
        title=title,
        summary=summary,
        institution=institution,
        filename=stored_name,
        original_name=file.filename or "unknown",
        file_size=len(content),
        author=admin.display_name or admin.username,
        publish_date=p_date,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


@router.get("/reports/{rid}/download")
async def download_report(rid: int, db: AsyncSession = Depends(get_db)):
    """下载报告文件"""
    result = await db.execute(select(Report).where(Report.id == rid))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    filepath = os.path.join(UPLOAD_DIR, report.filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")
    from urllib.parse import quote
    encoded_name = quote(report.original_name, safe='')
    return FileResponse(
        filepath,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        },
    )


@router.get("/reports/{rid}/preview")
async def preview_report(rid: int, db: AsyncSession = Depends(get_db)):
    """在线预览报告文件（PDF 以 inline 方式返回）"""
    result = await db.execute(select(Report).where(Report.id == rid))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    ext = os.path.splitext(report.filename)[1].lower()
    if ext != ".pdf":
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件在线预览")
    filepath = os.path.join(UPLOAD_DIR, report.filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")
    from urllib.parse import quote
    encoded_name = quote(report.original_name, safe='')
    return FileResponse(
        filepath,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_name}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/reports/{rid}")
async def delete_report(
    rid: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除报告（管理员）"""
    result = await db.execute(select(Report).where(Report.id == rid))
    report = result.scalar_one_or_none()
    if report:
        filepath = os.path.join(UPLOAD_DIR, report.filename)
        if os.path.exists(filepath):
            os.remove(filepath)
        await db.execute(delete(Report).where(Report.id == rid))
        await db.commit()
    return {"ok": True}


# ========== 自选股票池接口 ==========

MAX_WATCHLIST = 10


@router.get("/watchlist", response_model=list[WatchlistOut])
async def get_watchlist(
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户自选股列表"""
    q = select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.added_at)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/watchlist", response_model=WatchlistOut)
async def add_to_watchlist(
    req: WatchlistAdd,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """添加股票到自选（最多10只）"""
    # 检查数量限制
    count = await db.scalar(
        select(func.count(Watchlist.id)).where(Watchlist.user_id == user.id)
    )
    if count and count >= MAX_WATCHLIST:
        raise HTTPException(status_code=400, detail=f"自选股数量已达上限({MAX_WATCHLIST}只)")

    # 检查是否已在自选中
    existing = await db.execute(
        select(Watchlist).where(
            Watchlist.user_id == user.id,
            Watchlist.stock_code == req.stock_code,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该股票已在自选中")

    # 验证股票是否在系统中
    stock_result = await db.execute(
        select(Stock).where(Stock.code == req.stock_code, Stock.is_active == 1)
    )
    stock = stock_result.scalar_one_or_none()
    if not stock:
        raise HTTPException(status_code=400, detail="无效的股票代码")

    item = Watchlist(
        user_id=user.id,
        stock_code=stock.code,
        stock_name=stock.name,
        market=stock.market,
        note=req.note or "",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.put("/watchlist/{stock_code}")
async def update_watchlist_note(
    stock_code: str,
    req: WatchlistAdd,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """更新自选股备注"""
    result = await db.execute(
        select(Watchlist).where(
            Watchlist.user_id == user.id,
            Watchlist.stock_code == stock_code,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="自选股不存在")
    item.note = req.note or ""
    await db.commit()
    return {"ok": True}


@router.delete("/watchlist/{stock_code}")
async def remove_from_watchlist(
    stock_code: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """从自选中移除股票"""
    await db.execute(
        delete(Watchlist).where(
            Watchlist.user_id == user.id,
            Watchlist.stock_code == stock_code,
        )
    )
    await db.commit()
    return {"ok": True}


@router.get("/watchlist/analysis", response_model=list[WatchlistAnalysisItem])
async def get_watchlist_analysis(
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """获取自选股AI操作建议分析

    基于最新评级数据 + 近期趋势，由三模型联合生成操作建议。
    """
    import asyncio
    from app.llm_client import chat_deepseek, chat_glm, chat_kimi
    from app.config import DEEPSEEK_ENABLED, GLM_ENABLED, KIMI_ENABLED

    # 获取用户自选股
    wl_result = await db.execute(
        select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.added_at)
    )
    watchlist = wl_result.scalars().all()
    if not watchlist:
        return []

    codes = [w.stock_code for w in watchlist]

    # 批量获取最新评级（两个模型）
    latest_ratings = {}
    prev_ratings = {}
    for model_type in ("quant_ai", "soochow"):
        latest_date = await db.scalar(
            select(func.max(Rating.date)).where(Rating.model_type == model_type)
        )
        if latest_date:
            result = await db.execute(
                select(Rating).where(
                    Rating.date == latest_date,
                    Rating.model_type == model_type,
                    Rating.code.in_(codes),
                )
            )
            for r in result.scalars().all():
                key = f"{r.code}_{model_type}"
                latest_ratings[key] = r

            # 获取前一日评级（计算变化）
            prev_date = await db.scalar(
                select(func.max(Rating.date)).where(
                    Rating.model_type == model_type,
                    Rating.date < latest_date,
                )
            )
            if prev_date:
                result = await db.execute(
                    select(Rating).where(
                        Rating.date == prev_date,
                        Rating.model_type == model_type,
                        Rating.code.in_(codes),
                    )
                )
                for r in result.scalars().all():
                    key = f"{r.code}_{model_type}"
                    prev_ratings[key] = r

    # 构建每只股票的摘要，用于AI分析
    stock_summaries = []
    items_base = []
    for w in watchlist:
        qa_key = f"{w.stock_code}_quant_ai"
        sw_key = f"{w.stock_code}_soochow"
        qa = latest_ratings.get(qa_key)
        sw = latest_ratings.get(sw_key)
        best = qa or sw
        prev_qa = prev_ratings.get(qa_key)

        score = best.total_score if best else None
        rating = best.rating if best else None
        prev_score = prev_qa.total_score if prev_qa else None
        score_change = round(score - prev_score, 1) if score is not None and prev_score is not None else None

        items_base.append({
            "stock_code": w.stock_code,
            "stock_name": w.stock_name,
            "market": w.market,
            "latest_rating": rating,
            "latest_score": score,
            "score_change": score_change,
        })

        # 为AI prompt准备
        summary = f"{w.stock_name}({w.stock_code}, {w.market}股)"
        if best:
            summary += f"：综合评分{best.total_score}分，评级「{best.rating}」"
            if best.reason:
                reason_short = best.reason[:200]
                summary += f"，分析：{reason_short}"
        if score_change is not None:
            summary += f"，较前日变化{score_change:+.1f}分"
        stock_summaries.append(summary)

    # 调用AI生成操作建议
    if not stock_summaries:
        return [WatchlistAnalysisItem(**item, suggestion="暂无数据", reason="暂无评级数据") for item in items_base]

    prompt = f"""你是一位专业的房地产行业股票投资顾问。以下是用户自选股票池中{len(stock_summaries)}只股票的最新评级数据：

{"；".join(stock_summaries)}

请对每只股票给出简明的操作建议。要求：
1. 针对每只股票给出明确的操作建议：「买入」「加仓」「持有」「减仓」「观望」「回避」之一
2. 给出1-2句理由（不超过80字）
3. 综合考虑评分趋势变化、当前评级、市场环境

请严格按以下JSON数组格式返回，不要附加其他文字：
[{{"code":"股票代码","suggestion":"操作建议","reason":"理由"}}]"""

    system = "你是房地产行业资深投资顾问，擅长根据量化评级和基本面数据给出操作建议。请直接返回JSON，不要有其他文字。"

    tasks = []
    task_labels = []
    if DEEPSEEK_ENABLED:
        tasks.append(chat_deepseek(prompt, system=system, temperature=0.3))
        task_labels.append("DeepSeek")
    if GLM_ENABLED:
        tasks.append(chat_glm(prompt, system=system, temperature=0.3))
        task_labels.append("GLM-5")
    if KIMI_ENABLED:
        tasks.append(chat_kimi(prompt, system=system))
        task_labels.append("Kimi")

    suggestions_map = {}
    if tasks:
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        for resp, label in zip(raw_results, task_labels):
            if isinstance(resp, Exception) or not resp:
                continue
            try:
                # 提取JSON部分
                import re
                json_match = re.search(r'\[.*\]', resp, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    for item in parsed:
                        code = item.get("code", "")
                        if code and code not in suggestions_map:
                            suggestions_map[code] = {
                                "suggestion": item.get("suggestion", "观望"),
                                "reason": item.get("reason", ""),
                                "source": label,
                            }
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"解析{label}自选股建议失败: {e}")

    # 组装结果
    result = []
    for item in items_base:
        sug = suggestions_map.get(item["stock_code"], {})
        result.append(WatchlistAnalysisItem(
            **item,
            suggestion=sug.get("suggestion", "暂无建议"),
            reason=sug.get("reason", "等待AI分析"),
        ))
    return result


# ========== 公开分享页面（无需登录） ==========

def _share_html(title: str, description: str, content_html: str, meta_extra: str = "", request: Request = None) -> str:
    """生成分享页面 HTML（含 Open Graph meta 标签供微信抓取）"""
    base_url = ""
    if request:
        base_url = f"{request.url.scheme}://{request.headers.get('host', '')}"
    safe_title = title.replace('"', '&quot;').replace('<', '&lt;')
    safe_desc = description[:150].replace('"', '&quot;').replace('<', '&lt;').replace('\n', ' ')
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>{safe_title} - AI Haoxing@东吴地产</title>
<meta property="og:title" content="{safe_title}" />
<meta property="og:description" content="{safe_desc}" />
<meta property="og:type" content="article" />
<meta property="og:site_name" content="AI Haoxing@东吴地产" />
<meta name="description" content="{safe_desc}" />
<meta name="twitter:card" content="summary" />
<meta name="twitter:title" content="{safe_title}" />
<meta name="twitter:description" content="{safe_desc}" />
{meta_extra}
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;background:#f5f5f5;color:#1a1a1a;line-height:1.6}}
.share-page{{max-width:680px;margin:0 auto;padding:16px}}
.share-header{{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:24px 20px;border-radius:12px 12px 0 0}}
.share-header h1{{font-size:20px;font-weight:600;margin-bottom:8px}}
.share-meta{{font-size:13px;opacity:0.85;display:flex;flex-wrap:wrap;gap:12px}}
.share-meta span{{display:inline-flex;align-items:center;gap:4px}}
.share-body{{background:#fff;padding:24px 20px;border-radius:0 0 12px 12px;box-shadow:0 2px 12px rgba(0,0,0,0.08)}}
.share-body p,.share-body div{{font-size:15px;line-height:1.8;color:#333;white-space:normal;word-break:break-word}}
.share-tag{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:500;margin-right:8px}}
.tag-industry{{background:rgba(255,255,255,0.2);color:#fff}}
.tag-stock{{background:rgba(255,255,255,0.2);color:#fff}}
.tag-report{{background:rgba(255,255,255,0.2);color:#fff}}
.share-stocks{{margin-top:16px;padding-top:12px;border-top:1px solid #eee;font-size:13px;color:#666}}
.share-footer{{text-align:center;padding:20px;color:#999;font-size:12px}}
.share-footer a{{color:#667eea;text-decoration:none}}
.share-cta{{display:block;width:100%;max-width:320px;margin:20px auto 0;padding:12px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;border:none;border-radius:8px;font-size:15px;font-weight:500;cursor:pointer;text-align:center;text-decoration:none}}
.share-cta:active{{opacity:0.85}}
.dl-btn{{display:inline-block;padding:10px 32px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:500;cursor:pointer;text-decoration:none;margin-top:12px}}
.dl-btn:active{{opacity:0.85}}
</style>
</head>
<body>
<div class="share-page">
{content_html}
<div class="share-footer">
<p>来自 <strong>AI Haoxing@东吴地产</strong></p>
<p style="margin-top:4px">AI评级仅供参考，不构成投资建议</p>
{f'<a href="{base_url}" class="share-cta">打开完整系统 →</a>' if base_url else ''}
</div>
</div>
</body>
</html>"""


@router.get("/share/commentary/{cid}", response_class=HTMLResponse)
async def share_commentary(cid: int, request: Request, db: AsyncSession = Depends(get_db)):
    """市场点评公开分享页面（无需登录）"""
    result = await db.execute(select(Commentary).where(Commentary.id == cid, Commentary.is_published == True))
    item = result.scalar_one_or_none()
    if not item:
        return HTMLResponse("<h1>内容不存在或已下架</h1>", status_code=404)

    tag_cls = "tag-industry" if item.category == "industry" else "tag-stock"
    tag_label = "行业点评" if item.category == "industry" else "个股点评"

    stocks_html = ""
    if item.stock_codes:
        stocks_html = f'<div class="share-stocks">关联股票：{item.stock_codes}</div>'

    content_html = f"""
<div class="share-header">
<h1>{item.title}</h1>
<div class="share-meta">
<span class="share-tag {tag_cls}">{tag_label}</span>
<span>{item.author}</span>
<span>{item.publish_date}</span>
</div>
</div>
<div class="share-body">
<div>{'</div><div style="margin-bottom:12px">'.join(p for p in item.content.split(chr(10)) if p.strip())}</div>
{stocks_html}
</div>"""

    return _share_html(
        title=item.title,
        description=item.content[:150],
        content_html=content_html,
        request=request,
    )


@router.get("/share/report/{rid}", response_class=HTMLResponse)
async def share_report(rid: int, request: Request, db: AsyncSession = Depends(get_db)):
    """研究报告公开分享页面（无需登录）"""
    result = await db.execute(select(Report).where(Report.id == rid, Report.is_published == True))
    report = result.scalar_one_or_none()
    if not report:
        return HTMLResponse("<h1>内容不存在或已下架</h1>", status_code=404)

    import html as html_mod
    safe_title = html_mod.escape(report.title)
    safe_institution = html_mod.escape(report.institution or "")
    safe_author = html_mod.escape(report.author or "")
    safe_summary = html_mod.escape(report.summary or "")
    safe_original_name = html_mod.escape(report.original_name or "")

    file_size_str = f"{report.file_size / (1024*1024):.1f} MB" if report.file_size > 1024*1024 else f"{report.file_size / 1024:.1f} KB"
    download_url = f"/api/reports/{rid}/download"
    preview_url = f"/api/reports/{rid}/preview"
    ext = os.path.splitext(report.filename)[1].lower()

    summary_html = ""
    if safe_summary:
        # 智能分段：双换行一定分段；单换行时，如果上一行以句号等结尾则分段，否则合并（PDF碎片断行）
        import re as _re
        # 先统一换行符
        text = safe_summary.replace('\r\n', '\n').replace('\r', '\n')
        # 双换行替换为占位符保留段落
        text = _re.sub(r'\n{2,}', '\n\n', text)
        lines = text.split('\n')
        paragraphs = []
        current = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                # 空行 = 段落分隔
                if current:
                    paragraphs.append(' '.join(current))
                    current = []
                continue
            current.append(stripped)
            # 如果该行以段落结束标点结尾，视为段落结束
            if _re.search(r'[。！？.!?\u201d"】）)；;：:]$', stripped):
                paragraphs.append(' '.join(current))
                current = []
        if current:
            paragraphs.append(' '.join(current))
        summary_html = ''.join(f"<p style='margin-bottom:12px'>{p}</p>" for p in paragraphs if p)

    # PDF 文件提供 iframe 内嵌预览 + 错误容错
    if ext == ".pdf":
        preview_html = f"""<div style="margin-top:16px">
<iframe src="{preview_url}" style="width:100%;height:70vh;border:1px solid #eee;border-radius:8px" allowfullscreen
  onerror="this.style.display='none';document.getElementById('pdf-fallback').style.display='block'"></iframe>
<div id="pdf-fallback" style="display:none;padding:20px;text-align:center;background:#f8f9fa;border-radius:8px">
<p style="color:#666">PDF预览加载失败，请直接下载查看</p>
</div>
<div style="text-align:center;margin-top:12px">
<a href="{download_url}" class="dl-btn">下载报告</a>
</div>
</div>"""
    else:
        preview_html = f"""<div style="margin-top:16px;padding:16px;background:#f8f9fa;border-radius:8px;text-align:center">
<div style="font-size:36px;margin-bottom:8px">📄</div>
<div style="font-size:14px;color:#666;margin-bottom:4px">{safe_original_name}</div>
<div style="font-size:12px;color:#999">{file_size_str}</div>
<a href="{download_url}" class="dl-btn">下载报告</a>
</div>"""

    content_html = f"""
<div class="share-header">
<h1>{safe_title}</h1>
<div class="share-meta">
<span class="share-tag tag-report">研究报告</span>
{f'<span>{safe_institution}</span>' if safe_institution else ''}
<span>{safe_author}</span>
<span>{report.publish_date}</span>
</div>
</div>
<div class="share-body">
{summary_html}
{preview_html}
</div>"""

    desc = report.summary or f"{report.institution}研究报告：{report.title}"
    return _share_html(
        title=report.title,
        description=desc,
        content_html=content_html,
        request=request,
    )
