import { useEffect, useState } from 'react';
import {
  deleteApiKey, listApiKeys, setApiKey, testApiKey,
  type ApiKeyConnector, type ApiKeyOut,
} from '../../api';

// Connector catalog: human label + description + signup URL + cost hint.
// Used to render the grid even for connectors the user hasn't configured yet.
interface ConnectorCard {
  name: ApiKeyConnector;
  label: string;
  description: string;
  signup_url: string;
  cost: string;
  category: 'image' | 'phone' | 'email' | 'ip' | 'ai' | 'breach';
}

const CONNECTORS: ConnectorCard[] = [
  {
    name: 'ipinfo',
    label: 'IPInfo',
    description: 'Géolocalise une IP : pays, ville, ASN, drapeau VPN/proxy.',
    signup_url: 'https://ipinfo.io/signup',
    cost: 'Gratuit 50 k req/mois',
    category: 'ip',
  },
  {
    name: 'numverify',
    label: 'Numverify',
    description: 'Valide un numéro de téléphone et identifie le pays/opérateur.',
    signup_url: 'https://numverify.com/product',
    cost: 'Gratuit 250 req/mois',
    category: 'phone',
  },
  {
    name: 'hunter',
    label: 'Hunter.io',
    description: 'Email → nom complet, poste, entreprise.',
    signup_url: 'https://hunter.io/users/sign_up',
    cost: 'Gratuit 25 req/mois',
    category: 'email',
  },
  {
    name: 'hibp',
    label: 'Have I Been Pwned',
    description: 'Vérifie si un email a fuité dans des bases compromises.',
    signup_url: 'https://haveibeenpwned.com/API/Key',
    cost: '3.95 $/mois',
    category: 'breach',
  },
  {
    name: 'shodan',
    label: 'Shodan',
    description: 'IP/domaine → ports ouverts, services, vulnérabilités.',
    signup_url: 'https://account.shodan.io/register',
    cost: '69 $ une fois',
    category: 'ip',
  },
  {
    name: 'facecheck',
    label: 'FaceCheck.id',
    description: 'Recherche faciale inverse — trouve un visage sur le web.',
    signup_url: 'https://facecheck.id/account',
    cost: '≈ 19 $/mois',
    category: 'image',
  },
  {
    name: 'openai',
    label: 'OpenAI',
    description: 'Synthèses IA de l\'enquête, suggestions de pivots.',
    signup_url: 'https://platform.openai.com/api-keys',
    cost: 'Pay-as-you-go',
    category: 'ai',
  },
];

type Tab = 'profile' | 'keys';

export default function AccountView() {
  const [tab, setTab] = useState<Tab>('keys');

  return (
    <div className="account-page">
      <header className="account-page__head">
        <div>
          <div className="panel__eyebrow">Mon compte</div>
          <h1 className="account-page__title">Paramètres</h1>
        </div>
      </header>

      <nav className="account-page__tabs" role="tablist">
        <button
          role="tab" aria-selected={tab === 'profile'}
          className={`tab ${tab === 'profile' ? 'tab--active' : ''}`}
          onClick={() => setTab('profile')}
        >
          Profil
        </button>
        <button
          role="tab" aria-selected={tab === 'keys'}
          className={`tab ${tab === 'keys' ? 'tab--active' : ''}`}
          onClick={() => setTab('keys')}
        >
          🔑 Clés API
        </button>
      </nav>

      <div className="account-page__body">
        {tab === 'keys' ? <ApiKeysTab /> : <ProfileTab />}
      </div>
    </div>
  );
}

function ProfileTab() {
  return (
    <div className="account-section">
      <p className="account-section__lede">
        Gestion du profil utilisateur (mot de passe, sécurité) à venir.
        Pour l'instant, toute modification du compte passe par l'admin.
      </p>
    </div>
  );
}

