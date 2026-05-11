import { useState } from 'react';

const TYPES: { key: string; label: string; cssVar: string }[] = [
  { key: 'email', label: 'Email', cssVar: '--type-email-bg' },
  { key: 'username', label: 'Username', cssVar: '--type-username-bg' },
  { key: 'account', label: 'Compte', cssVar: '--type-account-bg' },
  { key: 'name', label: 'Nom', cssVar: '--type-name-bg' },
  { key: 'photo', label: 'Photo', cssVar: '--type-photo-bg' },
  { key: 'address', label: 'Adresse', cssVar: '--type-address-bg' },
  { key: 'phone', label: 'Téléphone', cssVar: '--type-phone-bg' },
  { key: 'domain', label: 'Domaine', cssVar: '--type-domain-bg' },
  { key: 'ip', label: 'IP', cssVar: '--type-ip-bg' },
  { key: 'url', label: 'URL', cssVar: '--type-url-bg' },
];

const DEPTHS: { depth: number; label: string; cssVar: string }[] = [
  { depth: 0, label: 'L0 — Seed', cssVar: '--depth-0' },
  { depth: 1, label: 'L1 — 1er pivot', cssVar: '--depth-1' },
  { depth: 2, label: 'L2 — 2e pivot', cssVar: '--depth-2' },
  { depth: 3, label: 'L3 — 3e pivot', cssVar: '--depth-3' },
  { depth: 4, label: 'L4+', cssVar: '--depth-4' },
];

export default function GraphLegend() {
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <div
        className="graph-legend graph-legend--collapsed"
        onClick={() => setCollapsed(false)}
        role="button"
        title="Afficher la légende"
      >
        <div className="graph-legend__title">Légende ↑</div>
      </div>
    );
  }

  return (
    <div className="graph-legend">
      <button
        className="graph-legend__collapse"
        onClick={() => setCollapsed(true)}
        aria-label="Réduire la légende"
        title="Réduire"
      >
        −
      </button>
      <div className="graph-legend__title">Légende</div>

      <div className="graph-legend__section">
        <div className="graph-legend__section-label">Type (fond)</div>
        {TYPES.map((t) => (
          <div key={t.key} className="graph-legend__row">
            <span
              className="graph-legend__chip"
              style={{ background: `var(${t.cssVar})` }}
            />
            <span className="graph-legend__label">{t.label}</span>
          </div>
        ))}
      </div>

      <div className="graph-legend__section">
        <div className="graph-legend__section-label">Profondeur (bordure)</div>
        {DEPTHS.map((d) => (
          <div key={d.depth} className="graph-legend__row">
            <span
              className="graph-legend__ring"
              style={{ borderColor: `var(${d.cssVar})` }}
            />
            <span className="graph-legend__label">{d.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
