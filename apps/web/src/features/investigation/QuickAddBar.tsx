import { useState } from 'react';
import { createDatapoint, type DataType } from '../../api';

const DATA_TYPES: { value: DataType; label: string }[] = [
  { value: 'email', label: 'Email' },
  { value: 'username', label: 'Pseudo' },
  { value: 'phone', label: 'Téléphone' },
  { value: 'name', label: 'Nom' },
  { value: 'url', label: 'URL' },
  { value: 'domain', label: 'Domaine' },
  { value: 'ip', label: 'IP' },
  { value: 'address', label: 'Adresse' },
  { value: 'other', label: 'Autre' },
];

interface Props {
  entityId: string;
  onAdded: () => void;
}

export default function QuickAddBar({ entityId, onAdded }: Props) {
  const [type, setType] = useState<DataType>('email');
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    setErr(null);
    setBusy(true);
    try {
      await createDatapoint(entityId, type, value.trim());
      setValue('');
      await onAdded();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="quick-add">
      <select
        className="quick-add__select"
        value={type}
        onChange={(e) => setType(e.target.value as DataType)}
      >
        {DATA_TYPES.map((t) => (
          <option key={t.value} value={t.value}>{t.label}</option>
        ))}
      </select>
      <input
        className="quick-add__input"
        placeholder={`Nouvel indice (${DATA_TYPES.find(t => t.value === type)?.label.toLowerCase()})`}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        required
      />
      <button className="btn btn--primary btn--sm" type="submit" disabled={busy}>
        {busy ? '…' : 'Ajouter'}
      </button>
      {err && <div className="form__error quick-add__error">{err}</div>}
    </form>
  );
}
