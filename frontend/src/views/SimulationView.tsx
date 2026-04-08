import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import * as graphApi from '../api/graph';
import { useWorkspace } from '../store/workspace';
import type { Project, GraphData } from '../types';
import WorkflowShell from '../components/WorkflowShell';
import GraphPanel from '../components/GraphPanel';
import Step2EnvSetup from '../components/steps/Step2EnvSetup';

type GraphDisplayMode = 'full' | 'focused';

export default function SimulationView() {
  const { simulationId } = useParams<{ simulationId: string }>();
  const navigate = useNavigate();
  const workspace = useWorkspace();

  const [projectData, setProjectData] = useState<Project | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphDisplayMode, setGraphDisplayMode] = useState<GraphDisplayMode>('full');
  const [logs, setLogs] = useState<string[]>([]);

  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const log = useCallback((msg: string) => {
    const ts = new Date().toLocaleTimeString();
    setLogs((prev) => [...prev, `[${ts}] ${msg}`]);
  }, []);

  const graphDataOpts = useCallback(
    (mode: GraphDisplayMode): { baseline: true; compact?: true } =>
      mode === 'focused' ? { baseline: true, compact: true } : { baseline: true },
    [],
  );

  /* -- Load project data for the simulation ----------------- */

  useEffect(() => {
    if (!simulationId) return;

    let cancelled = false;

    async function load() {
      try {
        workspace.setSimulationId(simulationId!);
        workspace.setCurrentStep(2);

        // Try to find the project_id for this simulation from history
        let pid = workspace.projectId;
        if (!pid) {
          try {
            const { getSimulationHistory } = await import('../api/simulation');
            const history = await getSimulationHistory();
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const match = (history as any[]).find((h: any) => h.simulation_id === simulationId);
            if (match?.project_id) {
              pid = match.project_id;
              workspace.setProjectId(pid!);
              workspace.setReportId(match.report_id ?? null);
            }
          } catch { /* non-critical */ }
        }

        if (pid) {
          log('Loading project data...');
          const proj = await graphApi.getProject(pid);
          if (cancelled) return;
          setProjectData(proj);

          if (proj.graph_id) {
            setGraphLoading(true);
            try {
              const gd = await graphApi.getGraphData(proj.graph_id, {
                ...graphDataOpts(graphDisplayMode),
              });
              if (!cancelled) {
                setGraphData(gd);
                workspace.setGraphId(proj.graph_id);
              }
            } catch (err) {
              log(`Graph load error: ${err instanceof Error ? err.message : String(err)}`);
            } finally {
              if (!cancelled) setGraphLoading(false);
            }
          }

          log(`Project loaded: ${proj.name}`);
        }
      } catch (err) {
        if (!cancelled) {
          log(`Error: ${err instanceof Error ? err.message : String(err)}`);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphDataOpts, graphDisplayMode, simulationId]);

  /* -- Callbacks -------------------------------------------- */

  const handleStartSimulation = useCallback(
    (maxRounds?: number) => {
      if (!simulationId) return;
      workspace.setCurrentStep(3);
      navigate(
        `/simulation/${simulationId}/start${maxRounds ? `?rounds=${maxRounds}` : ''}`,
      );
    },
    [simulationId, workspace, navigate],
  );

  const handleGoBack = useCallback(() => {
    const pid = workspace.projectId;
    if (pid) {
      navigate(`/process/${pid}`);
    } else {
      navigate('/');
    }
  }, [workspace.projectId, navigate]);

  if (!simulationId) {
    return <div>Missing simulation ID</div>;
  }

  return (
    <WorkflowShell
      graphPanel={
        <GraphPanel
          graphData={graphData}
          loading={graphLoading}
          graphMode={graphDisplayMode}
          onGraphModeChange={setGraphDisplayMode}
        />
      }
    >
      <Step2EnvSetup
        simulationId={simulationId}
        projectData={projectData}
        systemLogs={logs}
        onStartSimulation={handleStartSimulation}
        onGoBack={handleGoBack}
      />
    </WorkflowShell>
  );
}
