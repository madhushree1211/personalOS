import { useEffect, useState } from 'react';
import {
  BrowserRouter,
  Navigate,
  NavLink,
  Route,
  Routes,
  useNavigate,
} from 'react-router-dom';
import { apiFetch, clearSession, setToken, getToken } from './api';

function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem('personalos.user') || 'null');
    } catch {
      return null;
    }
  });
  const authenticated = Boolean(getToken() && user);
  const value = { user, authenticated, setUser };
  return children(value);
}

function Protected({ authenticated, children }) {
  return authenticated ? children : <Navigate to="/login" replace />;
}

function Layout({ user, children }) {
  const navigate = useNavigate();
  const logout = async () => {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST' });
    } catch {
      // Clear the local session even if revocation is unavailable.
    } finally {
      clearSession();
      navigate('/login');
    }
  };
  return (
    <div className="app-shell">
      <header className="topbar">
        <strong>PersonalOS</strong>
        <nav>
          <NavLink to="/chat">Chat</NavLink>
          <NavLink to="/approvals">Approvals</NavLink>
          <NavLink to="/audit">Audit</NavLink>
          <NavLink to="/alerts">Alerts</NavLink>
          <NavLink to="/documents">Documents</NavLink>
        </nav>
        <div><span>{user?.name}</span><button onClick={logout}>Logout</button></div>
      </header>
      <main>{children}</main>
    </div>
  );
}

function Login({ setUser }) {
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      const data = await apiFetch('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify(form),
      });
      setToken(data.token);
      sessionStorage.setItem('personalos.user', JSON.stringify(data.user));
      setUser(data.user);
      navigate('/chat');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <h1>PersonalOS</h1>
        <label>Email<input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
        <label>Password<input type="password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button disabled={loading}>{loading ? 'Signing in...' : 'Sign in'}</button>
      </form>
    </div>
  );
}

