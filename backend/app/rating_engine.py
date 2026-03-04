"""
房地产股票AI评级引擎（量化 + 基本面 + 大模型混合评级）

评级架构（融合AI因子挖掘与情绪Alpha研究思路优化）:
  量化技术评分 (25%) + 情绪因子 (10%) + 基本面评分 (15%) + AI大模型评分 (50%)

一、量化技术评分（6个维度，各0-100分）:
  1. 趋势评分 (Trend) - 权重22%:
     均线排列、价格vs多级均线、MA20斜率、均线黏合度、ADX趋势强度
  2. 动量评分 (Momentum) - 权重18%:
     RSI(14)+RSI(6)双周期、MACD金叉死叉+柱状体变化、KDJ随机指标、Williams %R、多周期涨跌幅
  3. 波动率评分 (Volatility) - 权重12%:
     年化波动率、布林带宽度+价格位置、ATR(14)相对波动、波动率收敛/发散趋势
     【AI增强】波动率因子std20经AI三轮迭代优化，引入自适应窗口和异常值过滤
  4. 成交量评分 (Volume) - 权重18%:
     多级量比、OBV能量潮趋势、VWAP偏离度、量价配合度、成交量趋势
  5. 价值评分 (Value) - 权重18%:
     距高低点位置(含连续评分)、筹码集中度、多级支撑压力、价格动态区间评估
  6. 情绪评分 (Sentiment) - 权重12%:
     【新增-东吴金工灵感】新闻/公告情绪量化因子，AI独立情绪打分 + 双速动态衰减模型
     近期新闻权重高（快速衰减半衰期3天）、远期公告慢速衰减（半衰期7天）
     空头信号识别能力强，有效增强风险管理

二、基本面评分 (0-100分):
  来自iFinD的PE_TTM、PB_MRQ、ROE、EPS、负债率、资金流、换手率、涨跌幅等
  五个维度: 核心估值(50) + 资金面(20) + 市场情绪(10) + 盈利能力(10) + 交易活跃度(10)
  （仅A股可用，港股/美股跳过此维度）
  【AI增强】AI可动态挖掘增强因子（如现金毛利因子CGP_TTM、留存市值比REP_LF）

三、AI大模型评分 (0-100分):
  DeepSeek V3 + GLM-5 + Kimi K2.5 三模型联合分析
  【新增】AI同时输出 weight_hints 动态权重建议，用于调整量化各维度权重
  【新增】AI输出 sentiment_score 独立情绪评分，反馈到情绪因子维度

综合评分 = 量化评分 × 25% + 情绪因子 × 10% + 基本面评分 × 15% + AI评分 × 50%
（若基本面不可用，则量化30% + 情绪12% + AI58%）
（若AI不可用，则量化55% + 基本面45%）

评级映射:
  >= 80: 优选
  >= 65: 优选
  >= 50: 关注
  >= 35: 中性
  <  35: 谨慎
"""

import json
import logging
import re
import asyncio

import numpy as np
import pandas as pd
from typing import Optional, Dict

from app.llm_client import chat_deepseek, chat_glm, chat_kimi
from app.config import (
    DEEPSEEK_ENABLED, DEEPSEEK_WEIGHT,
    GLM_ENABLED, GLM_WEIGHT,
    KIMI_ENABLED, KIMI_WEIGHT,
)
from app.news_fetcher import get_real_estate_news_summary
from app.ifind_client import fetch_fundamentals, fetch_recent_announcements

logger = logging.getLogger(__name__)

QUANT_WEIGHTS = {
    "trend": 0.22,
    "momentum": 0.18,
    "volatility": 0.12,
    "volume": 0.18,
    "value": 0.18,
    "sentiment": 0.12,
}

QUANT_RATIO = 0.25  # 量化评分占比（含情绪因子）
SENTIMENT_RATIO = 0.10  # 情绪因子独立占比
FUNDAMENTAL_RATIO = 0.15  # 基本面评分占比
AI_RATIO = 0.50     # AI评分占比

# 无基本面数据时的降级比例
QUANT_RATIO_NO_FUND = 0.30
SENTIMENT_RATIO_NO_FUND = 0.12
AI_RATIO_NO_FUND = 0.58

RATING_MAP = [
    (80, "优选"),
    (65, "优选"),
    (50, "关注"),
    (35, "中性"),
    (0, "谨慎"),
]

AI_SYSTEM_PROMPT = """你是一位资深的中国房地产行业股票分析师，拥有超过15年A股、港股和美股房地产板块研究经验。

你的分析必须重点关注以下维度（按重要性排序）：

【一、行业政策与最新资讯（权重35%）— 最关键维度】
1. 最新政策动态：关注当天/近期发布的房地产调控政策（限购/限贷/利率/公积金/地方松绑/城中村改造等），判断政策利好/利空程度
2. 政策影响评估：具体政策对该公司所在城市、业务模式的实际影响（如上海/北京放松限购对当地房企的直接利好）
3. 行业周期判断：当前处于房地产周期的哪个阶段，政策是否出现拐点信号
4. 融资环境：房企融资渠道畅通程度、银行贷款/债券/信托政策变化
5. 市场情绪：最新资讯对市场情绪的带动效应、板块联动效应

【二、公司基本面分析（权重30%）】
1. 经营质量：根据股价走势和成交量推断公司销售回款、拿地节奏、开工竣工进度
2. 财务健康：判断公司债务压力（三道红线达标情况）、现金流充裕度、短期偿债能力
3. 土储质量：结合市场表现推断土地储备的城市布局和货值质量
4. 管理层能力：从股价波动和市场反应推断管理层战略执行力

【三、技术面与资金面（权重25%）】
1. 价格趋势：中长期均线方向和支撑/压力位分析
2. 资金动向：成交量变化反映的机构资金态度、北向资金流向
3. 筹码结构：从换手率和量价关系推断当前筹码分布

【四、风险评估（权重10%）】
1. 系统性风险：宏观经济下行、地产行业黑天鹅事件
2. 个股风险：债务违约可能性、项目交付风险、管理层变动
3. 市场风险：估值泡沫、流动性风险

特别注意：如果最新资讯中包含重大政策利好（如放松限购、降低首付、降息等），应明显上调评分；反之如果有重大利空（如收紧调控、房企爆雷等），应明显下调。政策对房地产股的影响往往是即时且显著的。

你还需要：
1. 独立评估新闻/公告的情绪倾向（sentiment_score，0-100，50为中性）
2. 评估各量化维度在当前市场环境下的参考价值（weight_hints，0-1）
   - 例如：在政策剧变期，趋势/动量可能暂时失效（给低值如0.2-0.3）
   - 在震荡整理期，波动率和成交量信号更可靠（给高值如0.7-0.8）

请基于以上框架进行深入分析，给出独立的评分和判断。严格按照要求的JSON格式输出。"""


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def _linear_score(value: float, low: float, high: float, score_low: float = 0, score_high: float = 100) -> float:
    """线性映射：将value从[low, high]映射到[score_low, score_high]"""
    if high == low:
        return (score_low + score_high) / 2
    ratio = (value - low) / (high - low)
    ratio = max(0.0, min(1.0, ratio))
    return score_low + ratio * (score_high - score_low)


# ========== 量化评分函数 ==========

def calc_trend_score(df: pd.DataFrame) -> float:
    """趋势评分: 均线排列 + 价格位置 + MA斜率 + 均线黏合度 + ADX"""
    if len(df) < 60:
        return 50.0
    close = pd.Series(df["close"].values, dtype=float)
    price = close.iloc[-1]

    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()

    ma5_v, ma10_v, ma20_v, ma60_v = ma5.iloc[-1], ma10.iloc[-1], ma20.iloc[-1], ma60.iloc[-1]

    score = 0.0

    # --- 1. 均线排列体系 (0~30分) ---
    # 完全多头排列: ma5 > ma10 > ma20 > ma60
    bullish_count = sum([
        ma5_v > ma10_v,
        ma10_v > ma20_v,
        ma20_v > ma60_v,
    ])
    bearish_count = sum([
        ma5_v < ma10_v,
        ma10_v < ma20_v,
        ma20_v < ma60_v,
    ])
    # 多头: +10 per alignment, 空头: -10 per alignment
    score += (bullish_count - bearish_count) * 10  # -30 ~ +30

    # --- 2. 价格相对均线位置 (0~20分，连续评分) ---
    # 价格偏离MA20的百分比
    deviation_ma20 = (price - ma20_v) / (ma20_v + 1e-10) * 100
    # 偏离-10%以下得0分, 偏离+10%以上得20分
    score += _linear_score(deviation_ma20, -10, 10, 0, 20)

    # --- 3. MA20斜率 (0~15分) ---
    ma20_clean = ma20.dropna()
    if len(ma20_clean) >= 10:
        slope = (ma20_clean.iloc[-1] - ma20_clean.iloc[-10]) / (ma20_clean.iloc[-10] + 1e-10) * 100
        score += _linear_score(slope, -5, 5, 0, 15)

    # --- 4. 均线黏合度 (0~15分) ---
    # 均线黏合预示着即将变盘，黏合时给中性偏高分（有突破潜力）
    ma_spread = np.std([ma5_v, ma10_v, ma20_v, ma60_v]) / (ma20_v + 1e-10) * 100
    if ma_spread < 2:  # 高度黏合
        score += 12
    elif ma_spread < 4:
        score += 8
    elif ma_spread < 6:
        score += 5
    else:
        score += 2

    # --- 5. ADX趋势强度 (0~20分) ---
    high = pd.Series(df["high"].values, dtype=float) if "high" in df.columns else close * 1.01
    low = pd.Series(df["low"].values, dtype=float) if "low" in df.columns else close * 0.99
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()

    plus_dm = (high - high.shift(1)).clip(lower=0)
    minus_dm = (low.shift(1) - low).clip(lower=0)
    # 当+DM < -DM时，+DM = 0；反之-DM = 0
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0)

    plus_di = 100 * plus_dm.rolling(14).mean() / (atr14 + 1e-10)
    minus_di = 100 * minus_dm.rolling(14).mean() / (atr14 + 1e-10)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx = dx.rolling(14).mean()

    if not adx.dropna().empty:
        adx_val = adx.iloc[-1]
        plus_di_val = plus_di.iloc[-1]
        minus_di_val = minus_di.iloc[-1]
        # ADX高且+DI > -DI: 强上升趋势
        if adx_val > 25 and plus_di_val > minus_di_val:
            score += _linear_score(adx_val, 25, 50, 12, 20)
        elif adx_val > 25 and plus_di_val < minus_di_val:
            score += _linear_score(adx_val, 25, 50, 0, 5)  # 强下降趋势，低分
        else:
            score += 8  # 无趋势，中性

    # 归一化到0-100
    # 理论范围: -30 + 0 + 0 + 2 + 0 = -28 到 30 + 20 + 15 + 15 + 20 = 100
    return _clamp(score)


