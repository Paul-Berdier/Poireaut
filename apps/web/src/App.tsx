import { useEffect, useState } from 'react';
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
        if (!res.ok) throw new Error(String(res.status));
        const body = (await res.json()) as { status?: string };
        setState(body.status === 'ok' ? 'ok' : 'down');
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

export default function App() {
  const health = useApiHealth();

  return (
    <div className="landing">
      <nav className="landing__nav">
        <div className="landing__nav-brand">
          <img src="/poireautico.png" alt="" />
          <span>Poireaut</span>
        </div>
        <span>v0.1.0 · Étape 1 / 5</span>
      </nav>

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
            <button className="btn btn--primary" disabled>
              Ouvrir une enquête
            </button>
            <a
              className="btn btn--ghost"
              href="http://localhost:8000/docs"
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

      <footer className="landing__footer">
        Scaffold déployé · Étape suivante : modèles de données &amp;
        authentification
      </footer>

      <SystemCheck state={health} />
    </div>
  );
}
