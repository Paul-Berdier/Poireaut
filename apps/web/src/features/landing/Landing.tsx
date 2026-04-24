import poireautPortrait from '../../assets/poireaut1.png';
import { useRoute } from '../../router';
import { env } from '../../api';

export default function Landing() {
  const [, navigate] = useRoute();

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
          <button
            className="btn btn--primary"
            onClick={() => navigate({ name: 'login' })}
          >
            Ouvrir une enquête
          </button>
          <a
            className="btn btn--ghost"
            href={`${env.API_URL}/docs`}
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