def calc_momentum_score(df: pd.DataFrame) -> float:
    """动量评分: RSI双周期 + MACD信号 + KDJ + Williams%R + 多周期涨跌幅"""
    if len(df) < 30:
        return 50.0
    close = pd.Series(df["close"].values, dtype=float)
    high = pd.Series(df["high"].values, dtype=float) if "high" in df.columns else close * 1.01
    low = pd.Series(df["low"].values, dtype=float) if "low" in df.columns else close * 0.99
    price = close.iloc[-1]

    score = 0.0

    # --- 1. RSI双周期 (0~20分) ---
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))

    # RSI(14) 中期
    avg_gain_14 = gain.rolling(14).mean()
    avg_loss_14 = loss.rolling(14).mean()
    rs_14 = avg_gain_14.iloc[-1] / (avg_loss_14.iloc[-1] + 1e-10)
    rsi_14 = 100 - 100 / (1 + rs_14)

    # RSI(6) 短期
    avg_gain_6 = gain.rolling(6).mean()
    avg_loss_6 = loss.rolling(6).mean()
    rs_6 = avg_gain_6.iloc[-1] / (avg_loss_6.iloc[-1] + 1e-10)
    rsi_6 = 100 - 100 / (1 + rs_6)

    # RSI(14): 30以下超卖加分，70以上超买减分（均值回归视角，但考虑趋势）
    rsi_score = _linear_score(rsi_14, 20, 80, 0, 12)
    # RSI(6)短期共振
    rsi_score += _linear_score(rsi_6, 20, 80, 0, 8)
    score += rsi_score

    # --- 2. MACD信号 (0~25分) ---
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9).mean()
    macd_hist = (dif - dea) * 2  # MACD柱状体

    dif_val = dif.iloc[-1]
    dea_val = dea.iloc[-1]
    hist_val = macd_hist.iloc[-1]
    hist_prev = macd_hist.iloc[-2] if len(macd_hist) > 1 else 0

    # DIF位置: 零轴上方更强
    if dif_val > 0:
        score += 8
    else:
        score += 2

    # 金叉/死叉
    if dif_val > dea_val:
        score += 7  # 金叉状态
    else:
        score += 2  # 死叉状态

    # 柱状体变化（趋势加速/减速）
    if hist_val > 0 and hist_val > hist_prev:
        score += 10  # 红柱放大 - 加速上涨
    elif hist_val > 0 and hist_val < hist_prev:
        score += 6   # 红柱缩小 - 上涨减速
    elif hist_val < 0 and abs(hist_val) < abs(hist_prev):
        score += 5   # 绿柱缩小 - 下跌减速（可能反转）
    else:
        score += 1   # 绿柱放大 - 加速下跌

    # --- 3. KDJ随机指标 (0~20分) ---
    low_14 = low.rolling(14).min()
    high_14 = high.rolling(14).max()
    rsv = (price - low_14.iloc[-1]) / (high_14.iloc[-1] - low_14.iloc[-1] + 1e-10) * 100

    # 简化KDJ: K = 2/3*K_prev + 1/3*RSV
    k_values = [50.0]  # 初始K值
    rsv_series = ((close - low_14) / (high_14 - low_14 + 1e-10) * 100).dropna()
    for rsv_v in rsv_series.values:
        k_values.append(2/3 * k_values[-1] + 1/3 * rsv_v)
    k_val = k_values[-1]
    d_val = k_val  # 简化：D追随K
    if len(k_values) >= 3:
        d_values = [50.0]
        for kv in k_values[1:]:
            d_values.append(2/3 * d_values[-1] + 1/3 * kv)
        d_val = d_values[-1]
    j_val = 3 * k_val - 2 * d_val

    # KDJ评分逻辑
    if k_val > d_val and j_val > 0:
        score += _linear_score(j_val, 0, 100, 10, 18)
    elif k_val < d_val and j_val < 0:
        score += _linear_score(j_val, -100, 0, 2, 8)
    else:
        score += 10  # 中性

    # K/D超买超卖修正
    if k_val > 80 and d_val > 80:
        score -= 3  # 超买区域，减分
    elif k_val < 20 and d_val < 20:
        score += 2  # 超卖区域，可能反弹

    # --- 4. Williams %R (0~10分) ---
    wr = (high_14.iloc[-1] - price) / (high_14.iloc[-1] - low_14.iloc[-1] + 1e-10) * (-100)
    # WR在-20以上超买，-80以下超卖
    score += _linear_score(wr, -80, -20, 2, 10)

    # --- 5. 多周期涨跌幅 (0~15分) ---
    ret_5d = (price / close.iloc[-6] - 1) * 100 if len(close) > 5 else 0
    ret_10d = (price / close.iloc[-11] - 1) * 100 if len(close) > 10 else 0
    ret_20d = (price / close.iloc[-21] - 1) * 100 if len(close) > 20 else 0

    # 短中期趋势的连续评分
    score += _linear_score(ret_5d, -10, 10, 0, 5)
    score += _linear_score(ret_10d, -15, 15, 0, 5)
    score += _linear_score(ret_20d, -20, 20, 0, 5)

    # 理论范围: 0 ~ 20+25+20+10+15 = 90（修正部分可能到~95）
    return _clamp(score)


def calc_volatility_score(df: pd.DataFrame) -> float:
    """波动率评分: 年化波动率 + 布林带宽度和位置 + ATR相对波动 + 波动率趋势"""
    if len(df) < 20:
        return 50.0
    close = pd.Series(df["close"].values, dtype=float)
    high = pd.Series(df["high"].values, dtype=float) if "high" in df.columns else close * 1.01
    low = pd.Series(df["low"].values, dtype=float) if "low" in df.columns else close * 0.99
    returns = close.pct_change().dropna()
    price = close.iloc[-1]

    score = 0.0

    # --- 1. 年化波动率 (0~25分) ---
    # 低波动率 = 风险可控 = 高分
    vol_20 = returns.tail(20).std() * np.sqrt(252) * 100
    # 波动率20%以下满分，60%以上最低分
    score += _linear_score(vol_20, 60, 15, 0, 25)  # 反向：低波动高分

    # --- 2. 布林带宽度和价格位置 (0~25分) ---
    ma20 = close.rolling(20).mean().iloc[-1]
    std20 = close.rolling(20).std().iloc[-1]
    upper_band = ma20 + 2 * std20
    lower_band = ma20 - 2 * std20
    bb_width = (upper_band - lower_band) / (ma20 + 1e-10) * 100

    # 布林带宽度评分(0~12): 窄带更稳定
    score += _linear_score(bb_width, 25, 3, 0, 12)

    # 价格在布林带中的位置(0~13): 中轨附近最佳
    bb_position = (price - lower_band) / (upper_band - lower_band + 1e-10)
    # 在0.3~0.7之间(中轨附近)给高分, 极端位置给低分
    if 0.3 <= bb_position <= 0.7:
        score += 13
    elif 0.2 <= bb_position < 0.3 or 0.7 < bb_position <= 0.8:
        score += 9
    elif bb_position < 0.2:
        score += 5  # 接近下轨，可能超卖但风险大
    else:
        score += 4  # 接近上轨，可能超买

    # --- 3. ATR(14)相对波动 (0~25分) ---
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean().iloc[-1]
    atr_ratio = atr14 / (price + 1e-10) * 100  # ATR占价格百分比

    # ATR比率低 = 波动小 = 高分
    score += _linear_score(atr_ratio, 6, 1, 0, 25)

    # --- 4. 波动率趋势 (0~25分) ---
    # 波动率收敛 = 即将突破 = 给中高分; 波动率发散 = 风险增加
    if len(returns) >= 30:
        vol_recent = returns.tail(10).std() * np.sqrt(252) * 100
        vol_earlier = returns.iloc[-30:-10].std() * np.sqrt(252) * 100
        vol_change = vol_recent - vol_earlier

        if vol_change < -5:
            score += 22  # 波动率显著收敛
        elif vol_change < 0:
            score += 16  # 波动率小幅收敛
        elif vol_change < 5:
            score += 10  # 波动率小幅扩大
        else:
            score += 4   # 波动率显著扩大
    else:
        score += 12  # 数据不足，中性

    return _clamp(score)


