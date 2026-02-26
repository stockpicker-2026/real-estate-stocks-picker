"""
股票数据获取模块（多数据源降级版本）
数据源优先级：
  A股:  iFinD(同花顺) → akshare(东方财富) → 腾讯财经 → 新浪财经
  港股: iFinD(同花顺) → akshare(东方财富) → 腾讯财经
  美股: akshare(东方财富) → 腾讯财经
当主数据源被封禁时自动降级到备选数据源
"""

import json
import logging
import random
import re
import time
from datetime import datetime, timedelta
from typing import Optional

import akshare as ak
import pandas as pd
import requests
import urllib3

from app.ifind_client import fetch_history as ifind_fetch_history

logger = logging.getLogger(__name__)

# 修复 macOS LibreSSL 兼容性问题
try:
    urllib3.util.ssl_.DEFAULT_CIPHERS = "ALL:@SECLEVEL=1"
except Exception:
    pass

MAX_RETRIES = 3
RETRY_DELAY = 2  # 基础重试延迟（秒）

# 浏览器 User-Agent 列表
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
]


def _get_headers():
    """获取随机浏览器请求头"""
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }


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


def _retry_fetch(fn, label: str, max_retries: int = MAX_RETRIES):
    """带指数退避重试的数据获取包装器"""
    for attempt in range(1, max_retries + 1):
        _patch_session_headers()
        time.sleep(random.uniform(0.5, 1.5))
        try:
            result = fn()
            return result
        except Exception as e:
            if attempt < max_retries:
                delay = RETRY_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)
                logger.info(f"{label} 第{attempt}次失败, {delay:.1f}秒后重试: {e}")
                time.sleep(delay)
            else:
                logger.warning(f"{label} 失败(已重试{max_retries}次): {e}")
                return None


# ==============================================================================
# iFinD (同花顺) 数据源 - 最高优先级
# ==============================================================================

def _ifind_stock_hist(code: str, market: str, days: int = 120) -> Optional[pd.DataFrame]:
    """通过 iFinD HTTP API 获取历史行情"""
    try:
        df = ifind_fetch_history(code, market, days)
        if df is not None and not df.empty and len(df) >= 2:
            logger.info(f"iFinD {market}股 {code} 获取成功 ({len(df)}行)")
            return df
    except Exception as e:
        logger.warning(f"iFinD {market}股 {code} 获取失败: {e}")
    return None


# ==============================================================================
# 腾讯财经 API 数据源 (web.ifzq.gtimg.cn)
# 支持: A股、港股、美股
# ==============================================================================

def _tencent_a_stock_hist(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """通过腾讯财经 API 获取A股历史日K线"""
    if code.startswith("6") or code.startswith("9"):
        symbol = f"sh{code}"
    else:
        symbol = f"sz{code}"

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    url = (
        f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
        f"param={symbol},day,{start_date.strftime('%Y-%m-%d')},"
        f"{end_date.strftime('%Y-%m-%d')},{days},qfq"
    )

    try:
        resp = requests.get(url, headers=_get_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()

        kline_data = data.get("data", {}).get(symbol, {})
        day_data = kline_data.get("qfqday") or kline_data.get("day")
        if not day_data:
            return None

        rows = []
        for item in day_data:
            if len(item) >= 6:
                rows.append({
                    "date": item[0],
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5]),
                })

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["turnover"] = 0.0
        df["change_pct"] = df["close"].pct_change() * 100
        df["change_pct"] = df["change_pct"].fillna(0)
        return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]
    except Exception as e:
        logger.warning(f"腾讯A股 {code} 获取失败: {e}")
        return None


def _tencent_hk_stock_hist(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """通过腾讯财经 API 获取港股历史日K线"""
    symbol = f"hk{code}"

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    url = (
        f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
        f"param={symbol},day,{start_date.strftime('%Y-%m-%d')},"
        f"{end_date.strftime('%Y-%m-%d')},{days},qfq"
    )

    try:
        resp = requests.get(url, headers=_get_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()

        kline_data = data.get("data", {}).get(symbol, {})
        day_data = kline_data.get("qfqday") or kline_data.get("day")
        if not day_data:
            return None

        rows = []
        for item in day_data:
            if len(item) >= 6:
                rows.append({
                    "date": item[0],
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5]),
                })

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["turnover"] = 0.0
        df["change_pct"] = df["close"].pct_change() * 100
        df["change_pct"] = df["change_pct"].fillna(0)
        return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]
    except Exception as e:
        logger.warning(f"腾讯港股 {code} 获取失败: {e}")
        return None


