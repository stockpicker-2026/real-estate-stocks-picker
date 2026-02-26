"""
同花顺 iFinD HTTP API 客户端
API文档: https://ftwc.51ifind.com/gwstatic/static/ds_web/quantapi-web/example.html

功能:
  - Token 自动管理（refresh_token → access_token，7天有效期自动刷新）
  - 历史行情 (cmd_history_quotation)
  - 实时行情 (real_time_quotation) — 含资金流、PE/PB/市值、多周期涨跌等80+指标
  - 基础数据 (basic_data_service) — PE/PB/市值/换手率等
  - 日期序列 (date_sequence) — 时间序列数据
  - 财务指标 (basic_data_service) — ROE/EPS等（需报告期日期）
  - 公告查询 (report_query) — 上市公司最新公告
  - 数据量查询 (get_data_volume) — 查询本月数据用量

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
TOKEN_GET_URL = f"{BASE_URL}/get_access_token"
TOKEN_UPDATE_URL = f"{BASE_URL}/update_access_token"

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


def refresh_access_token(force_new: bool = False) -> Optional[str]:
    """通过 refresh_token 获取 access_token（有效期7天）
    
    Args:
        force_new: True=调用 update_access_token 强制生成新token（旧token失效）
                   False=调用 get_access_token 获取当前有效的token
    """
    refresh_token = _get_refresh_token()
    if not refresh_token:
        logger.error("iFinD refresh_token 未配置")
        return None

    url = TOKEN_UPDATE_URL if force_new else TOKEN_GET_URL
    action = "更新" if force_new else "获取"

    try:
        resp = requests.post(
            url,
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
            # 提前1天过期，确保安全
            _token_cache["expires_at"] = time.time() + 6 * 86400
            logger.info(f"iFinD access_token {action}成功")
            return token
        else:
            logger.error(f"iFinD token{action}失败: {data}")
            # 如果 get 失败，尝试 update 强制生成新的
            if not force_new:
                logger.info("尝试强制更新 access_token...")
                return refresh_access_token(force_new=True)
            return None
    except Exception as e:
        logger.error(f"iFinD token{action}异常: {e}")
        return None


def get_access_token() -> Optional[str]:
    """获取有效的 access_token（自动刷新）
    
    策略:
      1. 缓存未过期 → 直接返回
      2. 缓存过期或为空 → 用 refresh_token 重新获取
      3. refresh 失败 → 尝试 .env 中的 IFIND_ACCESS_TOKEN 作为最后备选
    """
    # 如果缓存有效
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    # 缓存过期或为空，通过 refresh_token 重新获取
    logger.info("iFinD access_token 缓存过期或为空，尝试刷新...")
    token = refresh_access_token()
    if token:
        return token

    # refresh 失败，最后尝试 .env 中的静态 token（可能已过期）
    env_token = _get_access_token_from_env()
    if env_token:
        logger.warning("iFinD refresh 失败，使用 .env 中的 IFIND_ACCESS_TOKEN（可能已过期）")
        _token_cache["access_token"] = env_token
        # 短有效期，1小时后再次尝试刷新
        _token_cache["expires_at"] = time.time() + 3600
        return env_token

    logger.error("iFinD 无法获取任何有效 access_token")
    return None


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
    港股: 02007 → 2007.HK, 00688 → 0688.HK (数字部分去多余前导零，至少保留4位)
    美股: KE → KE.N (暂不支持，保留)
    """
    if market == "A":
        if code.startswith(("6", "9")):
            return f"{code}.SH"
        else:
            return f"{code}.SZ"
    elif market == "HK":
        # iFinD港股代码: 去掉多余前导零，但至少保留4位数字
        num = code.lstrip('0') or '0'
        if len(num) < 4:
            num = num.zfill(4)
        return f"{num}.HK"
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
# 实时行情（增强版 — 含资金流/估值/多周期涨跌）
# =====================================================================

# 实时行情可用的丰富指标（按用途分组）
_RT_BASIC = "open,high,low,latest,volume,amount,changeRatio,preClose,change"
_RT_VALUATION = "pe_ttm,pbr_lf,totalCapital,mv,turnoverRatio"
_RT_MONEY_FLOW = "mainNetInflow,retailNetInflow,largeNetInflow,bigNetInflow,middleNetInflow,smallNetInflow"
_RT_PERIOD_CHG = "chg_5d,chg_10d,chg_20d,chg_60d,chg_120d,chg_year"
_RT_EXTRA = "riseDayCount,vol_ratio,committee,commission_diff,swing"


