"""
房地产行业新闻资讯获取模块
数据源：
1. 东方财富搜索 API（主力）：多关键词搜索，获取最新房地产新闻
2. 中国政府网政策库（补充）：房地产相关政策文件
获取后通过 AI 进行相关性筛选，只保留高度相关的房地产政策新闻
"""

import json
import logging
import random
import re
import time
import urllib.parse
from datetime import datetime
from typing import List, Dict, Optional

import requests

from app.llm_client import chat_hunyuan

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# 新闻缓存
_news_cache: Dict[str, dict] = {}
_CACHE_TTL = 3600  # 1小时

# 房地产核心关键词（用于初步过滤）
_RE_KEYWORDS = re.compile(
    r"房地产|楼市|房企|地产|住房|限购|限贷|公积金|土地出让|保交楼|"
    r"房贷|首付|棚改|旧改|城中村|住建部|不动产|房价|二手房|新房|"
    r"商品房|住宅|物业|土地市场|房住不炒|LPR|按揭|购房|预售|"
    r"土拍|宅基地|住房公积金|房产税|存量房|经适房|保障房|"
    r"碧桂园|万科|恒大|融创|华润置地|中海|龙湖|保利|招商蛇口|金地"
)


def _get_headers():
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _get_json_headers():
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.eastmoney.com/",
    }


def _get_cached(key: str) -> Optional[List[Dict]]:
    if key in _news_cache:
        entry = _news_cache[key]
        if time.time() - entry["ts"] < _CACHE_TTL:
            return entry["data"]
    return None


def _set_cache(key: str, data: List[Dict]):
    _news_cache[key] = {"ts": time.time(), "data": data}


# ========== 数据源 ==========

