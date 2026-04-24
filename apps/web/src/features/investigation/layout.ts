/**
 * Simple deterministic graph layout.
 *
 * We roll our own instead of pulling in a heavy layout engine (dagre, elk…).
 * The shape of a Poireaut investigation is a tree rooted at the entity:
 *   entity → seed datapoints → their children → …
 *
 * We place children on an arc below their parent, with spacing growing with
 * the number of siblings. It's not perfect but it's predictable and cheap,
 * and React Flow lets the user drag nodes around freely afterwards.
 */
import type { Graph } from '../../api';
import type { Edge, Node } from 'reactflow';

const ENTITY_Y = 0;
const FIRST_ROW_Y = 180;
const ROW_SPACING = 170;
const MIN_H_SPACING = 210;

interface Layout {
  nodes: Node[];
  edges: Edge[];
}

export function layoutGraph(
  graph: Graph,
  onOpenDatapoint: (id: string) => void,
  selectedId: string | null,
): Layout {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  // children[parentId] = [childId, …] following 'pivot' edges
  const children = new Map<string, string[]>();
  // parent[childId] = parentId
  const parent = new Map<string, string>();
  // ownership[entityId] = [datapointId, …] following 'owns' edges
  const ownership = new Map<string, string[]>();

  for (const e of graph.edges) {
    if (e.kind === 'pivot') {
      (children.get(e.source) ?? children.set(e.source, []).get(e.source)!).push(e.target);
      parent.set(e.target, e.source);
    } else if (e.kind === 'owns') {
      (ownership.get(e.source) ?? ownership.set(e.source, []).get(e.source)!).push(e.target);
    }
  }

  // Find the "seed" datapoints — those with no source_datapoint parent.
  const seeds: string[] = [];
  for (const n of graph.nodes) {
    if (n.kind === 'datapoint' && !parent.has(n.id)) seeds.push(n.id);
  }

  const positions = new Map<string, { x: number; y: number }>();

  // Place entities in a row at y=0
  const entities = graph.nodes.filter((n) => n.kind === 'entity');
  entities.forEach((e, idx) => {
    const offset = (idx - (entities.length - 1) / 2) * 400;
    positions.set(e.id, { x: offset, y: ENTITY_Y });
  });

  // Place seeds in a row below the (only) entity
  const spread = Math.max(1, seeds.length);
  seeds.forEach((id, idx) => {
    const x = (idx - (spread - 1) / 2) * MIN_H_SPACING;
    positions.set(id, { x, y: FIRST_ROW_Y });
  });

  // BFS-place remaining datapoints row by row
  const queue: Array<{ id: string; depth: number }> =
    seeds.map((id) => ({ id, depth: 1 }));
  let head = 0;
  while (head < queue.length) {
    const { id: parentId, depth } = queue[head++];
    const kids = children.get(parentId) ?? [];
    if (kids.length === 0) continue;
    const parentPos = positions.get(parentId) ?? { x: 0, y: FIRST_ROW_Y };
    // Fan them out around the parent on the next row
    kids.forEach((kid, idx) => {
      const x = parentPos.x + (idx - (kids.length - 1) / 2) * MIN_H_SPACING;
      const y = FIRST_ROW_Y + depth * ROW_SPACING;
      positions.set(kid, { x, y });
      queue.push({ id: kid, depth: depth + 1 });
    });
  }

  // Build react-flow nodes
  const nodes: Node[] = graph.nodes.map((n) => {
    const pos = positions.get(n.id) ?? { x: 0, y: 0 };
    if (n.kind === 'entity') {
      return {
        id: n.id,
        type: 'entity',
        position: pos,
        data: { label: n.label, role: 'target' },
        draggable: true,
      };
    }
    return {
      id: n.id,
      type: 'datapoint',
      position: pos,
      data: {
        label: n.label,
        dataType: n.data_type!,
        status: n.status!,
        confidence: n.confidence,
        onOpen: () => onOpenDatapoint(n.id),
        selected: selectedId === n.id,
      },
      draggable: true,
    };
  });

  const edges: Edge[] = graph.edges
    // Hide entity→datapoint 'owns' edges. They clutter the graph and the
    // parent-child relationship is already visually obvious from placement.
    .filter((e) => {
      if (e.kind !== 'owns') return true;
      // keep the link from entity to seed datapoints only
      const tgt = byId.get(e.target);
      return !!tgt && !parent.has(tgt.id);
    })
    .map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      animated: false,
      label: e.kind === 'pivot' ? e.connector_name ?? undefined : undefined,
      style: {
        stroke: e.kind === 'pivot' ? 'var(--gold)' : 'rgba(45,74,43,0.35)',
        strokeWidth: e.kind === 'pivot' ? 1.5 : 1,
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
    }));

  return { nodes, edges };
}