def fetch_realtime(codes: List[str], market: str, rich: bool = False) -> Optional[Dict[str, dict]]:
    """获取实时行情
    codes: 内部代码列表, e.g. ["001979", "600048"]
    rich: True=获取全部指标（资金流/估值/多周期涨跌等），False=仅基础行情
    返回: {code: {latest, open, high, low, volume, amount, change_ratio, ...}}
    """
    ifind_codes = [to_ifind_code(c, market) for c in codes]

    indicators = _RT_BASIC
    if rich:
        indicators = f"{_RT_BASIC},{_RT_VALUATION},{_RT_MONEY_FLOW},{_RT_PERIOD_CHG},{_RT_EXTRA}"

    data = _post("real_time_quotation", {
        "codes": ",".join(ifind_codes),
        "indicators": indicators,
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
            internal_code = internal_code.zfill(5)

        item = {
            "latest": tbl.get("latest", [None])[0],
            "open": tbl.get("open", [None])[0],
            "high": tbl.get("high", [None])[0],
            "low": tbl.get("low", [None])[0],
            "volume": tbl.get("volume", [None])[0],
            "amount": tbl.get("amount", [None])[0],
            "change_ratio": tbl.get("changeRatio", [None])[0],
            "pre_close": tbl.get("preClose", [None])[0],
            "change": tbl.get("change", [None])[0],
        }

        if rich:
            # 估值指标
            item["pe_ttm"] = tbl.get("pe_ttm", [None])[0]
            item["pb_lf"] = tbl.get("pbr_lf", [None])[0]
            item["total_capital"] = tbl.get("totalCapital", [None])[0]  # 总市值
            item["mv"] = tbl.get("mv", [None])[0]  # 流通市值
            item["turnover_ratio"] = tbl.get("turnoverRatio", [None])[0]

            # 资金流数据
            item["main_net_inflow"] = tbl.get("mainNetInflow", [None])[0]  # 主力净流入
            item["retail_net_inflow"] = tbl.get("retailNetInflow", [None])[0]  # 散户净流入
            item["large_net_inflow"] = tbl.get("largeNetInflow", [None])[0]  # 超大单净流入
            item["big_net_inflow"] = tbl.get("bigNetInflow", [None])[0]  # 大单净流入
            item["middle_net_inflow"] = tbl.get("middleNetInflow", [None])[0]  # 中单净流入
            item["small_net_inflow"] = tbl.get("smallNetInflow", [None])[0]  # 小单净流入

            # 多周期涨跌幅
            item["chg_5d"] = tbl.get("chg_5d", [None])[0]
            item["chg_10d"] = tbl.get("chg_10d", [None])[0]
            item["chg_20d"] = tbl.get("chg_20d", [None])[0]
            item["chg_60d"] = tbl.get("chg_60d", [None])[0]
            item["chg_120d"] = tbl.get("chg_120d", [None])[0]
            item["chg_year"] = tbl.get("chg_year", [None])[0]

            # 其他
            item["rise_day_count"] = tbl.get("riseDayCount", [None])[0]  # 连涨天数
            item["vol_ratio"] = tbl.get("vol_ratio", [None])[0]  # 量比
            item["committee"] = tbl.get("committee", [None])[0]  # 委比
            item["commission_diff"] = tbl.get("commission_diff", [None])[0]  # 委差
            item["swing"] = tbl.get("swing", [None])[0]  # 振幅

        result[internal_code] = item

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
            "market_value": round(market_value / 1e8, 2) if market_value is not None and market_value > 0 else None,  # 转为亿元，0视为无效
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
    合并估值+财务指标+实时资金流
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

    # 实时资金流和估值补充（通过 real_time_quotation 获取）
    try:
        rt = fetch_realtime([code], market, rich=True)
        if rt and code in rt:
            rt_data = rt[code]
            # 资金流数据
            if rt_data.get("main_net_inflow") is not None:
                result["main_net_inflow"] = round(rt_data["main_net_inflow"] / 1e4, 2) if rt_data["main_net_inflow"] else None  # 转万元
                result["retail_net_inflow"] = round(rt_data["retail_net_inflow"] / 1e4, 2) if rt_data.get("retail_net_inflow") else None
                result["large_net_inflow"] = round(rt_data["large_net_inflow"] / 1e4, 2) if rt_data.get("large_net_inflow") else None
            # 连涨天数
            if rt_data.get("rise_day_count") is not None:
                result["rise_day_count"] = int(rt_data["rise_day_count"])
            # 量比
            if rt_data.get("vol_ratio") is not None:
                result["vol_ratio"] = round(rt_data["vol_ratio"], 2)
            # 振幅
            if rt_data.get("swing") is not None:
                result["swing"] = round(rt_data["swing"], 2)
            # 多周期涨跌幅（从实时接口获取比手动计算更准确）
            for key in ["chg_5d", "chg_10d", "chg_20d", "chg_60d", "chg_120d", "chg_year"]:
                if rt_data.get(key) is not None:
                    result[key] = round(rt_data[key], 2)
            # 用实时接口的PE/PB补充（如果 basic_data_service 没拿到）
            if result.get("pe_ttm") is None and rt_data.get("pe_ttm") is not None:
                result["pe_ttm"] = round(rt_data["pe_ttm"], 2)
            if result.get("pb_mrq") is None and rt_data.get("pb_lf") is not None:
                result["pb_mrq"] = round(rt_data["pb_lf"], 4)
            if not result.get("market_value") and rt_data.get("total_capital") is not None and rt_data["total_capital"] > 0:
                result["market_value"] = round(rt_data["total_capital"] / 1e8, 2)
    except Exception as e:
        logger.debug(f"实时增强数据获取失败（非关键）: {e}")

    return result if result else None


# =====================================================================
# 公告查询
# =====================================================================

def fetch_reports(codes: List[str], market: str, days: int = 30,
                  report_type: str = "903", keyword: str = "") -> Optional[List[dict]]:
    """查询上市公司公告
    Args:
        codes: 内部代码列表
        market: 市场类型
        days: 回溯天数
        report_type: 903=全部, 901002004=上市公告书 等
        keyword: 标题关键词筛选（如"半年度报告"）
    Returns:
        [{thscode, secName, reportDate, reportTitle, pdfURL, ctime}, ...]
    """
    ifind_codes = [to_ifind_code(c, market) for c in codes]
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    payload = {
        "codes": ",".join(ifind_codes),
        "functionpara": {
            "reportType": report_type,
        },
        "beginrDate": start_date,
        "endrDate": end_date,
        "outputpara": "reportDate:Y,thscode:Y,secName:Y,ctime:Y,reportTitle:Y,pdfURL:Y",
    }
    if keyword:
        payload["functionpara"]["keyWord"] = keyword

    data = _post("report_query", payload, f"公告查询 {market}")
    if not data:
        return None

    tables = data.get("tables", [])
    if not tables:
        return None

    results = []
    for t in tables:
        tbl = t.get("table", {})
        # report_query 返回结构是列表形式
        report_dates = tbl.get("reportDate", [])
        thscodes = tbl.get("thscode", [])
        sec_names = tbl.get("secName", [])
        ctimes = tbl.get("ctime", [])
        titles = tbl.get("reportTitle", [])
        urls = tbl.get("pdfURL", [])

        n = len(titles) if titles else 0
        for i in range(n):
            results.append({
                "thscode": thscodes[i] if i < len(thscodes) else "",
                "sec_name": sec_names[i] if i < len(sec_names) else "",
                "report_date": report_dates[i] if i < len(report_dates) else "",
                "report_title": titles[i] if i < len(titles) else "",
                "pdf_url": urls[i] if i < len(urls) else "",
                "ctime": ctimes[i] if i < len(ctimes) else "",
            })

    return results if results else None


def fetch_recent_announcements(code: str, market: str, days: int = 30) -> Optional[str]:
    """获取单只股票近期公告摘要（用于AI分析）
    返回格式化的公告标题列表字符串
    """
    reports = fetch_reports([code], market, days=days)
    if not reports:
        return None

    # 取最近10条公告
    recent = reports[:10]
    lines = []
    for r in recent:
        date_str = r.get("report_date", "")
        title = r.get("report_title", "")
        if title:
            lines.append(f"  [{date_str}] {title}")

    if not lines:
        return None

    return "【近期公告（同花顺iFinD）】\n" + "\n".join(lines)


# =====================================================================
# 数据量查询
# =====================================================================

def get_data_volume() -> Optional[dict]:
    """查询本月 iFinD API 数据用量"""
    today = datetime.now().strftime("%Y-%m-%d")
    first_of_month = datetime.now().replace(day=1).strftime("%Y-%m-%d")

    data = _post("get_data_volume", {
        "startdate": first_of_month,
        "enddate": today,
    }, "数据量查询")

    if data and data.get("errorcode") == 0:
        return data.get("data", {})
    return None


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
