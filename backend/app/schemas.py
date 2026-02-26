from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel


# ========== 认证相关 ==========
class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = ""


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    is_admin: bool

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ========== 点评相关 ==========
class CommentaryCreate(BaseModel):
    title: str
    content: str
    category: str = "industry"
    stock_codes: Optional[str] = ""
    publish_date: Optional[date] = None


class CommentaryUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    stock_codes: Optional[str] = None
    is_published: Optional[bool] = None


class CommentaryOut(BaseModel):
    id: int
    title: str
    content: str
    category: str
    stock_codes: str
    author: str
    is_published: bool
    publish_date: date
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ========== 报告相关 ==========
class ReportOut(BaseModel):
    id: int
    title: str
    summary: str
    institution: str
    original_name: str
    file_size: int
    author: str
    is_published: bool
    publish_date: date
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ========== 原有模型 ==========
class StockOut(BaseModel):
    id: int
    code: str
    name: str
    market: str
    sector: str
    is_active: int

    class Config:
        from_attributes = True


class RatingOut(BaseModel):
    id: int
    code: str
    name: str
    market: str
    date: date
    trend_score: float
    momentum_score: float
    volatility_score: float
    volume_score: float
    value_score: float
    ai_score: float
    total_score: float
    rating: str
    reason: str
    # 基本面数据（来自iFinD，可选）
    pe_ttm: Optional[float] = None
    pb_mrq: Optional[float] = None
    roe: Optional[float] = None
    eps: Optional[float] = None
    market_value: Optional[float] = None
    debt_ratio: Optional[float] = None
    fundamental_score: Optional[float] = None
    # 资金流数据
    main_net_inflow: Optional[float] = None
    rise_day_count: Optional[int] = None

    class Config:
        from_attributes = True


class PriceOut(BaseModel):
    date: date
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]
    volume: Optional[float]
    change_pct: Optional[float]

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    total_stocks: int
    rated_today: int
    avg_score: float
    market_distribution: dict
    rating_distribution: dict
    ai_success_count: int = 0
    quant_only_count: int = 0
    refresh_time: Optional[str] = None


class RatingHistoryOut(BaseModel):
    date: date
    total_score: float
    rating: str

    class Config:
        from_attributes = True
