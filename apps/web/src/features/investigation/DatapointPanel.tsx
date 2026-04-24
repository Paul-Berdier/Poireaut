import { useState } from 'react';
import {
  deleteDatapoint, pivot, updateDatapoint,
  type DataPoint,
} from '../../api';

interface Props {
  datapoint: DataPoint;
  onChange: () => void;
  onClose: () => void;
}

export default function DatapointPanel({ datapoint, onChange, onClose }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setErr(null);
    setBusy(label);
    try { await fn(); await onChange(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(null); }
  };

  const validate   = () => run('validate', () => updateDatapoint(datapoint.id, { status: 'validated' }));
  const reject     = () => run('reject',   () => updateDatapoint(datapoint.id, { status: 'rejected' }));
  const unmark     = () => run('unmark',   () => updateDatapoint(datapoint.id, { status: 'unverified' }));
  const doPivot    = () => run('pivot',    () => pivot(datapoint.id));
  const doDelete   = () => {
    if (!confirm('Supprimer ce datapoint ? Ses enfants pivotés restent mais orphelins.')) return;
    return run('delete', async () => { await deleteDatapoint(datapoint.id); onClose(); });
  };

  const confidencePct = datapoint.confidence != null
    ? `${Math.round(datapoint.confidence * 100)}%`
    : '—';

  return (
    <aside className="dp-panel">
      <div className="dp-panel__head">
        <div className="dp-panel__eyebrow">{datapoint.type}</div>
        <button className="dp-panel__close" onClick={onClose} aria-label="Fermer">×</button>
      </div>

      <h3 className="dp-panel__value" title={datapoint.value}>{datapoint.value}</h3>

      <dl className="dp-panel__meta">
        <dt>Statut</dt>
        <dd><span className={`dp-status dp-status--${datapoint.status}`}>{datapoint.status}</span></dd>

        <dt>Confiance</dt>
        <dd>{confidencePct}</dd>

        {datapoint.source_url && (<>
          <dt>Source</dt>
          <dd>
            <a href={datapoint.source_url} target="_blank" rel="noreferrer" className="dp-panel__link">
              {new URL(datapoint.source_url).host}
            </a>
          </dd>
        </>)}

        {datapoint.extracted_at && (<>
          <dt>Extrait le</dt>
          <dd>{new Date(datapoint.extracted_at).toLocaleString('fr-FR')}</dd>
        </>)}
      </dl>

      {datapoint.notes && (
        <div className="dp-panel__notes">{datapoint.notes}</div>
      )}

      {err && <div className="form__error" style={{ marginTop: 'var(--s-3)' }}>{err}</div>}

      <div className="dp-panel__actions">
        {datapoint.status !== 'validated' && (
          <button className="btn btn--primary btn--sm" onClick={validate} disabled={busy !== null}>
            {busy === 'validate' ? '…' : 'Valider'}
          </button>
        )}
        {datapoint.status !== 'rejected' && (
          <button className="btn btn--ghost btn--sm" onClick={reject} disabled={busy !== null}>
            {busy === 'reject' ? '…' : 'Rejeter'}
          </button>
        )}
        {datapoint.status !== 'unverified' && (
          <button className="btn btn--ghost btn--sm" onClick={unmark} disabled={busy !== null}>
            {busy === 'unmark' ? '…' : 'Remettre en doute'}
          </button>
        )}
      </div>

      <div className="dp-panel__actions dp-panel__actions--primary">
        <button
          className="btn btn--primary"
          onClick={doPivot}
          disabled={busy !== null || datapoint.status === 'rejected'}
          title={
            datapoint.status === 'rejected'
              ? 'On ne pivote pas sur un datapoint rejeté'
              : 'Lancer tous les connecteurs compatibles'
          }
        >
          {busy === 'pivot' ? 'Pivot en cours…' : '🔎 Pivoter'}
        </button>
        <button
          className="btn btn--ghost btn--sm"
          onClick={doDelete}
          disabled={busy !== null}
        >
          Supprimer
        </button>
      </div>
    </aside>
  );
}
