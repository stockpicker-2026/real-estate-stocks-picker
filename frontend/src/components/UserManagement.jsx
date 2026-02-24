import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../api'

const MAX_USERS = 100

export default function UserManagement() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)

  const loadUsers = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getUsers()
      setUsers(data)
    } catch (err) {
      console.error('加载用户列表失败:', err)
    }
    setLoading(false)
  }, [])

  useEffect(() => { loadUsers() }, [loadUsers])

  const handleDelete = async (user) => {
    if (!window.confirm(`确定删除用户「${user.display_name || user.username}」？`)) return
    try {
      await api.deleteUser(user.id)
      loadUsers()
    } catch (err) {
      alert('删除失败: ' + err.message)
    }
  }

  return (
    <div className="user-mgmt-section">
      <div className="section-header">
        <div className="section-title-row">
          <h2 className="section-title">用户管理</h2>
          <span className="section-desc">最多支持 {MAX_USERS} 个账户，当前 {users.length} 个</span>
        </div>
        <button
          className="btn btn-primary btn-sm"
          onClick={() => setShowCreate(true)}
          disabled={users.length >= MAX_USERS}
        >
          + 创建用户
        </button>
      </div>

      {loading ? (
        <div className="loading">
          <div className="loading-dot" />
          <div className="loading-dot" />
          <div className="loading-dot" />
        </div>
      ) : (
        <div className="table-wrapper">
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>用户名</th>
                <th>显示名称</th>
                <th>角色</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id}>
                  <td>{u.id}</td>
                  <td style={{ fontWeight: 600 }}>{u.username}</td>
                  <td>{u.display_name}</td>
                  <td>
                    {u.is_admin
                      ? <span className="admin-badge">管理员</span>
                      : <span className="user-badge">普通用户</span>
                    }
                  </td>
                  <td>
                    {u.is_admin
                      ? <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>—</span>
                      : <button className="btn btn-sm btn-danger" onClick={() => handleDelete(u)}>删除</button>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <CreateUserModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); loadUsers() }}
        />
      )}
    </div>
  )
}

function CreateUserModal({ onClose, onCreated }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!username.trim() || !password.trim()) {
      setError('用户名和密码不能为空')
      return
    }
    if (password.length < 6) {
      setError('密码至少6位')
      return
    }
    setSaving(true)
    setError('')
    try {
      await api.createUser(username.trim(), password, displayName.trim() || undefined)
      onCreated()
    } catch (err) {
      setError(err.message || '创建失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content editor-modal" style={{ maxWidth: 420 }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>创建用户</h3>
          <button className="detail-close" onClick={onClose}>×</button>
        </div>
        <form onSubmit={handleSubmit} className="editor-form">
          <div className="form-group">
            <label>用户名</label>
            <input type="text" value={username} onChange={e => setUsername(e.target.value)} placeholder="请输入用户名" />
          </div>
          <div className="form-group">
            <label>密码</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="至少6位" />
          </div>
          <div className="form-group">
            <label>显示名称 <span className="optional">(选填)</span></label>
            <input type="text" value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder="用户昵称" />
          </div>
          {error && <div className="login-error">{error}</div>}
          <div className="editor-actions">
            <button type="button" className="btn" onClick={onClose}>取消</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? '创建中...' : '创建'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
