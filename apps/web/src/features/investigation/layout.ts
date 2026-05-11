/**
 * Radial graph layout.
 *
 * The entity sits at the center of the canvas. Datapoints orbit around
 * it in concentric rings based on `pivot_depth`:
 *   - depth 0 (seeds, manually added)     → ring 1
 *   - depth 1 (1st auto-pivot)            → ring 2
 *   - depth 2 (2nd auto-pivot)            → ring 3
 *   - ...
 *
 * Within each ring, nodes are placed at evenly-spaced angles. Children
 * inherit their parent's angle ±a small fan, so chains visually radiate
 * outward from the seed they came from.
 *
 * Clustering:
 *   When a parent has CLUSTER_THRESHOLD+ children of the same type, the
 *   children are replaced by a single cluster node sitting at the
 *   parent's angle on the next ring out. Clicking the cluster expands it.
 *
 * Visual encoding (handled in nodes.tsx, layout just sets `data.depth`):
 *   - background color   ← data_type (email red, account blue, photo
 *                          violet, …)
 *   - border color/style ← pivot_depth (depth 0 forest, 1 light green,
 *                          2 gold, 3 orange, …)
 */
import type { Edge, Node } from 'reactflow';
import { MarkerType } from 'reactflow';
import type { Graph, GraphNode } from '../../api';

// ── Tunables ────────────────────────────────────────
const RING_BASE_RADIUS = 220;       // first ring radius from center
const RING_GAP = 200;                // distance between concentric rings
const MIN_ANGLE_SEPARATION = 0.25;  // radians — tightest angle between siblings
const CLUSTER_THRESHOLD = 3;
const FAN_PER_CHILD = 0.12;          // angle a parent fans out per child

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

interface TreeNode {
  id: string;
  parentId: string | null;
  depth: number;
  graphNode: GraphNode;
  children: TreeNode[];
}

// ── Main entry point ────────────────────────────────

