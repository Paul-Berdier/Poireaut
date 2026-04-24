import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import {
  deleteDatapoint, pivot, updateDatapoint,
  type DataPoint,
} from '../../api';

interface Props {
  datapoint: DataPoint;
  isPivoting: boolean;
  onChange: () => void;
  onClose: () => void;
}

export default function DatapointPanel({ datapoint, isPivoting, onChange, onClose }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setErr(null);
    setBusy(label);
    try { await fn(); await onChange(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(null); }
  };

  const validate = () => run('validate', () => updateDatapoint(datapoint.id, { status: 'validated' }));
  const reject   = () => run('reject',   () => updateDatapoint(datapoint.id, { status: 'rejected' }));
  const unmark   = () => run('unmark',   () => updateDatapoint(datapoint.id, { status: 'unverified' }));
  const doPivot  = () => run('pivot',    () => pivot(datapoint.id));
  const doDelete = () => {
    if (!confirm('Supprimer ce datapoint ? Ses enfants pivotés restent mais orphelins.')) return;
    return run('delete', async () => { await deleteDatapoint(datapoint.id); onClose(); });
  };

  const confidencePct = datapoint.confidence != null
    ? `${Math.round(datapoint.confidence * 100)}%`
    : '—';

  // If the server confirmed a pivot started (via WS), show a banner.
  const showPivotBanner = isPivoting || busy === 'pivot';

  const valueIsUrl = /^https?:\/\//i.test(datapoint.value);
  const isPhoto = datapoint.type === 'photo' && valueIsUrl;

  return (
    <aside className="dp-panel">
      <div className="dp-panel__head">
        <div className="dp-panel__eyebrow">{datapoint.type}</div>
        <button className="dp-panel__close" onClick={onClose} aria-label="Fermer">×</button>
      </div>

      {isPhoto && (
        <a
          href={datapoint.value}
          target="_blank"
          rel="noreferrer noopener"
          className="dp-panel__photo-wrap"
          title="Ouvrir l'image en grand"
        >
          <img
            src={datapoint.value}
            alt=""
            className="dp-panel__photo"
            referrerPolicy="no-referrer"
            loading="lazy"
          />
        </a>
      )}

      <h3 className="dp-panel__value" title={datapoint.value}>
        {valueIsUrl ? (
          <a href={datapoint.value} target="_blank" rel="noreferrer noopener" className="dp-panel__link">
            {datapoint.value}
          </a>
        ) : (
          datapoint.value
        )}
      </h3>

      {showPivotBanner && (
        <div className="pivot-banner">
          <Loader2 size={14} className="pivot-banner__spin" />
          <span>Mr. Poireaut tire sur les fils…</span>
        </div>
      )}

      <dl className="dp-panel__meta">
        <dt>Statut</dt>
        <dd><span className={`dp-status dp-status--${datapoint.status}`}>{datapoint.status}</span></dd>

        <dt>Confiance</dt>
        <dd>{confidencePct}</dd>

        {datapoint.source_url && datapoint.source_url !== datapoint.value && (<>
          <dt>Source</dt>
          <dd>
            <a href={datapoint.source_url} target="_blank" rel="noreferrer noopener" className="dp-panel__link">
              {safeHost(datapoint.source_url)}
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
          disabled={busy !== null || datapoint.status === 'rejected' || isPivoting}
          title={
            isPivoting
              ? 'Un pivot est déjà en cours sur ce datapoint'
              : datapoint.status === 'rejected'
                ? 'On ne pivote pas sur un datapoint rejeté'
                : 'Lancer tous les connecteurs compatibles'
          }
        >
          {busy === 'pivot' || isPivoting
            ? <><Loader2 size={14} className="dp-node__spin" style={{ marginRight: 6 }} /> Pivot en cours…</>
            : '🔎 Pivoter'}
        </button>
        <button className="btn btn--ghost btn--sm" onClick={doDelete} disabled={busy !== null}>
          Supprimer
        </button>
      </div>
    </aside>
  );
}

function safeHost(url: string): string {
  try { return new URL(url).host; }
  catch { return url; }
}
