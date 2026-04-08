import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { useWorkspace } from '../store/workspace';
import WorkflowShell from '../components/WorkflowShell';
import GraphPanel from '../components/GraphPanel';
import Step3Simulation from '../components/steps/Step3Simulation';
import * as simulationApi from '../api/simulation';
import type { GraphData } from '../types';
import * as graphApi from '../api/graph';

export default function SimulationRunView() {
  const { simulationId } = useParams<{ simulationId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const {
    setCurrentStep,
    setSimulationId,
    setProjectId,
    setReportId,
    setGraphId,
    graphId,
  } = useWorkspace();

  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [baselineGraphData, setBaselineGraphData] = useState<GraphData | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [projectData, setProjectData] = useState<Record<string, unknown> | null>(null);
  const [systemLogs, setSystemLogs] = useState<string[]>([]);
  const [runnerStatus, setRunnerStatus] = useState<'idle' | 'starting' | 'running' | 'completed' | 'failed' | 'stopped'>('idle');
  const previousSimulatingRef = useRef(false);
  const graphRefreshInFlightRef = useRef(false);

  const appendSystemLog = useCallback((line: string) => {
    setSystemLogs((prev) => [...prev, line].slice(-200));
  }, []);

  const isSimulating = runnerStatus === 'running' || runnerStatus === 'starting';

  const createEmptyGraphData = useCallback((): GraphData => ({
    nodes: [],
    edges: [],
    metadata: {
      node_count: 0,
      edge_count: 0,
      entity_types: [],
      edge_types: [],
    },
  }), []);

  const getEdgeKey = useCallback((edge: GraphData['edges'][number]) => (
    edge.uuid || [
      edge.source_uuid ?? '',
      edge.target_uuid ?? '',
      edge.relation_type ?? '',
      edge.fact ?? '',
    ].join('::')
  ), []);

  const graphSnapshotKey = useCallback((graph: GraphData | null): string => {
    if (!graph) return 'empty';
    const nodeIds = graph.nodes.map((node) => node.uuid).sort().join('|');
    const edgeIds = graph.edges.map((edge) => getEdgeKey(edge)).sort().join('|');
    return `${graph.nodes.length}:${graph.edges.length}:${nodeIds}:${edgeIds}`;
  }, [getEdgeKey]);

  const buildSimulationDeltaGraph = useCallback((
    baseline: GraphData | null,
    current: GraphData,
  ): GraphData => {
    if (!baseline) {
      return current;
    }

    const baseNodeIds = new Set(baseline.nodes.map((node) => node.uuid));
    const baseEdgeKeys = new Set(baseline.edges.map(getEdgeKey));
    const currentNodeMap = new Map(current.nodes.map((node) => [node.uuid, node]));
    const includedNodeIds = new Set<string>();

    const deltaEdges = current.edges.filter((edge) => {
      const isNewEdge = !baseEdgeKeys.has(getEdgeKey(edge));
      if (isNewEdge) {
        includedNodeIds.add(edge.source_uuid);
        includedNodeIds.add(edge.target_uuid);
      }
      return isNewEdge;
    });

    current.nodes.forEach((node) => {
      if (!baseNodeIds.has(node.uuid)) {
        includedNodeIds.add(node.uuid);
      }
    });

    const deltaNodes = Array.from(includedNodeIds)
      .map((nodeId) => currentNodeMap.get(nodeId))
      .filter((node): node is NonNullable<typeof node> => Boolean(node));

    return {
      nodes: deltaNodes,
      edges: deltaEdges,
      metadata: {
        node_count: deltaNodes.length,
        edge_count: deltaEdges.length,
        entity_types: [...new Set(deltaNodes.map((node) => node.label))].sort(),
        edge_types: [...new Set(deltaEdges.map((edge) => edge.relation_type))].sort(),
      },
    };
  }, [getEdgeKey]);

  const graphPanelEmptyState = useMemo(() => ({
    title: isSimulating
      ? 'Simulation-added graph changes will appear here'
      : 'Simulation graph changes will appear here',
    hint: 'Existing project nodes stay hidden while this view shows only new nodes and relationships created during the run.',
  }), [isSimulating]);
  const autoStartEnabled = !graphLoading && (!graphId || baselineGraphData !== null);
  const requestedMaxRounds = useMemo(() => {
    const value = new URLSearchParams(location.search).get('rounds');
    if (!value) return undefined;
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
  }, [location.search]);
  const baselineStorageKey = useMemo(
    () => (simulationId ? `simulation-baseline:v2:${simulationId}` : null),
    [simulationId],
  );

  const restoreBaselineGraph = useCallback((): GraphData | null => {
    if (!baselineStorageKey) return null;
    try {
      const raw = window.sessionStorage.getItem(baselineStorageKey);
      if (!raw) return null;
      const parsed = JSON.parse(raw) as GraphData;
      if (!parsed || !Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges)) {
        return null;
      }
      return parsed;
    } catch {
      return null;
    }
  }, [baselineStorageKey]);

  const persistBaselineGraph = useCallback((data: GraphData) => {
    if (!baselineStorageKey) return;
    try {
      window.sessionStorage.setItem(baselineStorageKey, JSON.stringify(data));
    } catch {
      // Ignore storage errors; baseline persistence is a best-effort enhancement.
    }
  }, [baselineStorageKey]);

  /* -- Sync workspace step --------------------------------- */

  useEffect(() => {
    setCurrentStep(3);
    if (simulationId) setSimulationId(simulationId);
  }, [simulationId, setCurrentStep, setSimulationId]);

  useEffect(() => {
    if (!simulationId) return;

    let cancelled = false;

    async function hydrateWorkflow() {
      try {
        const entry = await simulationApi.findSimulationHistoryEntry({ simulationId });
        if (cancelled || !entry) return;

        if (entry.project_id) {
          setProjectId(entry.project_id);

          if (!graphId) {
            const project = await graphApi.getProject(entry.project_id);
            if (cancelled) return;

            if (project.graph_id) {
              setGraphId(project.graph_id);
            }
          }
        }

        setReportId(entry.report_id ?? null);
      } catch (err) {
        if (!cancelled) {
          appendSystemLog(`[warn] Could not hydrate workflow context: ${err}`);
        }
      }
    }

    hydrateWorkflow();
    return () => { cancelled = true; };
  }, [appendSystemLog, graphId, setGraphId, setProjectId, setReportId, simulationId]);

  /* -- Load baseline graph if available -------------------- */

  useEffect(() => {
    if (!graphId) return;
    let cancelled = false;
    setGraphLoading(true);
    setBaselineGraphData(null);
    setGraphData(null);

    const restored = restoreBaselineGraph();
    if (restored) {
      setBaselineGraphData(restored);
      setGraphData(createEmptyGraphData());
      appendSystemLog(
        `[info] Restored baseline graph snapshot (${restored.metadata?.node_count ?? restored.nodes.length} nodes hidden until the simulation adds changes)`,
      );
      setGraphLoading(false);
      return () => { cancelled = true; };
    }

    graphApi.getGraphData(graphId, { baseline: true })
      .then((data) => {
        if (cancelled) return;
        const normalized = data as GraphData;
        setBaselineGraphData(normalized);
        persistBaselineGraph(normalized);
        setGraphData(createEmptyGraphData());
        appendSystemLog(
          `[info] Baseline graph loaded (${normalized.metadata?.node_count ?? normalized.nodes.length} nodes hidden until the simulation adds changes)`,
        );
      })
      .catch((err) => {
        console.error('[SimulationRunView] baseline graph load failed', err);
        if (!cancelled) {
          setBaselineGraphData(createEmptyGraphData());
          setGraphData(createEmptyGraphData());
          appendSystemLog(`[warn] Could not load baseline graph: ${err}`);
        }
      })
      .finally(() => {
        if (!cancelled) setGraphLoading(false);
      });

    return () => { cancelled = true; };
  }, [appendSystemLog, createEmptyGraphData, graphId, persistBaselineGraph, restoreBaselineGraph]);

  const refreshGraph = useCallback(async () => {
    if (!graphId || graphRefreshInFlightRef.current) return;

    graphRefreshInFlightRef.current = true;
    try {
      const current = await graphApi.getGraphData(graphId);
      const normalized = current as GraphData;
      const nextGraph = buildSimulationDeltaGraph(baselineGraphData, normalized);
      const nextKey = graphSnapshotKey(nextGraph);
      setGraphData((previous) => (
        graphSnapshotKey(previous) === nextKey ? previous : nextGraph
      ));
    } catch (err) {
      console.error('[SimulationRunView] graph refresh failed', err);
      appendSystemLog(`[warn] Could not refresh simulation graph delta: ${err}`);
    } finally {
      graphRefreshInFlightRef.current = false;
    }
  }, [appendSystemLog, baselineGraphData, buildSimulationDeltaGraph, graphId, graphSnapshotKey]);

  /* -- Load simulation metadata (for projectData) ---------- */

  useEffect(() => {
    if (!simulationId) return;
    let cancelled = false;

    simulationApi.getConfig(simulationId)
      .then((cfg) => {
        if (!cancelled) setProjectData(cfg);
      })
      .catch((err) => {
        if (!cancelled) {
          appendSystemLog(`[warn] Could not load config: ${err}`);
        }
      });

    return () => { cancelled = true; };
  }, [appendSystemLog, simulationId]);

  /* -- Poll run status ------------------------------------- */

  useEffect(() => {
    if (!simulationId) return;
    let cancelled = false;

    const normalizeRunnerStatus = (status: unknown) => {
      switch (status) {
        case 'starting':
        case 'running':
        case 'completed':
        case 'failed':
        case 'stopped':
          return status;
        default:
          return 'idle';
      }
    };

    const poll = async () => {
      try {
        const status = await simulationApi.getRunStatus(simulationId);
        if (cancelled) return;
        setRunnerStatus(normalizeRunnerStatus(status.runner_status));
      } catch (err) {
        if (!cancelled) {
          appendSystemLog(`[warn] Could not load run status: ${err}`);
        }
      }
    };

    poll();
    const intervalId = window.setInterval(poll, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [appendSystemLog, simulationId]);

  /* -- Refresh graph delta while simulation is running ----- */

  useEffect(() => {
    if (!graphId) return;

    if (isSimulating) {
      appendSystemLog('[info] Starting live graph refresh (5s)');
      refreshGraph();
      const intervalId = window.setInterval(() => {
        void refreshGraph();
      }, 5000);
      previousSimulatingRef.current = true;
      return () => {
        window.clearInterval(intervalId);
      };
    }

    if (previousSimulatingRef.current) {
      appendSystemLog('[info] Finalizing simulation graph delta');
      void refreshGraph();
    }
    previousSimulatingRef.current = false;
  }, [appendSystemLog, graphId, isSimulating, refreshGraph]);

  useEffect(() => {
    if (!graphId || !baselineGraphData || !isSimulating) return;
    void refreshGraph();
  }, [baselineGraphData, graphId, isSimulating, refreshGraph]);

  useEffect(() => {
    if (!graphId || !baselineGraphData) return;
    if (!['running', 'starting', 'completed', 'failed', 'stopped'].includes(runnerStatus)) return;
    void refreshGraph();
  }, [baselineGraphData, graphId, refreshGraph, runnerStatus]);

  /* -- Navigate to report on generation -------------------- */

  const handleGenerateReport = useCallback(
    (reportId: string) => {
      navigate(`/report/${reportId}`);
    },
    [navigate],
  );

  if (!simulationId) {
    return (
      <WorkflowShell>
        <div style={{ padding: '2rem', color: 'var(--text-muted)' }}>
          Missing simulation ID.
        </div>
      </WorkflowShell>
    );
  }

  return (
    <WorkflowShell
      graphPanel={
        <GraphPanel
          graphData={graphData}
          loading={graphLoading}
          emptyTitle={graphPanelEmptyState.title}
          emptyHint={graphPanelEmptyState.hint}
        />
      }
    >
      <Step3Simulation
        simulationId={simulationId}
        maxRounds={requestedMaxRounds}
        projectData={projectData}
        systemLogs={systemLogs}
        onGenerateReport={handleGenerateReport}
        autoStartEnabled={autoStartEnabled}
      />
    </WorkflowShell>
  );
}