export function layoutGraph(
  graph: Graph,
  opts: LayoutOptions,
): LayoutResult {
  const { filter } = opts;

  // 1. Filter datapoint nodes by predicate
  const visibleNodes = graph.nodes.filter((n) => {
    if (n.kind !== 'datapoint') return true;
    return !filter || filter(n);
  });
  const visibleIds = new Set(visibleNodes.map((n) => n.id));

  // 2. Build parent index from pivot edges
  const parentOf = new Map<string, string>();
  for (const e of graph.edges) {
    if (e.kind === 'pivot' && visibleIds.has(e.source) && visibleIds.has(e.target)) {
      parentOf.set(e.target, e.source);
    }
  }

  // 3. Detect clusters (parent + connector → siblings)
  const childrenByParentConnector = new Map<string, GraphNode[]>();
  for (const e of graph.edges) {
    if (e.kind !== 'pivot') continue;
    if (!visibleIds.has(e.target)) continue;
    const child = visibleNodes.find((n) => n.id === e.target);
    if (!child) continue;
    const key = `${e.source}::${e.connector_name ?? 'unknown'}`;
    const arr = childrenByParentConnector.get(key) ?? [];
    arr.push(child);
    childrenByParentConnector.set(key, arr);
  }

  const clusters = new Map<string, ClusterInfo>();
  const hiddenByCluster = new Set<string>();
  for (const [key, children] of childrenByParentConnector.entries()) {
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

  // 4. Find the entity node (root). If multiple, take the first.
  const entityNode = visibleNodes.find((n) => n.kind === 'entity');
  if (!entityNode) {
    // No entity → nothing to lay out radially. Just stack everything.
    return _fallbackStackLayout(visibleNodes, hiddenByCluster, opts);
  }

  // 5. Build a tree rooted at the entity.
  //    Seeds (depth=0 datapoints) are direct children of the entity via
  //    'owns' edges. Subsequent auto-pivots are children of their source dp.
  const tree = _buildTree(
    entityNode, visibleNodes, parentOf, hiddenByCluster, clusters,
  );

  // 6. Lay out in concentric rings around (0, 0)
  const positions = new Map<string, { x: number; y: number }>();
  positions.set(entityNode.id, { x: 0, y: 0 });
  _placeChildrenRadially(tree, 0, 2 * Math.PI, RING_BASE_RADIUS, positions);

  // Cluster nodes get a position derived from their parent (slightly outward)
  for (const info of clusters.values()) {
    if (positions.has(info.key)) continue;
    const parentPos = positions.get(info.sourceDatapointId);
    if (!parentPos) continue;
    // Push the cluster outward from the center along the parent's bearing.
    const dist = Math.hypot(parentPos.x, parentPos.y);
    if (dist < 1) {
      // Parent is the entity — drop the cluster on ring 1
      positions.set(info.key, { x: RING_BASE_RADIUS, y: 0 });
    } else {
      const ux = parentPos.x / dist;
      const uy = parentPos.y / dist;
      positions.set(info.key, {
        x: parentPos.x + ux * RING_GAP,
        y: parentPos.y + uy * RING_GAP,
      });
    }
  }

  // 7. Build the React Flow node and edge arrays
  const reactFlowNodes: Node[] = [];
  const NODE_WIDTH = 240;
  const NODE_HEIGHT = 70;

  for (const n of visibleNodes) {
    if (n.kind === 'entity') {
      reactFlowNodes.push({
        id: n.id,
        type: 'entity',
        position: { x: -NODE_WIDTH / 2, y: -NODE_HEIGHT / 2 },
        data: { label: n.label, role: 'target' },
        draggable: true,
      });
      continue;
    }
    if (hiddenByCluster.has(n.id)) continue;
    const pos = positions.get(n.id);
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
    const pos = positions.get(info.key);
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

  // Edges
  const layoutEdges: Edge[] = [];
  for (const e of graph.edges) {
    if (!visibleIds.has(e.source) || !visibleIds.has(e.target)) continue;
    if (hiddenByCluster.has(e.target)) continue;
    if (hiddenByCluster.has(e.source)) continue;

    if (e.kind === 'pivot') {
      layoutEdges.push({
        id: `e-${e.source}-${e.target}`,
        source: e.source,
        target: e.target,
        type: 'straight',     // radial layout: straight lines look cleanest
        style: { stroke: 'var(--edge-pivot)', strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--edge-pivot)', width: 12, height: 12 },
      });
    } else if (e.kind === 'owns') {
      // Subtle "owns" edge from entity to seed datapoints
      layoutEdges.push({
        id: `o-${e.source}-${e.target}`,
        source: e.source,
        target: e.target,
        type: 'straight',
        style: { stroke: 'var(--edge-owns)', strokeWidth: 1, opacity: 0.4 },
      });
    }
  }

  // Synthetic edges to cluster nodes
  for (const info of clusters.values()) {
    layoutEdges.push({
      id: `c-${info.sourceDatapointId}-${info.key}`,
      source: info.sourceDatapointId,
      target: info.key,
      type: 'straight',
      style: { stroke: 'var(--edge-cluster)', strokeWidth: 2, strokeDasharray: '6 4' },
      markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--edge-cluster)', width: 12, height: 12 },
    });
  }

  return {
    nodes: reactFlowNodes,
    edges: layoutEdges,
    clusters,
    hiddenClusterIds: hiddenByCluster,
  };
}


// ── Internals ───────────────────────────────────────

function _buildTree(
  entity: GraphNode,
  allNodes: GraphNode[],
  parentOf: Map<string, string>,
  hiddenByCluster: Set<string>,
  clusters: Map<string, ClusterInfo>,
): TreeNode {
  // Datapoints whose parent is in `parentOf` get attached there.
  // Datapoints with no parent (seeds typed manually) attach to the entity.
  const nodeMap = new Map<string, TreeNode>();
  nodeMap.set(entity.id, {
    id: entity.id, parentId: null, depth: -1, graphNode: entity, children: [],
  });

  for (const n of allNodes) {
    if (n.kind === 'entity') continue;
    if (hiddenByCluster.has(n.id)) continue;
    const parentId = parentOf.get(n.id) ?? entity.id;
    const t: TreeNode = {
      id: n.id, parentId, depth: 0, graphNode: n, children: [],
    };
    nodeMap.set(n.id, t);
  }
  // Cluster nodes attach to their parent dp
  for (const info of clusters.values()) {
    const t: TreeNode = {
      id: info.key, parentId: info.sourceDatapointId, depth: 0,
      graphNode: {
        id: info.key, kind: 'datapoint', label: `cluster`,
        data_type: info.representativeType as any,
      },
      children: [],
    };
    nodeMap.set(info.key, t);
  }

  // Wire children
  for (const t of nodeMap.values()) {
    if (t.parentId && nodeMap.has(t.parentId)) {
      nodeMap.get(t.parentId)!.children.push(t);
    }
  }

  // Compute depth via BFS from root
  const root = nodeMap.get(entity.id)!;
  const queue: TreeNode[] = [root];
  root.depth = 0;
  while (queue.length > 0) {
    const cur = queue.shift()!;
    for (const c of cur.children) {
      c.depth = cur.depth + 1;
      queue.push(c);
    }
  }

  return root;
}

function _placeChildrenRadially(
  parent: TreeNode,
  startAngle: number,
  arcWidth: number,
  ringRadius: number,
  positions: Map<string, { x: number; y: number }>,
): void {
  const children = parent.children;
  if (children.length === 0) return;

  // Compute angles. If we have plenty of arc, space evenly with margins.
  // If tight, fall back to MIN_ANGLE_SEPARATION.
  let step = arcWidth / children.length;
  if (step < MIN_ANGLE_SEPARATION) step = MIN_ANGLE_SEPARATION;

  // Center the kids in the arc
  const totalUsed = step * (children.length - 1);
  const angleOffset = startAngle + (arcWidth - totalUsed) / 2;

  children.forEach((child, idx) => {
    const angle = angleOffset + idx * step;
    positions.set(child.id, {
      x: Math.cos(angle) * ringRadius,
      y: Math.sin(angle) * ringRadius,
    });

    // Recurse: each child gets a fan based on how many descendants it has
    const childArc = Math.max(
      MIN_ANGLE_SEPARATION,
      Math.min(step, FAN_PER_CHILD * Math.max(child.children.length, 1)),
    );
    _placeChildrenRadially(
      child,
      angle - childArc / 2,
      childArc,
      ringRadius + RING_GAP,
      positions,
    );
  });
}

function _fallbackStackLayout(
  visibleNodes: GraphNode[],
  hiddenByCluster: Set<string>,
  opts: LayoutOptions,
): LayoutResult {
  const reactFlowNodes: Node[] = visibleNodes
    .filter((n) => !(n.kind === 'datapoint' && hiddenByCluster.has(n.id)))
    .map((n, idx) => ({
      id: n.id,
      type: n.kind === 'entity' ? 'entity' : 'datapoint',
      position: { x: 0, y: idx * 100 },
      data: n.kind === 'entity'
        ? { label: n.label, role: 'target' }
        : {
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
    }));
  return {
    nodes: reactFlowNodes,
    edges: [],
    clusters: new Map(),
    hiddenClusterIds: hiddenByCluster,
  };
}
