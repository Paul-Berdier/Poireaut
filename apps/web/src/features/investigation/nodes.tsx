import { Handle, Position } from 'reactflow';
import {
  Mail, User, Phone, MapPin, Link2, Image, Globe,
  Server, UserCircle, Briefcase, GraduationCap, Users,
  Calendar, HelpCircle, Circle, Fingerprint,
  type LucideIcon,
} from 'lucide-react';
import type { DataType, VerificationStatus } from '../../api';

// Map every DataType to an icon so the graph is scannable at a glance.
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
  onOpen?: () => void;
  selected?: boolean;
}

export function DataPointNode({ data }: { data: DataPointNodeData }) {
  const Icon = ICONS[data.dataType] ?? Circle;
  const classes = [
    'dp-node',
    `dp-node--${data.status}`,
    data.selected ? 'dp-node--selected' : '',
  ].join(' ');

  return (
    <button className={classes} onClick={data.onOpen} type="button">
      <Handle type="target" position={Position.Top} />
      <div className="dp-node__icon"><Icon size={14} /></div>
      <div className="dp-node__body">
        <div className="dp-node__type">{data.dataType}</div>
        <div className="dp-node__value" title={data.label}>{data.label}</div>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </button>
  );
}

export interface EntityNodeData {
  label: string;
  role: 'target' | 'related';
}

export function EntityNode({ data }: { data: EntityNodeData }) {
  const classes = ['entity-node', `entity-node--${data.role}`].join(' ');
  return (
    <div className={classes}>
      <Handle type="source" position={Position.Bottom} />
      <div className="entity-node__eyebrow">
        {data.role === 'target' ? 'Cible' : 'Lié'}
      </div>
      <div className="entity-node__name">{data.label}</div>
    </div>
  );
}

export const nodeTypes = {
  datapoint: DataPointNode,
  entity: EntityNode,
};
