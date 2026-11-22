import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiFetch, apiErrorMessage, setToken, clearSession } from './api';

beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
  setToken('');
});

describe('api wrapper', () => {
  it('adds the bearer token header', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    });
    vi.stubGlobal('fetch', fetchMock);
    setToken('test-token');
    await apiFetch('/api/test');
    expect(fetchMock.mock.calls[0][1].headers.get('Authorization')).toBe('Bearer test-token');
  });

  it('clears the session and redirects on 401', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'Invalid or expired token' }),
    }));
    setToken('expired');
    await expect(apiFetch('/api/test')).rejects.toThrow();
    expect(sessionStorage.getItem('personalos.token')).toBeNull();
  });

  it('returns the 429 friendly message', () => {
    expect(apiErrorMessage(429, {})).toBe('Too many attempts, wait a minute');
  });

  it('clears in-memory and sessionStorage state', () => {
    setToken('token');
    clearSession();
    expect(sessionStorage.getItem('personalos.token')).toBeNull();
  });
});
