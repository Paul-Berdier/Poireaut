import { useEffect, useState } from 'react';
import {
  createInvestigation,
  deleteInvestigation,
  listInvestigations,
  type Investigation,
} from '../../api';
import { useRoute } from '../../router';

export default function Dashboard() {
  const [, navigate] = useRoute();
  const [investigations, setInvestigations] = useState<Investigation[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try { setInvestigations(await listInvestigations()); }
    catch (e) { setErr((e as Error).message); }
  };
  useEffect(() => { refresh(); }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    setBusy(true);
    try {
      const inv = await createInvestigation(newTitle.trim());
      setNewTitle('');
      // Jump straight into the new enquête — it's empty and ready.
      navigate({ name: 'investigation', id: inv.id });
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };

  const onDelete = async (id: string, title: string) => {
    if (!confirm(`Supprimer définitivement l'enquête "${title}" ?`)) return;
    try {
      await deleteInvestigation(id);
      await refresh();
    } catch (e) { setErr((e as Error).message); }
  };

  return (
    <main className="panel">
      <div className="panel__card panel__card--wide">
        <div className="panel__header">
          <div>
            <div className="panel__eyebrow">Dossiers ouverts</div>
            <h2 className="panel__title">Mes enquêtes</h2>
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
                <button
                  className="case-list__main"
                  onClick={() => navigate({ name: 'investigation', id: i.id })}
                >
                  <div className="case-list__title">{i.title}</div>
                  <div className="case-list__meta">
                    {i.status} · ouvert le{' '}
                    {new Date(i.created_at).toLocaleDateString('fr-FR')}
                  </div>
                </button>
                <div className="case-list__actions">
                  <button
                    className="btn btn--ghost btn--sm"
                    onClick={() => onDelete(i.id, i.title)}
                    title="Supprimer"
                  >
                    Supprimer
                  </button>
                  <span className="case-list__arrow">→</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
