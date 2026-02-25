"""
股票数据获取模块
使用 akshare 获取 A股/港股/美股行情数据
增加反爬对策：User-Agent伪装、随机延迟、指数退避重试
"""

import logging
import random
import ssl
import time
from datetime import datetime, timedelta
from typing import Optional

import akshare as ak
import pandas as pd
import requests
import urllib3

logger = logging.getLogger(__name__)

# 修复 macOS LibreSSL 兼容性问题
try:
    urllib3.util.ssl_.DEFAULT_CIPHERS = "ALL:@SECLEVEL=1"
except Exception:
    pass

MAX_RETRIES = 5
RETRY_DELAY = 3  # 基础重试延迟（秒）

# 浏览器 User-Agent 列表，随机选择
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
]


def _patch_session_headers():
    """给 requests 默认 Session 注入浏览器 User-Agent"""
    ua = random.choice(_USER_AGENTS)
    if hasattr(requests, 'Session'):
        original_init = requests.Session.__init__

        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            self.headers.update({
                'User-Agent': ua,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Connection': 'keep-alive',
            })

        requests.Session.__init__ = patched_init


# 启动时注入 UA
_patch_session_headers()


def _retry_fetch(fn, label: str):
    """带指数退避重试的数据获取包装器"""
    for attempt in range(1, MAX_RETRIES + 1):
        # 每次请求前随机更换 UA
        _patch_session_headers()
        # 请求前随机延迟 1~3 秒，模拟人类行为
        time.sleep(random.uniform(1.0, 3.0))
        try:
            result = fn()
            return result
        except Exception as e:
            if attempt < MAX_RETRIES:
                # 指数退避：3s, 6s, 12s, 24s
                delay = RETRY_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 2)
                logger.info(f"{label} 第{attempt}次失败, {delay:.1f}秒后重试: {e}")
                time.sleep(delay)
            else:
                logger.warning(f"{label} 数据失败(已重试{MAX_RETRIES}次): {e}")
                return None


def fetch_a_stock_hist(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """获取A股历史行情"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    def _do():
        return ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=start_date, end_date=end_date, adjust="qfq"
        )

    df = _retry_fetch(_do, f"获取A股 {code}")
    if df is None or df.empty:
        return None
    try:
        df = df.rename(columns={
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume",
            "成交额": "turnover", "涨跌幅": "change_pct"
        })
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]
    except Exception as e:
        logger.warning(f"处理A股 {code} 数据失败: {e}")
        return None


def fetch_hk_stock_hist(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """获取港股历史行情"""
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    end_date = datetime.now().strftime("%Y%m%d")

    def _do():
        return ak.stock_hk_hist(
            symbol=code, period="daily",
            start_date=start_date, end_date=end_date, adjust="qfq"
        )

    df = _retry_fetch(_do, f"获取港股 {code}")
    if df is None or df.empty:
        return None
    try:
        df = df.rename(columns={
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume",
            "成交额": "turnover", "涨跌幅": "change_pct"
        })
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]
    except Exception as e:
        logger.warning(f"处理港股 {code} 数据失败: {e}")
        return None


def fetch_us_stock_hist(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """获取美股历史行情
    akshare 美股接口需要带市场前缀: 105.=纳斯达克, 106.=纽交所
    自动尝试两个市场前缀
    """
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    end_date = datetime.now().strftime("%Y%m%d")

    # 如果 code 已包含前缀则直接使用，否则自动尝试
    if "." in code:
        prefixes = [code]
    else:
        prefixes = [f"105.{code}", f"106.{code}"]

    for symbol in prefixes:
        try:
            df = ak.stock_us_hist(
                symbol=symbol, period="daily",
                start_date=start_date, end_date=end_date,
                adjust="qfq"
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "日期": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low", "成交量": "volume",
                    "成交额": "turnover", "涨跌幅": "change_pct"
                })
                df["date"] = pd.to_datetime(df["date"]).dt.date
                return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]
        except Exception:
            continue

    logger.warning(f"获取美股 {code} 数据失败: 所有市场前缀均无数据")
    return None


def fetch_stock_hist(code: str, market: str, days: int = 120) -> Optional[pd.DataFrame]:
    """统一接口获取股票历史行情"""
    if market == "A":
        return fetch_a_stock_hist(code, days)
    elif market == "HK":
        return fetch_hk_stock_hist(code, days)
    elif market == "US":
        return fetch_us_stock_hist(code, days)
    return None
