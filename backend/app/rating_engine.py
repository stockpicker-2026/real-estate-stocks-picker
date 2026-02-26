"""
房地产股票AI评级引擎（量化 + 基本面 + 大模型混合评级）

评级架构:
  量化技术评分 (40%) + 基本面评分 (15%) + AI大模型评分 (45%)

一、量化技术评分（5个维度，各0-100分）:
  1. 趋势评分 (Trend) - 权重25%:
     均线排列、价格vs多级均线、MA20斜率、均线黏合度、ADX趋势强度
  2. 动量评分 (Momentum) - 权重20%:
     RSI(14)+RSI(6)双周期、MACD金叉死叉+柱状体变化、KDJ随机指标、Williams %R、多周期涨跌幅
  3. 波动率评分 (Volatility) - 权重15%:
     年化波动率、布林带宽度+价格位置、ATR(14)相对波动、波动率收敛/发散趋势
  4. 成交量评分 (Volume) - 权重20%:
     多级量比、OBV能量潮趋势、VWAP偏离度、量价配合度、成交量趋势
  5. 价值评分 (Value) - 权重20%:
     距高低点位置(含连续评分)、筹码集中度、多级支撑压力、价格动态区间评估

二、基本面评分 (0-100分):
  来自iFinD的PE_TTM、PB_MRQ、ROE、EPS等财务数据
  （仅A股可用，港股/美股跳过此维度）

三、AI大模型评分 (0-100分):
  腾讯混元重点分析公司基本面、财务状况、行业政策、市场情绪，给出AI综合评分和专业分析

综合评分 = 量化评分 × 40% + 基本面评分 × 15% + AI评分 × 45%
（若基本面不可用，则量化50% + AI50%）
（若AI不可用，则100%使用量化评分+基本面）

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

import numpy as np
import pandas as pd
from typing import Optional, Dict

from app.llm_client import chat_hunyuan
from app.news_fetcher import get_real_estate_news_summary
from app.ifind_client import fetch_fundamentals

logger = logging.getLogger(__name__)

QUANT_WEIGHTS = {
    "trend": 0.25,
    "momentum": 0.20,
    "volatility": 0.15,
    "volume": 0.20,
    "value": 0.20,
}

QUANT_RATIO = 0.40  # 量化评分占比
FUNDAMENTAL_RATIO = 0.15  # 基本面评分占比
AI_RATIO = 0.45     # AI评分占比

# 无基本面数据时的降级比例
QUANT_RATIO_NO_FUND = 0.50
AI_RATIO_NO_FUND = 0.50

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


def calc_quant_score(df: pd.DataFrame) -> Dict[str, float]:
    """计算所有量化评分维度"""
    scores = {
        "trend": round(calc_trend_score(df), 2),
        "momentum": round(calc_momentum_score(df), 2),
        "volatility": round(calc_volatility_score(df), 2),
        "volume": round(calc_volume_score(df), 2),
        "value": round(calc_value_score(df), 2),
    }
    total = sum(scores[k] * QUANT_WEIGHTS[k] for k in QUANT_WEIGHTS)
    scores["quant_total"] = round(total, 2)
    return scores


# ========== 基本面评分（iFinD财务数据）==========

def calc_fundamental_score(fundamentals: Optional[dict]) -> Optional[float]:
    """基本面评分: 基于iFinD的PE/PB/ROE/EPS等财务数据
    房地产行业特定评分逻辑:
      - PE_TTM: 负值减分，10-30合理区间加分
      - PB_MRQ: <1破净有估值修复空间，1-2合理
      - ROE: 越高越好，>10优秀
      - 负债率: 房企普遍高，<80合理，>85预警
    """
    if not fundamentals:
        return None

    pe = fundamentals.get("pe_ttm")
    pb = fundamentals.get("pb_mrq")
    roe = fundamentals.get("roe")
    debt_ratio = fundamentals.get("debt_ratio")
    eps = fundamentals.get("eps")

    # 至少需要PE或PB才能评分
    if pe is None and pb is None:
        return None

    score = 0.0
    count = 0

    # PE_TTM 评分 (0~30分)
    if pe is not None:
        count += 1
        if pe < 0:
            score += 5  # 亏损，低分
        elif pe < 8:
            score += 28  # 极低PE，深度价值
        elif pe <= 15:
            score += 25  # 低PE，价值区间
        elif pe <= 30:
            score += 18  # 合理PE
        elif pe <= 50:
            score += 10  # 偏高
        else:
            score += 5  # 极高PE

    # PB_MRQ 评分 (0~25分) — 房地产行业特别关注PB
    if pb is not None:
        count += 1
        if pb < 0:
            score += 3  # 净资产为负
        elif pb < 0.5:
            score += 22  # 深度破净，可能有修复空间
        elif pb < 1.0:
            score += 25  # 破净，估值修复潜力大
        elif pb < 1.5:
            score += 20  # 合理区间
        elif pb < 2.5:
            score += 12  # 偏高
        else:
            score += 5  # 高溢价

    # ROE 评分 (0~25分)
    if roe is not None:
        count += 1
        if roe < 0:
            score += 3  # 亏损
        elif roe < 3:
            score += 8
        elif roe < 8:
            score += 15
        elif roe < 15:
            score += 22
        else:
            score += 25  # 高ROE

    # 负债率评分 (0~20分) — 房企三道红线视角
    if debt_ratio is not None:
        count += 1
        if debt_ratio < 70:
            score += 20  # 低负债，非常健康
        elif debt_ratio < 75:
            score += 16
        elif debt_ratio < 80:
            score += 12  # 行业平均水平
        elif debt_ratio < 85:
            score += 7  # 偏高
        else:
            score += 3  # 高负债预警

    if count == 0:
        return None

    # 归一化到0-100
    max_possible = count * 25  # 每个指标平均25分
    if max_possible > 0:
        normalized = score / max_possible * 100
    else:
        normalized = 50.0

    return _clamp(normalized)


# ========== AI大模型评分 ==========

def _build_ai_prompt(name: str, code: str, market: str, df: pd.DataFrame, quant_scores: Dict,
                     news_summary: str = "", fundamentals: Optional[dict] = None) -> str:
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
        if fund_lines:
            fund_section = "【财务数据（来自同花顺iFinD）】\n" + "\n".join(fund_lines) + "\n\n"

    prompt = f"""请对以下中国房地产相关股票进行深度分析，结合最新政策资讯和行情数据，给出你独立的AI评分。

