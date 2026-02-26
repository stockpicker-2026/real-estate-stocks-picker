"""
同花顺 iFinD HTTP API 客户端
API文档: https://ftwc.51ifind.com/gwstatic/static/ds_web/quantapi-web/example.html

功能:
  - Token 自动管理（refresh_token → access_token，7天有效期自动刷新）
  - 历史行情 (cmd_history_quotation)
  - 实时行情 (real_time_quotation)
  - 基础数据 (basic_data_service) — PE/PB/市值/换手率等
  - 日期序列 (date_sequence) — 时间序列数据
  - 财务指标 (basic_data_service) — ROE/EPS等（需报告期日期）

注意:
  - A股代码格式: 001979.SZ / 600048.SH
  - 港股代码格式: 2007.HK (不带前导零)
  - 港股PE/PB等基础数据受限（FREEIAL账号），但历史行情和实时行情可用
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

import requests
import pandas as pd

logger = logging.getLogger(__name__)

BASE_URL = "https://quantapi.51ifind.com/api/v1"
TOKEN_REFRESH_URL = f"{BASE_URL}/get_access_token"

# Token 缓存
_token_cache = {
    "access_token": None,
    "expires_at": 0,  # Unix timestamp
}

MAX_RETRIES = 3
RETRY_DELAY = 2


def _get_refresh_token() -> str:
    return os.getenv("IFIND_REFRESH_TOKEN", "")


def _get_access_token_from_env() -> str:
    return os.getenv("IFIND_ACCESS_TOKEN", "")


def refresh_access_token() -> Optional[str]:
    """通过 refresh_token 获取新的 access_token（有效期7天）"""
    refresh_token = _get_refresh_token()
    if not refresh_token:
        logger.error("iFinD refresh_token 未配置")
        return None

    try:
        resp = requests.post(
            TOKEN_REFRESH_URL,
            headers={
                "Content-Type": "application/json",
                "refresh_token": refresh_token,
            },
            json={},
            timeout=15,
        )
        data = resp.json()
        if data.get("errorcode") == 0:
            token = data["data"]["access_token"]
            _token_cache["access_token"] = token
            # 提前12小时过期，确保安全
            _token_cache["expires_at"] = time.time() + 6 * 86400
            logger.info("iFinD access_token 刷新成功")
            return token
        else:
            logger.error(f"iFinD token刷新失败: {data}")
            return None
    except Exception as e:
        logger.error(f"iFinD token刷新异常: {e}")
        return None


def get_access_token() -> Optional[str]:
    """获取有效的 access_token（自动刷新）"""
    # 如果缓存有效
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    # 尝试从环境变量获取
    env_token = _get_access_token_from_env()
    if env_token and not _token_cache["access_token"]:
        _token_cache["access_token"] = env_token
        # 假设env中的token还有3天有效期
        _token_cache["expires_at"] = time.time() + 3 * 86400
        return env_token

    # 刷新token
    return refresh_access_token()


def _post(endpoint: str, payload: dict, label: str = "") -> Optional[dict]:
    """带重试和token管理的POST请求"""
    token = get_access_token()
    if not token:
        logger.warning(f"iFinD {label}: 无可用token")
        return None

    url = f"{BASE_URL}/{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "access_token": token,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            data = resp.json()
            ec = data.get("errorcode", -1)

            if ec == 0:
                return data
            elif ec == -4001:
                # Token过期，刷新后重试
                logger.info(f"iFinD {label}: token过期，刷新中...")
                _token_cache["access_token"] = None
                _token_cache["expires_at"] = 0
                token = refresh_access_token()
                if token:
                    headers["access_token"] = token
                    continue
                return None
            else:
                logger.warning(f"iFinD {label} 错误[{ec}]: {data.get('errmsg', '')}")
                return None
        except requests.exceptions.SSLError as e:
            if attempt < MAX_RETRIES:
                delay = RETRY_DELAY * attempt
                logger.debug(f"iFinD {label} SSL重试({attempt}): {e}")
                time.sleep(delay)
            else:
                logger.warning(f"iFinD {label} SSL失败: {e}")
                return None
        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                logger.warning(f"iFinD {label} 异常: {e}")
                return None
    return None


# =====================================================================
# 代码转换工具
# =====================================================================

def to_ifind_code(code: str, market: str) -> str:
    """将内部代码转换为iFinD代码格式
    A股: 000002 → 000002.SZ / 600048 → 600048.SH
    港股: 02007 → 2007.HK (去前导零)
    美股: KE → KE.N (暂不支持，保留)
    """
    if market == "A":
        if code.startswith(("6", "9")):
            return f"{code}.SH"
        else:
            return f"{code}.SZ"
    elif market == "HK":
        # 去掉前导零
        return f"{code.lstrip('0')}.HK"
    elif market == "US":
        return f"{code}.N"
    return code


# =====================================================================
# 历史行情
# =====================================================================

def fetch_history(code: str, market: str, days: int = 120) -> Optional[pd.DataFrame]:
    """获取历史日K线数据
    返回DataFrame: date, open, high, low, close, volume, turnover, change_pct
    """
    ifind_code = to_ifind_code(code, market)
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    data = _post("cmd_history_quotation", {
        "codes": ifind_code,
        "indicators": "open,high,low,close,volume,amount,changeRatio",
        "startdate": start_date,
        "enddate": end_date,
    }, f"历史行情 {ifind_code}")

    if not data:
        return None

    tables = data.get("tables", [])
    if not tables:
        return None

    t = tables[0]
    times = t.get("time", [])
    tbl = t.get("table", {})

    if not times or "close" not in tbl:
        return None

    rows = []
    n = len(times)
    opens = tbl.get("open", [None] * n)
    highs = tbl.get("high", [None] * n)
    lows = tbl.get("low", [None] * n)
    closes = tbl.get("close", [None] * n)
    volumes = tbl.get("volume", [0] * n)
    amounts = tbl.get("amount", [0] * n)
    change_ratios = tbl.get("changeRatio", [0] * n)

    for i in range(n):
        rows.append({
            "date": times[i],
            "open": float(opens[i]) if opens[i] is not None else None,
            "high": float(highs[i]) if highs[i] is not None else None,
            "low": float(lows[i]) if lows[i] is not None else None,
            "close": float(closes[i]) if closes[i] is not None else None,
            "volume": float(volumes[i]) if volumes[i] is not None else 0,
            "turnover": float(amounts[i]) if amounts[i] is not None else 0,
            "change_pct": float(change_ratios[i]) if change_ratios[i] is not None else 0,
        })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    # 过滤无效行
    df = df.dropna(subset=["close"])

    if df.empty or len(df) < 2:
        return None

    # 如果change_pct全为0，手动计算
    if (df["change_pct"] == 0).all():
        df["change_pct"] = df["close"].pct_change() * 100
        df["change_pct"] = df["change_pct"].fillna(0)

    return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]


# =====================================================================
# 实时行情
# =====================================================================

def fetch_realtime(codes: List[str], market: str) -> Optional[Dict[str, dict]]:
    """获取实时行情
    codes: 内部代码列表, e.g. ["001979", "600048"]
    返回: {code: {latest, open, high, low, volume, amount, change_ratio}}
    """
    ifind_codes = [to_ifind_code(c, market) for c in codes]

    data = _post("real_time_quotation", {
        "codes": ",".join(ifind_codes),
        "indicators": "open,high,low,latest,volume,amount,changeRatio",
    }, f"实时行情 {market}")

    if not data:
        return None

    result = {}
    for t in data.get("tables", []):
        thscode = t.get("thscode", "")
        tbl = t.get("table", {})
        # 还原为内部代码
        internal_code = thscode.split(".")[0]
        if market == "HK":
            # 补全前导零
            internal_code = internal_code.zfill(5)

        result[internal_code] = {
            "latest": tbl.get("latest", [None])[0],
            "open": tbl.get("open", [None])[0],
            "high": tbl.get("high", [None])[0],
            "low": tbl.get("low", [None])[0],
            "volume": tbl.get("volume", [None])[0],
            "amount": tbl.get("amount", [None])[0],
            "change_ratio": tbl.get("changeRatio", [None])[0],
        }

    return result if result else None


# =====================================================================
# 基础数据（估值指标）
# =====================================================================

def fetch_valuation(codes: List[str], market: str) -> Optional[Dict[str, dict]]:
    """获取估值数据: PE_TTM, PB_MRQ, 总市值, 换手率
    仅A股有效，港股返回null
    """
    ifind_codes = [to_ifind_code(c, market) for c in codes]
    today = datetime.now().strftime("%Y%m%d")

    data = _post("basic_data_service", {
        "codes": ",".join(ifind_codes),
        "indipara": [
            {"indicator": "ths_pe_ttm_stock", "indiparams": [today]},
            {"indicator": "ths_pb_mrq_stock", "indiparams": [today]},
            {"indicator": "ths_market_value_stock", "indiparams": [today]},
            {"indicator": "ths_turnover_ratio_stock", "indiparams": [today]},
        ]
    }, f"估值数据 {market}")

    if not data:
        return None

    result = {}
    for t in data.get("tables", []):
        thscode = t.get("thscode", "")
        tbl = t.get("table", {})
        internal_code = thscode.split(".")[0]
        if market == "HK":
            internal_code = internal_code.zfill(5)

        pe = tbl.get("ths_pe_ttm_stock", [None])[0]
        pb = tbl.get("ths_pb_mrq_stock", [None])[0]
        market_value = tbl.get("ths_market_value_stock", [None])[0]
        turnover = tbl.get("ths_turnover_ratio_stock", [None])[0]

        # 跳过全null的数据（港股等）
        if pe is None and pb is None and market_value is None:
            continue

        result[internal_code] = {
            "pe_ttm": round(pe, 2) if pe is not None else None,
            "pb_mrq": round(pb, 4) if pb is not None else None,
            "market_value": round(market_value / 1e8, 2) if market_value is not None else None,  # 转为亿元
            "turnover_ratio": round(turnover, 2) if turnover is not None else None,
        }

    return result if result else None


# =====================================================================
# 财务指标
# =====================================================================

def _get_latest_report_date() -> str:
    """获取最近的财报报告期日期
    Q1: 03-31, Q2(中报): 06-30, Q3: 09-30, Q4(年报): 12-31
    """
    now = datetime.now()
    year = now.year
    month = now.month

    # 财报有滞后性：通常3个月后才出
    # 当前月份 -> 可用最新报告期
    if month >= 11:
        return f"{year}0930"   # Q3已出
    elif month >= 9:
        return f"{year}0630"   # 中报已出
    elif month >= 5:
        return f"{year - 1}1231"  # 年报已出
    elif month >= 4:
        return f"{year - 1}0930"  # 上年Q3
    else:
        return f"{year - 1}0630"  # 上年中报


def fetch_financials(codes: List[str], market: str) -> Optional[Dict[str, dict]]:
    """获取财务指标: ROE, EPS
    使用最近的报告期日期
    仅A股有效
    """
    if market != "A":
        return None

    ifind_codes = [to_ifind_code(c, market) for c in codes]
    report_date = _get_latest_report_date()

    data = _post("basic_data_service", {
        "codes": ",".join(ifind_codes),
        "indipara": [
            {"indicator": "ths_roe_stock", "indiparams": [report_date]},
            {"indicator": "ths_basic_eps_stock", "indiparams": [report_date]},
            {"indicator": "ths_asset_liability_ratio_stock", "indiparams": [report_date]},
        ]
    }, f"财务指标 {market}")

    if not data:
        return None

    result = {}
    for t in data.get("tables", []):
        thscode = t.get("thscode", "")
        tbl = t.get("table", {})
        internal_code = thscode.split(".")[0]

        roe = tbl.get("ths_roe_stock", [None])[0]
        eps = tbl.get("ths_basic_eps_stock", [None])[0]
        debt_ratio = tbl.get("ths_asset_liability_ratio_stock", [None])[0]

        if roe is None and eps is None and debt_ratio is None:
            continue

        result[internal_code] = {
            "roe": round(roe, 2) if roe is not None else None,
            "eps": round(eps, 4) if eps is not None else None,
            "debt_ratio": round(debt_ratio, 2) if debt_ratio is not None else None,
            "report_date": report_date,
        }

    return result if result else None


# =====================================================================
# 批量获取所有基本面数据（合并调用）
# =====================================================================

def fetch_fundamentals(code: str, market: str) -> Optional[dict]:
    """获取单只股票的全部基本面数据
    合并估值+财务指标
    """
    result = {}

    # 估值数据
    val = fetch_valuation([code], market)
    if val and code in val:
        result.update(val[code])

    # 财务数据（仅A股）
    if market == "A":
        fin = fetch_financials([code], market)
        if fin and code in fin:
            result.update(fin[code])

    return result if result else None


# =====================================================================
# 健康检查
# =====================================================================

def check_health() -> bool:
    """检查 iFinD API 是否可用"""
    token = get_access_token()
    if not token:
        return False

    data = _post("basic_data_service", {
        "codes": "001979.SZ",
        "indipara": [
            {"indicator": "ths_stock_short_name_stock", "indiparams": [""]},
        ]
    }, "健康检查")

    if data and data.get("errorcode") == 0:
        tables = data.get("tables", [])
        if tables:
            name = tables[0].get("table", {}).get("ths_stock_short_name_stock", [None])[0]
            logger.info(f"iFinD 健康检查通过: {name}")
            return True
    return False