function ApiKeysTab() {
  const [keys, setKeys] = useState<ApiKeyOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const list = await listApiKeys();
      setKeys(list);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  const byName = new Map(keys.map((k) => [k.connector_name, k]));

  return (
    <div className="account-section">
      <div className="account-section__intro">
        <h2 className="account-section__title">Clés d'API des outils tiers</h2>
        <p className="account-section__lede">
          Ces clés débloquent les connecteurs payants ou à quota strict.
          Sans clé, Poireaut continue de fonctionner avec les outils gratuits
          (Holehe, Maigret, crt.sh, Wayback, scrapers). Ajouter une clé
          active automatiquement le connecteur correspondant.
        </p>
        <div className="account-section__notice">
          🔒 Les clés sont chiffrées au repos (Fernet AES-128) avant stockage
          en base. Elles ne sont jamais renvoyées en clair par l'API — seul
          un aperçu masqué est affiché.
        </div>
      </div>

      {err && <div className="form__error">{err}</div>}
      {loading && <div className="panel__empty">Chargement…</div>}

      <div className="keys-grid">
        {CONNECTORS.map((c) => (
          <ApiKeyCard
            key={c.name}
            connector={c}
            current={byName.get(c.name)}
            onChanged={refresh}
          />
        ))}
      </div>
    </div>
  );
}

function ApiKeyCard({
  connector, current, onChanged,
}: {
  connector: ConnectorCard;
  current: ApiKeyOut | undefined;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);

  const save = async () => {
    if (!value.trim()) return;
    setBusy('save');
    try {
      await setApiKey(connector.name, value.trim());
      setValue('');
      setEditing(false);
      onChanged();
    } catch (e) {
      setTestResult(`Erreur : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!confirm(`Supprimer la clé ${connector.label} ?`)) return;
    setBusy('delete');
    try {
      await deleteApiKey(connector.name);
      onChanged();
    } catch (e) {
      setTestResult(`Erreur : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    setBusy('test');
    setTestResult(null);
    try {
      const r = await testApiKey(connector.name);
      setTestResult(`${r.ok ? '✅' : '❌'} ${r.detail}`);
      onChanged();
    } catch (e) {
      setTestResult(`Erreur : ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  const isConfigured = current !== undefined;

  return (
    <div className={`key-card ${isConfigured ? 'key-card--configured' : ''}`}>
      <div className="key-card__head">
        <div className="key-card__title">
          <span className={`key-card__dot key-card__dot--${connector.category}`} />
          <span>{connector.label}</span>
          {isConfigured && <span className="key-card__badge">configuré</span>}
        </div>
        <div className="key-card__cost">{connector.cost}</div>
      </div>

      <p className="key-card__desc">{connector.description}</p>

      {isConfigured && !editing && (
        <div className="key-card__current">
          <code className="key-card__preview">{current!.masked_preview}</code>
          {current!.last_test_ok != null && (
            <span className={`key-card__status ${current!.last_test_ok ? 'is-ok' : 'is-bad'}`}>
              {current!.last_test_ok ? '✓ testée' : '✗ échec'}
            </span>
          )}
        </div>
      )}

      {editing && (
        <div className="key-card__editor">
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Coller la clé ici…"
            className="form__input"
            autoFocus
          />
          <div className="key-card__editor-actions">
            <button
              className="btn btn--primary btn--sm"
              onClick={save}
              disabled={busy !== null || !value.trim()}
            >
              {busy === 'save' ? '…' : 'Enregistrer'}
            </button>
            <button
              className="btn btn--ghost btn--sm"
              onClick={() => { setEditing(false); setValue(''); setTestResult(null); }}
            >
              Annuler
            </button>
          </div>
        </div>
      )}

      {testResult && <div className="key-card__test-result">{testResult}</div>}

      <div className="key-card__actions">
        {!isConfigured && !editing && (
          <button className="btn btn--primary btn--sm" onClick={() => setEditing(true)}>
            Configurer
          </button>
        )}
        {isConfigured && !editing && (
          <>
            <button className="btn btn--ghost btn--sm" onClick={() => setEditing(true)}>
              Modifier
            </button>
            <button
              className="btn btn--ghost btn--sm"
              onClick={test}
              disabled={busy !== null}
            >
              {busy === 'test' ? '…' : 'Tester'}
            </button>
            <button
              className="btn btn--ghost btn--sm btn--danger"
              onClick={remove}
              disabled={busy !== null}
            >
              Supprimer
            </button>
          </>
        )}
        <a
          href={connector.signup_url}
          target="_blank"
          rel="noreferrer noopener"
          className="btn btn--ghost btn--sm key-card__signup"
        >
          Obtenir une clé ↗
        </a>
      </div>
    </div>
  );
}
