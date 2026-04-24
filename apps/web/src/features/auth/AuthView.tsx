import { useState } from 'react';
import { login, register } from '../../api';

type AuthMode = 'login' | 'register';

interface Props {
  onSuccess: () => void;
  onCancel: () => void;
}

export default function AuthView({ onSuccess, onCancel }: Props) {
  const [mode, setMode] = useState<AuthMode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const switchMode = (next: AuthMode) => { setMode(next); setErr(null); setConfirm(''); };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    if (mode === 'register') {
      if (password.length < 8) { setErr('Le mot de passe doit faire au moins 8 caractères.'); return; }
      if (password !== confirm) { setErr('Les mots de passe ne correspondent pas.'); return; }
    }
    setBusy(true);
    try {
      if (mode === 'register') {
        await register(email, password);
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
          {isRegister ? "Nouveau dossier d'enquêteur" : 'Identification'}
        </div>
        <h2 className="panel__title">
          {isRegister ? 'Créer un compte' : "Accès à l'enquête"}
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
            <input type="email" autoComplete="email" required
              value={email} onChange={(e) => setEmail(e.target.value)}
              className="form__input" />
          </label>
          <label className="form__row">
            <span className="form__label">Mot de passe</span>
            <input type="password"
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              required minLength={isRegister ? 8 : undefined}
              value={password} onChange={(e) => setPassword(e.target.value)}
              className="form__input" />
          </label>
          {isRegister && (
            <label className="form__row">
              <span className="form__label">Confirmation</span>
              <input type="password" autoComplete="new-password" required minLength={8}
                value={confirm} onChange={(e) => setConfirm(e.target.value)}
                className="form__input" />
            </label>
          )}
          {err && <div className="form__error">{err}</div>}
          <div className="form__actions">
            <button type="button" className="btn btn--ghost" onClick={onCancel}>
              Annuler
            </button>
            <button type="submit" className="btn btn--primary" disabled={busy}>
              {busy ? '…' : isRegister ? 'Créer le compte' : 'Se connecter'}
            </button>
          </div>
        </form>
      </div>
    </main>
  );
}