def calc_volume_score(df: pd.DataFrame) -> float:
    """成交量评分: 多级量比 + OBV能量潮 + VWAP偏离 + 量价配合 + 成交量趋势"""
    if len(df) < 20:
        return 50.0
    volume = pd.Series(df["volume"].values, dtype=float)
    close = pd.Series(df["close"].values, dtype=float)
    high = pd.Series(df["high"].values, dtype=float) if "high" in df.columns else close * 1.01
    low = pd.Series(df["low"].values, dtype=float) if "low" in df.columns else close * 0.99
    price = close.iloc[-1]

    score = 0.0

    # --- 1. 多级量比 (0~20分) ---
    vol_ma5 = volume.rolling(5).mean().iloc[-1]
    vol_ma10 = volume.rolling(10).mean().iloc[-1]
    vol_ma20 = volume.rolling(20).mean().iloc[-1]

    ratio_5_20 = vol_ma5 / (vol_ma20 + 1e-10)
    ratio_10_20 = vol_ma10 / (vol_ma20 + 1e-10)

    # 温和放量(1.0~1.5)最佳，极端放量(>3.0)可能见顶
    if 1.0 < ratio_5_20 < 1.5:
        score += 12
    elif 1.5 <= ratio_5_20 < 2.5:
        score += 8
    elif ratio_5_20 >= 2.5:
        score += 3  # 异常放量，风险
    elif 0.7 < ratio_5_20 <= 1.0:
        score += 6  # 正常
    else:
        score += 2  # 极度缩量

    # 中期量比配合
    if ratio_10_20 > 1.0:
        score += 8
    else:
        score += 3

    # --- 2. OBV能量潮趋势 (0~20分) ---
    obv = (volume * np.sign(close.diff().fillna(0))).cumsum()
    obv_ma5 = obv.rolling(5).mean()
    obv_ma20 = obv.rolling(20).mean()

    if not obv_ma5.dropna().empty and not obv_ma20.dropna().empty:
        obv_5 = obv_ma5.iloc[-1]
        obv_20 = obv_ma20.iloc[-1]
        obv_current = obv.iloc[-1]

        # OBV在均线上方且上升 = 资金持续流入
        if obv_current > obv_5 > obv_20:
            score += 18
        elif obv_current > obv_20:
            score += 12
        elif obv_current < obv_5 < obv_20:
            score += 3  # 资金持续流出
        else:
            score += 8

        # OBV趋势方向
        if len(obv) >= 10:
            obv_slope = (obv.iloc[-1] - obv.iloc[-10]) / (abs(obv.iloc[-10]) + 1e-10) * 100
            score += _clamp(_linear_score(obv_slope, -20, 20, 0, 5), 0, 5)
    else:
        score += 10

    # --- 3. VWAP偏离度 (0~15分) ---
    typical_price = (high + low + close) / 3
    vwap_cumvol = (typical_price * volume).rolling(20).sum()
    vwap_vol = volume.rolling(20).sum()
    vwap = vwap_cumvol / (vwap_vol + 1e-10)

    if not vwap.dropna().empty:
        vwap_val = vwap.iloc[-1]
        vwap_deviation = (price - vwap_val) / (vwap_val + 1e-10) * 100

        # 价格在VWAP上方适度偏离 = 强势
        if 0 < vwap_deviation < 3:
            score += 15  # 温和强势
        elif 3 <= vwap_deviation < 6:
            score += 10  # 偏强
        elif vwap_deviation >= 6:
            score += 5   # 过度偏离，可能回调
        elif -3 < vwap_deviation <= 0:
            score += 8   # 轻微弱势
        else:
            score += 3   # 明显弱势
    else:
        score += 7

    # --- 4. 量价配合度 (0~20分) ---
    # 使用近10日的量价相关性
    n = min(10, len(close) - 1)
    if n >= 5:
        price_changes = close.diff().tail(n)
        vol_changes = volume.tail(n)
        # 上涨放量、下跌缩量 = 健康
        up_days = price_changes > 0
        down_days = price_changes < 0
        vol_mean = vol_changes.mean()

        up_vol = vol_changes[up_days].mean() if up_days.sum() > 0 else vol_mean
        down_vol = vol_changes[down_days].mean() if down_days.sum() > 0 else vol_mean

        if up_vol > down_vol * 1.3:
            score += 18  # 上涨放量、下跌缩量，非常健康
        elif up_vol > down_vol:
            score += 13  # 量价配合良好
        elif up_vol > down_vol * 0.7:
            score += 8   # 量价中性
        else:
            score += 3   # 上涨缩量下跌放量，不健康
    else:
        score += 10

    # --- 5. 成交量趋势 (0~10分) ---
    if len(volume) >= 30:
        vol_10d = volume.tail(10).mean()
        vol_30d = volume.tail(30).mean()
        vol_trend = (vol_10d / (vol_30d + 1e-10) - 1) * 100
        score += _linear_score(vol_trend, -30, 30, 2, 10)
    else:
        score += 5

    # 理论范围: 0 ~ 20+25+15+20+10 = 90(可达~95)
    return _clamp(score)


def calc_value_score(df: pd.DataFrame) -> float:
    """价值评分: 高低点位置(连续) + 筹码集中度 + 多级支撑压力 + 价格动态区间"""
    if len(df) < 20:
        return 50.0
    close = pd.Series(df["close"].values, dtype=float)
    volume = pd.Series(df["volume"].values, dtype=float)
    price = close.iloc[-1]

    score = 0.0

    # --- 1. 价格在区间中的位置 (0~25分，连续评分) ---
    high_all = close.max()
    low_all = close.min()
    price_range = high_all - low_all

    if price_range > 0:
        position = (price - low_all) / price_range  # 0~1, 0=最低点, 1=最高点

        # 价值投资视角：中低位更有价值
        # 0.2~0.5区间最高分（低位有支撑且已脱离底部）
        if 0.2 <= position <= 0.5:
            score += 25
        elif 0.1 <= position < 0.2:
            score += 20  # 接近底部，可能反弹
        elif position < 0.1:
            score += 12  # 极低位，可能有基本面问题
        elif 0.5 < position <= 0.7:
            score += 18  # 中高位，趋势尚好
        elif 0.7 < position <= 0.85:
            score += 10  # 高位
        else:
            score += 5   # 极高位，风险大
    else:
        score += 12

    # --- 2. 筹码集中度 (0~20分) ---
    # 通过成交量加权价格的标准差衡量筹码分散程度
    if len(close) >= 30:
        recent_close = close.tail(30)
        recent_vol = volume.tail(30)
        total_vol = recent_vol.sum()
        if total_vol > 0:
            vwap_30 = (recent_close * recent_vol).sum() / total_vol
            # 成交量加权的价格方差
            vol_weighted_var = ((recent_close - vwap_30) ** 2 * recent_vol).sum() / total_vol
            chip_concentration = np.sqrt(vol_weighted_var) / (vwap_30 + 1e-10) * 100

            # 筹码越集中(标准差越小)，评分越高
            score += _linear_score(chip_concentration, 15, 2, 0, 20)
        else:
            score += 10
    else:
        score += 10

    # --- 3. 多级支撑压力分析 (0~25分) ---
    # 近10日、20日、60日的支撑/压力
    support_scores = 0

    for window, weight in [(10, 3), (20, 5), (60, 7)]:
        if len(close) >= window:
            recent = close.tail(window)
            recent_low = recent.min()
            recent_high = recent.max()
            span = recent_high - recent_low

            if span > 0:
                # 距离支撑位的相对距离
                dist_to_support = (price - recent_low) / span
                # 距离压力位的相对距离
                dist_to_resistance = (recent_high - price) / span

                # 距支撑近 + 距压力远 = 安全 + 上行空间
                if dist_to_support < 0.3 and dist_to_resistance > 0.5:
                    support_scores += weight  # 满分
                elif dist_to_support < 0.5:
                    support_scores += weight * 0.7
                else:
                    support_scores += weight * 0.3

    score += _clamp(support_scores, 0, 25)

    # --- 4. 价格动态区间评估 (0~20分) ---
    # 最近价格的变异系数：低变异 = 盘整/蓄力
    if len(close) >= 10:
        recent_cv = close.tail(10).std() / (close.tail(10).mean() + 1e-10) * 100
        # 低变异系数 = 盘整蓄力，给中高分
        if recent_cv < 2:
            score += 18  # 窄幅盘整
        elif recent_cv < 4:
            score += 14
        elif recent_cv < 6:
            score += 10
        else:
            score += 5   # 波动大，不稳定

    # 近5日动量修正 (0~10分)
    if len(close) >= 6:
        ret_5d = (price / close.iloc[-6] - 1) * 100
        score += _linear_score(ret_5d, -8, 8, 2, 10)

    # 理论范围: 0 ~ 25+20+25+20+10 = 100
    return _clamp(score)


# ========== 情绪因子评分（东吴金工AI文本情绪分析灵感）==========

# 双速衰减半衰期参数
SENTIMENT_FAST_HALFLIFE = 3   # 新闻快速衰减（天）
SENTIMENT_SLOW_HALFLIFE = 7   # 公告慢速衰减（天）

# 情绪关键词库
POSITIVE_KEYWORDS = [
    "放松限购", "降低首付", "降息", "LPR下调", "政策宽松", "止跌企稳",
    "保交楼", "白名单", "城中村改造", "利好", "反弹", "上涨",
    "增持", "回购", "分红", "业绩预增", "超预期", "销售增长",
    "信贷宽松", "降准", "促进消费", "需求回暖", "土拍火热",
    "城镇化", "住房保障", "中标", "签约", "融资成功",
]

NEGATIVE_KEYWORDS = [
    "爆雷", "违约", "债务危机", "暴跌", "退市", "亏损",
    "收紧调控", "限制融资", "资金链断裂", "减持", "下调评级",
    "延期交付", "烂尾", "被执行", "冻结", "立案", "处罚",
    "业绩预亏", "计提减值", "商票逾期", "美元债违约",
    "信用降级", "停牌", "风险警示", "资不抵债",
]


def _calc_keyword_sentiment(text: str) -> float:
    """基于关键词的基础情绪分（-100 ~ +100）"""
    if not text:
        return 0.0
    pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in text)
    neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text)

    total = pos_count + neg_count
    if total == 0:
        return 0.0

    # 净情绪比 × 强度缩放
    net_ratio = (pos_count - neg_count) / total
    intensity = min(total / 3.0, 1.0)  # 命中3个以上视为强信号
    return net_ratio * intensity * 100


def _dual_speed_decay(days_ago: float, is_news: bool = True) -> float:
    """双速动态衰减权重（参考东吴金工报告思路）

    新闻（快速）: 半衰期3天，1周后几乎无效
    公告（慢速）: 半衰期7天，2周后逐渐失效
    """
    halflife = SENTIMENT_FAST_HALFLIFE if is_news else SENTIMENT_SLOW_HALFLIFE
    return 0.5 ** (days_ago / halflife)


