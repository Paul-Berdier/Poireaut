import { useEffect, useState } from 'react';
import {
  Mail, User, Phone, MapPin, Link2, Image as ImageIcon, Globe,
  Server, UserCircle, Briefcase, GraduationCap, Users,
  Calendar, HelpCircle, Fingerprint, CheckCircle2, XCircle, Clock,
  type LucideIcon,
} from 'lucide-react';
import {
  createDatapoint, getIdentity, updateDatapoint,
  type DataType, type DatapointSummary, type IdentityCard, type TypeGroup,
} from '../../api';

const ICONS: Record<DataType, LucideIcon> = {
  email: Mail, username: User, phone: Phone, name: UserCircle,
  address: MapPin, url: Link2, photo: ImageIcon, ip: Server,
  domain: Globe, date_of_birth: Calendar, account: Fingerprint,
  location: MapPin, employer: Briefcase, school: GraduationCap,
  family: Users, other: HelpCircle,
};

const TYPE_LABELS: Record<DataType, string> = {
  email: 'Emails', username: 'Pseudos', phone: 'Téléphones', name: 'Noms',
  address: 'Adresses', url: 'URLs', photo: 'Photos', ip: 'IPs',
  domain: 'Domaines', date_of_birth: 'Naissance', account: 'Comptes',
  location: 'Localisations', employer: 'Employeurs', school: 'Écoles',
  family: 'Famille', other: 'Autres',
};

// Fields shown in the "saisie rapide" block — ordered like a detective file.
const QUICK_FIELDS: { type: DataType; placeholder: string }[] = [
  { type: 'name',          placeholder: 'Nom complet' },
  { type: 'date_of_birth', placeholder: 'Date de naissance (ex. 1990-05-12)' },
  { type: 'email',         placeholder: 'Email' },
  { type: 'phone',         placeholder: 'Téléphone' },
  { type: 'username',      placeholder: 'Pseudo / handle' },
  { type: 'address',       placeholder: 'Adresse' },
  { type: 'employer',      placeholder: 'Employeur' },
  { type: 'school',        placeholder: 'École / université' },
];

interface Props {
  investigationId: string;
  entityId: string | null;
  onDataChange: () => void;
}