def _tencent_us_stock_hist(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """通过腾讯财经 API 获取美股历史日K线
    腾讯美股代码格式: us{TICKER}.N (纽交所) 或 us{TICKER}.OQ (纳斯达克)
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    # 尝试不同后缀: .N(纽交所), .OQ(纳斯达克), 无后缀
    candidates = [f"us{code}.N", f"us{code}.OQ", f"us{code}"]

    for symbol in candidates:
        try:
            url = (
                f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
                f"param={symbol},day,{start_date.strftime('%Y-%m-%d')},"
                f"{end_date.strftime('%Y-%m-%d')},{days},qfq"
            )
            resp = requests.get(url, headers=_get_headers(), timeout=15)
            resp.raise_for_status()
            data = resp.json()

            kline_data = data.get("data", {}).get(symbol, {})
            day_data = kline_data.get("qfqday") or kline_data.get("day")
            if not day_data or len(day_data) < 2:
                continue

            rows = []
            for item in day_data:
                if len(item) >= 6:
                    rows.append({
                        "date": item[0],
                        "open": float(item[1]),
                        "close": float(item[2]),
                        "high": float(item[3]),
                        "low": float(item[4]),
                        "volume": float(item[5]),
                    })

            if not rows:
                continue

            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df["turnover"] = 0.0
            df["change_pct"] = df["close"].pct_change() * 100
            df["change_pct"] = df["change_pct"].fillna(0)
            return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]
        except Exception:
            continue

    logger.warning(f"腾讯美股 {code} 获取失败")
    return None


# ==============================================================================
# 新浪财经 API 数据源 (money.finance.sina.com.cn)
# 仅支持: A股
# ==============================================================================

def _sina_a_stock_hist(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """通过新浪财经 API 获取A股历史K线"""
    if code.startswith("6") or code.startswith("9"):
        symbol = f"sh{code}"
    else:
        symbol = f"sz{code}"

    url = (
        f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?"
        f"symbol={symbol}&scale=240&ma=no&datalen={days}"
    )

    try:
        resp = requests.get(url, headers=_get_headers(), timeout=15)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text or text == "null":
            return None

        data = json.loads(text)
        if not data:
            return None

        df = pd.DataFrame(data)
        df = df.rename(columns={"day": "date"})
        df["date"] = pd.to_datetime(df["date"]).dt.date
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["turnover"] = 0.0
        df["change_pct"] = df["close"].pct_change() * 100
        df["change_pct"] = df["change_pct"].fillna(0)
        return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]
    except Exception as e:
        logger.warning(f"新浪A股 {code} 获取失败: {e}")
        return None


# ==============================================================================
# akshare (东方财富) 数据源 - 原始主数据源
# ==============================================================================

def _akshare_a_stock_hist(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """通过 akshare (东方财富) 获取A股历史行情"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    def _do():
        return ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=start_date, end_date=end_date, adjust="qfq"
        )

    df = _retry_fetch(_do, f"akshare A股 {code}", max_retries=2)
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
        logger.warning(f"处理akshare A股 {code} 数据失败: {e}")
        return None


