/**
 * Graph layout using dagre.
 *
 * Why dagre: the previous BFS-based layout produced criss-crossing edges
 * when chains branched. Dagre is a proven graph layout library that
 * minimizes edge crossings and gives us a tidy top-down tree even on
 * complex investigations.
 *
 * Rules:
 *   1. Entity node at the top (rank 0)
 *   2. Datapoints flow down by pivot_depth
 *   3. Edges "owns" (entity → datapoint) are hidden — entity ownership
 *      is implicit and cluttered the canvas.
 *   4. When a datapoint has many same-connector children (≥ CLUSTER_THRESHOLD),
 *      they're replaced with a single expandable cluster node.
 *   5. A filter predicate can hide datapoints (typically validated-only).
 */
import dagre from 'dagre';
import type { Edge, Node } from 'reactflow';
import { MarkerType } from 'reactflow';
import type { Graph, GraphNode } from '../../api';

// ── Tunables ────────────────────────────────────────
const NODE_WIDTH = 240;
const NODE_HEIGHT = 70;
const RANK_SEP = 90;
const NODE_SEP = 50;
const CLUSTER_THRESHOLD = 5;

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
  clusters: Map<string, ClusterInfo>;
  hiddenClusterIds: Set<string>;
}

export interface ClusterInfo {
  key: string;
  connectorName: string;
  sourceDatapointId: string;
  count: number;
  childIds: string[];
  representativeType: string;
}

export function layoutGraph(
  graph: Graph,
  opts: LayoutOptions,
): LayoutResult {
  const { filter } = opts;

  const visibleNodes = graph.nodes.filter((n) => {
    if (n.kind !== 'datapoint') return true;
    return !filter || filter(n);
  });
  const visibleIds = new Set(visibleNodes.map((n) => n.id));

  // Detect clusters: groups of siblings (same source, same connector)
  const childrenBySource = new Map<string, GraphNode[]>();
  for (const e of graph.edges) {
    if (e.kind !== 'pivot') continue;
    if (!visibleIds.has(e.target)) continue;
    const child = visibleNodes.find((n) => n.id === e.target);
    if (!child) continue;
    const key = `${e.source}::${e.connector_name ?? 'unknown'}`;
    const arr = childrenBySource.get(key) ?? [];
    arr.push(child);
    childrenBySource.set(key, arr);
  }

  const clusters = new Map<string, ClusterInfo>();
  const hiddenByCluster = new Set<string>();
  for (const [key, children] of childrenBySource.entries()) {
    if (children.length < CLUSTER_THRESHOLD) continue;
    if (opts.expandedClusters.has(key)) continue;
    const [sourceId, connectorName] = key.split('::');
    const info: ClusterInfo = {
      key,
      connectorName: connectorName || 'inconnu',
      sourceDatapointId: sourceId,
      count: children.length,
      childIds: children.map((c) => c.id),
      representativeType: children[0].data_type ?? 'other',
    };
    clusters.set(key, info);
    for (const c of children) hiddenByCluster.add(c.id);
  }

  // Dagre graph
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'TB', nodesep: NODE_SEP, ranksep: RANK_SEP, marginx: 60, marginy: 40 });
  g.setDefaultEdgeLabel(() => ({}));

  for (const n of visibleNodes) {
    if (n.kind === 'datapoint' && hiddenByCluster.has(n.id)) continue;
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const info of clusters.values()) {
    g.setNode(info.key, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }

  // Edges: pivot only, no `owns`
  const layoutEdges: Edge[] = [];

  for (const e of graph.edges) {
    if (e.kind !== 'pivot') continue;

    const sourceHidden = hiddenByCluster.has(e.source);
    const targetHidden = hiddenByCluster.has(e.target);

    if (targetHidden || sourceHidden) continue;
    if (!visibleIds.has(e.source) || !visibleIds.has(e.target)) continue;

    g.setEdge(e.source, e.target);

    layoutEdges.push({
      id: `e-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      animated: false,
      style: { stroke: 'var(--edge-pivot)', strokeWidth: 1.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--edge-pivot)', width: 14, height: 14 },
      data: { connectorName: e.connector_name },
    });
  }

  // We DO need synthetic edges from entity → seed datapoints, even though
  // we hide the kind='owns' ones, otherwise seeds float. So we add them
  // as faint background edges.
  for (const e of graph.edges) {
    if (e.kind !== 'owns') continue;
    if (!visibleIds.has(e.source) || !visibleIds.has(e.target)) continue;
    if (hiddenByCluster.has(e.target)) continue;
    g.setEdge(e.source, e.target);
    layoutEdges.push({
      id: `o-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      style: { stroke: 'var(--edge-owns)', strokeWidth: 1, opacity: 0.35 },
      markerEnd: undefined,
    });
  }

  // Synthetic cluster edges
  for (const info of clusters.values()) {
    g.setEdge(info.sourceDatapointId, info.key);
    layoutEdges.push({
      id: `c-${info.sourceDatapointId}-${info.key}`,
      source: info.sourceDatapointId,
      target: info.key,
      type: 'smoothstep',
      style: { stroke: 'var(--edge-cluster)', strokeWidth: 2, strokeDasharray: '6 4' },
      markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--edge-cluster)', width: 14, height: 14 },
    });
  }

  dagre.layout(g);

  const reactFlowNodes: Node[] = [];

  for (const n of visibleNodes) {
    if (n.kind !== 'entity') continue;
    const pos = g.node(n.id);
    if (!pos) continue;
    reactFlowNodes.push({
      id: n.id,
      type: 'entity',
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
      data: { label: n.label, role: 'target' },
      draggable: true,
    });
  }

  for (const n of visibleNodes) {
    if (n.kind !== 'datapoint') continue;
    if (hiddenByCluster.has(n.id)) continue;
    const pos = g.node(n.id);
    if (!pos) continue;
    reactFlowNodes.push({
      id: n.id,
      type: 'datapoint',
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
      data: {
        label: n.label,
        dataType: n.data_type!,
        status: n.status!,
        confidence: n.confidence ?? null,
        pivoting: opts.pivotingIds.has(n.id),
        depth: n.pivot_depth,
        onOpen: () => opts.onOpenDatapoint(n.id),
        selected: opts.selectedId === n.id,
      },
      draggable: true,
    });
  }

  for (const info of clusters.values()) {
    const pos = g.node(info.key);
    if (!pos) continue;
    reactFlowNodes.push({
      id: info.key,
      type: 'cluster',
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
      data: {
        count: info.count,
        connectorName: info.connectorName,
        dataType: info.representativeType,
        onToggle: () => opts.onToggleCluster(info.key),
      },
      draggable: true,
    });
  }

  return {
    nodes: reactFlowNodes,
    edges: layoutEdges,
    clusters,
    hiddenClusterIds: hiddenByCluster,
  };
}
