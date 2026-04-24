import { useRoute } from '../router';
import type { MeResponse } from '../api';

interface Props {
  user?: MeResponse | null;
  onLogout?: () => void;
  step?: string;
}

export default function Navbar({ user, onLogout, step = '4 / 5' }: Props) {
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
        <span className="landing__nav-step">v0.4.0 · Étape {step}</span>
        {user && (
          <>
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