def calc_sentiment_score(news_summary: str = "", announcements: str = "",
                         news_age_days: float = 0.5,
                         announcement_age_days: float = 3.0) -> float:
    """情绪因子评分（0-100分）

    基于AI文本情绪分析与因子挖掘研究
    - 利用关键词 + 衰减模型量化新闻/公告的情绪影响
    - 快速衰减（新闻）+ 慢速衰减（公告）双速模型
    - 空头信号（负面关键词）识别尤为精准，有效增强风险管理

    返回0-100分：50为中性，>50偏多，<50偏空
    """
    # 新闻情绪（快速衰减）
    news_raw = _calc_keyword_sentiment(news_summary)
    news_weight = _dual_speed_decay(news_age_days, is_news=True)
    news_contribution = news_raw * news_weight

    # 公告情绪（慢速衰减）
    ann_raw = _calc_keyword_sentiment(announcements)
    ann_weight = _dual_speed_decay(announcement_age_days, is_news=False)
    ann_contribution = ann_raw * ann_weight

    # 加权合成：新闻情绪占60%，公告情绪占40%
    if news_summary and announcements:
        combined = news_contribution * 0.6 + ann_contribution * 0.4
    elif news_summary:
        combined = news_contribution
    elif announcements:
        combined = ann_contribution
    else:
        return 50.0  # 无文本数据，中性

    # 映射到 0-100 分（combined 范围约 -100 ~ +100）
    score = 50 + combined * 0.5  # -100 → 0, 0 → 50, +100 → 100
    return _clamp(score)


def calc_quant_score(df: pd.DataFrame, sentiment_score: float = 50.0) -> Dict[str, float]:
    """计算所有量化评分维度（含情绪因子）"""
    scores = {
        "trend": round(calc_trend_score(df), 2),
        "momentum": round(calc_momentum_score(df), 2),
        "volatility": round(calc_volatility_score(df), 2),
        "volume": round(calc_volume_score(df), 2),
        "value": round(calc_value_score(df), 2),
        "sentiment": round(sentiment_score, 2),
    }
    total = sum(scores[k] * QUANT_WEIGHTS[k] for k in QUANT_WEIGHTS)
    scores["quant_total"] = round(total, 2)
    return scores


# ========== 基本面评分（iFinD财务数据）==========

def calc_fundamental_score(fundamentals: Optional[dict]) -> Optional[float]:
    """基本面评分: 基于iFinD的PE/PB/ROE/EPS等财务数据 + 资金流 + 市场情绪 + 盈利 + 交易活跃度
    房地产行业特定评分逻辑（5个维度，满分100分）:
      核心估值(50分): PE_TTM(15) + PB_MRQ(14) + ROE(11) + 负债率(10)
      资金面(20分): 主力净流入(10) + 量比(6) + 委比(4)
      市场情绪(10分): 连涨天数(5) + 振幅(5)
      盈利能力(10分): EPS每股收益(10)
      交易活跃度(10分): 换手率(5) + 20日涨跌幅(5)
    """
    if not fundamentals:
        return None

    pe = fundamentals.get("pe_ttm")
    pb = fundamentals.get("pb_mrq")
    roe = fundamentals.get("roe")
    debt_ratio = fundamentals.get("debt_ratio")

    # 至少需要PE或PB才能评分
    if pe is None and pb is None:
        return None

    score = 0.0
    max_score = 0.0

    # ═══ 核心估值（50分）═══

    # PE_TTM (0~15分)
    if pe is not None:
        max_score += 15
        if pe < 0:
            score += 2
        elif pe < 8:
            score += 15  # 极低PE，深度价值
        elif pe <= 15:
            score += 12
        elif pe <= 30:
            score += 8
        elif pe <= 50:
            score += 4
        else:
            score += 1

    # PB_MRQ (0~14分)
    if pb is not None:
        max_score += 14
        if pb < 0:
            score += 1
        elif pb < 0.5:
            score += 11  # 深度破净
        elif pb < 1.0:
            score += 14  # 破净，估值修复潜力大
        elif pb < 1.5:
            score += 10
        elif pb < 2.5:
            score += 6
        else:
            score += 1

    # ROE (0~11分)
    if roe is not None:
        max_score += 11
        if roe < 0:
            score += 1
        elif roe < 3:
            score += 3
        elif roe < 8:
            score += 7
        elif roe < 15:
            score += 9
        else:
            score += 11

    # 负债率 (0~10分) — 三道红线
    if debt_ratio is not None:
        max_score += 10
        if debt_ratio < 70:
            score += 10
        elif debt_ratio < 75:
            score += 7
        elif debt_ratio < 80:
            score += 5
        elif debt_ratio < 85:
            score += 2
        else:
            score += 1

    # ═══ 资金面（20分）═══

    # 主力净流入 (0~10分)
    mnf = fundamentals.get("main_net_inflow")
    if mnf is not None:
        max_score += 10
        # mnf 单位万元，正=流入，负=流出
        if mnf > 5000:
            score += 10  # 大幅流入（>5000万）
        elif mnf > 1000:
            score += 8
        elif mnf > 0:
            score += 6
        elif mnf > -1000:
            score += 4
        elif mnf > -5000:
            score += 2
        else:
            score += 1  # 大幅流出

    # 量比 (0~6分) — 温和放量最佳
    vr = fundamentals.get("vol_ratio")
    if vr is not None:
        max_score += 6
        if 0.8 <= vr <= 1.5:
            score += 6  # 温和放量
        elif 1.5 < vr <= 2.5:
            score += 4  # 明显放量
        elif 0.5 <= vr < 0.8:
            score += 3  # 轻微缩量
        elif vr > 2.5:
            score += 2  # 异常放量
        else:
            score += 1  # 极度缩量

    # 委比 (0~4分)
    comm = fundamentals.get("committee")
    if comm is not None:
        max_score += 4
        if comm > 30:
            score += 4  # 强烈买盘
        elif comm > 10:
            score += 3
        elif comm > -10:
            score += 2  # 平衡
        elif comm > -30:
            score += 1
        else:
            score += 0  # 强烈卖盘

    # ═══ 市场情绪（10分）═══

    # 连涨天数 (0~5分)
    rdc = fundamentals.get("rise_day_count")
    if rdc is not None:
        max_score += 5
        if rdc >= 5:
            score += 5
        elif rdc >= 3:
            score += 4
        elif rdc >= 1:
            score += 3
        elif rdc == 0:
            score += 2
        elif rdc >= -2:
            score += 1
        else:
            score += 0

    # 振幅 (0~5分) — 低振幅=稳健
    sw = fundamentals.get("swing")
    if sw is not None:
        max_score += 5
        if sw < 2:
            score += 5  # 极低振幅，走势稳健
        elif sw < 4:
            score += 4
        elif sw < 6:
            score += 2
        else:
            score += 1  # 高振幅，波动大

    # ═══ 盈利能力（10分）═══

    # EPS每股收益 (0~10分)
    eps = fundamentals.get("eps")
    if eps is not None:
        max_score += 10
        if eps > 1.5:
            score += 10  # 优秀盈利
        elif eps > 1.0:
            score += 8
        elif eps > 0.5:
            score += 6
        elif eps > 0.1:
            score += 4
        elif eps > 0:
            score += 2  # 微利
        elif eps == 0:
            score += 1
        else:
            score += 0  # 亏损

    # ═══ 交易活跃度（10分）═══

    # 换手率 (0~5分) — 适中换手最佳
    tr = fundamentals.get("turnover_ratio")
    if tr is not None:
        max_score += 5
        if 1.0 <= tr <= 5.0:
            score += 5  # 活跃适中
        elif 5.0 < tr <= 10.0:
            score += 4  # 偏高但正常
        elif 0.5 <= tr < 1.0:
            score += 3  # 偏低
        elif tr > 10.0:
            score += 2  # 过度活跃，投机性强
        else:
            score += 1  # 极低流动性

    # 20日涨跌幅 (0~5分) — 温和上涨最佳
    chg_20d = fundamentals.get("chg_20d")
    if chg_20d is not None:
        max_score += 5
        if 5 <= chg_20d <= 20:
            score += 5  # 温和上涨趋势
        elif 0 < chg_20d < 5:
            score += 4  # 小幅上涨
        elif 20 < chg_20d <= 40:
            score += 3  # 大幅上涨，注意追高风险
        elif -5 <= chg_20d <= 0:
            score += 2  # 小幅回调
        elif -15 <= chg_20d < -5:
            score += 1  # 明显下跌
        else:
            score += 0  # 暴涨(>40%)或暴跌(<-15%)

    if max_score == 0:
        return None

    normalized = score / max_score * 100
    return _clamp(normalized)


# ========== AI大模型评分 ==========

