/**
 * Graph layout for the spider web.
 *
 * Rules the layout obeys:
 *   1. Entity at top, seed datapoints on row 2, their children below, …
 *   2. When a datapoint has many same-connector children (default: >= 5),
 *      replace them with a single expandable cluster node. The cluster has
 *      a synthetic id like `cluster:{sourceId}:{connectorName}` and keeps
 *      track of its wrapped datapoint ids so callers can still select them.
 *   3. A filter predicate can hide datapoints (typically to show only
 *      validated ones). Hidden items don't contribute to cluster counts
 *      either — they're just gone from the graph.
 *
 * The function returns the react-flow node/edge arrays *and* the meta info
 * the UI needs to render the cluster expand panel (what's inside each
 * cluster, etc.).
 */
import type { Graph, GraphNode } from '../../api';
import type { Edge, Node } from 'reactflow';

// ── Tunables ────────────────────────────────────────
const ENTITY_Y = 0;
const FIRST_ROW_Y = 180;
const ROW_SPACING = 170;
const MIN_H_SPACING = 220;
const CLUSTER_THRESHOLD = 5;   // group when a pivot produced >= this many findings

// ── Types ───────────────────────────────────────────

export interface LayoutOptions {
  selectedId: string | null;
  pivotingIds: Set<string>;
  onOpenDatapoint: (id: string) => void;
  onToggleCluster: (key: string) => void;
  expandedClusters: Set<string>;
  filter?: (node: GraphNode) => boolean;
}

export interface LayoutResult {
  nodes: Node[];
  edges: Edge[];
  clusters: Map<string, ClusterInfo>;   // cluster key → contents
  hiddenClusterIds: Set<string>;         // datapoint ids hidden behind a cluster
}

export interface ClusterInfo {
  key: string;
  connectorName: string;
  sourceDatapointId: string;
  count: number;
  validated: number;
  datapointIds: string[];
}

// ── Implementation ──────────────────────────────────

