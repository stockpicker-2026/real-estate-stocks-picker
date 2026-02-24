import React, { useState } from 'react'
import { api, setToken } from '../api'

export default function LoginPage({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password.trim()) {
      setError('请输入用户名和密码')
      return
    }
    setLoading(true)
    try {
      const res = await api.login(username.trim(), password)
      setToken(res.access_token)
      onLogin(res.user)
    } catch (err) {
      setError(err.message || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <div className="logo-icon">AI</div>
          <span>房地产股票评级</span>
        </div>
        <p className="login-subtitle">智能AI评级 · 市场深度点评 · 机构研究报告</p>

        <form onSubmit={handleSubmit} className="login-form">
          <div className="form-group">
            <label>用户名</label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="请输入用户名"
              autoComplete="username"
            />
          </div>
          <div className="form-group">
            <label>密码</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="请输入密码"
              autoComplete="current-password"
            />
          </div>

          {error && <div className="login-error">{error}</div>}

          <button type="submit" className="btn btn-primary login-btn" disabled={loading}>
            {loading ? '登录中...' : '登录'}
          </button>
        </form>

        <p className="login-hint">如需账号请联系管理员</p>
      </div>

      <footer className="login-footer">
        AI评级仅供参考, 不构成投资建议。投资有风险, 入市需谨慎。
      </footer>
    </div>
  )
}
