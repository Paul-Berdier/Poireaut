import { useRoute } from '../router';
import type { MeResponse } from '../api';

interface Props {
  user?: MeResponse | null;
  onLogout?: () => void;
}

export default function Navbar({ user, onLogout }: Props) {
  const [, navigate] = useRoute();
  return (
    <nav className="landing__nav">
      <button
        className="landing__nav-brand"
        onClick={() => navigate(user ? { name: 'dashboard' } : { name: 'landing' })}
        aria-label="Retour"
      >
        <img src="/poireautico.png" alt="" />
        <span>Poireaut</span>
      </button>
      <div className="landing__nav-right">
        <span className="landing__nav-step">v0.5.0 · Étape 5 / 5</span>
        {user && (
          <>
            <button
              className="btn btn--ghost btn--sm"
              onClick={() => navigate({ name: 'admin' })}
            >
              Connecteurs
            </button>
            <span className="landing__nav-user">{user.email}</span>
            <button className="btn btn--ghost btn--sm" onClick={onLogout}>
              Déconnexion
            </button>
          </>
        )}
      </div>
    </nav>
  );
}