export function layoutGraph(graph: Graph, opts: LayoutOptions): LayoutResult {
  const {
    selectedId, pivotingIds, onOpenDatapoint, onToggleCluster,
    expandedClusters, filter,
  } = opts;

  const byId = new Map(graph.nodes.map((n) => [n.id, n]));

  // pivot-kind edges (source → target) and the connector that produced them
  const pivotParent = new Map<string, string>();           // child → parent
  const pivotConnector = new Map<string, string | null>(); // child → connector
  const children = new Map<string, string[]>();            // parent → [child]
  const ownership = new Map<string, string[]>();           // entity → [seedDP]

  for (const e of graph.edges) {
    if (e.kind === 'pivot') {
      pivotParent.set(e.target, e.source);
      pivotConnector.set(e.target, e.connector_name ?? null);
      (children.get(e.source) ?? children.set(e.source, []).get(e.source)!).push(e.target);
    } else if (e.kind === 'owns') {
      (ownership.get(e.source) ?? ownership.set(e.source, []).get(e.source)!).push(e.target);
    }
  }

  // Apply the filter (hide everything that fails)
  const isVisible = (id: string): boolean => {
    const n = byId.get(id);
    if (!n) return false;
    if (!filter) return true;
    return filter(n);
  };

  // ── Build clusters ──
  // For each parent, look at its pivot children. Group them by connector.
  // If a group has >= CLUSTER_THRESHOLD visible members, it becomes a cluster.
  const clusters = new Map<string, ClusterInfo>();
  const hiddenClusterIds = new Set<string>();   // ids represented by a cluster (not drawn as DP)

  for (const [parentId, childIds] of children.entries()) {
    const visibleChildren = childIds.filter(isVisible);
    // Group by connector
    const groupsByConnector = new Map<string, string[]>();
    for (const cid of visibleChildren) {
      const conn = pivotConnector.get(cid) ?? 'autre';
      (groupsByConnector.get(conn) ?? groupsByConnector.set(conn, []).get(conn)!).push(cid);
    }
    for (const [conn, ids] of groupsByConnector) {
      if (ids.length < CLUSTER_THRESHOLD) continue;
      const key = `cluster:${parentId}:${conn}`;
      const validated = ids.reduce((acc, id) => {
        const n = byId.get(id);
        return acc + (n?.status === 'validated' ? 1 : 0);
      }, 0);
      clusters.set(key, {
        key,
        connectorName: conn,
        sourceDatapointId: parentId,
        count: ids.length,
        validated,
        datapointIds: ids,
      });
      // If not expanded, hide the individual nodes
      if (!expandedClusters.has(key)) {
        for (const id of ids) hiddenClusterIds.add(id);
      }
    }
  }

  // ── Place nodes ──
  const positions = new Map<string, { x: number; y: number }>();
  const entities = graph.nodes.filter((n) => n.kind === 'entity');
  entities.forEach((e, idx) => {
    const offset = (idx - (entities.length - 1) / 2) * 400;
    positions.set(e.id, { x: offset, y: ENTITY_Y });
  });

  // Seed datapoints: those without a pivotParent
  const seeds: string[] = [];
  for (const n of graph.nodes) {
    if (n.kind === 'datapoint' && !pivotParent.has(n.id) && isVisible(n.id)) {
      seeds.push(n.id);
    }
  }
  const seedSpread = Math.max(1, seeds.length);
  seeds.forEach((id, idx) => {
    const x = (idx - (seedSpread - 1) / 2) * MIN_H_SPACING;
    positions.set(id, { x, y: FIRST_ROW_Y });
  });

  // BFS — place non-clustered children below their parent
  const queue: Array<{ id: string; depth: number }> =
    seeds.map((id) => ({ id, depth: 1 }));
  let head = 0;
  while (head < queue.length) {
    const { id: parentId, depth } = queue[head++];
    const parentPos = positions.get(parentId) ?? { x: 0, y: FIRST_ROW_Y };

    // Build the list of "visual children" of parentId:
    //   * clusters that group some of its kids
    //   * individual visible kids that aren't inside a hidden cluster
    const allKids = children.get(parentId) ?? [];
    const clusterKidsByKey = new Map<string, string[]>();
    const individuals: string[] = [];
    for (const cid of allKids) {
      if (!isVisible(cid)) continue;
      const conn = pivotConnector.get(cid) ?? 'autre';
      const key = `cluster:${parentId}:${conn}`;
      if (clusters.has(key)) {
        (clusterKidsByKey.get(key) ?? clusterKidsByKey.set(key, []).get(key)!).push(cid);
      } else {
        individuals.push(cid);
      }
    }
    const visualItems: Array<{ type: 'node'; id: string } | { type: 'cluster'; key: string }> = [
      ...[...clusterKidsByKey.keys()].map((k) => ({ type: 'cluster' as const, key: k })),
      ...individuals.map((id) => ({ type: 'node' as const, id })),
    ];
    if (visualItems.length === 0) continue;

    visualItems.forEach((item, idx) => {
      const x = parentPos.x + (idx - (visualItems.length - 1) / 2) * MIN_H_SPACING;
      const y = FIRST_ROW_Y + depth * ROW_SPACING;
      if (item.type === 'node') {
        positions.set(item.id, { x, y });
        queue.push({ id: item.id, depth: depth + 1 });
      } else {
        positions.set(item.key, { x, y });
        // If the cluster is expanded, lay out its kids right below it.
        if (expandedClusters.has(item.key)) {
          const kids = clusters.get(item.key)?.datapointIds ?? [];
          kids.forEach((kid, kidIdx) => {
            const kx = x + (kidIdx - (kids.length - 1) / 2) * Math.max(160, MIN_H_SPACING - 60);
            const ky = y + ROW_SPACING;
            positions.set(kid, { x: kx, y: ky });
            queue.push({ id: kid, depth: depth + 2 });
          });
        }
      }
    });
  }

  // ── Build react-flow nodes ──
  const nodes: Node[] = [];

  for (const n of graph.nodes) {
    if (n.kind === 'entity') {
      const pos = positions.get(n.id) ?? { x: 0, y: 0 };
      nodes.push({
        id: n.id,
        type: 'entity',
        position: pos,
        data: { label: n.label, role: 'target' },
        draggable: true,
      });
      continue;
    }
    if (!isVisible(n.id)) continue;
    if (hiddenClusterIds.has(n.id)) continue;
    const pos = positions.get(n.id);
    if (!pos) continue;
    nodes.push({
      id: n.id,
      type: 'datapoint',
      position: pos,
      data: {
        label: n.label,
        dataType: n.data_type!,
        status: n.status!,
        confidence: n.confidence ?? null,
        pivoting: pivotingIds.has(n.id),
        onOpen: () => onOpenDatapoint(n.id),
        selected: selectedId === n.id,
      },
      draggable: true,
    });
  }

  for (const [key, info] of clusters.entries()) {
    const pos = positions.get(key) ?? { x: 0, y: FIRST_ROW_Y };
    nodes.push({
      id: key,
      type: 'cluster',
      position: pos,
      data: {
        connectorName: info.connectorName,
        count: info.count,
        validated: info.validated,
        expanded: expandedClusters.has(key),
        onToggle: () => onToggleCluster(key),
      },
      draggable: true,
    });
  }

  // ── Build edges ──
  const edges: Edge[] = [];
  const nodeIds = new Set(nodes.map((n) => n.id));

  for (const e of graph.edges) {
    if (e.kind === 'owns') {
      // Only the entity-to-seed edge is interesting to draw
      if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) continue;
      if (pivotParent.has(e.target)) continue;  // only seed links
      edges.push(_edge(e.id, e.source, e.target, 'owns'));
      continue;
    }
    // pivot edge
    // If the target is hidden by a cluster, re-route: entity→cluster
    if (hiddenClusterIds.has(e.target)) {
      const conn = pivotConnector.get(e.target) ?? 'autre';
      const clusterKey = `cluster:${e.source}:${conn}`;
      if (!nodeIds.has(clusterKey)) continue;
      const syntheticId = `pv-cl-${e.source}-${clusterKey}`;
      // dedup
      if (!edges.some((x) => x.id === syntheticId)) {
        edges.push(_edge(syntheticId, e.source, clusterKey, 'pivot', conn));
      }
      continue;
    }
    if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) continue;
    edges.push(_edge(e.id, e.source, e.target, 'pivot', e.connector_name));
  }

  // Also: edges from each cluster to its expanded kids
  for (const info of clusters.values()) {
    if (!expandedClusters.has(info.key)) continue;
    for (const kid of info.datapointIds) {
      if (!nodeIds.has(kid)) continue;
      edges.push(_edge(`cl-kid-${info.key}-${kid}`, info.key, kid, 'pivot'));
    }
  }

  return { nodes, edges, clusters, hiddenClusterIds };
}

function _edge(
  id: string, source: string, target: string,
  kind: 'pivot' | 'owns', label?: string | null,
): Edge {
  return {
    id,
    source,
    target,
    type: 'smoothstep',
    animated: false,
    label: kind === 'pivot' ? label ?? undefined : undefined,
    style: {
      stroke: kind === 'pivot' ? 'var(--gold)' : 'rgba(45,74,43,0.35)',
      strokeWidth: kind === 'pivot' ? 1.5 : 1,
    },
    labelStyle: {
      fontFamily: 'var(--font-display)',
      fontSize: 10,
      letterSpacing: '0.14em',
      textTransform: 'uppercase',
      fill: 'var(--gold-deep)',
    },
    labelBgStyle: {
      fill: 'var(--cream)',
      fillOpacity: 0.9,
    },
  };
}
