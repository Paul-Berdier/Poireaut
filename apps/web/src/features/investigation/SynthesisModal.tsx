import { useEffect, useState } from 'react';
import { synthesizeInvestigation, type SynthesisResponse } from '../../api';

interface Props {
  investigationId: string;
  onClose: () => void;
}

export default function SynthesisModal({ investigationId, onClose }: Props) {
  const [result, setResult] = useState<SynthesisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [onlyValidated, setOnlyValidated] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const runSynthesis = async (validated: boolean) => {
    setLoading(true);
    setErr(null);
    try {
      const r = await synthesizeInvestigation(investigationId, validated);
      setResult(r);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // Initial fetch on mount
  useEffect(() => {
    runSynthesis(onlyValidated);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [investigationId]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal__head">
          <div className="panel__eyebrow">Synthèse IA</div>
          <button className="dp-panel__close" onClick={onClose} aria-label="Fermer">×</button>
        </div>

        <h2 className="modal__title">Rapport généré par Mr. Poireaut</h2>

        <label className="modal__filter">
          <input
            type="checkbox"
            checked={onlyValidated}
            onChange={(e) => {
              setOnlyValidated(e.target.checked);
              runSynthesis(e.target.checked);
            }}
          />
          <span>Utiliser uniquement les données validées</span>
        </label>

        <div className="modal__body">
          {loading ? (
            <div className="panel__empty">Mr. Poireaut consulte ses notes…</div>
          ) : err ? (
            <div className="form__error">{err}</div>
          ) : result ? (
            <>
              <pre className="synthesis-text">{result.summary}</pre>
              <div className="synthesis-meta">
                {result.datapoints_used} datapoint{result.datapoints_used > 1 ? 's' : ''} utilisé{result.datapoints_used > 1 ? 's' : ''} · modèle <code>{result.model}</code>
              </div>
            </>
          ) : null}
        </div>

        <div className="modal__actions">
          <button
            className="btn btn--primary btn--sm"
            onClick={() => runSynthesis(onlyValidated)}
            disabled={loading}
          >
            {loading ? '…' : 'Régénérer'}
          </button>
          <button className="btn btn--ghost btn--sm" onClick={onClose}>
            Fermer
          </button>
        </div>
      </div>
    </div>
  );
}
