import { useState } from 'react';
import { updateInvestigation, type AutoPivotMode, type Investigation } from '../../api';

interface Props {
  investigation: Investigation;
  onUpdated: (next: Investigation) => void;
  onClose: () => void;
}

const MODE_LABELS: Record<AutoPivotMode, string> = {
  off: 'Désactivé',
  manual_only: 'Manuel uniquement',
  auto: 'Automatique agressif',
};

const MODE_HINTS: Record<AutoPivotMode, string> = {
  off:
    'Aucun pivot automatique. Vous lancez chaque pivot manuellement depuis la toile.',
  manual_only:
    'Pivot automatique seulement quand vous validez un datapoint (case ✓ Valider). Sécurisé pour les enquêtes sensibles.',
  auto:
    'Tout finding dépassant le seuil de confiance déclenche un nouveau pivot automatiquement, dans la limite de la profondeur maximale.',
};

export default function SettingsPanel({ investigation, onUpdated, onClose }: Props) {
  const [mode, setMode] = useState<AutoPivotMode>(investigation.auto_pivot_mode);
  const [minConf, setMinConf] = useState<number>(investigation.auto_pivot_min_confidence);
  const [maxDepth, setMaxDepth] = useState<number>(investigation.auto_pivot_max_depth);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const dirty =
    mode !== investigation.auto_pivot_mode
    || Math.abs(minConf - investigation.auto_pivot_min_confidence) > 0.001
    || maxDepth !== investigation.auto_pivot_max_depth;

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const next = await updateInvestigation(investigation.id, {
        auto_pivot_mode: mode,
        auto_pivot_min_confidence: minConf,
        auto_pivot_max_depth: maxDepth,
      });
      onUpdated(next);
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside className="settings-panel">
      <div className="dp-panel__head">
        <div className="dp-panel__eyebrow">Paramètres de l'enquête</div>
        <button className="dp-panel__close" onClick={onClose} aria-label="Fermer">×</button>
      </div>

      <h3 className="dp-panel__value">Auto-pivot</h3>

      <p className="settings-panel__lede">
        Mr. Poireaut peut continuer l'enquête tout seul à partir des résultats
        qu'il trouve. Voici comment l'encadrer.
      </p>

      <div className="settings-panel__section">
        <div className="settings-panel__label">Mode</div>
        <div className="settings-panel__radio-group" role="radiogroup">
          {(['off', 'manual_only', 'auto'] as AutoPivotMode[]).map((m) => (
            <label key={m} className={`settings-panel__radio ${mode === m ? 'settings-panel__radio--active' : ''}`}>
              <input
                type="radio"
                name="mode"
                value={m}
                checked={mode === m}
                onChange={() => setMode(m)}
              />
              <span className="settings-panel__radio-label">{MODE_LABELS[m]}</span>
            </label>
          ))}
        </div>
        <div className="settings-panel__hint">{MODE_HINTS[mode]}</div>
      </div>

      <div className="settings-panel__section">
        <div className="settings-panel__label">
          Seuil de confiance minimum : <strong>{Math.round(minConf * 100)} %</strong>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={Math.round(minConf * 100)}
          onChange={(e) => setMinConf(Number(e.target.value) / 100)}
          disabled={mode !== 'auto'}
          className="settings-panel__slider"
        />
        <div className="settings-panel__hint">
          {mode === 'auto'
            ? 'Seuls les findings dépassant ce seuil seront pivotés automatiquement.'
            : 'Cette valeur n\'est utilisée qu\'en mode Automatique.'}
        </div>
      </div>

      <div className="settings-panel__section">
        <div className="settings-panel__label">
          Profondeur maximale : <strong>{maxDepth}</strong>
        </div>
        <input
          type="range"
          min={0}
          max={10}
          step={1}
          value={maxDepth}
          onChange={(e) => setMaxDepth(Number(e.target.value))}
          disabled={mode === 'off'}
          className="settings-panel__slider"
        />
        <div className="settings-panel__hint">
          Nombre maximum de "hops" depuis le seed. Au-delà, l'auto-pivot s'arrête.
          Limite dure : 10. Recommandé : 2-4.
        </div>
      </div>

      <div className="settings-panel__section settings-panel__breakers">
        <div className="settings-panel__label">⚠️ Garde-fous fixes</div>
        <ul className="settings-panel__list">
          <li>500 datapoints auto-créés max par enquête</li>
          <li>200 datapoints auto-créés max par heure</li>
          <li>Doublons (mêmes valeur + type) jamais re-pivotés</li>
        </ul>
      </div>

      {err && <div className="form__error">{err}</div>}

      <div className="dp-panel__actions dp-panel__actions--primary">
        <button
          className="btn btn--primary"
          onClick={save}
          disabled={!dirty || busy}
        >
          {busy ? '…' : 'Enregistrer'}
        </button>
        <button className="btn btn--ghost btn--sm" onClick={onClose} disabled={busy}>
          Annuler
        </button>
      </div>
    </aside>
  );
}
