from datetime import datetime

from sqlalchemy import Column, String, Float, Integer, DateTime, Date, Text, Index, Boolean, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True, index=True)
    hashed_password = Column(String(200), nullable=False)
    display_name = Column(String(100), default="")
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


class Commentary(Base):
    """每日市场点评"""
    __tablename__ = "commentaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(20), default="industry")  # industry=行业点评, stock=个股点评
    stock_codes = Column(String(500), default="")  # 关联股票代码，逗号分隔
    author = Column(String(50), default="admin")
    is_published = Column(Boolean, default=True)
    publish_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class Report(Base):
    """机构研究报告"""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(300), nullable=False)
    summary = Column(Text, default="")
    institution = Column(String(100), default="")  # 发布机构
    filename = Column(String(300), nullable=False)  # 存储文件名
    original_name = Column(String(300), nullable=False)  # 原始文件名
    file_size = Column(Integer, default=0)  # 文件大小(bytes)
    author = Column(String(50), default="admin")
    is_published = Column(Boolean, default=True)
    publish_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    market = Column(String(10), nullable=False)  # A, HK, US
    sector = Column(String(50), default="房地产")
    market_cap = Column(Float, nullable=True)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class StockPrice(Base):
    __tablename__ = "stock_prices"
    __table_args__ = (Index("ix_price_code_date", "code", "date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    turnover = Column(Float)
    change_pct = Column(Float)


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (Index("ix_rating_code_date_model", "code", "date", "model_type"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    market = Column(String(10), nullable=False)
    date = Column(Date, nullable=False)
    model_type = Column(String(20), nullable=False, default="quant_ai")  # quant_ai / soochow
    # 评分维度 (0-100)
    trend_score = Column(Float, default=0)
    momentum_score = Column(Float, default=0)
    volatility_score = Column(Float, default=0)
    volume_score = Column(Float, default=0)
    value_score = Column(Float, default=0)
    ai_score = Column(Float, default=0)
    # 综合评分
    total_score = Column(Float, default=0)
    # 评级: 优选/关注/中性/谨慎
    rating = Column(String(20), nullable=False)
    # 评级理由
    reason = Column(Text, default="")
    # 基本面数据（来自iFinD）
    pe_ttm = Column(Float, nullable=True)
    pb_mrq = Column(Float, nullable=True)
    roe = Column(Float, nullable=True)
    eps = Column(Float, nullable=True)
    market_value = Column(Float, nullable=True)  # 亿元
    debt_ratio = Column(Float, nullable=True)
    fundamental_score = Column(Float, nullable=True)
    # 资金流数据（来自iFinD实时行情）
    main_net_inflow = Column(Float, nullable=True)  # 主力净流入（万元）
    retail_net_inflow = Column(Float, nullable=True)  # 散户净流入（万元）
    large_net_inflow = Column(Float, nullable=True)  # 超大单净流入（万元）
    rise_day_count = Column(Integer, nullable=True)  # 连涨/跌天数
    vol_ratio = Column(Float, nullable=True)  # 量比
    swing = Column(Float, nullable=True)  # 振幅%
    committee = Column(Float, nullable=True)  # 委比%
    turnover_ratio = Column(Float, nullable=True)  # 换手率%
    # iFinD多周期涨跌幅
    chg_5d = Column(Float, nullable=True)
    chg_10d = Column(Float, nullable=True)
    chg_20d = Column(Float, nullable=True)
    chg_60d = Column(Float, nullable=True)
    chg_120d = Column(Float, nullable=True)
    chg_year = Column(Float, nullable=True)  # 年初至今涨跌幅
    created_at = Column(DateTime, default=datetime.now)


class Watchlist(Base):
    """用户自选股票池"""
    __tablename__ = "watchlists"
    __table_args__ = (
        UniqueConstraint("user_id", "stock_code", name="uq_watchlist_user_stock"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    stock_code = Column(String(20), nullable=False)
    stock_name = Column(String(100), nullable=False)
    market = Column(String(10), nullable=False)
    note = Column(String(500), default="")  # 用户备注
    added_at = Column(DateTime, default=datetime.now)


class PortfolioWeight(Base):
    """模拟仓位权重"""
    __tablename__ = "portfolio_weights"
    __table_args__ = (
        UniqueConstraint("user_id", "stock_code", name="uq_portfolio_user_stock"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    stock_code = Column(String(20), nullable=False)
    weight = Column(Float, nullable=False, default=0)  # 仓位百分比 0~100
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
