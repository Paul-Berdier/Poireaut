import { useEffect, useState } from 'react';
import {
  listConnectors, listConnectorRuns, triggerHealthcheck,
  type ConnectorInfo, type ConnectorRun,
} from '../../api';
import { useRoute } from '../../router';

export default function AdminView() {
  const [, navigate] = useRoute();
  const [connectors, setConnectors] = useState<ConnectorInfo[] | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [runs, setRuns] = useState<Record<string, ConnectorRun[]>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const refresh = async () => {
    try { setConnectors(await listConnectors()); }
    catch (e) { setErr((e as Error).message); }
  };
  useEffect(() => { refresh(); }, []);

  const toggle = async (id: string) => {
    if (expandedId === id) { setExpandedId(null); return; }
    setExpandedId(id);
    if (!runs[id]) {
      try {
        const r = await listConnectorRuns(id, 10);
        setRuns((prev) => ({ ...prev, [id]: r }));
      } catch (e) {
        setErr((e as Error).message);
      }
    }
  };

  const doHealthcheck = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await triggerHealthcheck();
      setToast(r.message);
      window.setTimeout(() => setToast(null), 5000);
      // Poll once after 20s to refresh healths
      window.setTimeout(refresh, 20_000);
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
            <button
              className="investigation__back"
              onClick={() => navigate({ name: 'dashboard' })}
            >
              ← Retour
            </button>
            <div className="panel__eyebrow">Boîte à outils</div>
            <h2 className="panel__title">Connecteurs OSINT</h2>
          </div>
          <button
            className="btn btn--primary btn--sm"
            onClick={doHealthcheck}
            disabled={busy}
          >
            {busy ? '…' : 'Relancer le healthcheck'}
          </button>
        </div>

        {err && <div className="form__error">{err}</div>}

        {connectors === null ? (
          <div className="panel__empty">Chargement…</div>
        ) : connectors.length === 0 ? (
          <div className="panel__empty">
            Aucun connecteur enregistré — lancez un pivot depuis une enquête
            pour peupler la base. Les connecteurs s'auto-enregistrent au 1ᵉʳ usage.
          </div>
        ) : (
          <ul className="connector-list">
            {connectors.map((c) => (
              <li key={c.id} className="connector-list__item">
                <button
                  className="connector-list__header"
                  onClick={() => toggle(c.id)}
                >
                  <div className="connector-list__main">
                    <div className="connector-list__name">{c.display_name}</div>
                    <div className="connector-list__meta">
                      <span className="connector-list__category">{c.category}</span>
                      <span>·</span>
                      <span>
                        {c.input_types.join(', ')} → {c.output_types.join(', ')}
                      </span>
                      {c.cost !== 'free' && (<>
                        <span>·</span>
                        <span className="connector-list__cost">
                          {c.cost === 'paid' ? 'payant' : 'clé API'}
                        </span>
                      </>)}
                    </div>
                    {c.description && (
                      <div className="connector-list__desc">{c.description}</div>
                    )}
                  </div>
                  <div className="connector-list__right">
                    <span className={`health-pill health-pill--${c.health}`}>
                      {c.health}
                    </span>
                    {c.last_health_check && (
                      <div className="connector-list__lastcheck">
                        {new Date(c.last_health_check).toLocaleString('fr-FR', {
                          dateStyle: 'short', timeStyle: 'short',
                        })}
                      </div>
                    )}
                    <span className="case-list__arrow">
                      {expandedId === c.id ? '▾' : '▸'}
                    </span>
                  </div>
                </button>

                {expandedId === c.id && (
                  <div className="connector-list__runs">
                    <div className="connector-list__runs-header">
                      10 derniers runs
                      {c.homepage_url && (
                        <a
                          href={c.homepage_url}
                          target="_blank"
                          rel="noreferrer"
                          className="connector-list__homepage"
                        >
                          Source ↗
                        </a>
                      )}
                    </div>
                    {!runs[c.id] ? (
                      <div className="panel__empty" style={{ margin: 0 }}>
                        Chargement…
                      </div>
                    ) : runs[c.id].length === 0 ? (
                      <div className="panel__empty" style={{ margin: 0 }}>
                        Jamais exécuté.
                      </div>
                    ) : (
                      <table className="runs-table">
                        <thead>
                          <tr>
                            <th>Date</th>
                            <th>Statut</th>
                            <th>Durée</th>
                            <th>Résultats</th>
                            <th>Erreur</th>
                          </tr>
                        </thead>
                        <tbody>
                          {runs[c.id].map((r) => (
                            <tr key={r.id}>
                              <td>
                                {new Date(r.created_at).toLocaleString('fr-FR', {
                                  dateStyle: 'short', timeStyle: 'short',
                                })}
                              </td>
                              <td>
                                <span className={`run-status run-status--${r.status}`}>
                                  {r.status}
                                </span>
                              </td>
                              <td>
                                {r.duration_ms != null
                                  ? `${(r.duration_ms / 1000).toFixed(1)}s`
                                  : '—'}
                              </td>
                              <td>{r.result_count}</td>
                              <td className="runs-table__error" title={r.error_message ?? ''}>
                                {r.error_message ?? '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      {toast && <div className="toast">{toast}</div>}
    </main>
  );
}