def _build_ai_prompt(name: str, code: str, market: str, df: pd.DataFrame, quant_scores: Dict,
                     news_summary: str = "", fundamentals: Optional[dict] = None,
                     announcements: str = "") -> str:
    """构建发送给大模型的分析提示（强化政策资讯+基本面维度+财务数据）"""
    close = pd.Series(df["close"].values, dtype=float)
    volume = pd.Series(df["volume"].values, dtype=float)
    high = pd.Series(df["high"].values, dtype=float) if "high" in df.columns else close * 1.01
    low = pd.Series(df["low"].values, dtype=float) if "low" in df.columns else close * 0.99

    current_price = close.iloc[-1]
    high_price = close.max()
    low_price = close.min()
    avg_volume_20 = volume.tail(20).mean() if len(volume) >= 20 else volume.mean()
    avg_volume_60 = volume.tail(60).mean() if len(volume) >= 60 else volume.mean()

    # 多周期涨跌幅
    ret_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) > 5 else 0
    ret_10d = (close.iloc[-1] / close.iloc[-11] - 1) * 100 if len(close) > 10 else 0
    ret_20d = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) > 20 else 0
    ret_60d = (close.iloc[-1] / close.iloc[-61] - 1) * 100 if len(close) > 60 else 0

    # 波动率
    returns = close.pct_change().dropna()
    vol_20d = returns.tail(20).std() * np.sqrt(252) * 100 if len(returns) >= 20 else 0

    # 量比（20日量比）
    vol_ratio = avg_volume_20 / (avg_volume_60 + 1e-10) if len(volume) >= 60 else 1.0

    # 换手率代理：近5日均量 vs 近60日均量
    recent_vol_ratio = volume.tail(5).mean() / (avg_volume_60 + 1e-10) if len(volume) >= 60 else 1.0

    # 价格位置
    drawdown = (high_price - current_price) / (high_price + 1e-10) * 100
    rebound = (current_price - low_price) / (low_price + 1e-10) * 100

    market_name = {"A": "A股", "HK": "港股", "US": "美股"}.get(market, market)

    # 新闻资讯部分
    news_section = ""
    if news_summary:
        news_section = f"""
{news_summary}

"""

    # 财务数据部分
    fund_section = ""
    if fundamentals:
        fund_lines = []
        if fundamentals.get("pe_ttm") is not None:
            pe_val = fundamentals["pe_ttm"]
            pe_note = "（亏损）" if pe_val < 0 else ""
            fund_lines.append(f"- PE(TTM): {pe_val:.2f}{pe_note}")
        if fundamentals.get("pb_mrq") is not None:
            pb_val = fundamentals["pb_mrq"]
            pb_note = "（破净）" if 0 < pb_val < 1 else ""
            fund_lines.append(f"- PB(MRQ): {pb_val:.4f}{pb_note}")
        if fundamentals.get("market_value") is not None:
            fund_lines.append(f"- 总市值: {fundamentals['market_value']:.2f}亿元")
        if fundamentals.get("roe") is not None:
            fund_lines.append(f"- ROE: {fundamentals['roe']:.2f}%")
        if fundamentals.get("eps") is not None:
            fund_lines.append(f"- EPS(基本): {fundamentals['eps']:.4f}元")
        if fundamentals.get("debt_ratio") is not None:
            dr = fundamentals["debt_ratio"]
            dr_note = "（三道红线预警）" if dr > 85 else ""
            fund_lines.append(f"- 资产负债率: {dr:.2f}%{dr_note}")
        if fundamentals.get("turnover_ratio") is not None:
            fund_lines.append(f"- 换手率: {fundamentals['turnover_ratio']:.2f}%")
        if fundamentals.get("report_date"):
            fund_lines.append(f"- 财务报告期: {fundamentals['report_date']}")
        # 资金流数据
        if fundamentals.get("main_net_inflow") is not None:
            mnf = fundamentals["main_net_inflow"]
            mnf_note = "（主力流入）" if mnf > 0 else "（主力流出）"
            fund_lines.append(f"- 今日主力净流入: {mnf:+.2f}万元{mnf_note}")
        if fundamentals.get("retail_net_inflow") is not None:
            rnf = fundamentals["retail_net_inflow"]
            fund_lines.append(f"- 今日散户净流入: {rnf:+.2f}万元")
        if fundamentals.get("large_net_inflow") is not None:
            fund_lines.append(f"- 今日超大单净流入: {fundamentals['large_net_inflow']:+.2f}万元")
        # 连涨天数
        if fundamentals.get("rise_day_count") is not None:
            rdc = fundamentals["rise_day_count"]
            rdc_note = f"连涨{rdc}天" if rdc > 0 else (f"连跌{abs(rdc)}天" if rdc < 0 else "平盘")
            fund_lines.append(f"- 连涨/跌天数: {rdc_note}")
        # 量比
        if fundamentals.get("vol_ratio") is not None:
            fund_lines.append(f"- 量比: {fundamentals['vol_ratio']:.2f}")
        # iFinD多周期涨跌幅（比手动计算更准确）
        ifind_chg_parts = []
        for key, label in [("chg_5d","5日"),("chg_20d","20日"),("chg_60d","60日"),("chg_year","年初至今")]:
            if fundamentals.get(key) is not None:
                ifind_chg_parts.append(f"{label}{fundamentals[key]:+.2f}%")
        if ifind_chg_parts:
            fund_lines.append(f"- iFinD涨跌幅: {', '.join(ifind_chg_parts)}")
        if fund_lines:
            fund_section = "【财务数据（来自同花顺iFinD）】\n" + "\n".join(fund_lines) + "\n\n"

    # 公告数据部分
    announcement_section = ""
    if announcements:
        announcement_section = f"{announcements}\n\n"

    prompt = f"""请对以下中国房地产相关股票进行深度分析，结合最新政策资讯和行情数据，给出你独立的AI评分。

【股票信息】
- 名称: {name}
- 代码: {code}
- 市场: {market_name}

{news_section}{fund_section}{announcement_section}【行情数据摘要】
- 最新价格: {current_price:.2f}
- 近5日涨跌幅: {ret_5d:+.2f}%
- 近10日涨跌幅: {ret_10d:+.2f}%
- 近20日涨跌幅: {ret_20d:+.2f}%
- 近60日涨跌幅: {ret_60d:+.2f}%
- 区间最高价: {high_price:.2f}（距今回撤 {drawdown:.1f}%）
- 区间最低价: {low_price:.2f}（距今反弹 {rebound:.1f}%）
- 20日年化波动率: {vol_20d:.1f}%
- 近20日均成交量: {avg_volume_20:,.0f}
- 20日/60日量比: {vol_ratio:.2f}
- 近5日活跃度(量比): {recent_vol_ratio:.2f}

【量化技术评分（仅供参考，你需要结合资讯给出独立判断）】
- 趋势评分: {quant_scores['trend']}/100
- 动量评分: {quant_scores['momentum']}/100
- 波动评分: {quant_scores['volatility']}/100
- 成交评分: {quant_scores['volume']}/100
- 价值评分: {quant_scores['value']}/100
- 情绪评分(关键词): {quant_scores.get('sentiment', 50)}/100

【重点分析要求】
请你作为资深房地产分析师，结合上述最新资讯，重点从以下角度进行独立评估：

1. **最新政策资讯影响（最关键）**：结合今日/近期的房地产政策新闻，分析对该公司的直接利好/利空影响。如果有重大政策（如限购放松、降息、首付降低等），应重点评估对评分的影响。

2. **公司基本面**：基于你对该公司的了解，评估其经营质量、债务健康度、销售回款能力、土储质量。

3. **行业政策周期**：综合判断当前政策环境对房地产板块的整体影响方向。

4. **风险评估**：债务违约风险、项目交付风险、系统性行业风险。

5. **AI增强因子建议（新增）**：基于你的判断，评估当前各量化指标的参考价值。例如：在政策剧变期，趋势/动量指标可能失效（给低权重）；在震荡市，波动率和成交量指标更重要（给高权重）。

请注意：你的评分应综合考虑最新政策资讯（35%）+ 基本面（30%）+ 技术面（25%）+ 风险（10%）。重大政策利好/利空可以显著影响评分。
同时，请独立评估新闻/公告的情绪倾向（sentiment_score），以及各量化维度当前的参考价值（weight_hints）。

请输出以下JSON格式（不要输出其他内容）:
{{
  "ai_score": <0-100的整数，你独立给出的AI综合评分>,
  "sentiment_score": <0-100的整数，你对该股票当前新闻/政策情绪的独立评分，50为中性，>70偏积极，<30偏消极>,
  "weight_hints": {{
    "trend": <0.0-1.0，你认为当前趋势指标的参考价值，默认0.5>,
    "momentum": <0.0-1.0，你认为当前动量指标的参考价值，默认0.5>,
    "volatility": <0.0-1.0，你认为当前波动率指标的参考价值，默认0.5>,
    "volume": <0.0-1.0，你认为当前成交量指标的参考价值，默认0.5>,
    "value": <0.0-1.0，你认为当前价值指标的参考价值，默认0.5>
  }},
  "analysis": "<250字以内的专业分析，必须包含：1.最新政策/资讯影响 2.公司基本面评价 3.财务/债务风险判断 4.综合操作建议>"
}}"""
    return prompt


def _parse_ai_response(response: str) -> Optional[Dict]:
    """解析AI返回的JSON（含 sentiment_score 和 weight_hints）"""
    if not response:
        return None

    def _extract_fields(data: dict) -> Optional[Dict]:
        if "ai_score" not in data:
            return None
        result = {
            "ai_score": _clamp(int(data["ai_score"])),
            "analysis": str(data.get("analysis", "")).strip(),
        }
        # 提取AI情绪评分（可选）
        if "sentiment_score" in data:
            try:
                result["sentiment_score"] = _clamp(int(data["sentiment_score"]))
            except (ValueError, TypeError):
                pass
        # 提取AI权重建议（可选）
        if "weight_hints" in data and isinstance(data["weight_hints"], dict):
            hints = {}
            for k in ("trend", "momentum", "volatility", "volume", "value"):
                v = data["weight_hints"].get(k)
                if v is not None:
                    try:
                        hints[k] = max(0.0, min(1.0, float(v)))
                    except (ValueError, TypeError):
                        pass
            if hints:
                result["weight_hints"] = hints
        return result

    # 尝试直接解析
    try:
        data = json.loads(response)
        result = _extract_fields(data)
        if result:
            return result
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取JSON块（支持嵌套的 weight_hints）
    try:
        match = re.search(r'\{.*"ai_score".*\}', response, re.DOTALL)
        if match:
            # 找到最外层的完整JSON
            text = match.group()
            # 平衡括号
            depth = 0
            end = 0
            for i, ch in enumerate(text):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end > 0:
                data = json.loads(text[:end])
                result = _extract_fields(data)
                if result:
                    return result
    except Exception:
        pass

    # 尝试提取数字作为分数（降级方案）
    try:
        score_match = re.search(r'"ai_score"\s*:\s*(\d+)', response)
        analysis_match = re.search(r'"analysis"\s*:\s*"([^"]*)"', response)
        sentiment_match = re.search(r'"sentiment_score"\s*:\s*(\d+)', response)
        if score_match:
            result = {
                "ai_score": _clamp(int(score_match.group(1))),
                "analysis": analysis_match.group(1) if analysis_match else "AI分析结果解析异常",
            }
            if sentiment_match:
                result["sentiment_score"] = _clamp(int(sentiment_match.group(1)))
            return result
    except Exception:
        pass

    logger.warning(f"无法解析AI响应: {response[:200]}")
    return None


