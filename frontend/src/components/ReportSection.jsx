import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../api'

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function getFileIcon(name) {
  const ext = (name || '').split('.').pop()?.toLowerCase()
  if (ext === 'pdf') return '📕'
  if (['doc', 'docx'].includes(ext)) return '📘'
  if (['xls', 'xlsx'].includes(ext)) return '📗'
  if (['ppt', 'pptx'].includes(ext)) return '📙'
  return '📄'
}

export default function ReportSection({ user }) {
  const [reports, setReports] = useState([])
  const [loading, setLoading] = useState(true)
  const [showUpload, setShowUpload] = useState(false)

  const isAdmin = user?.is_admin

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getReports()
      setReports(data)
    } catch (err) {
      console.error('加载报告失败:', err)
    }
    setLoading(false)
  }, [])

  useEffect(() => { loadData() }, [loadData])

  const handleDelete = async (id) => {
    if (!window.confirm('确定删除此报告？')) return
    try {
      await api.deleteReport(id)
      loadData()
    } catch (err) {
      alert('删除失败: ' + err.message)
    }
  }

  const handleDownload = (id) => {
    const url = api.getReportDownloadUrl(id)
    const token = localStorage.getItem('token')
    // 使用带认证的下载方式 or 直接下载（下载接口无需认证）
    window.open(url, '_blank')
  }

  return (
    <div className="report-section">
      <div className="section-header">
        <div className="section-title-row">
          <h2 className="section-title">研究报告</h2>
          <span className="section-desc">机构专业研究报告，深度行业分析</span>
        </div>
        {isAdmin && (
          <button className="btn btn-primary btn-sm" onClick={() => setShowUpload(true)}>
            + 上传报告
          </button>
        )}
      </div>

      {loading ? (
        <div className="loading">
          <div className="loading-dot" />
          <div className="loading-dot" />
          <div className="loading-dot" />
        </div>
      ) : reports.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📚</div>
          <div className="empty-state-title">暂无报告</div>
          <div className="empty-state-desc">
            {isAdmin ? '点击上方按钮上传第一份研究报告' : '管理员尚未上传研究报告'}
          </div>
        </div>
      ) : (
        <div className="report-list">
          {reports.map(r => (
            <div key={r.id} className="report-card">
              <div className="report-card-icon">{getFileIcon(r.original_name)}</div>
              <div className="report-card-body">
                <h3 className="report-card-title">{r.title}</h3>
                {r.summary && <p className="report-card-summary">{r.summary}</p>}
                <div className="report-card-meta">
                  {r.institution && <span className="report-institution">{r.institution}</span>}
                  <span className="report-date">{r.publish_date}</span>
                  <span className="report-size">{formatFileSize(r.file_size)}</span>
                  <span className="report-filename">{r.original_name}</span>
                </div>
              </div>
              <div className="report-card-actions">
                <button className="btn btn-primary btn-sm" onClick={() => handleDownload(r.id)}>
                  下载
                </button>
                {isAdmin && (
                  <button className="btn btn-sm btn-danger" onClick={() => handleDelete(r.id)}>
                    删除
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {showUpload && (
        <ReportUploader
          onClose={() => setShowUpload(false)}
          onUploaded={() => { setShowUpload(false); loadData() }}
        />
      )}
    </div>
  )
}


function ReportUploader({ onClose, onUploaded }) {
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [institution, setInstitution] = useState('')
  const [publishDate, setPublishDate] = useState(new Date().toISOString().split('T')[0])
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!title.trim()) { setError('请输入报告标题'); return }
    if (!file) { setError('请选择文件'); return }
    setUploading(true)
    setError('')
    try {
      const formData = new FormData()
      formData.append('title', title.trim())
      formData.append('summary', summary.trim())
      formData.append('institution', institution.trim())
      formData.append('publish_date', publishDate)
      formData.append('file', file)
      await api.uploadReport(formData)
      onUploaded()
    } catch (err) {
      setError(err.message || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content editor-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>上传研究报告</h3>
          <button className="detail-close" onClick={onClose}>×</button>
        </div>
        <form onSubmit={handleSubmit} className="editor-form">
          <div className="form-group">
            <label>报告标题</label>
            <input type="text" value={title} onChange={e => setTitle(e.target.value)} placeholder="请输入报告标题" />
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>发布机构 <span className="optional">(选填)</span></label>
              <input type="text" value={institution} onChange={e => setInstitution(e.target.value)} placeholder="如: 中金公司" />
            </div>
            <div className="form-group">
              <label>发布日期</label>
              <input type="date" value={publishDate} onChange={e => setPublishDate(e.target.value)} />
            </div>
          </div>
          <div className="form-group">
            <label>摘要 <span className="optional">(选填)</span></label>
            <textarea value={summary} onChange={e => setSummary(e.target.value)} placeholder="报告内容简介..." rows={3} />
          </div>
          <div className="form-group">
            <label>选择文件</label>
            <div className="file-upload-area">
              <input
                type="file"
                accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx"
                onChange={e => setFile(e.target.files?.[0] || null)}
              />
              {file && (
                <div className="file-selected">
                  {getFileIcon(file.name)} {file.name} ({formatFileSize(file.size)})
                </div>
              )}
              <p className="file-hint">支持 PDF, Word, Excel, PPT 格式，最大 50MB</p>
            </div>
          </div>
          {error && <div className="login-error">{error}</div>}
          <div className="editor-actions">
            <button type="button" className="btn" onClick={onClose}>取消</button>
            <button type="submit" className="btn btn-primary" disabled={uploading}>
              {uploading ? '上传中...' : '上传'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
