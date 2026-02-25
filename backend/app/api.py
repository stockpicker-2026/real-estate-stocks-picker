"""
API路由 - 包含评级、认证、点评、报告模块
"""

import os
import uuid
from datetime import date, timedelta
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy import select, func, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    hash_password, verify_password, create_token,
    get_current_user, require_user, require_admin,
)
from app.config import UPLOAD_DIR
from app.database import get_db
from app.models import Stock, Rating, StockPrice, User, Commentary, Report
from app.schemas import (
    StockOut, RatingOut, PriceOut, DashboardStats, RatingHistoryOut,
    LoginRequest, RegisterRequest, TokenResponse, UserOut,
    CommentaryCreate, CommentaryUpdate, CommentaryOut,
    ReportOut,
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
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    """仪表盘统计数据"""
    total = await db.scalar(select(func.count(Stock.id)).where(Stock.is_active == 1))
    latest_date = await db.scalar(select(func.max(Rating.date)))
    if not latest_date:
        return DashboardStats(
            total_stocks=total or 0, rated_today=0, avg_score=0,
            market_distribution={}, rating_distribution={}
        )
    rated_q = select(Rating).where(Rating.date == latest_date)
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
    refresh_time_str = latest_time.strftime("%Y-%m-%d %H:%M") if latest_time else None
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
    db: AsyncSession = Depends(get_db),
):
    """获取最新一期评级"""
    latest_date = await db.scalar(select(func.max(Rating.date)))
    if not latest_date:
        return []
    q = select(Rating).where(Rating.date == latest_date)
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
    db: AsyncSession = Depends(get_db),
):
    """获取某只股票的历史评级"""
    since = date.today() - timedelta(days=days)
    q = (
        select(Rating)
        .where(Rating.code == code, Rating.date >= since)
        .order_by(desc(Rating.date))
    )
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/ratings/date/{target_date}", response_model=list[RatingOut])
async def get_ratings_by_date(
    target_date: date,
    market: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取指定日期的评级"""
    q = select(Rating).where(Rating.date == target_date)
    if market:
        q = q.where(Rating.market == market)
    q = q.order_by(desc(Rating.total_score))
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/ratings/dates", response_model=list[date])
async def get_available_dates(db: AsyncSession = Depends(get_db)):
    """获取所有有评级数据的日期"""
    q = select(Rating.date).distinct().order_by(desc(Rating.date)).limit(90)
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
    db: AsyncSession = Depends(get_db),
):
    """获取评分趋势"""
    since = date.today() - timedelta(days=days)
    q = (
        select(Rating.date, Rating.total_score, Rating.rating)
        .where(Rating.code == code, Rating.date >= since)
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
    return FileResponse(
        filepath,
        filename=report.original_name,
        media_type="application/octet-stream",
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
