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
  type GraphNode,
  type Investigation,
  type WsEvent,
} from '../../api';
import { useRoute } from '../../router';
import { nodeTypes } from './nodes';
import { layoutGraph } from './layout';
import DatapointPanel from './DatapointPanel';
import QuickAddBar from './QuickAddBar';
import FicheView from './FicheView';

type WsStatus = 'connecting' | 'open' | 'closed';
type ViewTab = 'web' | 'fiche';
type GraphFilter = 'all' | 'validated' | 'unverified';

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

  // Tabs + filter + cluster expansion
  const [tab, setTab] = useState<ViewTab>('web');
  const [filter, setFilter] = useState<GraphFilter>('all');
  const [expandedClusters, setExpandedClusters] = useState<Set<string>>(new Set());

  // Pivots currently running, keyed by source datapoint id.
  // WS events pivot.started / pivot.finished toggle this set.
  const [pivotingIds, setPivotingIds] = useState<Set<string>>(new Set());

  // Toast queue
  const [toast, setToast] = useState<string | null>(null);
  const toastTimerRef = useRef<number | null>(null);
  const showToast = useCallback((msg: string) => {
    setToast(msg);
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 4000);
  }, []);

  // ─── Bootstrap ────────────────────────────────────────────

  const bootstrap = useCallback(async () => {
    setErr(null);
    try {
      const inv = await getInvestigation(investigationId);
      setInvestigation(inv);
      let entities = await listEntities(investigationId);
      if (entities.length === 0) {
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

  const refreshGraph = useCallback(async () => {
    try { setGraph(await getGraph(investigationId)); }
    catch { /* ignore */ }
  }, [investigationId]);

  // ─── WebSocket ───────────────────────────────────────────

  useEffect(() => {
    const close = openInvestigationSocket(
      investigationId,
      (ev: WsEvent) => {
        if (ev.type === 'pivot.started') {
          const id = String(ev.datapoint_id ?? '');
          if (id) {
            setPivotingIds((prev) => {
              const next = new Set(prev);
              next.add(id);
              return next;
            });
            showToast(`Pivot lancé (${(ev.connectors as string[] | undefined)?.length ?? '?'} connecteurs)`);
          }
        } else if (ev.type === 'pivot.finished') {
          const id = String(ev.datapoint_id ?? '');
          const n = Number(ev.findings_count ?? 0);
          setPivotingIds((prev) => {
            if (!prev.has(id)) return prev;
            const next = new Set(prev);
            next.delete(id);
            return next;
          });
          showToast(
            n > 0
              ? `Pivot terminé · ${n} nouveau${n > 1 ? 'x' : ''} résultat${n > 1 ? 's' : ''}`
              : 'Pivot terminé · aucun résultat',
          );
          refreshGraph();
        } else if (ev.type === 'datapoint.created') {
          // Incremental refresh — just re-fetch the graph. Cheaper than
          // reconciling locally and keeps things consistent.
          refreshGraph();
        }
      },
      setWsStatus,
    );
    return close;
  }, [investigationId, refreshGraph, showToast]);

  // ─── Selection & panel state ─────────────────────────────

  const openDatapoint = useCallback(async (id: string) => {
    setSelectedId(id);
    try {
      if (!entity) return;
      const dps = await listDatapoints(entity.id);
      const dp = dps.find((d) => d.id === id) ?? null;
      setSelectedDp(dp);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [entity]);

  const toggleCluster = useCallback((key: string) => {
    setExpandedClusters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }, []);

  // ─── Derived nodes/edges ─────────────────────────────────

  const graphFilter = useMemo(() => {
    if (filter === 'all') return undefined;
    return (n: GraphNode) => {
      if (n.kind !== 'datapoint') return true;
      if (filter === 'validated') return n.status === 'validated';
      if (filter === 'unverified') return n.status === 'unverified';
      return true;
    };
  }, [filter]);

  const layout = useMemo(
    () => graph
      ? layoutGraph(graph, {
          selectedId,
          pivotingIds,
          onOpenDatapoint: openDatapoint,
          onToggleCluster: toggleCluster,
          expandedClusters,
          filter: graphFilter,
        })
      : { nodes: [] as Node[], edges: [] as Edge[], clusters: new Map(), hiddenClusterIds: new Set() },
    [graph, selectedId, pivotingIds, openDatapoint, toggleCluster, expandedClusters, graphFilter],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(layout.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layout.edges);
  useEffect(() => { setNodes(layout.nodes); }, [layout.nodes, setNodes]);
  useEffect(() => { setEdges(layout.edges); }, [layout.edges, setEdges]);

  const onPaneClick = () => { setSelectedId(null); setSelectedDp(null); };
  const handlePanelChange = async () => {
    await refreshGraph();
    if (selectedId) await openDatapoint(selectedId);
  };

  // ─── Render ──────────────────────────────────────────────

  if (err && !investigation) {
    return (
      <main className="panel">
        <div className="panel__card">
          <div className="panel__eyebrow">Erreur</div>
          <h2 className="panel__title">Enquête introuvable</h2>
          <p className="lede">{err}</p>
          <button className="btn btn--primary" onClick={() => navigate({ name: 'dashboard' })}>
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
  const pivotCount = pivotingIds.size;

  return (
    <main className="investigation">
      <header className="investigation__header">
        <div className="investigation__header-left">
          <button className="investigation__back" onClick={() => navigate({ name: 'dashboard' })}>
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
            {pivotCount > 0 && (
              <>
                <span>·</span>
                <span className="pivot-badge">
                  <span className="pivot-badge__spin" /> {pivotCount} pivot{pivotCount > 1 ? 's' : ''} en cours
                </span>
              </>
            )}
          </div>
        </div>

        <div className="investigation__tabs" role="tablist">
          <button
            role="tab"
            aria-selected={tab === 'web'}
            className={`tab ${tab === 'web' ? 'tab--active' : ''}`}
            onClick={() => setTab('web')}
          >
            Toile
          </button>
          <button
            role="tab"
            aria-selected={tab === 'fiche'}
            className={`tab ${tab === 'fiche' ? 'tab--active' : ''}`}
            onClick={() => setTab('fiche')}
          >
            Fiche identité
          </button>
        </div>
      </header>

      {tab === 'web' ? (
        <>
          <div className="investigation__toolbar">
            <QuickAddBar entityId={entity.id} onAdded={refreshGraph} />
            <div className="filter-group" role="radiogroup" aria-label="Filtre toile">
              <button
                role="radio" aria-checked={filter === 'all'}
                className={`filter ${filter === 'all' ? 'filter--active' : ''}`}
                onClick={() => setFilter('all')}
              >
                Tout
              </button>
              <button
                role="radio" aria-checked={filter === 'validated'}
                className={`filter ${filter === 'validated' ? 'filter--active' : ''}`}
                onClick={() => setFilter('validated')}
              >
                Validés
              </button>
              <button
                role="radio" aria-checked={filter === 'unverified'}
                className={`filter ${filter === 'unverified' ? 'filter--active' : ''}`}
                onClick={() => setFilter('unverified')}
              >
                En attente
              </button>
            </div>
          </div>

          <div className="investigation__body">
            <div className="investigation__canvas">
              {!hasDatapoints ? (
                <div className="investigation__empty">
                  <div className="investigation__empty-title">Mr. Poireaut attend</div>
                  <div className="investigation__empty-sub">
                    Ajoutez le premier indice — email, pseudo, numéro — et pivotez
                    depuis son nœud pour lancer les connecteurs. Ou passez à
                    l'onglet <b>Fiche identité</b> pour saisir des données à la main.
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
                    <Background color="var(--gold)" gap={24} size={1.2} style={{ opacity: 0.35 }} />
                    <Controls position="bottom-right" showInteractive={false} className="rf-controls" />
                    <MiniMap
                      position="bottom-left"
                      pannable zoomable
                      style={{
                        background: 'var(--cream-deep)',
                        border: '1px solid var(--gold)',
                        borderRadius: 8,
                      }}
                      maskColor="rgba(45,74,43,0.08)"
                      nodeColor={(n) =>
                        n.type === 'entity' ? 'var(--forest)'
                          : n.type === 'cluster' ? 'var(--gold)'
                            : 'var(--leaf)'
                      }
                    />
                  </ReactFlow>
                </ReactFlowProvider>
              )}
            </div>

            {selectedDp && (
              <DatapointPanel
                datapoint={selectedDp}
                isPivoting={pivotingIds.has(selectedDp.id)}
                onChange={handlePanelChange}
                onClose={() => { setSelectedId(null); setSelectedDp(null); }}
              />
            )}
          </div>
        </>
      ) : (
        <FicheView
          investigationId={investigationId}
          entityId={entity.id}
          onDataChange={refreshGraph}
        />
      )}

      {toast && <div className="toast">{toast}</div>}
    </main>
  );
}
