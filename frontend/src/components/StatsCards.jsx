import React, { useState, useEffect } from 'react'
import { api } from '../api'

export default function StatsCards({ dashboard }) {
  const [showStockList, setShowStockList] = useState(false)
  const [showRatedList, setShowRatedList] = useState(false)
  const [stockList, setStockList] = useState([])
  const [ratedList, setRatedList] = useState([])

  useEffect(() => {
    if (showStockList && stockList.length === 0) {
      api.getStocks().then(setStockList).catch(() => {})
    }
  }, [showStockList, stockList.length])

  useEffect(() => {
    if (showRatedList && ratedList.length === 0) {
      api.getLatestRatings({ sort_by: 'total_score', sort_dir: 'desc' })
        .then(setRatedList)
        .catch(() => {})
    }
  }, [showRatedList, ratedList.length])

  if (!dashboard) return null

  const {
    total_stocks, rated_today, avg_score, rating_distribution,
    ai_success_count = 0, quant_only_count = 0, refresh_time,
  } = dashboard

  const allAI = rated_today > 0 && ai_success_count === rated_today
  const partialAI = ai_success_count > 0 && ai_success_count < rated_today
  const noAI = rated_today > 0 && ai_success_count === 0

  return (
    <>
      <div className="stats-grid">
        <div
          className="stat-card stat-card-clickable"
          onClick={() => setShowStockList(true)}
          title="点击查看股票清单"
        >
          <div className="stat-label">跟踪股票</div>
          <div className="stat-value">{total_stocks}</div>
          <div className="stat-sub">A股 / 港股 / 美股 <span className="stat-click-hint">点击查看</span></div>
        </div>
        <div
          className="stat-card stat-card-clickable"
          onClick={() => setShowRatedList(true)}
          title="点击查看已评级清单"
        >
          <div className="stat-label">已评级</div>
          <div className="stat-value">{rated_today}</div>
          <div className="stat-sub">最新一期 <span className="stat-click-hint">点击查看</span></div>
        </div>
        <div className="stat-card">
          <div className="stat-label">平均评分</div>
          <div className="stat-value" style={{ color: avg_score >= 60 ? 'var(--green)' : avg_score >= 45 ? 'var(--orange)' : 'var(--red)' }}>
            {avg_score}
          </div>
          <div className="stat-sub">满分100</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">评级分布</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            {Object.entries(rating_distribution || {}).map(([k, v]) => (
              <span key={k} className={`badge ${getBadgeClass(k)}`}>
                {k} {v}
              </span>
            ))}
            {Object.keys(rating_distribution || {}).length === 0 && (
              <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>暂无数据</span>
            )}
          </div>
        </div>
      </div>

      {/* AI分析状态提示 */}
      {rated_today > 0 && (
        <div className={`refresh-status ${allAI ? 'status-success' : partialAI ? 'status-partial' : 'status-quant'}`}>
          <span className="status-icon">{allAI ? '✅' : partialAI ? '⚠️' : '📊'}</span>
          <span className="status-text">
            {allAI && `AI+量化混合分析成功 — 全部 ${rated_today} 只股票均已完成AI大模型+量化双引擎评级`}
            {partialAI && `部分AI分析成功 — ${ai_success_count} 只使用AI+量化混合评级，${quant_only_count} 只仅使用量化评级`}
            {noAI && `纯量化分析模式 — AI大模型暂不可用，${rated_today} 只股票均使用量化引擎评级`}
          </span>
          {refresh_time && (
            <span className="status-time">更新于 {refresh_time}</span>
          )}
        </div>
      )}

      {/* 跟踪股票清单弹窗 */}
      {showStockList && (
        <div className="modal-overlay" onClick={() => setShowStockList(false)}>
          <div className="modal-content stock-list-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>跟踪股票清单（{stockList.length}只）</h3>
              <button className="detail-close" onClick={() => setShowStockList(false)}>×</button>
            </div>
            <div className="modal-body">
              {['A', 'HK', 'US'].map(market => {
                const items = stockList.filter(s => s.market === market)
                if (items.length === 0) return null
                return (
                  <div key={market} className="stock-list-group">
                    <div className="stock-list-group-title">
                      <span className={`market-tag ${getMarketClass(market)}`}>{getMarketLabel(market)}</span>
                      <span className="stock-list-count">{items.length}只</span>
                    </div>
                    <div className="stock-list-items">
                      {items.map(s => (
                        <div key={s.code} className="stock-list-item">
                          <span className="stock-list-name">{s.name}</span>
                          <span className="stock-list-code">{s.code}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* 已评级股票清单弹窗 */}
      {showRatedList && (
        <div className="modal-overlay" onClick={() => setShowRatedList(false)}>
          <div className="modal-content stock-list-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>已评级股票清单（{ratedList.length}只）</h3>
              <button className="detail-close" onClick={() => setShowRatedList(false)}>×</button>
            </div>
            <div className="modal-body">
              <table className="table" style={{ fontSize: 13 }}>
                <thead>
                  <tr>
                    <th>股票名称</th>
                    <th>代码</th>
                    <th>市场</th>
                    <th>综合评分</th>
                    <th>评级</th>
                    <th>AI评分</th>
                  </tr>
                </thead>
                <tbody>
                  {ratedList.map(r => (
                    <tr key={r.code} style={{ cursor: 'default' }}>
                      <td style={{ fontWeight: 600 }}>{r.name}</td>
                      <td style={{ fontFamily: 'monospace', color: 'var(--text-secondary)' }}>{r.code}</td>
                      <td>
                        <span className={`market-tag ${getMarketClass(r.market)}`}>
                          {getMarketLabel(r.market)}
                        </span>
                      </td>
                      <td style={{ fontWeight: 700, color: getScoreColor(r.total_score) }}>
                        {r.total_score}
                      </td>
                      <td><span className={`badge ${getBadgeClass(r.rating)}`}>{r.rating}</span></td>
                      <td>
                        {r.ai_score > 0
                          ? <span style={{ fontWeight: 600, color: getScoreColor(r.ai_score) }}>{r.ai_score}</span>
                          : <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>--</span>
                        }
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function getBadgeClass(rating) {
  switch (rating) {
    case '强烈推荐': return 'badge-strong-buy'
    case '推荐': return 'badge-buy'
    case '中性': return 'badge-neutral'
    case '谨慎': return 'badge-caution'
    case '回避': return 'badge-avoid'
    default: return 'badge-neutral'
  }
}

function getScoreColor(score) {
  if (score >= 70) return 'var(--green)'
  if (score >= 50) return 'var(--accent)'
  if (score >= 35) return 'var(--orange)'
  return 'var(--red)'
}

function getMarketClass(market) {
  switch (market) {
    case 'A': return 'market-a'
    case 'HK': return 'market-hk'
    case 'US': return 'market-us'
    default: return ''
  }
}

function getMarketLabel(market) {
  switch (market) {
    case 'A': return 'A股'
    case 'HK': return '港股'
    case 'US': return '美股'
    default: return market
  }
}
