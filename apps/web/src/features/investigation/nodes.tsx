import { useState } from 'react';
import { Handle, Position } from 'reactflow';
import {
  Mail, User, Phone, MapPin, Link2, Image, Globe,
  Server, UserCircle, Briefcase, GraduationCap, Users,
  Calendar, HelpCircle, Circle, Fingerprint, Folder, Loader2,
  type LucideIcon,
} from 'lucide-react';
import type { DataType, VerificationStatus } from '../../api';

const ICONS: Record<DataType, LucideIcon> = {
  email: Mail,
  username: User,
  phone: Phone,
  name: UserCircle,
  address: MapPin,
  url: Link2,
  photo: Image,
  ip: Server,
  domain: Globe,
  date_of_birth: Calendar,
  account: Fingerprint,
  location: MapPin,
  employer: Briefcase,
  school: GraduationCap,
  family: Users,
  other: HelpCircle,
};

export interface DataPointNodeData {
  label: string;
  dataType: DataType;
  status: VerificationStatus;
  confidence: number | null;
  pivoting?: boolean;
  depth?: number;            // pivot_depth — 0 for seeds, N for auto-pivots
  onOpen?: () => void;
  selected?: boolean;
}

export function DataPointNode({ data }: { data: DataPointNodeData }) {
  const Icon = ICONS[data.dataType] ?? Circle;
  const depth = data.depth ?? 0;
  // Color encoding:
  //   - background color   ← data_type (dp-node--type-email, etc.)
  //   - border color/style ← pivot_depth (dp-node--depth-0, -1, -2, …)
  // We cap depth at 5 in CSS — deeper still works, just shares the depth-5 style.
  const depthClass = `dp-node--depth-${Math.min(depth, 5)}`;
  const typeClass = `dp-node--type-${data.dataType}`;
  const classes = [
    'dp-node',
    `dp-node--${data.status}`,
    typeClass,
    depthClass,
    data.dataType === 'photo' ? 'dp-node--photo' : '',
    data.selected ? 'dp-node--selected' : '',
    data.pivoting ? 'dp-node--pivoting' : '',
  ].filter(Boolean).join(' ');

  // For PHOTO datapoints, use the URL as an actual image thumbnail.
  const isImage = data.dataType === 'photo' && /^https?:\/\//i.test(data.label);

  return (
    <button className={classes} onClick={data.onOpen} type="button">
      <Handle type="target" position={Position.Top} />
      {data.depth !== undefined && data.depth > 0 && (
        <span
          className="dp-node__depth"
          title={`Profondeur d'auto-pivot : ${data.depth}`}
        >
          L{data.depth}
        </span>
      )}
      <div className="dp-node__icon">
        {data.pivoting ? (
          <Loader2 size={14} className="dp-node__spin" />
        ) : isImage ? (
          <PhotoThumb url={data.label} />
        ) : (
          <Icon size={14} />
        )}
      </div>
      <div className="dp-node__body">
        <div className="dp-node__type">{data.dataType}</div>
        <div className="dp-node__value" title={data.label}>
          {isImage ? safeHost(data.label) : data.label}
        </div>
      </div>
      {data.confidence != null && (
        <div
          className="dp-node__conf"
          title={`Confiance ${Math.round(data.confidence * 100)}%`}
        >
          {Math.round(data.confidence * 100)}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} />
    </button>
  );
}

function safeHost(url: string): string {
  try { return new URL(url).host; }
  catch { return url; }
}

function PhotoThumb({ url }: { url: string }) {
  // A tiny wrapper so the onError fallback is local state, not a re-render
  // of the parent node. We keep the <img /> behind a <span> that handles
  // its own broken state so React Flow doesn't thrash.
  const [broken, setBroken] = useState(false);
  if (broken) return <Image size={14} />;
  return (
    <img
      src={url}
      alt=""
      className="dp-node__thumb"
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setBroken(true)}
    />
  );
}

export interface EntityNodeData {
  label: string;
  role: 'target' | 'related';
}

export function EntityNode({ data }: { data: EntityNodeData }) {
  return (
    <div className={`entity-node entity-node--${data.role}`}>
      <Handle type="source" position={Position.Bottom} />
      <div className="entity-node__eyebrow">
        {data.role === 'target' ? 'Cible' : 'Lié'}
      </div>
      <div className="entity-node__name">{data.label}</div>
    </div>
  );
}

// ─── Cluster node — virtual folder grouping many findings ─────────

export interface ClusterNodeData {
  connectorName: string;
  count: number;
  validated: number;
  expanded: boolean;
  onToggle: () => void;
}

export function ClusterNode({ data }: { data: ClusterNodeData }) {
  return (
    <button
      className={`cluster-node ${data.expanded ? 'cluster-node--open' : ''}`}
      onClick={data.onToggle}
      type="button"
    >
      <Handle type="target" position={Position.Top} />
      <div className="cluster-node__icon"><Folder size={16} /></div>
      <div className="cluster-node__body">
        <div className="cluster-node__connector">+{data.count} {data.connectorName}</div>
        <div className="cluster-node__count">
          {data.expanded ? 'Refermer' : 'Voir les autres'}
          {data.validated > 0 && (
            <span className="cluster-node__valid"> · {data.validated} validés</span>
          )}
        </div>
      </div>
      <div className="cluster-node__chevron">{data.expanded ? '▾' : '▸'}</div>
      <Handle type="source" position={Position.Bottom} />
    </button>
  );
}

export const nodeTypes = {
  datapoint: DataPointNode,
  entity: EntityNode,
  cluster: ClusterNode,
};
