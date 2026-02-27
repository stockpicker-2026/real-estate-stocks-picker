import { useState, useEffect } from 'react'
import { api } from '../api'

export default function NewsSection() {
  const [news, setNews] = useState({ industry_news: [], stock_news: [], announcements: [] })
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    loadNews(5)
    const timer = setInterval(() => loadNews(5), 300000)
    return () => clearInterval(timer)
  }, [])

  async function loadNews(limit) {
    try {
      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), 12000)
      )
      const data = await Promise.race([
        api.getNews(null, null, limit),
        timeoutPromise,
      ])
      setNews(data)
    } catch (e) {
      console.warn('获取资讯失败或超时:', e.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleExpand() {
    setExpanded(true)
    try {
      const data = await api.getNews(null, null, 10)
      setNews(data)
    } catch (e) {
      console.error('获取更多资讯失败:', e)
    }
  }

  // 合并新闻 + 公告，按时间排序
  const allItems = [
    ...(news.industry_news || []).map(n => ({ ...n, type: n.type || 'news' })),
    ...(news.announcements || []).map(n => ({ ...n, type: 'announcement' })),
  ]

  const displayCount = expanded ? 10 : 5
  const displayItems = allItems.slice(0, displayCount)
  const hasMore = !expanded && allItems.length > 5

  if (loading) {
    return (
      <div className="news-section">
        <div className="news-header">
          <h3>📰 地产行业要闻</h3>
          <span className="news-data-source">数据来源：东方财富 · 中国政府网 · 同花顺iFinD</span>
        </div>
        <div className="news-loading">加载资讯中...</div>
      </div>
    )
  }

  if (displayItems.length === 0) {
    return (
      <div className="news-section">
        <div className="news-header">
          <h3>📰 地产行业要闻</h3>
          <span className="news-data-source">数据来源：东方财富 · 中国政府网 · 同花顺iFinD</span>
        </div>
        <div className="news-empty">暂无资讯数据，将在下次刷新时获取</div>
      </div>
    )
  }

  return (
    <div className="news-section">
      <div className="news-header">
        <h3>📰 地产行业要闻</h3>
        <span className="news-data-source">东方财富 · 政府网 · iFinD</span>
        <span className="news-count">{displayItems.length} 条</span>
      </div>
      <div className="news-list">
        {displayItems.map((item, idx) => (
          <div key={idx} className={`news-item ${item.type === 'announcement' ? 'news-item-announcement' : ''}`}>
            <span className={`news-source ${item.type === 'announcement' ? 'news-source-ifind' : ''}`}>
              {item.source}
            </span>
            {item.url ? (
              <a href={item.url} target="_blank" rel="noopener noreferrer" className="news-title">
                {item.title}
              </a>
            ) : (
              <span className="news-title">{item.title}</span>
            )}
            {item.time && <span className="news-time">{item.time}</span>}
          </div>
        ))}
      </div>
      {hasMore && (
        <div className="news-more" onClick={handleExpand}>
          查看更多 ({allItems.length} 条)
        </div>
      )}
      {expanded && allItems.length > 5 && (
        <div className="news-more" onClick={() => setExpanded(false)}>
          收起
        </div>
      )}
    </div>
  )
}
