import React from 'react'

const COLUMNS = [
  { key: 'name', label: '股票名称', sortable: true },
  { key: 'code', label: '代码', sortable: true },
  { key: 'market', label: '市场', sortable: false },
  { key: 'total_score', label: '综合评分', sortable: true },
  { key: 'rating', label: '评级', sortable: false },
  { key: 'ai_score', label: 'AI评分', sortable: true },
  { key: 'trend_score', label: '趋势', sortable: true },
  { key: 'momentum_score', label: '动量', sortable: true },
  { key: 'volatility_score', label: '波动', sortable: true },
  { key: 'volume_score', label: '成交', sortable: true },
  { key: 'value_score', label: '价值', sortable: true },
]

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

function ScoreBar({ score }) {
  const color = getScoreColor(score)
  const display = typeof score === 'number' ? score.toFixed(2) : score
  return (
    <div className="score-bar">
      <div className="score-bar-track">
        <div
          className="score-bar-fill"
          style={{ width: `${score}%`, background: color }}
        />
      </div>
      <span className="score-bar-value" style={{ color }}>{display}</span>
    </div>
  )
}

export default function RatingTable({ ratings, sortBy, sortDir, onSort, onSelect }) {
  return (
    <div className="table-wrapper">
      <table className="table">
        <thead>
          <tr>
            {COLUMNS.map(col => (
              <th
                key={col.key}
                onClick={() => col.sortable && onSort(col.key)}
                style={{ cursor: col.sortable ? 'pointer' : 'default' }}
              >
                {col.label}
                {sortBy === col.key && (
                  <span style={{ marginLeft: 4 }}>
                    {sortDir === 'desc' ? '↓' : '↑'}
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ratings.map(r => (
            <tr key={r.code + r.date} onClick={() => onSelect(r)}>
              <td style={{ fontWeight: 600 }}>{r.name}</td>
              <td style={{ color: 'var(--text-secondary)', fontFamily: 'monospace' }}>{r.code}</td>
              <td>
                <span className={`market-tag ${getMarketClass(r.market)}`}>
                  {getMarketLabel(r.market)}
                </span>
              </td>
              <td>
                <span style={{
                  fontSize: 16,
                  fontWeight: 700,
                  color: getScoreColor(r.total_score),
                }}>
                  {typeof r.total_score === 'number' ? r.total_score.toFixed(2) : r.total_score}
                </span>
              </td>
              <td>
                <span className={`badge ${getBadgeClass(r.rating)}`}>{r.rating}</span>
              </td>
              <td>
                {r.ai_score > 0 ? (
                  <span style={{ fontSize: 13, fontWeight: 600, color: getScoreColor(r.ai_score) }}>
                    {typeof r.ai_score === 'number' ? r.ai_score.toFixed(2) : r.ai_score}
                  </span>
                ) : (
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>--</span>
                )}
              </td>
              <td><ScoreBar score={r.trend_score} /></td>
              <td><ScoreBar score={r.momentum_score} /></td>
              <td><ScoreBar score={r.volatility_score} /></td>
              <td><ScoreBar score={r.volume_score} /></td>
              <td><ScoreBar score={r.value_score} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