def _fuse_tri_model_results(
    deepseek_result: Optional[Dict],
    glm_result: Optional[Dict],
    kimi_result: Optional[Dict],
    name: str,
    model_label: str = "",
) -> Optional[Dict]:
    """融合 DeepSeek + GLM-5 + Kimi K2.5 三模型评分结果

    策略：
    - 多模型成功：按配置权重加权融合，权重自动归一化
    - 仅一个成功：使用该模型结果
    - 全部失败：返回 None
    - 【新增】同时融合 sentiment_score 和 weight_hints
    """
    results = []
    weights = []
    labels = []

    if deepseek_result:
        results.append(deepseek_result)
        weights.append(DEEPSEEK_WEIGHT)
        labels.append(f"DeepSeek({deepseek_result['ai_score']}分)")
    if glm_result:
        results.append(glm_result)
        weights.append(GLM_WEIGHT)
        labels.append(f"GLM-5({glm_result['ai_score']}分)")
    if kimi_result:
        results.append(kimi_result)
        weights.append(KIMI_WEIGHT)
        labels.append(f"Kimi({kimi_result['ai_score']}分)")

    if not results:
        return None

    if len(results) == 1:
        logger.info(f"  [{model_label}] 仅{labels[0]}可用")
        return results[0]

    # 权重归一化
    total_weight = sum(weights)
    norm_weights = [w / total_weight for w in weights]

    fused_score = round(sum(
        r["ai_score"] * w for r, w in zip(results, norm_weights)
    ))
    fused_score = _clamp(fused_score)

    analysis_parts = []
    for r, label in zip(results, labels):
        analysis_parts.append(f"【{label}】{r.get('analysis', '')}")
    fused_analysis = "\n".join(analysis_parts)

    # 融合 sentiment_score（多模型加权平均）
    sentiment_scores = []
    sentiment_ws = []
    for r, w in zip(results, norm_weights):
        if "sentiment_score" in r:
            sentiment_scores.append(r["sentiment_score"])
            sentiment_ws.append(w)
    fused_sentiment = None
    if sentiment_scores:
        sw_total = sum(sentiment_ws)
        fused_sentiment = round(sum(
            s * w / sw_total for s, w in zip(sentiment_scores, sentiment_ws)
        ))

    # 融合 weight_hints（多模型平均）
    fused_hints = {}
    hint_counts = {}
    for r in results:
        hints = r.get("weight_hints", {})
        for k, v in hints.items():
            fused_hints[k] = fused_hints.get(k, 0) + v
            hint_counts[k] = hint_counts.get(k, 0) + 1
    if fused_hints:
        fused_hints = {k: round(v / hint_counts[k], 2) for k, v in fused_hints.items()}

    weight_detail = " + ".join(
        f"{l} × {w:.0%}" for l, w in zip(labels, norm_weights)
    )
    logger.info(f"  [{model_label}] 三模型融合: {weight_detail} = {fused_score}")

    result = {"ai_score": fused_score, "analysis": fused_analysis}
    if fused_sentiment is not None:
        result["sentiment_score"] = fused_sentiment
    if fused_hints:
        result["weight_hints"] = fused_hints
    return result


async def get_ai_rating(name: str, code: str, market: str, df: pd.DataFrame,
                       quant_scores: Dict, fundamentals: Optional[dict] = None) -> Optional[Dict]:
    """获取AI大模型评分（DeepSeek + GLM-5 + Kimi K2.5 三模型融合）

    【改进】现在AI同时输出:
    - ai_score: 综合评分
    - sentiment_score: 独立情绪评分（反馈到情绪因子）
    - weight_hints: 各维度权重建议（动态调整量化权重）
    - analysis: 分析文本
    """
    # 获取最新房地产资讯
    try:
        news_summary = get_real_estate_news_summary(code, name)
        if news_summary:
            logger.info(f"  已获取{name}相关资讯，注入AI分析")
    except Exception as e:
        logger.warning(f"获取{name}资讯失败: {e}")
        news_summary = ""

    # 获取近期公告（iFinD）
    announcements = ""
    try:
        announcements = fetch_recent_announcements(code, market, days=30) or ""
        if announcements:
            logger.info(f"  已获取{name}近期公告，注入AI分析")
    except Exception as e:
        logger.debug(f"获取{name}公告失败（非关键）: {e}")

    prompt = _build_ai_prompt(name, code, market, df, quant_scores, news_summary, fundamentals, announcements)

    # ── 三模型并发调用 ──
    tasks = []
    task_labels = []

    if DEEPSEEK_ENABLED:
        tasks.append(chat_deepseek(prompt, system=AI_SYSTEM_PROMPT, temperature=0.3, enable_search=True))
        task_labels.append("DeepSeek")
    if GLM_ENABLED:
        tasks.append(chat_glm(prompt, system=AI_SYSTEM_PROMPT, temperature=0.3))
        task_labels.append("GLM-5")
    if KIMI_ENABLED:
        tasks.append(chat_kimi(prompt, system=AI_SYSTEM_PROMPT))
        task_labels.append("Kimi")

    if not tasks:
        logger.warning(f"所有AI模型均未启用，跳过{name}的AI评分")
        return None

    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    parsed = {}
    for i, (resp, label) in enumerate(zip(raw_results, task_labels)):
        if isinstance(resp, Exception):
            logger.warning(f"{label}调用异常({name}): {resp}")
        elif resp:
            parsed[label] = _parse_ai_response(resp)
        # resp is None means model disabled or failed silently

    return _fuse_tri_model_results(
        parsed.get("DeepSeek"), parsed.get("GLM-5"), parsed.get("Kimi"),
        name, "量化AI",
    )


# ========== 综合评级 ==========

def _generate_fallback_reason(name: str, scores: Dict[str, float], total: float, rating: str) -> str:
    """量化模式下的评级理由（AI不可用时的降级方案）"""
    reasons = []
    if scores["trend"] >= 70:
        reasons.append("均线多头排列，趋势向好")
    elif scores["trend"] <= 35:
        reasons.append("均线空头排列，趋势偏弱")
    if scores["momentum"] >= 70:
        reasons.append("技术动量强劲，MACD/RSI信号积极")
    elif scores["momentum"] <= 35:
        reasons.append("动量不足，技术指标偏空")
    if scores["volatility"] >= 70:
        reasons.append("波动率低，走势稳健")
    elif scores["volatility"] <= 35:
        reasons.append("波动较大，风险偏高")
    if scores["volume"] >= 70:
        reasons.append("量价配合良好，资金关注度高")
    elif scores["volume"] <= 35:
        reasons.append("成交低迷，市场关注度不足")
    if scores["value"] >= 70:
        reasons.append("估值处于合理区间，具备配置价值")
    elif scores["value"] <= 35:
        reasons.append("价格偏离较大，需警惕风险")
    # 情绪因子
    sentiment = scores.get("sentiment", 50)
    if sentiment >= 70:
        reasons.append("市场情绪积极，政策面偏暖")
    elif sentiment <= 30:
        reasons.append("市场情绪偏空，需关注负面信号")
    if not reasons:
        reasons.append("各项指标表现平稳，暂无明显方向信号")
    return f"{name}当前评级【{rating}】(综合{total:.0f}分): {'；'.join(reasons)}。"


def _apply_weight_hints(quant_scores: Dict[str, float], weight_hints: Dict[str, float]) -> float:
    """根据AI的 weight_hints 动态调整量化各维度权重（东吴金工AI因子优化思路）

    AI会评估当前每个维度的参考价值（0-1），用于微调基础权重：
    - hint > 0.5: 增强该维度权重（AI认为当前该维度信号更可靠）
    - hint < 0.5: 降低该维度权重（AI认为当前该维度信号失效）
    - hint = 0.5: 保持默认权重

    调整幅度控制在 ±30% 以内，避免极端偏移。
    """
    base_weights = {k: v for k, v in QUANT_WEIGHTS.items() if k != "sentiment"}

    adjusted = {}
    for dim, base_w in base_weights.items():
        hint = weight_hints.get(dim, 0.5)
        # hint 0→×0.7, 0.5→×1.0, 1.0→×1.3
        multiplier = 0.7 + hint * 0.6
        adjusted[dim] = base_w * multiplier

    # 加上 sentiment（不受 hint 调整）
    adjusted["sentiment"] = QUANT_WEIGHTS["sentiment"]

    # 归一化使总和=1.0
    total_w = sum(adjusted.values())
    if total_w > 0:
        adjusted = {k: v / total_w for k, v in adjusted.items()}

    # 计算调整后的加权总分
    weighted_total = sum(quant_scores.get(k, 50) * w for k, w in adjusted.items())
    return round(weighted_total, 2)


