let token = sessionStorage.getItem('personalos.token') || '';

export function getToken() {
  return token;
}

export function setToken(nextToken) {
  token = nextToken || '';
  if (token) sessionStorage.setItem('personalos.token', token);
  else sessionStorage.removeItem('personalos.token');
}

export function clearSession() {
  setToken('');
  sessionStorage.removeItem('personalos.user');
  if (window.location.pathname !== '/login') {
    window.history.replaceState({}, '', '/login');
    window.dispatchEvent(new PopStateEvent('popstate'));
  }
}

export function apiErrorMessage(status, data) {
  if (status === 429) return 'Too many attempts, wait a minute';
  if (data?.detail && typeof data.detail === 'string') return data.detail;
  if (data?.detail?.reason) return data.detail.reason;
  if (data?.detail?.code) return data.detail.code;
  if (data?.message) return data.message;
  return 'Request failed';
}

export async function apiFetch(path, options = {}) {
  const base = import.meta.env.VITE_API_URL || 'http://localhost:8000';
  const headers = new Headers(options.headers || {});
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${base}${path}`, { ...options, headers });
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (response.status === 401) {
    clearSession();
  }
  if (!response.ok) {
    const error = new Error(apiErrorMessage(response.status, data));
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}
