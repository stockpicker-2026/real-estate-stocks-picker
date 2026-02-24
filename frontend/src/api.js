const BASE = '/api'

function getToken() {
  return localStorage.getItem('token')
}

export function setToken(token) {
  localStorage.setItem('token', token)
}

export function removeToken() {
  localStorage.removeItem('token')
}

async function request(url, options = {}) {
  const token = getToken()
  const headers = { ...(options.headers || {}) }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  if (!(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }
  const res = await fetch(`${BASE}${url}`, { ...options, headers })
  if (res.status === 401) {
    removeToken()
    window.dispatchEvent(new Event('auth-expired'))
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  if (res.headers.get('content-type')?.includes('application/json')) {
    return res.json()
  }
  return res
}

export const api = {
  // ========== 认证 ==========
  login: (username, password) =>
    request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  getMe: () => request('/auth/me'),

  // ========== 用户管理（管理员） ==========
  getUsers: () => request('/users'),
  createUser: (username, password, display_name) =>
    request('/users', {
      method: 'POST',
      body: JSON.stringify({ username, password, display_name }),
    }),
  deleteUser: (id) => request(`/users/${id}`, { method: 'DELETE' }),

  // ========== 评级（原有） ==========
  getDashboard: () => request('/dashboard'),
  getStocks: (market) => request(`/stocks${market ? `?market=${market}` : ''}`),
  getLatestRatings: (params = {}) => {
    const qs = new URLSearchParams()
    if (params.market) qs.set('market', params.market)
    if (params.rating) qs.set('rating', params.rating)
    if (params.sort_by) qs.set('sort_by', params.sort_by)
    if (params.sort_dir) qs.set('sort_dir', params.sort_dir)
    const q = qs.toString()
    return request(`/ratings/latest${q ? `?${q}` : ''}`)
  },
  getRatingHistory: (code, days = 30) => request(`/ratings/history/${code}?days=${days}`),
  getRatingsByDate: (date, market) =>
    request(`/ratings/date/${date}${market ? `?market=${market}` : ''}`),
  getAvailableDates: () => request('/ratings/dates'),
  getPrices: (code, days = 60) => request(`/prices/${code}?days=${days}`),
  getRatingTrend: (code, days = 30) => request(`/rating-trend/${code}?days=${days}`),

  // ========== 市场点评 ==========
  getCommentaries: (category, limit = 20) => {
    const qs = new URLSearchParams()
    if (category) qs.set('category', category)
    qs.set('limit', limit)
    return request(`/commentaries?${qs}`)
  },
  getCommentary: (id) => request(`/commentaries/${id}`),
  createCommentary: (data) =>
    request('/commentaries', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateCommentary: (id, data) =>
    request(`/commentaries/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteCommentary: (id) =>
    request(`/commentaries/${id}`, { method: 'DELETE' }),

  // ========== 研究报告 ==========
  getReports: (limit = 20) => request(`/reports?limit=${limit}`),
  uploadReport: (formData) =>
    request('/reports', {
      method: 'POST',
      body: formData,
      headers: {},
    }),
  deleteReport: (id) => request(`/reports/${id}`, { method: 'DELETE' }),
  getReportDownloadUrl: (id) => `${BASE}/reports/${id}/download`,
}