async def rate_stock(df: pd.DataFrame, name: str = "", code: str = "", market: str = "") -> Optional[Dict]:
    """对单只股票进行混合评级（量化 + 情绪 + 基本面 + AI）

    改进点（东吴金工灵感）：
    1. 新增情绪因子维度（关键词 + AI情绪打分 + 双速衰减）
    2. AI输出 weight_hints 动态调整量化各维度权重
    3. AI输出 sentiment_score 反馈增强情绪因子
    """
    if df is None or len(df) < 20:
        return None

    # 1. 获取新闻和公告（提前获取，供情绪因子和AI共用）
    news_summary = ""
    try:
        news_summary = get_real_estate_news_summary(code, name)
        if news_summary:
            logger.info(f"  已获取{name}相关资讯，注入分析")
    except Exception as e:
        logger.warning(f"获取{name}资讯失败: {e}")

    announcements = ""
    try:
        announcements = fetch_recent_announcements(code, market, days=30) or ""
        if announcements:
            logger.info(f"  已获取{name}近期公告，注入分析")
    except Exception as e:
        logger.debug(f"获取{name}公告失败（非关键）: {e}")

    # 2. 计算基础情绪因子（关键词+衰减模型）
    base_sentiment = calc_sentiment_score(news_summary, announcements)
    logger.info(f"  情绪因子(关键词): {base_sentiment:.1f}")

    # 3. 量化评分（含情绪因子）
    quant_scores = calc_quant_score(df, sentiment_score=base_sentiment)
    quant_total = quant_scores["quant_total"]

    # 4. 基本面数据（iFinD）
    fundamentals = None
    fundamental_score = None
    try:
        fundamentals = fetch_fundamentals(code, market, history_df=df)
        if fundamentals:
            fundamental_score = calc_fundamental_score(fundamentals)
            if fundamental_score is not None:
                logger.info(f"  基本面评分: {fundamental_score:.1f} (PE={fundamentals.get('pe_ttm')}, PB={fundamentals.get('pb_mrq')})")
    except Exception as e:
        logger.warning(f"获取{name}基本面数据失败: {e}")

    # 5. AI大模型评分（含 sentiment_score + weight_hints）
    ai_result = await get_ai_rating(name, code, market, df, quant_scores, fundamentals)

    # 6. 用AI反馈增强情绪因子
    final_sentiment = base_sentiment
    if ai_result and "sentiment_score" in ai_result:
        ai_sentiment = ai_result["sentiment_score"]
        # AI情绪 + 关键词情绪加权融合（AI占60%，关键词占40%）
        final_sentiment = round(ai_sentiment * 0.6 + base_sentiment * 0.4)
        quant_scores["sentiment"] = final_sentiment
        logger.info(f"  情绪因子(AI增强): {base_sentiment:.0f} → {final_sentiment:.0f} (AI: {ai_sentiment})")

    # 7. AI动态权重调整
    if ai_result and "weight_hints" in ai_result:
        adjusted_quant = _apply_weight_hints(quant_scores, ai_result["weight_hints"])
        logger.info(f"  AI动态权重调整: {quant_total:.1f} → {adjusted_quant:.1f} (hints: {ai_result['weight_hints']})")
        quant_total = adjusted_quant
    else:
        # 重新计算（情绪分可能已更新）
        quant_total = round(sum(quant_scores.get(k, 50) * QUANT_WEIGHTS.get(k, 0) for k in QUANT_WEIGHTS), 2)

    # 8. 综合计算
    has_fund = fundamental_score is not None
    if ai_result:
        ai_score = ai_result["ai_score"]
        if has_fund:
            total = round(
                quant_total * QUANT_RATIO +
                final_sentiment * SENTIMENT_RATIO +
                fundamental_score * FUNDAMENTAL_RATIO +
                ai_score * AI_RATIO, 2
            )
        else:
            total = round(
                quant_total * QUANT_RATIO_NO_FUND +
                final_sentiment * SENTIMENT_RATIO_NO_FUND +
                ai_score * AI_RATIO_NO_FUND, 2
            )
        reason = ai_result["analysis"]
    else:
        ai_score = 0.0
        if has_fund:
            # AI不可用: 量化55% + 基本面45%
            total = round(quant_total * 0.55 + fundamental_score * 0.45, 2)
        else:
            total = round(quant_total, 2)
        reason = ""

    # 9. 映射评级
    rating = "谨慎"
    for threshold, label in RATING_MAP:
        if total >= threshold:
            rating = label
            break

    # 10. 如果AI没有给出理由，使用量化降级理由
    if not reason:
        reason = _generate_fallback_reason(name, quant_scores, total, rating)

    result = {
        "trend_score": quant_scores["trend"],
        "momentum_score": quant_scores["momentum"],
        "volatility_score": quant_scores["volatility"],
        "volume_score": quant_scores["volume"],
        "value_score": quant_scores["value"],
        "ai_score": round(ai_score, 2),
        "total_score": total,
        "rating": rating,
        "reason": reason,
    }

    # 7. 附加基本面数据到结果
    if fundamentals:
        result["pe_ttm"] = fundamentals.get("pe_ttm")
        result["pb_mrq"] = fundamentals.get("pb_mrq")
        result["roe"] = fundamentals.get("roe")
        result["eps"] = fundamentals.get("eps")
        result["market_value"] = fundamentals.get("market_value")
        result["debt_ratio"] = fundamentals.get("debt_ratio")
        # 资金流数据
        result["main_net_inflow"] = fundamentals.get("main_net_inflow")
        result["retail_net_inflow"] = fundamentals.get("retail_net_inflow")
        result["large_net_inflow"] = fundamentals.get("large_net_inflow")
        result["rise_day_count"] = fundamentals.get("rise_day_count")
        # 市场微观数据
        result["vol_ratio"] = fundamentals.get("vol_ratio")
        result["swing"] = fundamentals.get("swing")
        result["committee"] = fundamentals.get("committee")
        result["turnover_ratio"] = fundamentals.get("turnover_ratio")
        # iFinD多周期涨跌幅
        result["chg_5d"] = fundamentals.get("chg_5d")
        result["chg_10d"] = fundamentals.get("chg_10d")
        result["chg_20d"] = fundamentals.get("chg_20d")
        result["chg_60d"] = fundamentals.get("chg_60d")
        result["chg_120d"] = fundamentals.get("chg_120d")
        result["chg_year"] = fundamentals.get("chg_year")
    if fundamental_score is not None:
        result["fundamental_score"] = round(fundamental_score, 2)

    return result


# ========================================================================
# 东吴地产选股模型（基本面70% + AI30%）
# 核心逻辑：
#   宏观层面 - 5年LPR利率下行、社会融资规模环比提升
#   行业层面 - 新闻包含"放松限购/政策宽松/止跌企稳"等宽松信号
#   个股层面 - 收入增长稳健、计提减值充分、满足三条红线
#   估值层面 - PB < 1
# ========================================================================

SOOCHOW_FUND_RATIO = 0.50   # 基本面评分占比
SOOCHOW_AI_RATIO = 0.50     # AI评分占比
SOOCHOW_FUND_NO_AI = 1.00   # AI不可用时100%基本面

SOOCHOW_AI_PROMPT = """你是东吴证券地产研究团队的资深分析师，专注中国房地产行业基本面研究。

你的分析框架（按重要性排序）：

【一、宏观环境评估（权重25%）】
1. 利率环境：5年期LPR走势，是否处于下行通道（利好地产）
2. 融资环境：社会融资规模是否环比/同比提升，信贷是否宽松
3. 货币政策：降准降息预期、房贷利率走势
4. 经济基本面：GDP增速、居民收入、消费信心

【二、行业政策面（权重30%）— 最关键维度】
1. 需求端政策：是否出现"放松限购"、"降低首付"、"降低利率"等宽松信号
2. 供给端政策：是否有"保交楼"、"白名单"、"城中村改造"等托底政策
3. 政策基调：是否出现"止跌企稳"、"政策宽松"、"促进消费"等积极措辞
4. 地方落地：重点城市（北上广深、强二线）是否有实质性放松

【三、个股基本面（权重30%）】
1. 收入增长：营收是否同比增长或降幅收窄，结合行业趋势判断可持续性
2. 减值计提：是否已充分计提存货减值、土地减值，未来业绩是否轻装上阵
3. 三条红线：剔除预收后资产负债率<70%、净负债率<100%、现金短债比>1
4. 财务质量：经营性现金流是否为正、回款率、有息负债规模

【四、估值安全边际（权重15%）】
1. PB估值：PB<1为核心条件，破净程度越深安全边际越高
2. PE估值：PE_TTM是否合理，是否处于历史低位
3. 股息率：是否有稳定分红，股息率是否具有吸引力

请基于以上框架给出评分(0-100分)和详细分析。如果新闻中出现重大政策利好（放松限购、降息等），应显著上调评分。
严格按照要求的JSON格式输出。"""


def _calc_soochow_fundamental(fundamentals: Optional[dict]) -> Optional[float]:
    """东吴模型基本面评分（100分制）
    重点关注：三条红线(30分) + 估值安全边际(30分) + 盈利质量(20分) + 资金面(20分)
    """
    if not fundamentals:
        return None

    pb = fundamentals.get("pb_mrq")
    pe = fundamentals.get("pe_ttm")
    roe = fundamentals.get("roe")
    eps = fundamentals.get("eps")
    debt_ratio = fundamentals.get("debt_ratio")

    if pb is None and pe is None:
        return None

    score = 0.0
    max_score = 0.0

    # ═══ 三条红线 & 财务健康（30分）═══

    # 资产负债率 (0~15分) — 三道红线核心指标
    if debt_ratio is not None:
        max_score += 15
        if debt_ratio < 70:
            score += 15  # 绿档：完全达标
        elif debt_ratio < 75:
            score += 11
        elif debt_ratio < 80:
            score += 7
        elif debt_ratio < 85:
            score += 3
        else:
            score += 1  # 严重超标

    # ROE盈利能力 (0~15分)
    if roe is not None:
        max_score += 15
        if roe >= 15:
            score += 15
        elif roe >= 10:
            score += 12
        elif roe >= 5:
            score += 9
        elif roe >= 0:
            score += 5
        else:
            score += 1  # 亏损

    # ═══ 估值安全边际（30分）═══

    # PB估值 (0~20分) — 东吴模型核心条件
    if pb is not None:
        max_score += 20
        if pb < 0:
            score += 2   # 净资产为负
        elif pb < 0.3:
            score += 15  # 深度破净但可能有风险
        elif pb < 0.5:
            score += 18  # 严重低估
        elif pb < 0.8:
            score += 20  # 破净，最优区间
        elif pb < 1.0:
            score += 16  # 接近破净
        elif pb < 1.2:
            score += 10
        elif pb < 1.5:
            score += 6
        else:
            score += 2   # 偏贵

    # PE估值 (0~10分)
    if pe is not None:
        max_score += 10
        if pe < 0:
            score += 2   # 亏损
        elif pe < 8:
            score += 10  # 极低估值
        elif pe <= 15:
            score += 8
        elif pe <= 25:
            score += 5
        elif pe <= 40:
            score += 3
        else:
            score += 1

    # ═══ 盈利质量（20分）═══

    # EPS每股收益 (0~12分)
    if eps is not None:
        max_score += 12
        if eps > 2.0:
            score += 12
        elif eps > 1.0:
            score += 10
        elif eps > 0.5:
            score += 7
        elif eps > 0.1:
            score += 4
        elif eps > 0:
            score += 2
        else:
            score += 0  # 亏损

    # 20日涨跌幅趋势 (0~8分)
    chg_20d = fundamentals.get("chg_20d")
    if chg_20d is not None:
        max_score += 8
        if 5 <= chg_20d <= 20:
            score += 8
        elif 0 < chg_20d < 5:
            score += 6
        elif 20 < chg_20d <= 40:
            score += 5
        elif -5 <= chg_20d <= 0:
            score += 3
        elif -15 <= chg_20d < -5:
            score += 2
        else:
            score += 1

    # ═══ 资金面（20分）═══

    # 主力净流入 (0~12分)
    mnf = fundamentals.get("main_net_inflow")
    if mnf is not None:
        max_score += 12
        if mnf > 5000:
            score += 12
        elif mnf > 1000:
            score += 10
        elif mnf > 0:
            score += 7
        elif mnf > -1000:
            score += 4
        elif mnf > -5000:
            score += 2
        else:
            score += 1

    # 换手率 (0~8分)
    tr = fundamentals.get("turnover_ratio")
    if tr is not None:
        max_score += 8
        if 1.0 <= tr <= 5.0:
            score += 8
        elif 5.0 < tr <= 10.0:
            score += 6
        elif 0.5 <= tr < 1.0:
            score += 4
        elif tr > 10.0:
            score += 3
        else:
            score += 2

    if max_score == 0:
        return None

    normalized = score / max_score * 100
    return _clamp(normalized)


