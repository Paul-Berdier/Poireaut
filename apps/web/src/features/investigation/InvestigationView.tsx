import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from 'reactflow';
import 'reactflow/dist/style.css';

import {
  createEntity,
  getGraph,
  getInvestigation,
  listDatapoints,
  listEntities,
  openInvestigationSocket,
  type DataPoint,
  type Entity,
  type Graph,
  type Investigation,
  type WsEvent,
} from '../../api';
import { useRoute } from '../../router';
import { nodeTypes } from './nodes';
import { layoutGraph } from './layout';
import DatapointPanel from './DatapointPanel';
import QuickAddBar from './QuickAddBar';

type WsStatus = 'connecting' | 'open' | 'closed';

interface Props {
  investigationId: string;
}

export default function InvestigationView({ investigationId }: Props) {
  const [, navigate] = useRoute();
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [entity, setEntity] = useState<Entity | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedDp, setSelectedDp] = useState<DataPoint | null>(null);
  const [wsStatus, setWsStatus] = useState<WsStatus>('connecting');
  const [err, setErr] = useState<string | null>(null);
  const toastTimerRef = useRef<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToast(msg);
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 4000);
  };

  // ─── Initial bootstrap: load investigation + ensure one entity exists ──

  const bootstrap = useCallback(async () => {
    setErr(null);
    try {
      const inv = await getInvestigation(investigationId);
      setInvestigation(inv);

      let entities = await listEntities(investigationId);
      if (entities.length === 0) {
        // Auto-create the target entity with the investigation's title.
        const e = await createEntity(investigationId, inv.title, 'target');
        entities = [e];
      }
      setEntity(entities[0]);

      const g = await getGraph(investigationId);
      setGraph(g);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [investigationId]);

  useEffect(() => { bootstrap(); }, [bootstrap]);

  // ─── WebSocket: refresh graph on datapoint.created events ──

  const refreshGraph = useCallback(async () => {
    try { setGraph(await getGraph(investigationId)); }
    catch { /* ignore */ }
  }, [investigationId]);

  useEffect(() => {
    const close = openInvestigationSocket(
      investigationId,
      (ev: WsEvent) => {
        if (ev.type === 'datapoint.created') {
          showToast(`Nouveau pivot : ${String(ev.connector ?? '…')}`);
          refreshGraph();
        }
      },
      setWsStatus,
    );
    return close;
  }, [investigationId, refreshGraph]);

  // ─── React Flow nodes/edges derived from graph + selection ──

  const openDatapoint = useCallback(async (id: string) => {
    setSelectedId(id);
    try {
      // Fetch the full datapoint (graph view has only a trimmed projection)
      if (!entity) return;
      const dps = await listDatapoints(entity.id);
      const dp = dps.find((d) => d.id === id) ?? null;
      setSelectedDp(dp);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [entity]);

  const { nodes: computedNodes, edges: computedEdges } = useMemo(
    () => graph
      ? layoutGraph(graph, openDatapoint, selectedId)
      : { nodes: [] as Node[], edges: [] as Edge[] },
    [graph, openDatapoint, selectedId],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(computedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(computedEdges);

  useEffect(() => { setNodes(computedNodes); }, [computedNodes, setNodes]);
  useEffect(() => { setEdges(computedEdges); }, [computedEdges, setEdges]);

  const onPaneClick = () => { setSelectedId(null); setSelectedDp(null); };

  const handlePanelChange = async () => {
    await refreshGraph();
    if (selectedId) await openDatapoint(selectedId);
  };

  // ─── Rendering ──

  if (err && !investigation) {
    return (
      <main className="panel">
        <div className="panel__card">
          <div className="panel__eyebrow">Erreur</div>
          <h2 className="panel__title">Enquête introuvable</h2>
          <p className="lede">{err}</p>
          <button
            className="btn btn--primary"
            onClick={() => navigate({ name: 'dashboard' })}
          >
            Retour aux enquêtes
          </button>
        </div>
      </main>
    );
  }

  if (!investigation || !entity) {
    return <main className="panel"><div className="panel__empty">Chargement…</div></main>;
  }

  const hasDatapoints = (graph?.nodes.filter((n) => n.kind === 'datapoint').length ?? 0) > 0;

  return (
    <main className="investigation">
      <header className="investigation__header">
        <div>
          <button
            className="investigation__back"
            onClick={() => navigate({ name: 'dashboard' })}
          >
            ← Toutes les enquêtes
          </button>
          <h2 className="investigation__title">{investigation.title}</h2>
          <div className="investigation__meta">
            <span>Cible : {entity.display_name}</span>
            <span>·</span>
            <span className={`ws-dot ws-dot--${wsStatus}`} />
            <span>
              {wsStatus === 'open' ? 'Flux live connecté'
                : wsStatus === 'connecting' ? 'Connexion…'
                  : 'Déconnecté'}
            </span>
          </div>
        </div>
        <QuickAddBar entityId={entity.id} onAdded={refreshGraph} />
      </header>

      <div className="investigation__body">
        <div className="investigation__canvas">
          {!hasDatapoints ? (
            <div className="investigation__empty">
              <div className="investigation__empty-title">Mr. Poireaut attend</div>
              <div className="investigation__empty-sub">
                Ajoutez le premier indice — email, pseudo, numéro — et pivotez
                depuis son nœud pour lancer les connecteurs.
              </div>
            </div>
          ) : (
            <ReactFlowProvider>
              <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onPaneClick={onPaneClick}
                fitView
                fitViewOptions={{ padding: 0.2, maxZoom: 1.2 }}
                minZoom={0.2}
                maxZoom={1.6}
                proOptions={{ hideAttribution: true }}
                nodesDraggable
                nodesConnectable={false}
                elementsSelectable
              >
                <Background
                  color="var(--gold)"
                  gap={24}
                  size={1.2}
                  style={{ opacity: 0.35 }}
                />
                <Controls
                  position="bottom-right"
                  showInteractive={false}
                  className="rf-controls"
                />
                <MiniMap
                  position="bottom-left"
                  pannable
                  zoomable
                  style={{
                    background: 'var(--cream-deep)',
                    border: '1px solid var(--gold)',
                    borderRadius: 8,
                  }}
                  maskColor="rgba(45,74,43,0.08)"
                  nodeColor={(n) =>
                    n.type === 'entity' ? 'var(--forest)' : 'var(--leaf)'
                  }
                />
              </ReactFlow>
            </ReactFlowProvider>
          )}
        </div>

        {selectedDp && (
          <DatapointPanel
            datapoint={selectedDp}
            onChange={handlePanelChange}
            onClose={() => { setSelectedId(null); setSelectedDp(null); }}
          />
        )}
      </div>

      {toast && <div className="toast">{toast}</div>}
    </main>
  );
}