【股票信息】
- 名称: {name}
- 代码: {code}
- 市场: {market_name}

{news_section}{fund_section}【行情数据摘要】
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

【重点分析要求】
请你作为资深房地产分析师，结合上述最新资讯，重点从以下角度进行独立评估：

1. **最新政策资讯影响（最关键）**：结合今日/近期的房地产政策新闻，分析对该公司的直接利好/利空影响。如果有重大政策（如限购放松、降息、首付降低等），应重点评估对评分的影响。

2. **公司基本面**：基于你对该公司的了解，评估其经营质量、债务健康度、销售回款能力、土储质量。

3. **行业政策周期**：综合判断当前政策环境对房地产板块的整体影响方向。

4. **风险评估**：债务违约风险、项目交付风险、系统性行业风险。

请注意：你的评分应综合考虑最新政策资讯（35%）+ 基本面（30%）+ 技术面（25%）+ 风险（10%）。重大政策利好/利空可以显著影响评分。

请输出以下JSON格式（不要输出其他内容）:
{{
  "ai_score": <0-100的整数，你独立给出的AI综合评分>,
  "analysis": "<250字以内的专业分析，必须包含：1.最新政策/资讯影响 2.公司基本面评价 3.财务/债务风险判断 4.综合操作建议>"
}}"""
    return prompt


def _parse_ai_response(response: str) -> Optional[Dict]:
    """解析AI返回的JSON"""
    if not response:
        return None
    try:
        # 尝试直接解析
        data = json.loads(response)
        if "ai_score" in data and "analysis" in data:
            score = int(data["ai_score"])
            return {
                "ai_score": _clamp(score),
                "analysis": str(data["analysis"]).strip(),
            }
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取JSON块
    try:
        match = re.search(r'\{[^{}]*"ai_score"[^{}]*\}', response, re.DOTALL)
        if match:
            data = json.loads(match.group())
            score = int(data["ai_score"])
            return {
                "ai_score": _clamp(score),
                "analysis": str(data.get("analysis", "")).strip(),
            }
    except Exception:
        pass

    # 尝试提取数字作为分数
    try:
        score_match = re.search(r'"ai_score"\s*:\s*(\d+)', response)
        analysis_match = re.search(r'"analysis"\s*:\s*"([^"]*)"', response)
        if score_match:
            return {
                "ai_score": _clamp(int(score_match.group(1))),
                "analysis": analysis_match.group(1) if analysis_match else "AI分析结果解析异常",
            }
    except Exception:
        pass

    logger.warning(f"无法解析AI响应: {response[:200]}")
    return None


async def get_ai_rating(name: str, code: str, market: str, df: pd.DataFrame,
                       quant_scores: Dict, fundamentals: Optional[dict] = None) -> Optional[Dict]:
    """获取AI大模型评分（融合最新资讯 + 联网搜索 + 财务数据）"""
    # 获取最新房地产资讯
    try:
        news_summary = get_real_estate_news_summary(code, name)
        if news_summary:
            logger.info(f"  已获取{name}相关资讯，注入AI分析")
    except Exception as e:
        logger.warning(f"获取{name}资讯失败: {e}")
        news_summary = ""

    prompt = _build_ai_prompt(name, code, market, df, quant_scores, news_summary, fundamentals)
    # 开启联网搜索，让混元获取最新政策动态
    response = await chat_hunyuan(prompt, system=AI_SYSTEM_PROMPT, temperature=0.3, enable_search=True)
    if not response:
        return None
    result = _parse_ai_response(response)
    if result:
        logger.info(f"  AI评分: {result['ai_score']}")
    return result


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
    if not reasons:
        reasons.append("各项指标表现平稳，暂无明显方向信号")
    return f"{name}当前评级【{rating}】(综合{total:.0f}分): {'；'.join(reasons)}。"


async def rate_stock(df: pd.DataFrame, name: str = "", code: str = "", market: str = "") -> Optional[Dict]:
    """对单只股票进行混合评级（量化 + 基本面 + AI）"""
    if df is None or len(df) < 20:
        return None

    # 1. 量化评分
    quant_scores = calc_quant_score(df)
    quant_total = quant_scores["quant_total"]

    # 2. 基本面数据（iFinD）
    fundamentals = None
    fundamental_score = None
    try:
        fundamentals = fetch_fundamentals(code, market)
        if fundamentals:
            fundamental_score = calc_fundamental_score(fundamentals)
            if fundamental_score is not None:
                logger.info(f"  基本面评分: {fundamental_score:.1f} (PE={fundamentals.get('pe_ttm')}, PB={fundamentals.get('pb_mrq')})")
    except Exception as e:
        logger.warning(f"获取{name}基本面数据失败: {e}")

    # 3. AI大模型评分
    ai_result = await get_ai_rating(name, code, market, df, quant_scores, fundamentals)

    # 4. 综合计算
    has_fund = fundamental_score is not None
    if ai_result:
        ai_score = ai_result["ai_score"]
        if has_fund:
            total = round(
                quant_total * QUANT_RATIO +
                fundamental_score * FUNDAMENTAL_RATIO +
                ai_score * AI_RATIO, 2
            )
        else:
            total = round(
                quant_total * QUANT_RATIO_NO_FUND +
                ai_score * AI_RATIO_NO_FUND, 2
            )
        reason = ai_result["analysis"]
    else:
        ai_score = 0.0
        if has_fund:
            # AI不可用: 量化70% + 基本面30%
            total = round(quant_total * 0.70 + fundamental_score * 0.30, 2)
        else:
            total = round(quant_total, 2)
        reason = ""

    # 5. 映射评级
    rating = "谨慎"
    for threshold, label in RATING_MAP:
        if total >= threshold:
            rating = label
            break

    # 6. 如果AI没有给出理由，使用量化降级理由
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
    if fundamental_score is not None:
        result["fundamental_score"] = round(fundamental_score, 2)

    return result
