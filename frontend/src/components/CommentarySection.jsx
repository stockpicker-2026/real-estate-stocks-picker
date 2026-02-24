import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../api'

const CATEGORIES = [
  { value: '', label: '全部点评' },
  { value: 'industry', label: '行业点评' },
  { value: 'stock', label: '个股点评' },
]

export default function CommentarySection({ user }) {
  const [items, setItems] = useState([])
  const [category, setCategory] = useState('')
  const [loading, setLoading] = useState(true)
  const [selectedItem, setSelectedItem] = useState(null)
  const [showEditor, setShowEditor] = useState(false)
  const [editingItem, setEditingItem] = useState(null)

  const isAdmin = user?.is_admin

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getCommentaries(category || undefined)
      setItems(data)
    } catch (err) {
      console.error('加载点评失败:', err)
    }
    setLoading(false)
  }, [category])

  useEffect(() => { loadData() }, [loadData])

  const handleDelete = async (id) => {
    if (!window.confirm('确定删除此条点评？')) return
    try {
      await api.deleteCommentary(id)
      loadData()
      if (selectedItem?.id === id) setSelectedItem(null)
    } catch (err) {
      alert('删除失败: ' + err.message)
    }
  }

  const handleEdit = (item) => {
    setEditingItem(item)
    setShowEditor(true)
  }

  const handleCreate = () => {
    setEditingItem(null)
    setShowEditor(true)
  }

  const handleSaved = () => {
    setShowEditor(false)
    setEditingItem(null)
    loadData()
  }

  return (
    <div className="commentary-section">
      <div className="section-header">
        <div className="section-title-row">
          <h2 className="section-title">市场点评</h2>
          <span className="section-desc">每日房地产市场深度分析与个股点评</span>
        </div>
        {isAdmin && (
          <button className="btn btn-primary btn-sm" onClick={handleCreate}>
            + 发布点评
          </button>
        )}
      </div>

      <div className="commentary-filters">
        {CATEGORIES.map(f => (
          <button
            key={f.value}
            className={`filter-chip ${category === f.value ? 'active' : ''}`}
            onClick={() => setCategory(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="loading">
          <div className="loading-dot" />
          <div className="loading-dot" />
          <div className="loading-dot" />
        </div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📝</div>
          <div className="empty-state-title">暂无点评</div>
          <div className="empty-state-desc">
            {isAdmin ? '点击上方按钮发布第一条市场点评' : '管理员尚未发布市场点评'}
          </div>
        </div>
      ) : (
        <div className="commentary-list">
          {items.map(item => (
            <div
              key={item.id}
              className="commentary-card"
              onClick={() => setSelectedItem(selectedItem?.id === item.id ? null : item)}
            >
              <div className="commentary-card-header">
                <span className={`commentary-tag tag-${item.category}`}>
                  {item.category === 'industry' ? '行业' : '个股'}
                </span>
                <span className="commentary-date">{item.publish_date}</span>
              </div>
              <h3 className="commentary-card-title">{item.title}</h3>
              <p className="commentary-card-preview">
                {item.content.length > 120 ? item.content.slice(0, 120) + '...' : item.content}
              </p>
              <div className="commentary-card-footer">
                <span className="commentary-author">{item.author}</span>
                {isAdmin && (
                  <div className="commentary-actions" onClick={e => e.stopPropagation()}>
                    <button className="btn btn-sm" onClick={() => handleEdit(item)}>编辑</button>
                    <button className="btn btn-sm btn-danger" onClick={() => handleDelete(item.id)}>删除</button>
                  </div>
                )}
              </div>

              {selectedItem?.id === item.id && (
                <div className="commentary-full-content">
                  <div className="commentary-divider" />
                  <div className="commentary-body">{item.content}</div>
                  {item.stock_codes && (
                    <div className="commentary-stocks">
                      关联股票: {item.stock_codes}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {showEditor && (
        <CommentaryEditor
          item={editingItem}
          onClose={() => { setShowEditor(false); setEditingItem(null) }}
          onSaved={handleSaved}
        />
      )}
    </div>
  )
}


function CommentaryEditor({ item, onClose, onSaved }) {
  const [title, setTitle] = useState(item?.title || '')
  const [content, setContent] = useState(item?.content || '')
  const [category, setCategory] = useState(item?.category || 'industry')
  const [stockCodes, setStockCodes] = useState(item?.stock_codes || '')
  const [publishDate, setPublishDate] = useState(
    item?.publish_date || new Date().toISOString().split('T')[0]
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!title.trim() || !content.trim()) {
      setError('标题和内容不能为空')
      return
    }
    setSaving(true)
    setError('')
    try {
      const payload = {
        title: title.trim(),
        content: content.trim(),
        category,
        stock_codes: stockCodes.trim(),
        publish_date: publishDate,
      }
      if (item) {
        await api.updateCommentary(item.id, payload)
      } else {
        await api.createCommentary(payload)
      }
      onSaved()
    } catch (err) {
      setError(err.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content editor-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{item ? '编辑点评' : '发布点评'}</h3>
          <button className="detail-close" onClick={onClose}>×</button>
        </div>
        <form onSubmit={handleSubmit} className="editor-form">
          <div className="form-group">
            <label>标题</label>
            <input type="text" value={title} onChange={e => setTitle(e.target.value)} placeholder="请输入标题" />
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>类型</label>
              <select value={category} onChange={e => setCategory(e.target.value)}>
                <option value="industry">行业点评</option>
                <option value="stock">个股点评</option>
              </select>
            </div>
            <div className="form-group">
              <label>发布日期</label>
              <input type="date" value={publishDate} onChange={e => setPublishDate(e.target.value)} />
            </div>
          </div>
          {category === 'stock' && (
            <div className="form-group">
              <label>关联股票代码 <span className="optional">(逗号分隔)</span></label>
              <input type="text" value={stockCodes} onChange={e => setStockCodes(e.target.value)} placeholder="如: 001979.SZ, 00688.HK" />
            </div>
          )}
          <div className="form-group">
            <label>内容</label>
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              placeholder="请输入点评内容..."
              rows={10}
            />
          </div>
          {error && <div className="login-error">{error}</div>}
          <div className="editor-actions">
            <button type="button" className="btn" onClick={onClose}>取消</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? '保存中...' : '发布'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