def _akshare_hk_stock_hist(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """通过 akshare (东方财富) 获取港股历史行情"""
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    end_date = datetime.now().strftime("%Y%m%d")

    def _do():
        return ak.stock_hk_hist(
            symbol=code, period="daily",
            start_date=start_date, end_date=end_date, adjust="qfq"
        )

    df = _retry_fetch(_do, f"akshare 港股 {code}", max_retries=2)
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
        logger.warning(f"处理akshare 港股 {code} 数据失败: {e}")
        return None


def _akshare_us_stock_hist(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """通过 akshare (东方财富) 获取美股历史行情"""
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    end_date = datetime.now().strftime("%Y%m%d")

    if "." in code:
        prefixes = [code]
    else:
        prefixes = [f"105.{code}", f"106.{code}"]

    for symbol in prefixes:
        try:
            df = ak.stock_us_hist(
                symbol=symbol, period="daily",
                start_date=start_date, end_date=end_date, adjust="qfq"
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
    return None


# ==============================================================================
# 统一接口 - 多数据源降级
# ==============================================================================

# 全局记录每个数据源的连续失败次数，用于智能排序
_source_failures = {"ifind": 0, "akshare": 0, "sina": 0, "tencent": 0}
_FAILURE_THRESHOLD = 3  # 连续失败超过此次数，该数据源降低优先级


def _get_source_order(default_order: list) -> list:
    """
    根据历史失败记录动态调整数据源顺序。
    连续失败超过阈值的数据源会被放到最后。
    """
    healthy = [s for s in default_order if _source_failures.get(s, 0) < _FAILURE_THRESHOLD]
    unhealthy = [s for s in default_order if _source_failures.get(s, 0) >= _FAILURE_THRESHOLD]
    return healthy + unhealthy


def _fetch_with_fallback(code: str, sources: dict, default_order: list, label: str) -> Optional[pd.DataFrame]:
    """
    通用多数据源降级获取逻辑。
    依次尝试各数据源，成功则重置该源失败计数，失败则累加。
    """
    order = _get_source_order(default_order)

    for src_name in order:
        fn = sources.get(src_name)
        if fn is None:
            continue
        try:
            df = fn()
            if df is not None and not df.empty and len(df) >= 2:
                _source_failures[src_name] = 0
                if src_name != default_order[0]:
                    logger.info(f"{label} 使用备选数据源 [{src_name}] 成功 ({len(df)}行)")
                return df
            else:
                _source_failures[src_name] = _source_failures.get(src_name, 0) + 1
                logger.info(f"{label} 数据源 [{src_name}] 无有效数据")
        except Exception as e:
            _source_failures[src_name] = _source_failures.get(src_name, 0) + 1
            logger.warning(f"{label} 数据源 [{src_name}] 异常: {e}")

    logger.error(f"{label} 所有数据源均失败")
    return None


def fetch_a_stock_hist(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """获取A股历史行情 - 多数据源降级: iFinD → akshare → 腾讯 → 新浪"""
    sources = {
        "ifind": lambda: _ifind_stock_hist(code, "A", days),
        "akshare": lambda: _akshare_a_stock_hist(code, days),
        "tencent": lambda: _tencent_a_stock_hist(code, days),
        "sina": lambda: _sina_a_stock_hist(code, days),
    }
    return _fetch_with_fallback(code, sources, ["ifind", "akshare", "tencent", "sina"], f"A股 {code}")


def fetch_hk_stock_hist(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """获取港股历史行情 - 多数据源降级: iFinD → akshare → 腾讯"""
    sources = {
        "ifind": lambda: _ifind_stock_hist(code, "HK", days),
        "akshare": lambda: _akshare_hk_stock_hist(code, days),
        "tencent": lambda: _tencent_hk_stock_hist(code, days),
    }
    return _fetch_with_fallback(code, sources, ["ifind", "akshare", "tencent"], f"港股 {code}")


def fetch_us_stock_hist(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """获取美股历史行情 - 多数据源降级: akshare → 腾讯"""
    sources = {
        "akshare": lambda: _akshare_us_stock_hist(code, days),
        "tencent": lambda: _tencent_us_stock_hist(code, days),
    }
    return _fetch_with_fallback(code, sources, ["akshare", "tencent"], f"美股 {code}")


def fetch_stock_hist(code: str, market: str, days: int = 120) -> Optional[pd.DataFrame]:
    """统一接口获取股票历史行情"""
    if market == "A":
        return fetch_a_stock_hist(code, days)
    elif market == "HK":
        return fetch_hk_stock_hist(code, days)
    elif market == "US":
        return fetch_us_stock_hist(code, days)
    return None