def _parse_soochow_ai_response(raw: str) -> Optional[Dict]:
    """解析东吴模型AI返回的JSON（score + analysis 格式）"""
    if not raw:
        return None
    cleaned = raw.strip()

    # 正则匹配 {"score": N, "analysis": "..."}
    json_match = re.search(
        r'\{[^{}]*"score"\s*:\s*(\d+(?:\.\d+)?)[^{}]*"analysis"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',
        cleaned, re.DOTALL,
    )
    if json_match:
        ai_score = _clamp(float(json_match.group(1)))
        analysis = json_match.group(2).replace('\\"', '"').replace('\\n', '\n')
        return {"ai_score": ai_score, "analysis": analysis}

    # 尝试 ```json ... ``` 代码块
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            return {
                "ai_score": _clamp(float(parsed.get("score", 50))),
                "analysis": parsed.get("analysis", ""),
            }
        except (json.JSONDecodeError, ValueError):
            pass

    return None


async def _get_soochow_ai_rating(name: str, code: str, market: str,
                                  df: pd.DataFrame, fundamentals: Optional[dict]) -> Optional[dict]:
    """东吴模型的AI评分（混元 + DeepSeek 双模型融合）— 聚焦宏观政策+行业趋势+基本面验证"""
    try:
        news_summary = get_real_estate_news_summary(code, name)
        announcements = fetch_recent_announcements(code, market) or ""

        fund_info = ""
        if fundamentals:
            parts = []
            if fundamentals.get("pe_ttm") is not None:
                parts.append(f"PE(TTM)={fundamentals['pe_ttm']:.2f}")
            if fundamentals.get("pb_mrq") is not None:
                parts.append(f"PB(MRQ)={fundamentals['pb_mrq']:.4f}")
            if fundamentals.get("roe") is not None:
                parts.append(f"ROE={fundamentals['roe']:.2f}%")
            if fundamentals.get("eps") is not None:
                parts.append(f"EPS={fundamentals['eps']:.3f}")
            if fundamentals.get("debt_ratio") is not None:
                parts.append(f"资产负债率={fundamentals['debt_ratio']:.1f}%")
            if fundamentals.get("market_value") is not None:
                parts.append(f"总市值={fundamentals['market_value']:.1f}亿")
            fund_info = "；".join(parts)

        recent = df.tail(5)
        price_info = f"最新收盘价{recent.iloc[-1]['close']:.2f}，5日涨跌幅{((recent.iloc[-1]['close']/recent.iloc[0]['close'])-1)*100:.2f}%"

        user_msg = f"""请分析 {name}({code}) [{market}市场] 的投资价值。

【最新行业资讯与政策】
{news_summary}

【iFinD公告】
{announcements[:500] if announcements else '无近期公告'}

【基本面数据】
{fund_info or '暂无数据'}

【近期行情】
{price_info}

请重点关注：
1. 当前宏观利率环境和融资环境对房地产的影响
2. 最新政策中是否有"放松限购"、"政策宽松"、"止跌企稳"等积极信号
3. 该公司是否收入增长稳健、三条红线达标、减值计提充分
4. PB是否<1，估值是否具有安全边际

请给出你的评分(0-100分)和分析理由。
请严格使用如下JSON格式回复:
{{"score": 数字, "analysis": "你的详细分析"}}"""

        # ── 三模型并发调用 ──
        tasks = []
        task_labels = []

        if DEEPSEEK_ENABLED:
            tasks.append(chat_deepseek(user_msg, system=SOOCHOW_AI_PROMPT, temperature=0.3, enable_search=True))
            task_labels.append("DeepSeek")
        if GLM_ENABLED:
            tasks.append(chat_glm(user_msg, system=SOOCHOW_AI_PROMPT, temperature=0.3))
            task_labels.append("GLM-5")
        if KIMI_ENABLED:
            tasks.append(chat_kimi(user_msg, system=SOOCHOW_AI_PROMPT))
            task_labels.append("Kimi")

        if not tasks:
            return None

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        parsed = {}
        for resp, label in zip(raw_results, task_labels):
            if isinstance(resp, Exception):
                logger.warning(f"[东吴] {label}调用异常({name}): {resp}")
            elif resp:
                parsed[label] = _parse_soochow_ai_response(resp)

        return _fuse_tri_model_results(
            parsed.get("DeepSeek"), parsed.get("GLM-5"), parsed.get("Kimi"),
            name, "东吴AI",
        )

    except Exception as e:
        logger.warning(f"东吴模型AI评分失败({name}): {e}")
        return None


async def rate_stock_soochow(df: pd.DataFrame, name: str = "", code: str = "",
                              market: str = "") -> Optional[Dict]:
    """东吴地产选股模型评级（基本面70% + AI30%）"""
    if df is None or len(df) < 20:
        return None

    # 获取新闻和公告（供情绪因子使用）
    news_summary = ""
    try:
        news_summary = get_real_estate_news_summary(code, name)
    except Exception:
        pass
    ann_text = ""
    try:
        ann_text = fetch_recent_announcements(code, market) or ""
    except Exception:
        pass

    # 情绪因子
    sentiment = calc_sentiment_score(news_summary, ann_text)

    fundamentals = None
    fundamental_score = None
    try:
        fundamentals = fetch_fundamentals(code, market, history_df=df)
        if fundamentals:
            fundamental_score = _calc_soochow_fundamental(fundamentals)
            if fundamental_score is not None:
                logger.info(f"  [东吴] 基本面评分: {fundamental_score:.1f} (PB={fundamentals.get('pb_mrq')}, 负债率={fundamentals.get('debt_ratio')})")
    except Exception as e:
        logger.warning(f"[东吴] 获取{name}基本面数据失败: {e}")

    ai_result = await _get_soochow_ai_rating(name, code, market, df, fundamentals)

    # AI情绪反馈增强
    if ai_result and "sentiment_score" in ai_result:
        sentiment = round(ai_result["sentiment_score"] * 0.6 + sentiment * 0.4)

    has_fund = fundamental_score is not None
    if ai_result:
        ai_score = ai_result["ai_score"]
        if has_fund:
            total = round(fundamental_score * SOOCHOW_FUND_RATIO + ai_score * SOOCHOW_AI_RATIO, 2)
        else:
            total = round(ai_score, 2)
        reason = ai_result["analysis"]
    else:
        ai_score = 0.0
        if has_fund:
            total = round(fundamental_score * SOOCHOW_FUND_NO_AI, 2)
        else:
            return None
        reason = ""

    rating_label = "谨慎"
    for threshold, label in RATING_MAP:
        if total >= threshold:
            rating_label = label
            break

    if not reason and fundamentals:
        pb_str = f"PB={fundamentals.get('pb_mrq', 'N/A')}"
        debt_str = f"负债率={fundamentals.get('debt_ratio', 'N/A')}%"
        reason = f"东吴模型基本面评估：{pb_str}，{debt_str}，基本面评分{fundamental_score:.1f}分。"

    quant_scores = calc_quant_score(df, sentiment_score=sentiment)

    result = {
        "trend_score": quant_scores["trend"],
        "momentum_score": quant_scores["momentum"],
        "volatility_score": quant_scores["volatility"],
        "volume_score": quant_scores["volume"],
        "value_score": quant_scores["value"],
        "ai_score": round(ai_score, 2),
        "total_score": total,
        "rating": rating_label,
        "reason": reason,
    }

    if fundamentals:
        result["pe_ttm"] = fundamentals.get("pe_ttm")
        result["pb_mrq"] = fundamentals.get("pb_mrq")
        result["roe"] = fundamentals.get("roe")
        result["eps"] = fundamentals.get("eps")
        result["market_value"] = fundamentals.get("market_value")
        result["debt_ratio"] = fundamentals.get("debt_ratio")
        result["main_net_inflow"] = fundamentals.get("main_net_inflow")
        result["retail_net_inflow"] = fundamentals.get("retail_net_inflow")
        result["large_net_inflow"] = fundamentals.get("large_net_inflow")
        result["rise_day_count"] = fundamentals.get("rise_day_count")
        result["vol_ratio"] = fundamentals.get("vol_ratio")
        result["swing"] = fundamentals.get("swing")
        result["committee"] = fundamentals.get("committee")
        result["turnover_ratio"] = fundamentals.get("turnover_ratio")
        result["chg_5d"] = fundamentals.get("chg_5d")
        result["chg_10d"] = fundamentals.get("chg_10d")
        result["chg_20d"] = fundamentals.get("chg_20d")
        result["chg_60d"] = fundamentals.get("chg_60d")
        result["chg_120d"] = fundamentals.get("chg_120d")
        result["chg_year"] = fundamentals.get("chg_year")
    if fundamental_score is not None:
        result["fundamental_score"] = round(fundamental_score, 2)

    return result