def _fetch_eastmoney_search(keyword: str, page_size: int = 15) -> List[Dict]:
    """东方财富搜索 API — 按关键词搜索新闻"""
    news = []
    try:
        encoded_kw = urllib.parse.quote(keyword)
        url = (
            f"https://search-api-web.eastmoney.com/search/jsonp?"
            f"cb=jQuery&param=%7B%22uid%22%3A%22%22%2C%22keyword%22%3A%22{encoded_kw}%22"
            f"%2C%22type%22%3A%5B%22cmsArticleWebOld%22%5D"
            f"%2C%22client%22%3A%22web%22%2C%22clientType%22%3A%22web%22"
            f"%2C%22clientVersion%22%3A%22curr%22"
            f"%2C%22param%22%3A%7B%22cmsArticleWebOld%22%3A%7B%22searchScope%22%3A%22default%22"
            f"%2C%22sort%22%3A%22default%22%2C%22pageIndex%22%3A1%2C%22pageSize%22%3A{page_size}"
            f"%2C%22preTag%22%3A%22%22%2C%22postTag%22%3A%22%22%7D%7D%7D"
        )
        resp = requests.get(url, headers=_get_json_headers(), timeout=10)
        if resp.status_code == 200:
            match = re.search(r'jQuery\((\{.*\})\)', resp.text, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                cms = data.get("result", {}).get("cmsArticleWebOld", {})
                # API 可能返回 list 或 dict
                items = cms if isinstance(cms, list) else (cms.get("list", []) if isinstance(cms, dict) else [])
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    title = item.get("title", "").strip()
                    title = re.sub(r'<[^>]+>', '', title)  # 去除HTML标签
                    if title and len(title) > 6:
                        news.append({
                            "title": title,
                            "source": "东方财富",
                            "url": item.get("url", ""),
                            "time": item.get("date", ""),
                        })
        logger.info(f"东方财富搜索「{keyword}」: {len(news)} 条")
    except Exception as e:
        logger.warning(f"东方财富搜索「{keyword}」失败: {e}")
    return news


def _fetch_gov_cn() -> List[Dict]:
    """中国政府网 - 房地产相关政策文件"""
    news = []
    try:
        url = (
            "http://sousuo.www.gov.cn/search-gov/data?"
            "t=zhengce_gw&q=房地产&timetype=timeqb&mintime=&maxtime="
            "&sort=pubtime&sortType=1&searchfield=title&p=0&n=5"
        )
        resp = requests.get(url, headers=_get_json_headers(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            svo = data.get("searchVO")
            if svo and isinstance(svo, dict):
                items = svo.get("listVO", [])
                for item in items[:5]:
                    if not isinstance(item, dict):
                        continue
                    title = item.get("title", "").strip()
                    title = re.sub(r'<[^>]+>', '', title)
                    if title and len(title) > 6:
                        news.append({
                            "title": title,
                            "source": "中国政府网",
                            "url": item.get("url", ""),
                            "time": item.get("pubtimeStr", ""),
                        })
        logger.info(f"中国政府网: {len(news)} 条")
    except Exception as e:
        logger.warning(f"中国政府网获取失败: {e}")
    return news


# ========== AI 相关性筛选 ==========

async def _ai_filter_news(news_list: List[Dict], top_n: int = 5) -> List[Dict]:
    """
    用混元大模型对新闻进行相关性筛选
    筛选标准：只保留与房地产行业政策、调控、市场趋势高度相关的重要新闻
    """
    if len(news_list) <= top_n:
        return news_list

    # 构建新闻列表文本
    news_text = "\n".join(
        f"{i+1}. [{n['source']}] {n['title']}"
        for i, n in enumerate(news_list[:25])  # 最多送25条给AI筛选
    )

    prompt = f"""以下是今天获取到的房地产相关新闻列表，请从中筛选出最重要的{top_n}条，筛选标准：

1. 必须与中国房地产行业直接高度相关（政策调控、市场走势、房企动态、土地市场等）
2. 优先选择：中央/地方政府出台的房地产政策、重大市场数据（房价、销售额等）、头部房企重大事件
3. 排除：与房地产无关的一般财经新闻、广告软文、重复内容

新闻列表：
{news_text}

请直接返回筛选后的新闻编号（如"1,3,5,8,12"），只返回数字编号用逗号分隔，不要其他内容。"""

    try:
        result = await chat_hunyuan(prompt, temperature=0.1)
        if result:
            # 解析返回的编号
            result = result.strip()
            numbers = re.findall(r'\d+', result)
            selected_indices = []
            for num_str in numbers:
                idx = int(num_str) - 1  # 转为0-based
                if 0 <= idx < len(news_list):
                    selected_indices.append(idx)
            if selected_indices:
                filtered = [news_list[i] for i in selected_indices[:top_n]]
                logger.info(f"AI筛选: {len(news_list)}条 → {len(filtered)}条")
                return filtered
    except Exception as e:
        logger.warning(f"AI新闻筛选失败，使用关键词排序兜底: {e}")

    # AI不可用时的兜底：按来源权重+关键词密度排序
    return _keyword_rank_news(news_list, top_n)


def _keyword_rank_news(news_list: List[Dict], top_n: int = 5) -> List[Dict]:
    """基于来源权重和关键词密度的排序（AI不可用时的兜底）"""
    source_weight = {
        "中国政府网": 10,
        "人民网": 8,
        "新华网": 8,
        "新浪财经": 5,
        "东方财富": 4,
    }

    # 高权重关键词（政策类优先）
    policy_keywords = re.compile(
        r"限购|限贷|降息|LPR|首付|公积金|住建部|调控|政策|"
        r"保交楼|棚改|旧改|城中村|房产税|土地出让|土拍"
    )

    scored = []
    for n in news_list:
        score = source_weight.get(n["source"], 3)
        title = n["title"]
        # 政策关键词加分
        policy_matches = len(policy_keywords.findall(title))
        score += policy_matches * 3
        # 核心关键词匹配数
        core_matches = len(_RE_KEYWORDS.findall(title))
        score += core_matches
        scored.append((score, n))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:top_n]]


# ========== 获取所有新闻（聚合+去重） ==========

def fetch_all_industry_news() -> List[Dict]:
    """
    从多个数据源获取房地产行业新闻
    主力：东方财富搜索 API（多关键词）
    补充：中国政府网政策库
    返回去重后的新闻列表（尚未经过AI筛选）
    """
    cache_key = "all_industry_raw"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    all_news = []
    existing_titles = set()

    def _add_news(items: List[Dict]):
        for n in items:
            title = n["title"]
            if title in existing_titles:
                continue
            short = title[:15]
            if any(short == t[:15] for t in existing_titles):
                continue
            existing_titles.add(title)
            all_news.append(n)

    # 东方财富搜索 — 多关键词覆盖面更广
    search_keywords = ["房地产政策", "楼市", "房企"]
    for kw in search_keywords:
        try:
            items = _fetch_eastmoney_search(kw, page_size=15)
            _add_news(items)
        except Exception as e:
            logger.warning(f"东方财富搜索「{kw}」异常: {e}")

    # 中国政府网政策库（补充）
    try:
        gov_items = _fetch_gov_cn()
        _add_news(gov_items)
    except Exception as e:
        logger.warning(f"中国政府网异常: {e}")

    logger.info(f"新闻汇总: 共 {len(all_news)} 条（去重后）")
    _set_cache(cache_key, all_news)
    return all_news


async def fetch_filtered_news(top_n: int = 5) -> List[Dict]:
    """
    获取经过 AI 筛选的高质量房地产新闻
    返回 top_n 条最重要的新闻
    """
    cache_key = f"filtered_top{top_n}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    raw_news = fetch_all_industry_news()
    if not raw_news:
        return []

    # AI 筛选
    filtered = await _ai_filter_news(raw_news, top_n)
    _set_cache(cache_key, filtered)
    return filtered


# ========== 个股新闻 ==========

def fetch_stock_news(code: str, name: str, count: int = 5) -> List[Dict]:
    """获取个股相关新闻"""
    cache_key = f"stock_{code}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    news_list = []
    try:
        url = (
            f"https://search-api-web.eastmoney.com/search/jsonp?"
            f"cb=jQuery&param=%7B%22uid%22%3A%22%22%2C%22keyword%22%3A%22{name}%22"
            f"%2C%22type%22%3A%5B%22cmsArticleWebOld%22%5D"
            f"%2C%22client%22%3A%22web%22%2C%22clientType%22%3A%22web%22"
            f"%2C%22clientVersion%22%3A%22curr%22"
            f"%2C%22param%22%3A%7B%22cmsArticleWebOld%22%3A%7B%22searchScope%22%3A%22default%22"
            f"%2C%22sort%22%3A%22default%22%2C%22pageIndex%22%3A1%2C%22pageSize%22%3A{count}"
            f"%2C%22preTag%22%3A%22%22%2C%22postTag%22%3A%22%22%7D%7D%7D"
        )
        resp = requests.get(url, headers=_get_json_headers(), timeout=10)
        if resp.status_code == 200:
            text = resp.text
            match = re.search(r'jQuery\((\{.*\})\)', text, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                items = (
                    data.get("result", {})
                    .get("cmsArticleWebOld", {})
                    .get("list", [])
                )
                for item in items[:count]:
                    title = item.get("title", "").strip()
                    title = re.sub(r'<[^>]+>', '', title)
                    if title:
                        news_list.append({
                            "title": title,
                            "source": "东方财富",
                            "time": item.get("date", ""),
                            "url": item.get("url", ""),
                        })
    except Exception as e:
        logger.debug(f"获取{name}个股新闻失败: {e}")

    _set_cache(cache_key, news_list)
    return news_list


# ========== 供评级引擎调用 ==========

def get_real_estate_news_summary(code: str = "", name: str = "") -> str:
    """
    获取房地产行业新闻摘要，用于注入AI评级prompt
    这里使用原始新闻（不经过AI筛选，因为评级本身会做分析）
    """
    all_news = fetch_all_industry_news()

    stock_news = []
    if code and name:
        stock_news = fetch_stock_news(code, name, 5)

    lines = []
    today = datetime.now().strftime("%Y-%m-%d")

    if all_news:
        lines.append(f"【房地产行业最新资讯（{today}）】")
        for i, n in enumerate(all_news[:10], 1):
            time_str = f" ({n['time']})" if n.get("time") else ""
            lines.append(f"{i}. [{n['source']}] {n['title']}{time_str}")

    if stock_news:
        lines.append(f"\n【{name}({code})相关资讯】")
        for i, n in enumerate(stock_news[:5], 1):
            time_str = f" ({n['time']})" if n.get("time") else ""
            lines.append(f"{i}. {n['title']}{time_str}")

    if not lines:
        return ""

    return "\n".join(lines)
