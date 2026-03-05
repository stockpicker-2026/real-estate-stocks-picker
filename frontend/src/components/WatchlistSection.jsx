import React, { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../api'

const MAX_WATCHLIST = 15
const CACHE_KEY = 'watchlist_analysis'
const ANALYZING_KEY = 'watchlist_analyzing'

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

// 全局分析 promise，组件卸载后请求仍继续
let _analyzePromise = null

export default function WatchlistSection({ user, onSelectStock }) {
  const [watchlist, setWatchlist] = useState([])
  const [analysis, setAnalysis] = useState([])
  const [stocks, setStocks] = useState([])
  const [loading, setLoading] = useState(true)
  const [analyzing, setAnalyzing] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [addLoading, setAddLoading] = useState(false)
  const mountedRef = useRef(true)

  // 模拟仓位相关
  const [showPortfolio, setShowPortfolio] = useState(false)
  const [weights, setWeights] = useState({})        // { stock_code: number }
  const [savedWeights, setSavedWeights] = useState({})
  const [savingWeights, setSavingWeights] = useState(false)
  const [performance, setPerformance] = useState(null)
  const [perfLoading, setPerfLoading] = useState(false)
  const [perfDays, setPerfDays] = useState(30)

  // 组件挂载时恢复缓存的分析结果 & 检测后台分析状态
  useEffect(() => {
    mountedRef.current = true
    try {
      const cached = localStorage.getItem(CACHE_KEY)
      if (cached) {
        const { data, time } = JSON.parse(cached)
        // 缓存24小时内有效
        if (Date.now() - time < 24 * 60 * 60 * 1000 && Array.isArray(data)) {
          setAnalysis(data)
        }
      }
    } catch {}

    // 如果有后台分析正在进行，恢复 analyzing 状态并轮询
    if (_analyzePromise || localStorage.getItem(ANALYZING_KEY)) {
      setAnalyzing(true)
      if (_analyzePromise) {
        _analyzePromise.then(data => {
          if (mountedRef.current && data) {
            setAnalysis(data)
            setAnalyzing(false)
          }
        }).catch(() => {
          if (mountedRef.current) setAnalyzing(false)
        })
      } else {
        // 页面刷新后 promise 丢失，清除过期标记
        localStorage.removeItem(ANALYZING_KEY)
        setAnalyzing(false)
      }
    }

    return () => { mountedRef.current = false }
  }, [])

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

  const loadPortfolioWeights = useCallback(async () => {
    try {
      const data = await api.getPortfolioWeights()
      const wMap = {}
      data.forEach(d => { wMap[d.stock_code] = d.weight })
      setWeights(wMap)
      setSavedWeights(wMap)
    } catch (err) {
      console.error('加载仓位失败:', err)
    }
  }, [])

  const loadPerformance = useCallback(async (d) => {
    setPerfLoading(true)
    try {
      const data = await api.getPortfolioPerformance(d || perfDays)
      if (mountedRef.current) setPerformance(data)
    } catch (err) {
      console.error('加载收益率失败:', err)
    }
    if (mountedRef.current) setPerfLoading(false)
  }, [perfDays])

  useEffect(() => {
    loadWatchlist()
    loadStocks()
    loadPortfolioWeights()
  }, [loadWatchlist, loadStocks, loadPortfolioWeights])

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

  const handleAnalyze = () => {
    if (watchlist.length === 0 || _analyzePromise) return
    setAnalyzing(true)
    localStorage.setItem(ANALYZING_KEY, '1')

    _analyzePromise = api.getWatchlistAnalysis()
      .then(data => {
        // 缓存结果
        localStorage.setItem(CACHE_KEY, JSON.stringify({ data, time: Date.now() }))
        localStorage.removeItem(ANALYZING_KEY)
        if (mountedRef.current) {
          setAnalysis(data)
          setAnalyzing(false)
        }
        _analyzePromise = null
        return data
      })
      .catch(err => {
        localStorage.removeItem(ANALYZING_KEY)
        if (mountedRef.current) {
          setAnalyzing(false)
          alert('获取AI分析失败: ' + err.message)
        }
        _analyzePromise = null
        throw err
      })
  }

  // 仓位操作
  const handleWeightChange = (code, val) => {
    const num = parseFloat(val) || 0
    setWeights(prev => ({ ...prev, [code]: Math.min(100, Math.max(0, num)) }))
  }

  const handleEqualWeight = () => {
    const n = watchlist.length
    if (n === 0) return
    const w = parseFloat((100 / n).toFixed(2))
    const newWeights = {}
    watchlist.forEach((item, i) => {
      newWeights[item.stock_code] = i === n - 1 ? parseFloat((100 - w * (n - 1)).toFixed(2)) : w
    })
    setWeights(newWeights)
  }

  const handleSaveWeights = async () => {
    const weightList = watchlist
      .filter(w => (weights[w.stock_code] || 0) > 0)
      .map(w => ({ stock_code: w.stock_code, weight: weights[w.stock_code] || 0 }))
    const total = weightList.reduce((s, w) => s + w.weight, 0)
    if (weightList.length > 0 && Math.abs(total - 100) > 0.01) {
      alert(`仓位百分比之和须等于100%，当前为${total.toFixed(1)}%`)
      return
    }
    setSavingWeights(true)
    try {
      await api.updatePortfolioWeights(weightList)
      setSavedWeights({ ...weights })
      await loadPerformance()
    } catch (err) {
      alert('保存失败: ' + err.message)
    }
    setSavingWeights(false)
  }

  const totalWeight = watchlist.reduce((s, w) => s + (weights[w.stock_code] || 0), 0)
  const hasWeightChanges = JSON.stringify(weights) !== JSON.stringify(savedWeights)

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
              {analyzing ? 'AI分析中（可离开本页）...' : 'AI操作建议'}
            </button>
          )}
          {watchlist.length > 0 && (
            <button
              className="btn"
              onClick={() => { setShowPortfolio(!showPortfolio); if (!showPortfolio && Object.keys(savedWeights).length > 0) loadPerformance() }}
              style={showPortfolio ? { background: 'var(--primary)', color: '#fff' } : {}}
            >
              {showPortfolio ? '收起仓位' : '模拟仓位'}
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
            {filteredStocks.map(s => (
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

      {/* 模拟仓位配置 */}
      {showPortfolio && watchlist.length > 0 && (
        <div className="portfolio-section">
          <div className="portfolio-header">
            <h3 className="portfolio-title">模拟仓位配置</h3>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span className={`portfolio-total ${Math.abs(totalWeight - 100) < 0.01 ? 'valid' : totalWeight > 0 ? 'invalid' : ''}`}>
                合计: {totalWeight.toFixed(1)}%
              </span>
              <button className="btn btn-sm" onClick={handleEqualWeight}>均分</button>
              <button
                className="btn btn-sm btn-primary"
                onClick={handleSaveWeights}
                disabled={savingWeights || !hasWeightChanges}
              >
                {savingWeights ? '保存中...' : '保存'}
              </button>
            </div>
          </div>

          <div className="portfolio-grid">
            {watchlist.map(w => (
              <div key={w.stock_code} className="portfolio-item">
                <div className="portfolio-stock-info">
                  <span className="portfolio-stock-name">{w.stock_name}</span>
                  <span className="portfolio-stock-code">{w.stock_code}</span>
                </div>
                <div className="portfolio-weight-input-wrap">
                  <input
                    type="number"
                    className="portfolio-weight-input"
                    value={weights[w.stock_code] || ''}
                    onChange={e => handleWeightChange(w.stock_code, e.target.value)}
                    placeholder="0"
                    min="0"
                    max="100"
                    step="0.1"
                  />
                  <span className="portfolio-weight-unit">%</span>
                </div>
                <div className="portfolio-weight-bar">
                  <div
                    className="portfolio-weight-bar-fill"
                    style={{ width: `${Math.min(100, weights[w.stock_code] || 0)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>

          {/* 收益率统计 */}
          {performance && performance.daily_returns.length > 0 && (
            <div className="portfolio-perf">
              <div className="portfolio-perf-header">
                <h4 className="portfolio-perf-title">组合收益率</h4>
                <div className="portfolio-perf-days">
                  {[7, 30, 90].map(d => (
                    <button
                      key={d}
                      className={`btn btn-sm ${perfDays === d ? 'btn-primary' : ''}`}
                      onClick={() => { setPerfDays(d); loadPerformance(d) }}
                    >
                      {d}天
                    </button>
                  ))}
                </div>
              </div>

              <div className="portfolio-perf-stats">
                <div className="perf-stat">
                  <span className="perf-stat-label">总收益率</span>
                  <span className={`perf-stat-value ${performance.total_return >= 0 ? 'up' : 'down'}`}>
                    {performance.total_return >= 0 ? '+' : ''}{performance.total_return.toFixed(2)}%
                  </span>
                </div>
                {performance.annualized_return != null && (
                  <div className="perf-stat">
                    <span className="perf-stat-label">年化收益率</span>
                    <span className={`perf-stat-value ${performance.annualized_return >= 0 ? 'up' : 'down'}`}>
                      {performance.annualized_return >= 0 ? '+' : ''}{performance.annualized_return.toFixed(2)}%
                    </span>
                  </div>
                )}
                {performance.max_drawdown != null && (
                  <div className="perf-stat">
                    <span className="perf-stat-label">最大回撤</span>
                    <span className="perf-stat-value down">-{performance.max_drawdown.toFixed(2)}%</span>
                  </div>
                )}
              </div>

              {/* 简易收益率曲线 */}
              <div className="portfolio-chart">
                <PerformanceChart data={performance.daily_returns} />
              </div>

              {/* 每日收益率表格 */}
              <div className="portfolio-table-wrap">
                <table className="portfolio-table">
                  <thead>
                    <tr>
                      <th>日期</th>
                      <th>日收益率</th>
                      <th>累计收益率</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...performance.daily_returns].reverse().slice(0, 10).map(d => (
                      <tr key={d.date}>
                        <td>{d.date}</td>
                        <td className={d.daily_return >= 0 ? 'up' : 'down'}>
                          {d.daily_return >= 0 ? '+' : ''}{d.daily_return.toFixed(2)}%
                        </td>
                        <td className={d.cumulative_return >= 0 ? 'up' : 'down'}>
                          {d.cumulative_return >= 0 ? '+' : ''}{d.cumulative_return.toFixed(2)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {perfLoading && (
            <div className="loading" style={{ padding: '20px 0' }}>
              <div className="loading-dot" />
              <div className="loading-dot" />
              <div className="loading-dot" />
            </div>
          )}
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
          .portfolio-grid {
            grid-template-columns: 1fr;
          }
        }

        .portfolio-section {
          margin-top: 20px;
          background: var(--card-bg, #fff);
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 12px;
          padding: 20px;
        }
        .portfolio-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
          flex-wrap: wrap;
          gap: 8px;
        }
        .portfolio-title {
          font-size: 16px;
          font-weight: 600;
          margin: 0;
        }
        .portfolio-total {
          font-size: 13px;
          font-weight: 600;
          padding: 2px 10px;
          border-radius: 12px;
          background: #f3f4f6;
          color: #6b7280;
        }
        .portfolio-total.valid {
          background: #dcfce7;
          color: #166534;
        }
        .portfolio-total.invalid {
          background: #fee2e2;
          color: #991b1b;
        }
        .btn-sm {
          padding: 4px 12px;
          font-size: 12px;
          border-radius: 6px;
        }
        .portfolio-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
          gap: 10px;
        }
        .portfolio-item {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 8px 12px;
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 8px;
          background: var(--bg, #f9fafb);
        }
        .portfolio-stock-info {
          flex: 1;
          min-width: 0;
        }
        .portfolio-stock-name {
          font-weight: 500;
          font-size: 13px;
          display: block;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .portfolio-stock-code {
          font-size: 11px;
          color: var(--text-muted, #9ca3af);
        }
        .portfolio-weight-input-wrap {
          display: flex;
          align-items: center;
          gap: 2px;
        }
        .portfolio-weight-input {
          width: 56px;
          padding: 4px 6px;
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 6px;
          font-size: 13px;
          text-align: right;
          outline: none;
          background: var(--card-bg, #fff);
        }
        .portfolio-weight-input:focus {
          border-color: var(--primary, #667eea);
          box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.15);
        }
        .portfolio-weight-unit {
          font-size: 12px;
          color: var(--text-muted, #9ca3af);
        }
        .portfolio-weight-bar {
          width: 50px;
          height: 6px;
          background: #e5e7eb;
          border-radius: 3px;
          overflow: hidden;
        }
        .portfolio-weight-bar-fill {
          height: 100%;
          background: var(--primary, #667eea);
          border-radius: 3px;
          transition: width 0.2s;
        }

        .portfolio-perf {
          margin-top: 20px;
          padding-top: 20px;
          border-top: 1px solid var(--border, #e5e7eb);
        }
        .portfolio-perf-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }
        .portfolio-perf-title {
          font-size: 15px;
          font-weight: 600;
          margin: 0;
        }
        .portfolio-perf-days {
          display: flex;
          gap: 6px;
        }
        .portfolio-perf-stats {
          display: flex;
          gap: 24px;
          margin-bottom: 16px;
          flex-wrap: wrap;
        }
        .perf-stat {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .perf-stat-label {
          font-size: 12px;
          color: var(--text-muted, #9ca3af);
        }
        .perf-stat-value {
          font-size: 20px;
          font-weight: 700;
        }
        .perf-stat-value.up { color: #10b981; }
        .perf-stat-value.down { color: #ef4444; }

        .portfolio-chart {
          margin-bottom: 16px;
          background: var(--bg, #f9fafb);
          border-radius: 8px;
          padding: 12px;
        }
        .portfolio-chart svg {
          width: 100%;
          height: auto;
        }

        .portfolio-table-wrap {
          max-height: 300px;
          overflow-y: auto;
          border-radius: 8px;
          border: 1px solid var(--border, #e5e7eb);
        }
        .portfolio-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 13px;
        }
        .portfolio-table th {
          background: var(--bg, #f9fafb);
          padding: 8px 12px;
          text-align: left;
          font-weight: 600;
          position: sticky;
          top: 0;
          border-bottom: 1px solid var(--border, #e5e7eb);
        }
        .portfolio-table td {
          padding: 6px 12px;
          border-bottom: 1px solid var(--border, #e5e7eb);
        }
        .portfolio-table td.up { color: #10b981; font-weight: 500; }
        .portfolio-table td.down { color: #ef4444; font-weight: 500; }
      `}</style>
    </div>
  )
}


function PerformanceChart({ data }) {
  if (!data || data.length < 2) return null

  const width = 800
  const height = 200
  const padding = { top: 20, right: 20, bottom: 30, left: 50 }
  const chartW = width - padding.left - padding.right
  const chartH = height - padding.top - padding.bottom

  const values = data.map(d => d.cumulative_return)
  const minV = Math.min(0, ...values)
  const maxV = Math.max(0, ...values)
  const range = maxV - minV || 1

  const xScale = (i) => padding.left + (i / (data.length - 1)) * chartW
  const yScale = (v) => padding.top + chartH - ((v - minV) / range) * chartH

  const points = data.map((d, i) => `${xScale(i)},${yScale(d.cumulative_return)}`).join(' ')
  const zeroY = yScale(0)

  // 填充区域
  const areaPoints = [
    `${xScale(0)},${zeroY}`,
    ...data.map((d, i) => `${xScale(i)},${yScale(d.cumulative_return)}`),
    `${xScale(data.length - 1)},${zeroY}`,
  ].join(' ')

  const lastVal = values[values.length - 1]
  const lineColor = lastVal >= 0 ? '#10b981' : '#ef4444'
  const fillColor = lastVal >= 0 ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)'

  // Y轴刻度
  const yTicks = 5
  const yLabels = Array.from({ length: yTicks + 1 }, (_, i) => minV + (range / yTicks) * i)

  // X轴日期标签（最多显示6个）
  const xLabelCount = Math.min(6, data.length)
  const xStep = Math.max(1, Math.floor((data.length - 1) / (xLabelCount - 1)))

  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
      {/* 网格线 */}
      {yLabels.map((v, i) => (
        <g key={i}>
          <line x1={padding.left} y1={yScale(v)} x2={width - padding.right} y2={yScale(v)}
            stroke="#e5e7eb" strokeWidth="1" strokeDasharray={v === 0 ? '' : '4,4'} />
          <text x={padding.left - 6} y={yScale(v) + 4} textAnchor="end" fontSize="10" fill="#9ca3af">
            {v.toFixed(1)}%
          </text>
        </g>
      ))}

      {/* 零线 */}
      <line x1={padding.left} y1={zeroY} x2={width - padding.right} y2={zeroY}
        stroke="#9ca3af" strokeWidth="1" />

      {/* 填充 */}
      <polygon points={areaPoints} fill={fillColor} />

      {/* 曲线 */}
      <polyline points={points} fill="none" stroke={lineColor} strokeWidth="2" />

      {/* X轴标签 */}
      {Array.from({ length: xLabelCount }, (_, i) => {
        const idx = Math.min(i * xStep, data.length - 1)
        const label = data[idx].date.slice(5) // MM-DD
        return (
          <text key={i} x={xScale(idx)} y={height - 6} textAnchor="middle" fontSize="10" fill="#9ca3af">
            {label}
          </text>
        )
      })}
    </svg>
  )
}