function Chat() {
  const [query, setQuery] = useState('');
  const [reply, setReply] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const send = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError('');
    setReply(null);
    try {
      setReply(await apiFetch('/api/supervisor/route', {
        method: 'POST',
        body: JSON.stringify({ query }),
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };
  return (
    <section className="view">
      <h1>Supervisor chat</h1>
      <form onSubmit={send} className="chat-form">
        <textarea required value={query} onChange={(e) => setQuery(e.target.value)} rows={4} />
        <button disabled={loading}>{loading ? 'Routing...' : 'Send'}</button>
      </form>
      {loading && <p>Loading response...</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {reply && (
        <article className="panel">
          <div className="panel-header">
            <h2>{reply.agent || 'Supervisor'}</h2>
            {reply?.data?.demo === true && <span className="badge">demo data</span>}
          </div>
          <p>{reply.response}</p>
          <dl>
            <dt>Agent</dt><dd>{reply.agent}</dd>
            <dt>Workflow</dt><dd>{reply.workflow}</dd>
            <dt>routing_path</dt><dd>{reply.routing_path || 'not provided'}</dd>
            {reply.fallback_reason && <><dt>fallback_reason</dt><dd>{reply.fallback_reason}</dd></>}
            <dt>Policy verdict</dt><dd>{reply.policy?.allowed ? 'allowed' : 'denied'}</dd>
          </dl>
          <h3>tool_calls</h3>
          <pre>{JSON.stringify(reply.tool_calls || [], null, 2)}</pre>
        </article>
      )}
    </section>
  );
}

function Approvals() {
  const [proposalId, setProposalId] = useState('');
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const submit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError('');
    setResult(null);
    try {
      setResult(await apiFetch('/api/investment/confirm', {
        method: 'POST',
        body: JSON.stringify({ approved: true, proposalId, mfa_code: code }),
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };
  return (
    <section className="view">
      <h1>Approvals</h1>
      <p>Pending proposal listing endpoint not available.</p>
      <form onSubmit={submit} className="form-grid">
        <label>Proposal ID<input required value={proposalId} onChange={(e) => setProposalId(e.target.value)} /></label>
        <label>MFA code<input required minLength={6} maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} /></label>
        <button disabled={loading}>{loading ? 'Submitting...' : 'Confirm with MFA'}</button>
      </form>
      {loading && <p>Loading...</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {result && <pre>{JSON.stringify(result, null, 2)}</pre>}
    </section>
  );
}

function Audit() {
  const [entries, setEntries] = useState([]);
  const [limit, setLimit] = useState(10);
  const [offset, setOffset] = useState(0);
  const [eventFilter, setEventFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      if (eventFilter) params.set('event', eventFilter);
      const data = await apiFetch(`/api/audit-log?${params}`);
      setEntries(data.entries || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [limit, offset]);
  return (
    <section className="view">
      <h1>Audit log</h1>
      <div className="filters">
        <label>Event<input value={eventFilter} onChange={(e) => setEventFilter(e.target.value)} /></label>
        <label>Limit<input type="number" min="1" max="100" value={limit} onChange={(e) => setLimit(Math.min(100, Math.max(1, Number(e.target.value))))} /></label>
        <button onClick={load}>Apply</button>
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button>
        <button onClick={() => setOffset(offset + limit)}>Next</button>
      </div>
      {loading && <p>Loading audit entries...</p>}
      {error && <p className="error" role="alert">{error}</p>}
      <table>
        <thead><tr><th>ID</th><th>Time</th><th>Event</th><th>Details</th></tr></thead>
        <tbody>{entries.map((entry) => (
          <tr key={entry.id}>
            <td>{entry.id}</td><td>{entry.timestamp}</td><td>{entry.event}</td>
            <td><pre>{JSON.stringify(entry.details, null, 2)}</pre></td>
          </tr>
        ))}</tbody>
      </table>
    </section>
  );
}

function Alerts() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    apiFetch('/api/security/alerts')
      .then((data) => setAlerts(data.alerts || []))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);
  return (
    <section className="view">
      <h1>Security alerts</h1>
      {loading && <p>Loading alerts...</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {!loading && !error && alerts.length === 0 && <p>No detection alerts.</p>}
      <ul className="alert-list">{alerts.map((alert, index) => (
        <li key={`${alert.rule_id}-${alert.first_seen}-${index}`}>
          <strong>{alert.rule_id}</strong>
          <span>{alert.severity}</span>
          <span>Count: {alert.count}</span>
          <pre>{JSON.stringify(alert, null, 2)}</pre>
        </li>
      ))}</ul>
    </section>
  );
}

function Documents() {
  const [text, setText] = useState('');
  const [filename, setFilename] = useState('');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const upload = async (event) => {
    event.preventDefault();
    if (new TextEncoder().encode(text).length > 200 * 1024) {
      setError('Document exceeds 200 KB');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await apiFetch('/api/documents', {
        method: 'POST',
        body: JSON.stringify({ filename: filename || 'upload.txt', text }),
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };
  const search = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ q: query, limit: '20' });
      const data = await apiFetch(`/api/documents/search?${params}`);
      setResults(data.results || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };
  return (
    <section className="view">
      <h1>Documents</h1>
      <form onSubmit={upload} className="form-grid">
        <label>Filename<input value={filename} onChange={(e) => setFilename(e.target.value)} /></label>
        <label>Text<textarea required rows={8} value={text} onChange={(e) => setText(e.target.value)} /></label>
        <button disabled={loading}>{loading ? 'Uploading...' : 'Upload text'}</button>
      </form>
      <form onSubmit={search} className="form-grid">
        <label>Search<input required value={query} onChange={(e) => setQuery(e.target.value)} /></label>
        <button disabled={loading}>Search</button>
      </form>
      {loading && <p>Loading...</p>}
      {error && <p className="error" role="alert">{error}</p>}
      <ul className="results">{results.map((item) => (
        <li key={item.chunk_id}>
          <strong>{item.filename}</strong>
          <span>Score: {item.score}</span>
          <p>{item.text}</p>
        </li>
      ))}</ul>
    </section>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        {({ user, authenticated, setUser }) => (
          <Routes>
            <Route path="/login" element={authenticated ? <Navigate to="/chat" replace /> : <Login setUser={setUser} />} />
            <Route path="/" element={<Navigate to={authenticated ? '/chat' : '/login'} replace />} />
            <Route path="/chat" element={<Protected authenticated={authenticated}><Layout user={user}><Chat /></Layout></Protected>} />
            <Route path="/approvals" element={<Protected authenticated={authenticated}><Layout user={user}><Approvals /></Layout></Protected>} />
            <Route path="/audit" element={<Protected authenticated={authenticated}><Layout user={user}><Audit /></Layout></Protected>} />
            <Route path="/alerts" element={<Protected authenticated={authenticated}><Layout user={user}><Alerts /></Layout></Protected>} />
            <Route path="/documents" element={<Protected authenticated={authenticated}><Layout user={user}><Documents /></Layout></Protected>} />
            <Route path="*" element={<Navigate to={authenticated ? '/chat' : '/login'} replace />} />
          </Routes>
        )}
      </AuthProvider>
    </BrowserRouter>
  );
}
