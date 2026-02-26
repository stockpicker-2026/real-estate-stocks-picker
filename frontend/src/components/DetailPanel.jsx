import React, { useEffect, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid
} from 'recharts'
import { api } from '../api'

function getScoreColor(score) {
  if (score >= 70) return 'var(--green)'
  if (score >= 50) return 'var(--accent)'
  if (score >= 35) return 'var(--orange)'
  return 'var(--red)'
}

function getBadgeClass(rating) {
  switch (rating) {
    case '优选': return 'badge-strong-buy'
    case '关注': return 'badge-buy'
    case '中性': return 'badge-neutral'
    case '谨慎': return 'badge-caution'
    default: return 'badge-neutral'
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

export default function DetailPanel({ rating, onClose }) {
  const [prices, setPrices] = useState([])
  const [ratingTrend, setRatingTrend] = useState([])
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!rating) return
    setLoading(true)
    Promise.all([
      api.getPrices(rating.code, 60).catch(() => []),
      api.getRatingTrend(rating.code, 60).catch(() => []),
      api.getRatingHistory(rating.code, 60).catch(() => []),
    ]).then(([p, t, h]) => {
      setPrices(p)
      setRatingTrend(t)
      setHistory(h)
      setLoading(false)
    })
  }, [rating])

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!rating) return null

  // 计算量化综合分（5维度加权，保留2位小数）
  const quantScore = (
    rating.trend_score * 0.25 +
    rating.momentum_score * 0.20 +
    rating.volatility_score * 0.15 +
    rating.volume_score * 0.20 +
    rating.value_score * 0.20
  ).toFixed(2)

  const scores = [
    { label: '趋势评分', value: rating.trend_score, key: 'trend' },
    { label: '动量评分', value: rating.momentum_score, key: 'momentum' },
    { label: '波动评分', value: rating.volatility_score, key: 'volatility' },
    { label: '成交评分', value: rating.volume_score, key: 'volume' },
    { label: '价值评分', value: rating.value_score, key: 'value' },
    { label: 'AI评分', value: rating.ai_score, key: 'ai' },
  ]

  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={e => e.stopPropagation()}>
        <div className="detail-header">
          <div>
            <div className="detail-title">{rating.name}</div>
            <div className="detail-subtitle">
              {rating.code} · {getMarketLabel(rating.market)} · {rating.date}
            </div>
          </div>
          <button className="detail-close" onClick={onClose}>×</button>
        </div>

        <div className="detail-body">
          {/* 总评分 */}
          <div className="total-score-card">
            <div className="total-score-number">{typeof rating.total_score === 'number' ? rating.total_score.toFixed(2) : rating.total_score}</div>
            <div className="total-score-label">
              <span className={`badge ${getBadgeClass(rating.rating)}`} style={{ color: '#fff', background: 'rgba(255,255,255,0.2)' }}>
                {rating.rating}
              </span>
            </div>
            {rating.ai_score > 0 && (
              <div style={{ marginTop: 10, fontSize: 12, opacity: 0.75 }}>
                {rating.fundamental_score != null
                  ? `量化 ${quantScore}×40% + 基本面 ${rating.fundamental_score.toFixed(1)}×15% + AI ${typeof rating.ai_score === 'number' ? rating.ai_score.toFixed(2) : rating.ai_score}×45%`
                  : `量化 ${quantScore}×50% + AI ${typeof rating.ai_score === 'number' ? rating.ai_score.toFixed(2) : rating.ai_score}×50%`
                }
              </div>
            )}
          </div>

          {/* 财务数据（来自iFinD） */}
          {(rating.pe_ttm != null || rating.pb_mrq != null || rating.roe != null) && (
            <div className="detail-section">
              <div className="detail-section-title">财务数据 <span style={{fontSize:11,color:'var(--text-muted)',fontWeight:400}}>（同花顺iFinD）</span></div>
              <div className="scores-grid">
                {rating.pe_ttm != null && (
                  <div className="score-item">
                    <div className="score-item-label">PE(TTM)</div>
                    <div className="score-item-value" style={{ color: rating.pe_ttm < 0 ? 'var(--red)' : rating.pe_ttm < 30 ? 'var(--green)' : 'var(--orange)' }}>
                      {rating.pe_ttm.toFixed(2)}
                    </div>
                  </div>
                )}
                {rating.pb_mrq != null && (
                  <div className="score-item">
                    <div className="score-item-label">PB(MRQ)</div>
                    <div className="score-item-value" style={{ color: rating.pb_mrq < 1 ? 'var(--accent)' : 'var(--text-primary)' }}>
                      {rating.pb_mrq.toFixed(4)}{rating.pb_mrq < 1 && rating.pb_mrq > 0 ? ' 破净' : ''}
                    </div>
                  </div>
                )}
                {rating.market_value != null && (
                  <div className="score-item">
                    <div className="score-item-label">总市值</div>
                    <div className="score-item-value">{rating.market_value.toFixed(0)}亿</div>
                  </div>
                )}
                {rating.roe != null && (
                  <div className="score-item">
                    <div className="score-item-label">ROE</div>
                    <div className="score-item-value" style={{ color: rating.roe > 8 ? 'var(--green)' : rating.roe < 0 ? 'var(--red)' : 'var(--text-primary)' }}>
                      {rating.roe.toFixed(2)}%
                    </div>
                  </div>
                )}
                {rating.eps != null && (
                  <div className="score-item">
                    <div className="score-item-label">EPS</div>
                    <div className="score-item-value">{rating.eps.toFixed(4)}</div>
                  </div>
                )}
                {rating.debt_ratio != null && (
                  <div className="score-item">
                    <div className="score-item-label">负债率</div>
                    <div className="score-item-value" style={{ color: rating.debt_ratio > 85 ? 'var(--red)' : rating.debt_ratio > 80 ? 'var(--orange)' : 'var(--green)' }}>
                      {rating.debt_ratio.toFixed(1)}%
                    </div>
                  </div>
                )}
                {rating.fundamental_score != null && (
                  <div className="score-item">
                    <div className="score-item-label">基本面评分</div>
                    <div className="score-item-value" style={{ color: getScoreColor(rating.fundamental_score) }}>
                      {rating.fundamental_score.toFixed(2)}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 维度评分 */}
          <div className="detail-section">
            <div className="detail-section-title">维度评分</div>
            <div className="scores-grid">
              {scores.map(s => (
                <div className="score-item" key={s.key}>
                  <div className="score-item-label">{s.label}</div>
                  <div className="score-item-value" style={{ color: getScoreColor(s.value) }}>
                    {typeof s.value === 'number' ? s.value.toFixed(2) : s.value}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 评级理由 / AI分析 */}
          <div className="detail-section">
            <div className="detail-section-title">
              {rating.ai_score > 0 ? 'AI 专业分析' : '评级理由'}
            </div>

            {rating.ai_score > 0 ? (
              <div className="ai-analysis-card">
                <div className="ai-analysis-header">
                  <span className="ai-analysis-badge">
                    <span>&#x1F916;</span> 腾讯混元2.0
                  </span>
                  <span className="ai-analysis-model">AI评分: {typeof rating.ai_score === 'number' ? rating.ai_score.toFixed(2) : rating.ai_score}分</span>
                </div>
                <div className="ai-analysis-content">{rating.reason}</div>
                <div className="score-composition">
                  <span className="score-comp-part">
                    <span className="score-comp-dot" style={{ background: 'var(--accent)' }} />
                    量化({quantScore}) ×{rating.fundamental_score != null ? '40%' : '50%'}
                  </span>
                  {rating.fundamental_score != null && (
                    <>
                      <span style={{ color: 'var(--text-muted)' }}>+</span>
                      <span className="score-comp-part">
                        <span className="score-comp-dot" style={{ background: 'var(--green)' }} />
                        基本面({rating.fundamental_score.toFixed(1)}) ×15%
                      </span>
                    </>
                  )}
                  <span style={{ color: 'var(--text-muted)' }}>+</span>
                  <span className="score-comp-part">
                    <span className="score-comp-dot" style={{ background: 'var(--purple)' }} />
                    AI({typeof rating.ai_score === 'number' ? rating.ai_score.toFixed(2) : rating.ai_score}) ×{rating.fundamental_score != null ? '45%' : '50%'}
                  </span>
                  <span style={{ color: 'var(--text-muted)' }}>=</span>
                  <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                    综合 {typeof rating.total_score === 'number' ? rating.total_score.toFixed(2) : rating.total_score}
                  </span>
                </div>
              </div>
            ) : (
              <div className="reason-text">{rating.reason}</div>
            )}
          </div>

          {/* 价格走势 */}
          {!loading && prices.length > 0 && (
            <div className="detail-section">
              <div className="detail-section-title">近期价格走势</div>
              <div className="chart-container">
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={prices}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={v => v.slice(5)}
                      tick={{ fontSize: 11, fill: '#9ca3af' }}
                    />
                    <YAxis
                      domain={['dataMin', 'dataMax']}
                      tick={{ fontSize: 11, fill: '#9ca3af' }}
                      width={50}
                    />
                    <Tooltip
                      contentStyle={{ borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 12 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="close"
                      stroke="#2563eb"
                      strokeWidth={2}
                      dot={false}
                      name="收盘价"
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* 评分趋势 */}
          {!loading && ratingTrend.length > 1 && (
            <div className="detail-section">
              <div className="detail-section-title">评分趋势</div>
              <div className="chart-container">
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={ratingTrend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={v => v.slice(5)}
                      tick={{ fontSize: 11, fill: '#9ca3af' }}
                    />
                    <YAxis
                      domain={[0, 100]}
                      tick={{ fontSize: 11, fill: '#9ca3af' }}
                      width={35}
                    />
                    <Tooltip
                      contentStyle={{ borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 12 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="total_score"
                      stroke="#7c3aed"
                      strokeWidth={2}
                      dot={false}
                      name="综合评分"
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* 历史评级 */}
          {!loading && history.length > 0 && (
            <div className="detail-section">
              <div className="detail-section-title">历史评级记录</div>
              <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                <table className="table" style={{ fontSize: 12 }}>
                  <thead>
                    <tr>
                      <th>日期</th>
                      <th>评分</th>
                      <th>评级</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map(h => (
                      <tr key={h.date} style={{ cursor: 'default' }}>
                        <td>{h.date}</td>
                        <td style={{ fontWeight: 600, color: getScoreColor(h.total_score) }}>
                          {typeof h.total_score === 'number' ? h.total_score.toFixed(2) : h.total_score}
                        </td>
                        <td>
                          <span className={`badge ${getBadgeClass(h.rating)}`}>{h.rating}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
