import { useRoute } from '../router';
import type { MeResponse } from '../api';

interface Props {
  user?: MeResponse | null;
  onLogout?: () => void;
}

export default function Navbar({ user, onLogout }: Props) {
  const [route, navigate] = useRoute();
  const onAccountPage = route.name === 'account';

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
        {user && (
          <>
            <button
              className="btn btn--ghost btn--sm"
              onClick={() => navigate({ name: 'admin' })}
              title="Connecteurs"
            >
              Connecteurs
            </button>
            <button
              className={`btn btn--ghost btn--sm ${onAccountPage ? 'btn--active' : ''}`}
              onClick={() => navigate({ name: 'account' })}
              title="Mon compte et clés API"
              aria-label="Mon compte"
            >
              ⚙️
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