export default function FicheView({ investigationId, entityId, onDataChange }: Props) {
  const [card, setCard] = useState<IdentityCard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const c = await getIdentity(investigationId);
        if (!cancelled) setCard(c);
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      }
    })();
    return () => { cancelled = true; };
  }, [investigationId, refreshTick]);

  const refresh = () => { setRefreshTick((x) => x + 1); onDataChange(); };

  return (
    <div className="fiche">
      <div className="fiche__header">
        <div>
          <div className="panel__eyebrow">Fiche identité</div>
          <h2 className="fiche__title">{card?.display_name ?? '…'}</h2>
        </div>
        {card && (
          <div className="fiche__totals">
            <TotalBadge icon={<CheckCircle2 size={14} />} label="Validés" value={card.totals.validated} kind="ok" />
            <TotalBadge icon={<Clock size={14} />} label="En attente" value={card.totals.unverified} kind="warn" />
            <TotalBadge icon={<XCircle size={14} />} label="Rejetés" value={card.totals.rejected} kind="bad" />
          </div>
        )}
      </div>

      {err && <div className="form__error">{err}</div>}

      {entityId && (
        <QuickAddBlock
          entityId={entityId}
          onAdded={refresh}
        />
      )}

      {!card ? (
        <div className="panel__empty">Chargement…</div>
      ) : card.groups.length === 0 ? (
        <div className="panel__empty">
          Aucune donnée pour l'instant — utilisez le bloc ci-dessus ou la barre
          d'ajout rapide dans la toile pour commencer.
        </div>
      ) : (
        <div className="fiche__groups">
          {card.groups.map((g) => (
            <FicheGroup key={g.data_type} group={g} onChanged={refresh} />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Quick-add block ───────────────────────────────

function QuickAddBlock({ entityId, onAdded }: { entityId: string; onAdded: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (type: DataType) => {
    const value = (values[type] ?? '').trim();
    if (!value) return;
    setBusy(type);
    setErr(null);
    try {
      await createDatapoint(entityId, type, value);
      setValues((prev) => ({ ...prev, [type]: '' }));
      onAdded();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="fiche__quickadd">
      <div className="fiche__quickadd-title">Saisie rapide</div>
      <div className="fiche__quickadd-grid">
        {QUICK_FIELDS.map(({ type, placeholder }) => {
          const Icon = ICONS[type];
          return (
            <div key={type} className="fiche__quickadd-row">
              <div className="fiche__quickadd-icon"><Icon size={14} /></div>
              <input
                className="fiche__quickadd-input"
                placeholder={placeholder}
                value={values[type] ?? ''}
                onChange={(e) => setValues((prev) => ({ ...prev, [type]: e.target.value }))}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { e.preventDefault(); submit(type); }
                }}
              />
              <button
                className="btn btn--primary btn--sm"
                onClick={() => submit(type)}
                disabled={busy === type || !(values[type] ?? '').trim()}
                title={`Ajouter ${TYPE_LABELS[type]}`}
              >
                {busy === type ? '…' : '+'}
              </button>
            </div>
          );
        })}
      </div>
      {err && <div className="form__error" style={{ marginTop: 'var(--s-3)' }}>{err}</div>}
    </div>
  );
}

// ─── Group card ────────────────────────────────────

function FicheGroup({ group, onChanged }: { group: TypeGroup; onChanged: () => void }) {
  const [expanded, setExpanded] = useState(group.total <= 5);
  const Icon = ICONS[group.data_type];
  const visible = expanded ? group.items : group.items.slice(0, 3);

  return (
    <section className="fg">
      <div className="fg__header">
        <div className="fg__title">
          <span className="fg__icon"><Icon size={16} /></span>
          {TYPE_LABELS[group.data_type]}
          <span className="fg__count">{group.total}</span>
        </div>
        <div className="fg__badges">
          {group.validated > 0 && (
            <span className="fg__badge fg__badge--ok">{group.validated} ✓</span>
          )}
          {group.rejected > 0 && (
            <span className="fg__badge fg__badge--bad">{group.rejected} ✗</span>
          )}
        </div>
      </div>

      <ul className="fg__items">
        {visible.map((d) => (
          <FicheItem key={d.id} dp={d} onChanged={onChanged} />
        ))}
      </ul>

      {group.total > visible.length && !expanded && (
        <button className="fg__more" onClick={() => setExpanded(true)}>
          Voir les {group.total - visible.length} autres →
        </button>
      )}
      {expanded && group.total > 5 && (
        <button className="fg__more" onClick={() => setExpanded(false)}>
          Réduire
        </button>
      )}
    </section>
  );
}

// ─── Single item row ───────────────────────────────

function FicheItem({
  dp, onChanged,
}: {
  dp: DatapointSummary;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  const run = async (label: string, patch: { status: 'validated' | 'rejected' | 'unverified' }) => {
    setBusy(label);
    try {
      await updateDatapoint(dp.id, patch);
      onChanged();
    } catch {
      setBusy(null);
    }
  };

  return (
    <li className={`fi fi--${dp.status}`}>
      <div className="fi__main">
        <span className="fi__value" title={dp.value}>
          {dp.source_url ? (
            <a href={dp.source_url} target="_blank" rel="noreferrer" className="fi__link">
              {dp.value}
            </a>
          ) : (
            dp.value
          )}
        </span>
        {dp.confidence != null && (
          <span className="fi__conf" title={`Confiance ${Math.round(dp.confidence * 100)}%`}>
            {Math.round(dp.confidence * 100)}%
          </span>
        )}
      </div>
      {dp.notes && <div className="fi__notes">{dp.notes}</div>}
      <div className="fi__actions">
        {dp.status !== 'validated' && (
          <button className="fi__btn fi__btn--ok" onClick={() => run('v', { status: 'validated' })} disabled={busy !== null}>
            ✓ Valider
          </button>
        )}
        {dp.status !== 'rejected' && (
          <button className="fi__btn fi__btn--bad" onClick={() => run('r', { status: 'rejected' })} disabled={busy !== null}>
            ✗ Rejeter
          </button>
        )}
        {dp.status !== 'unverified' && (
          <button className="fi__btn fi__btn--warn" onClick={() => run('u', { status: 'unverified' })} disabled={busy !== null}>
            ↺ En attente
          </button>
        )}
      </div>
    </li>
  );
}

// ─── Small bits ────────────────────────────────────

function TotalBadge({
  icon, label, value, kind,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  kind: 'ok' | 'warn' | 'bad';
}) {
  return (
    <div className={`total-badge total-badge--${kind}`}>
      <span className="total-badge__icon">{icon}</span>
      <span className="total-badge__label">{label}</span>
      <span className="total-badge__value">{value}</span>
    </div>
  );
}
