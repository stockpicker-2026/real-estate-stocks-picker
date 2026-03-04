import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../api'

const MAX_WATCHLIST = 10

const SUGGESTION_COLORS = {
  '买入': { bg: '#dcfce7', color: '#166534', border: '#86efac' },
  '加仓': { bg: '#dcfce7', color: '#166534', border: '#86efac' },
  '持有': { bg: '#dbeafe', color: '#1e40af', border: '#93c5fd' },
  '减仓': { bg: '#fef3c7', color: '#92400e', border: '#fcd34d' },
  '观望': { bg: '#f3f4f6', color: '#4b5563', border: '#d1d5db' },
  '回避': { bg: '#fee2e2', color: '#991b1b', border: '#fca5a5' },
}

const RATING_COLORS = {
  '优选': '#10b981',
  '关注': '#3b82f6',
  '中性': '#f59e0b',
  '谨慎': '#ef4444',
}

export default function WatchlistSection({ user, onSelectStock }) {
  const [watchlist, setWatchlist] = useState([])
  const [analysis, setAnalysis] = useState([])
  const [stocks, setStocks] = useState([])
  const [loading, setLoading] = useState(true)
  const [analyzing, setAnalyzing] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [addLoading, setAddLoading] = useState(false)

  const loadWatchlist = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getWatchlist()
      setWatchlist(data)
    } catch (err) {
      console.error('加载自选股失败:', err)
    }
    setLoading(false)
  }, [])

  const loadStocks = useCallback(async () => {
    try {
      const data = await api.getStocks()
      setStocks(data)
    } catch (err) {
      console.error('加载股票列表失败:', err)
    }
  }, [])

  useEffect(() => {
    loadWatchlist()
    loadStocks()
  }, [loadWatchlist, loadStocks])

  const handleAdd = async (stock) => {
    setAddLoading(true)
    try {
      await api.addToWatchlist(stock.code)
      await loadWatchlist()
      setSearchText('')
    } catch (err) {
      alert(err.message)
    }
    setAddLoading(false)
  }

  const handleRemove = async (code) => {
    if (!window.confirm('确定从自选中移除？')) return
    try {
      await api.removeFromWatchlist(code)
      setWatchlist(prev => prev.filter(w => w.stock_code !== code))
      setAnalysis(prev => prev.filter(a => a.stock_code !== code))
    } catch (err) {
      alert('移除失败: ' + err.message)
    }
  }

  const handleAnalyze = async () => {
    if (watchlist.length === 0) return
    setAnalyzing(true)
    try {
      const data = await api.getWatchlistAnalysis()
      setAnalysis(data)
    } catch (err) {
      alert('获取AI分析失败: ' + err.message)
    }
    setAnalyzing(false)
  }

  // 已在自选中的code集合
  const watchlistCodes = new Set(watchlist.map(w => w.stock_code))

  // 筛选可添加的股票
  const filteredStocks = stocks.filter(s =>
    !watchlistCodes.has(s.code) &&
    (searchText === '' || s.name.includes(searchText) || s.code.includes(searchText))
  )

  // 将analysis与watchlist合并
  const analysisMap = {}
  analysis.forEach(a => { analysisMap[a.stock_code] = a })

  return (
    <div className="watchlist-section">
      <div className="section-header">
        <div className="section-title-row">
          <h2 className="section-title">自选股票池</h2>
          <span className="section-desc">
            已选 {watchlist.length}/{MAX_WATCHLIST} 只 · 从60只房地产股中选择长期跟踪标的
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {watchlist.length > 0 && (
            <button
              className="btn btn-primary"
              onClick={handleAnalyze}
              disabled={analyzing}
            >
              {analyzing ? 'AI分析中...' : 'AI操作建议'}
            </button>
          )}
          {watchlist.length < MAX_WATCHLIST && (
            <button className="btn" onClick={() => setShowAdd(!showAdd)}>
              {showAdd ? '收起' : '+ 添加股票'}
            </button>
          )}
        </div>
      </div>

      {/* 添加股票面板 */}
      {showAdd && (
        <div className="watchlist-add-panel">
          <input
            type="text"
            className="watchlist-search"
            placeholder="搜索股票名称或代码..."
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            autoFocus
          />
          <div className="watchlist-stock-grid">
            {filteredStocks.slice(0, 20).map(s => (
              <button
                key={s.code}
                className="watchlist-stock-chip"
                onClick={() => handleAdd(s)}
                disabled={addLoading}
              >
                <span className="chip-name">{s.name}</span>
                <span className="chip-code">{s.code}</span>
                <span className={`chip-market chip-market-${s.market}`}>{s.market}</span>
              </button>
            ))}
            {filteredStocks.length === 0 && (
              <div style={{ padding: '12px 0', color: 'var(--text-muted)', fontSize: 13 }}>
                {searchText ? '无匹配股票' : '所有股票已在自选中'}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 自选股列表 */}
      {loading ? (
        <div className="loading">
          <div className="loading-dot" />
          <div className="loading-dot" />
          <div className="loading-dot" />
        </div>
      ) : watchlist.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📋</div>
          <div className="empty-state-title">暂无自选股</div>
          <div className="empty-state-desc">
            点击「+ 添加股票」从60只房地产股中选择您关注的标的
          </div>
        </div>
      ) : (
        <div className="watchlist-cards">
          {watchlist.map(w => {
            const a = analysisMap[w.stock_code]
            const sugStyle = a ? (SUGGESTION_COLORS[a.suggestion] || SUGGESTION_COLORS['观望']) : null
            const ratingColor = a?.latest_rating ? (RATING_COLORS[a.latest_rating] || '#6b7280') : '#6b7280'

            return (
              <div key={w.stock_code} className="watchlist-card">
                <div className="watchlist-card-header">
                  <div className="watchlist-card-info">
                    <span className="watchlist-card-name">{w.stock_name}</span>
                    <span className="watchlist-card-code">{w.stock_code}</span>
                    <span className={`watchlist-card-market market-${w.market}`}>{w.market}</span>
                  </div>
                  <button
                    className="watchlist-remove-btn"
                    onClick={() => handleRemove(w.stock_code)}
                    title="移除"
                  >×</button>
                </div>

                {a && (
                  <div className="watchlist-card-analysis">
                    <div className="watchlist-card-scores">
                      <div className="watchlist-score-item">
                        <span className="score-label">评分</span>
                        <span className="score-value">{a.latest_score != null ? a.latest_score.toFixed(1) : '-'}</span>
                      </div>
                      <div className="watchlist-score-item">
                        <span className="score-label">变化</span>
                        <span className={`score-value ${a.score_change > 0 ? 'up' : a.score_change < 0 ? 'down' : ''}`}>
                          {a.score_change != null ? `${a.score_change > 0 ? '+' : ''}${a.score_change}` : '-'}
                        </span>
                      </div>
                      <div className="watchlist-score-item">
                        <span className="score-label">评级</span>
                        <span className="score-value" style={{ color: ratingColor }}>
                          {a.latest_rating || '-'}
                        </span>
                      </div>
                    </div>

                    <div className="watchlist-suggestion" style={{
                      background: sugStyle?.bg,
                      color: sugStyle?.color,
                      borderColor: sugStyle?.border,
                    }}>
                      <span className="suggestion-tag">{a.suggestion}</span>
                      <span className="suggestion-reason">{a.reason}</span>
                    </div>
                  </div>
                )}

                {!a && !analyzing && (
                  <div className="watchlist-card-placeholder">
                    点击「AI操作建议」获取分析
                  </div>
                )}

                {!a && analyzing && (
                  <div className="watchlist-card-placeholder analyzing">
                    <div className="loading-dot" />
                    <div className="loading-dot" />
                    <div className="loading-dot" />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      <style>{`
        .watchlist-section {
          margin-top: 16px;
        }
        .watchlist-add-panel {
          background: var(--card-bg, #fff);
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 12px;
          padding: 16px;
          margin-top: 12px;
        }
        .watchlist-search {
          width: 100%;
          padding: 10px 14px;
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 8px;
          font-size: 14px;
          outline: none;
          background: var(--bg, #f9fafb);
          margin-bottom: 12px;
        }
        .watchlist-search:focus {
          border-color: var(--primary, #667eea);
          box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.15);
        }
        .watchlist-stock-grid {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          max-height: 200px;
          overflow-y: auto;
        }
        .watchlist-stock-chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 20px;
          background: var(--card-bg, #fff);
          cursor: pointer;
          font-size: 13px;
          transition: all 0.15s;
        }
        .watchlist-stock-chip:hover {
          border-color: var(--primary, #667eea);
          background: rgba(102, 126, 234, 0.05);
        }
        .watchlist-stock-chip:disabled {
          opacity: 0.5;
          cursor: wait;
        }
        .chip-name { font-weight: 500; }
        .chip-code { color: var(--text-muted, #9ca3af); font-size: 12px; }
        .chip-market {
          font-size: 10px;
          padding: 1px 6px;
          border-radius: 4px;
          font-weight: 500;
        }
        .chip-market-A { background: #dbeafe; color: #1e40af; }
        .chip-market-HK { background: #fef3c7; color: #92400e; }
        .chip-market-US { background: #dcfce7; color: #166534; }

        .watchlist-cards {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 12px;
          margin-top: 16px;
        }
        .watchlist-card {
          background: var(--card-bg, #fff);
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 12px;
          padding: 16px;
          transition: box-shadow 0.2s;
        }
        .watchlist-card:hover {
          box-shadow: 0 4px 16px rgba(0,0,0,0.08);
        }
        .watchlist-card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
        }
        .watchlist-card-info {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .watchlist-card-name {
          font-weight: 600;
          font-size: 15px;
        }
        .watchlist-card-code {
          color: var(--text-muted, #9ca3af);
          font-size: 12px;
        }
        .watchlist-card-market {
          font-size: 10px;
          padding: 1px 6px;
          border-radius: 4px;
          font-weight: 500;
        }
        .market-A { background: #dbeafe; color: #1e40af; }
        .market-HK { background: #fef3c7; color: #92400e; }
        .market-US { background: #dcfce7; color: #166534; }

        .watchlist-remove-btn {
          width: 24px;
          height: 24px;
          border: none;
          background: transparent;
          color: var(--text-muted, #9ca3af);
          font-size: 18px;
          cursor: pointer;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.15s;
        }
        .watchlist-remove-btn:hover {
          background: #fee2e2;
          color: #ef4444;
        }

        .watchlist-card-analysis {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .watchlist-card-scores {
          display: flex;
          gap: 16px;
        }
        .watchlist-score-item {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .score-label {
          font-size: 11px;
          color: var(--text-muted, #9ca3af);
        }
        .score-value {
          font-size: 16px;
          font-weight: 600;
        }
        .score-value.up { color: #10b981; }
        .score-value.down { color: #ef4444; }

        .watchlist-suggestion {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 14px;
          border-radius: 8px;
          border: 1px solid;
          font-size: 13px;
        }
        .suggestion-tag {
          font-weight: 600;
          white-space: nowrap;
          font-size: 14px;
        }
        .suggestion-reason {
          flex: 1;
          line-height: 1.5;
        }

        .watchlist-card-placeholder {
          color: var(--text-muted, #9ca3af);
          font-size: 13px;
          padding: 8px 0;
        }
        .watchlist-card-placeholder.analyzing {
          display: flex;
          gap: 4px;
          align-items: center;
        }

        @media (max-width: 768px) {
          .watchlist-cards {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  )
}
