import { useEffect, useState } from 'react';
import {
  login,
  logout,
  me,
  register,
  listInvestigations,
  createInvestigation,
  getToken,
  type Investigation,
  type MeResponse,
} from './api';
import poireautPortrait from './assets/poireaut1.png';

type HealthState = 'checking' | 'ok' | 'down';

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

function useApiHealth(): HealthState {
  const [state, setState] = useState<HealthState>('checking');
  useEffect(() => {
    const ctrl = new AbortController();
    const tick = async () => {
      try {
        const res = await fetch(`${API_URL}/health`, { signal: ctrl.signal });
        setState(res.ok ? 'ok' : 'down');
      } catch (err) {
        if ((err as Error).name !== 'AbortError') setState('down');
      }
    };
    tick();
    const id = window.setInterval(tick, 15_000);
    return () => {
      ctrl.abort();
      window.clearInterval(id);
    };
  }, []);
  return state;
}

function SystemCheck({ state }: { state: HealthState }) {
  const label = {
    checking: 'Connexion…',
    ok: 'API en ligne',
    down: 'API injoignable',
  }[state];
  const dotClass =
    state === 'ok'
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

// ─── Landing (logged out) ────────────────────────────────────

function Landing({ onOpenLogin }: { onOpenLogin: () => void }) {
  return (
    <main className="landing__hero">
      <div>
        <h1 className="wordmark">
          Poireaut<span className="wordmark__dot">.</span>
        </h1>
        <div className="tagline">
          <span className="tagline__rule" aria-hidden />
          <span>Outil OSINT</span>
          <span className="tagline__rule" aria-hidden />
        </div>
        <p className="lede">
          Investigation en sources ouvertes, par pivots successifs. Entrez une
          miette — un pseudo, un email, un numéro — et laissez Mr. Poireaut
          tisser la toile. Vous validez chaque indice, il en cherche le
          suivant.
        </p>
        <div className="cta-row">
          <button className="btn btn--primary" onClick={onOpenLogin}>
            Ouvrir une enquête
          </button>
          <a
            className="btn btn--ghost"
            href={`${API_URL}/docs`}
            target="_blank"
            rel="noreferrer"
          >
            Documentation API →
          </a>
        </div>
      </div>
      <div className="portrait">
        <img src={poireautPortrait} alt="Mr. Poireaut, enquêteur OSINT" />
      </div>
    </main>
  );
}

// ─── Auth form (login or register) ──────────────────────────

type AuthMode = 'login' | 'register';

function AuthView({
  onSuccess,
  onCancel,
}: {
  onSuccess: () => void;
  onCancel: () => void;
}) {
  const [mode, setMode] = useState<AuthMode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const switchMode = (next: AuthMode) => {
    setMode(next);
    setErr(null);
    setConfirm('');
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);

    if (mode === 'register') {
      if (password.length < 8) {
        setErr('Le mot de passe doit faire au moins 8 caractères.');
        return;
      }
      if (password !== confirm) {
        setErr('Les mots de passe ne correspondent pas.');
        return;
      }
    }

    setBusy(true);
    try {
      if (mode === 'register') {
        await register(email, password);
        // Auto-login right after registration for a seamless flow.
        await login(email, password);
      } else {
        await login(email, password);
      }
      onSuccess();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const isRegister = mode === 'register';

  return (
    <main className="panel">
      <div className="panel__card">
        <div className="panel__eyebrow">
          {isRegister ? 'Nouveau dossier d’enquêteur' : 'Identification'}
        </div>
        <h2 className="panel__title">
          {isRegister ? 'Créer un compte' : 'Accès à l\'enquête'}
        </h2>

        <div className="auth-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={!isRegister}
            className={`auth-tabs__tab ${!isRegister ? 'auth-tabs__tab--active' : ''}`}
            onClick={() => switchMode('login')}
          >
            Connexion
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={isRegister}
            className={`auth-tabs__tab ${isRegister ? 'auth-tabs__tab--active' : ''}`}
            onClick={() => switchMode('register')}
          >
            Nouveau compte
          </button>
        </div>

        <form onSubmit={submit} className="form">
          <label className="form__row">
            <span className="form__label">Adresse email</span>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="form__input"
            />
          </label>
          <label className="form__row">
            <span className="form__label">Mot de passe</span>
            <input
              type="password"
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              required
              minLength={isRegister ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="form__input"
            />
          </label>
          {isRegister && (
            <label className="form__row">
              <span className="form__label">Confirmation</span>
              <input
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                className="form__input"
              />
            </label>
          )}

          {err && <div className="form__error">{err}</div>}

          <div className="form__actions">
            <button type="button" className="btn btn--ghost" onClick={onCancel}>
              Annuler
            </button>
            <button type="submit" className="btn btn--primary" disabled={busy}>
              {busy
                ? '…'
                : isRegister
                  ? 'Créer le compte'
                  : 'Se connecter'}
            </button>
          </div>
        </form>
      </div>
    </main>
  );
}

// ─── Dashboard (logged in) ───────────────────────────────────

function Dashboard({ user, onLogout }: { user: MeResponse; onLogout: () => void }) {
  const [investigations, setInvestigations] = useState<Investigation[] | null>(
    null,
  );
  const [err, setErr] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      setInvestigations(await listInvestigations());
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    setBusy(true);
    try {
      await createInvestigation(newTitle.trim());
      setNewTitle('');
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="panel">
      <div className="panel__card panel__card--wide">
        <div className="panel__header">
          <div>
            <div className="panel__eyebrow">Dossiers ouverts</div>
            <h2 className="panel__title">Mes enquêtes</h2>
          </div>
          <div className="panel__user">
            <span className="panel__user-email">{user.email}</span>
            <button className="btn btn--ghost btn--sm" onClick={onLogout}>
              Déconnexion
            </button>
          </div>
        </div>

        <form onSubmit={create} className="form form--inline">
          <input
            className="form__input"
            placeholder="Titre de l'enquête (ex. Affaire du boulanger fantôme)"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            required
          />
          <button type="submit" className="btn btn--primary" disabled={busy}>
            {busy ? '…' : 'Ouvrir'}
          </button>
        </form>

        {err && <div className="form__error">{err}</div>}

        {investigations === null ? (
          <div className="panel__empty">Chargement…</div>
        ) : investigations.length === 0 ? (
          <div className="panel__empty">
            Aucune enquête pour l'instant. Mr. Poireaut s'ennuie.
          </div>
        ) : (
          <ul className="case-list">
            {investigations.map((i) => (
              <li key={i.id} className="case-list__item">
                <div>
                  <div className="case-list__title">{i.title}</div>
                  <div className="case-list__meta">
                    {i.status} · ouvert le{' '}
                    {new Date(i.created_at).toLocaleDateString('fr-FR')}
                  </div>
                </div>
                <span className="case-list__arrow">→</span>
              </li>
            ))}
          </ul>
        )}

        <div className="panel__footnote">
          La toile d'araignée interactive arrive à l'étape 4.
        </div>
      </div>
    </main>
  );
}

// ─── Root component ──────────────────────────────────────────

type View = 'landing' | 'login' | 'dashboard';

export default function App() {
  const health = useApiHealth();
  const [view, setView] = useState<View>('landing');
  const [user, setUser] = useState<MeResponse | null>(null);

  // On mount, if we have a token, try to resolve the user.
  useEffect(() => {
    if (!getToken()) return;
    me()
      .then((u) => {
        setUser(u);
        setView('dashboard');
      })
      .catch(() => {
        logout();
      });
  }, []);

  const handleLoginSuccess = async () => {
    try {
      const u = await me();
      setUser(u);
      setView('dashboard');
    } catch {
      logout();
      setView('login');
    }
  };

  const handleLogout = () => {
    logout();
    setUser(null);
    setView('landing');
  };

  return (
    <div className="landing">
      <nav className="landing__nav">
        <div className="landing__nav-brand">
          <img src="/poireautico.png" alt="" />
          <span>Poireaut</span>
        </div>
        <span>v0.3.0 · Étape 3 / 5</span>
      </nav>

      {view === 'landing' && <Landing onOpenLogin={() => setView('login')} />}
      {view === 'login' && (
        <AuthView
          onSuccess={handleLoginSuccess}
          onCancel={() => setView('landing')}
        />
      )}
      {view === 'dashboard' && user && (
        <Dashboard user={user} onLogout={handleLogout} />
      )}

      <footer className="landing__footer">
        Connecteur actif : Holehe (email → comptes) · toile interactive à l'étape 4
      </footer>

      <SystemCheck state={health} />
    </div>
  );
}
