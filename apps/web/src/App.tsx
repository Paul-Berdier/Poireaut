import { useEffect, useState } from 'react';
import { getToken, logout, me, type MeResponse, env } from './api';
import { useRoute } from './router';
import Navbar from './features/Navbar';
import Landing from './features/landing/Landing';
import AuthView from './features/auth/AuthView';
import Dashboard from './features/dashboard/Dashboard';
import InvestigationView from './features/investigation/InvestigationView';
import AdminView from './features/admin/AdminView';

type HealthState = 'checking' | 'ok' | 'down';

function useApiHealth(): HealthState {
  const [state, setState] = useState<HealthState>('checking');
  useEffect(() => {
    const ctrl = new AbortController();
    const tick = async () => {
      try {
        const res = await fetch(`${env.API_URL}/health`, { signal: ctrl.signal });
        setState(res.ok ? 'ok' : 'down');
      } catch (err) {
        if ((err as Error).name !== 'AbortError') setState('down');
      }
    };
    tick();
    const id = window.setInterval(tick, 30_000);
    return () => { ctrl.abort(); window.clearInterval(id); };
  }, []);
  return state;
}

function SystemCheck({ state }: { state: HealthState }) {
  const label = { checking: 'Connexion…', ok: 'API en ligne', down: 'API injoignable' }[state];
  const dotClass = state === 'ok'
    ? 'sys-check__dot sys-check__dot--ok'
    : state === 'down'
      ? 'sys-check__dot sys-check__dot--ko'
      : 'sys-check__dot';
  return (
    <aside className="sys-check" aria-live="polite">
      <span className={dotClass} />
      <div>
        <div className="sys-check__label">Diagnostic</div>
        <div className="sys-check__status">{label}</div>
      </div>
    </aside>
  );
}

export default function App() {
  const health = useApiHealth();
  const [route, navigate] = useRoute();
  const [user, setUser] = useState<MeResponse | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);

  // Resolve user on first mount if a token exists
  useEffect(() => {
    if (!getToken()) { setBootstrapping(false); return; }
    me()
      .then((u) => setUser(u))
      .catch(() => logout())
      .finally(() => setBootstrapping(false));
  }, []);

  const handleLoginSuccess = async () => {
    try {
      const u = await me();
      setUser(u);
      navigate({ name: 'dashboard' });
    } catch {
      logout();
      navigate({ name: 'login' });
    }
  };

  const handleLogout = () => {
    logout();
    setUser(null);
    navigate({ name: 'landing' });
  };

  // Route guards
  const needsAuth = route.name === 'dashboard' || route.name === 'investigation' || route.name === 'admin';
  if (bootstrapping) {
    return <div className="landing"><div className="panel__empty">Chargement…</div></div>;
  }
  if (needsAuth && !user) {
    navigate({ name: 'login' });
    return null;
  }

  const isFullscreen = route.name === 'investigation';
  const containerClass = isFullscreen ? 'landing landing--fullscreen' : 'landing';

  return (
    <div className={containerClass}>
      <Navbar user={user} onLogout={handleLogout} />

      {route.name === 'landing' && <Landing />}
      {route.name === 'login' && (
        <AuthView
          onSuccess={handleLoginSuccess}
          onCancel={() => navigate({ name: 'landing' })}
        />
      )}
      {route.name === 'dashboard' && user && <Dashboard />}
      {route.name === 'investigation' && user && (
        <InvestigationView investigationId={route.id} />
      )}
      {route.name === 'admin' && user && <AdminView />}

      <SystemCheck state={health} />
    </div>
  );
}
