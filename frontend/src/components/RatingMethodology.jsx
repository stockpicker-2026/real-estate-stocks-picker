import React, { useState } from 'react'

export default function RatingMethodology() {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="methodology-card">
      <div
        className="methodology-header"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="methodology-title-row">
          <span className="methodology-icon">&#x1f4d0;</span>
          <span className="methodology-title">评级逻辑说明</span>
        </div>
        <span className={`methodology-arrow ${expanded ? 'expanded' : ''}`}>&#x25B6;</span>
      </div>

      {expanded && (
        <div className="methodology-body">
          {/* 总公式 */}
          <div className="methodology-formula">
            <span className="formula-label">综合评分</span>
            <span className="formula-eq">=</span>
            <span className="formula-part quant">量化技术评分 × 50%</span>
            <span className="formula-plus">+</span>
            <span className="formula-part ai">AI大模型评分 × 50%</span>
          </div>
          <div className="methodology-fallback">若AI不可用，则自动降级为100%量化评分</div>

          <div className="methodology-columns">
            {/* 左列: 量化 */}
            <div className="methodology-col">
              <div className="methodology-col-title">
                <span className="col-dot quant-dot" />
                量化技术评分 (50%)
              </div>
              <div className="methodology-col-desc">
                基于近期行情数据，通过5个量化维度综合评估
              </div>
              <div className="dimension-list">
                <DimensionItem
                  name="趋势评分"
                  weight="25%"
                  desc="四级均线排列(MA5/10/20/60)、价格偏离度、MA20斜率、均线黏合度、ADX趋势强度"
                />
                <DimensionItem
                  name="动量评分"
                  weight="20%"
                  desc="RSI双周期(6+14)、MACD信号+柱状体变化、KDJ随机指标、Williams %R、多周期涨跌幅"
                />
                <DimensionItem
                  name="波动率评分"
                  weight="15%"
                  desc="年化波动率、布林带宽度+价格位置、ATR(14)相对波动、波动率收敛/发散趋势"
                />
                <DimensionItem
                  name="成交量评分"
                  weight="20%"
                  desc="多级量比(5/10/20日)、OBV能量潮、VWAP偏离度、量价配合度、成交量趋势"
                />
                <DimensionItem
                  name="价值评分"
                  weight="20%"
                  desc="区间位置连续评分、筹码集中度、多级支撑压力(10/20/60日)、价格动态区间"
                />
              </div>
            </div>

            {/* 右列: AI */}
            <div className="methodology-col">
              <div className="methodology-col-title">
                <span className="col-dot ai-dot" />
                AI大模型评分 (50%)
              </div>
              <div className="methodology-col-desc">
                由腾讯混元2.0大模型进行专业分析，每只股票单独评估
              </div>
              <div className="dimension-list">
                <DimensionItem
                  name="公司基本面"
                  weight="40%"
                  desc="经营质量、财务健康(三道红线)、土储质量、销售回款、管理层能力"
                />
                <DimensionItem
                  name="行业政策与周期"
                  weight="30%"
                  desc="房地产调控政策、行业周期阶段、融资环境、市场供需格局"
                />
                <DimensionItem
                  name="技术面与资金面"
                  weight="20%"
                  desc="价格趋势、机构资金动向、北向资金、筹码结构分析"
                />
                <DimensionItem
                  name="风险评估"
                  weight="10%"
                  desc="债务违约风险、项目交付风险、系统性行业风险"
                />
              </div>
            </div>
          </div>

          {/* 评级映射 */}
          <div className="methodology-ratings">
            <div className="methodology-ratings-title">评级映射标准</div>
            <div className="rating-map-row">
              <RatingBadge label="强烈推荐" range="≥ 80分" cls="badge-strong-buy" />
              <RatingBadge label="推荐" range="65-79分" cls="badge-buy" />
              <RatingBadge label="中性" range="50-64分" cls="badge-neutral" />
              <RatingBadge label="谨慎" range="35-49分" cls="badge-caution" />
              <RatingBadge label="回避" range="< 35分" cls="badge-avoid" />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function DimensionItem({ name, weight, desc }) {
  return (
    <div className="dimension-item">
      <div className="dimension-name">
        {name}
        {weight && <span className="dimension-weight">{weight}</span>}
      </div>
      <div className="dimension-desc">{desc}</div>
    </div>
  )
}

function RatingBadge({ label, range, cls }) {
  return (
    <div className="rating-map-item">
      <span className={`badge ${cls}`}>{label}</span>
      <span className="rating-map-range">{range}</span>
    </div>
  )
}
