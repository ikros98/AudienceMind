import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import * as graphApi from '../api/graph';
import * as simulationApi from '../api/simulation';
import { useWorkspace } from '../store/workspace';
import { usePendingUpload } from '../store/pendingUpload';
import type { Project, TaskInfo, GraphData } from '../types';
import { ontologyToGraph } from '../utils/ontologyToGraph';
import WorkflowShell from '../components/WorkflowShell';
import GraphPanel from '../components/GraphPanel';
import Step1GraphBuild from '../components/steps/Step1GraphBuild';
import Step2EnvSetup from '../components/steps/Step2EnvSetup';

const MAX_LOG_LINES = 200;
const TASK_LOG_PROGRESS_STEP = 5;
const TASK_STALL_WARNING_MS = 45_000;
const POLL_RETRY_DELAY_MS = 3_000;
const POLL_INTERVAL_MS = 2_000;
const PROCESS_RESUME_STORAGE_KEY = 'personagraph.frontendGlass.processResumeProjectId';
type LogLevel = 'info' | 'warn' | 'error';

interface TaskPollState {
  lastStatus?: string;
  lastMessage?: string;
  lastProgressBucket?: number;
  lastUpdateAt: number;
  stallWarned: boolean;
  pollErrorLogged: boolean;
}

type NewProjectStartResult = {
  ontResult: Awaited<ReturnType<typeof graphApi.generateOntology>>;
  buildResult: Awaited<ReturnType<typeof graphApi.buildGraph>>;
};

type GraphDisplayMode = 'full' | 'focused';

const newProjectStartPromises = new Map<string, Promise<NewProjectStartResult>>();

function readResumableProjectId(): string | null {
  if (typeof window === 'undefined') return null;
  return window.sessionStorage.getItem(PROCESS_RESUME_STORAGE_KEY);
}

function writeResumableProjectId(projectId: string): void {
  if (typeof window === 'undefined') return;
  window.sessionStorage.setItem(PROCESS_RESUME_STORAGE_KEY, projectId);
}

function clearResumableProjectId(projectId?: string | null): void {
  if (typeof window === 'undefined') return;
  const current = window.sessionStorage.getItem(PROCESS_RESUME_STORAGE_KEY);
  if (!current) return;
  if (projectId && current !== projectId) return;
  window.sessionStorage.removeItem(PROCESS_RESUME_STORAGE_KEY);
}

function firstMeaningfulLine(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const line = value
    .split(/\r?\n/)
    .map((part) => part.trim())
    .find(Boolean);
  return line ?? null;
}

function summarizeTaskError(info: TaskInfo): string {
  return (
    firstMeaningfulLine(info.message) ??
    firstMeaningfulLine(info.error) ??
    'Task failed'
  );
}

function summarizeTaskProgress(taskId: string, info: TaskInfo): string {
  const label = taskId.slice(0, 8);
  const message =
    firstMeaningfulLine(info.message) ??
    (info.status === 'processing'
      ? 'Task is processing'
      : info.status === 'pending'
        ? 'Task is pending'
        : info.status === 'completed'
          ? 'Task completed'
          : 'Task update');
  const progress =
    typeof info.progress === 'number' ? ` (${Math.max(0, info.progress)}%)` : '';
  return `[Task ${label}] ${message}${progress}`;
}

function buildPendingUploadKey(files: File[], requirement: string): string {
  const fileKey = files
    .map((file) => `${file.name}:${file.size}:${file.lastModified}`)
    .join('|');
  return `${requirement.trim()}::${fileKey}`;
}

export default function ProcessView() {
  const { projectId: paramId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const workspace = useWorkspace();
  const { clearWorkflowContext } = workspace;
  const { upload, clear: clearUpload } = usePendingUpload();

  const [projectId, setProjectId] = useState<string | null>(
    paramId === 'new' ? null : paramId ?? null,
  );
  const [projectData, setProjectData] = useState<Project | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [displayGraphData, setDisplayGraphData] = useState<GraphData | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [schemaMode, setSchemaMode] = useState(false);
  const [ontologyProgress, setOntologyProgress] = useState<TaskInfo | null>(null);
  const [buildProgress, setBuildProgress] = useState<TaskInfo | null>(null);
  const [localStep, setLocalStep] = useState<'step1' | 'step2'>('step1');
  const [simulationId, setSimulationId] = useState<string | null>(null);
  const [graphDisplayMode, setGraphDisplayMode] = useState<GraphDisplayMode>('full');
  const [logs, setLogs] = useState<string[]>([]);

  const mountedRef = useRef(true);
  const taskPollStateRef = useRef<Record<string, TaskPollState>>({});

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const log = useCallback((msg: string, level: LogLevel = 'info') => {
    const ts = new Date().toLocaleTimeString();
    const prefix = level === 'info' ? '[INFO]' : level === 'warn' ? '[WARN]' : '[ERROR]';
    setLogs((prev) => {
      const next = [...prev, `[${ts}] ${prefix} ${msg}`];
      return next.length > MAX_LOG_LINES ? next.slice(next.length - MAX_LOG_LINES) : next;
    });
  }, []);

  const failGraphBuild = useCallback((message: string) => {
    const summary = firstMeaningfulLine(message) ?? 'Graph build failed';
    setGraphData(null);
    setDisplayGraphData(null);
    setSchemaMode(false);
    setGraphLoading(false);
    setBuildProgress((prev) => ({
      task_id: prev?.task_id ?? '',
      status: 'failed',
      progress: 0,
      message: summary,
      error: message,
      created_at: prev?.created_at,
      updated_at: prev?.updated_at,
    }));
    setProjectData((prev) =>
      prev
        ? {
            ...prev,
            status: 'failed',
            error: message,
          }
        : prev,
    );
  }, []);

  const graphDataOpts = useCallback(
    (mode: GraphDisplayMode): { baseline: true; compact?: true } =>
      mode === 'focused' ? { baseline: true, compact: true } : { baseline: true },
    [],
  );

  /* -- Sync local view with workspace step changes ---------- */

  useEffect(() => {
    if (workspace.currentStep === 1) {
      setLocalStep('step1');
    } else if (workspace.currentStep === 2) {
      setLocalStep('step2');
    }
  }, [workspace.currentStep]);

  /* -- Phase number for Step1 component --------------------- */

  const phaseNumber = (() => {
    const status = projectData?.status;
    if (status === 'graph_completed') return 2;
    if (status === 'ontology_generated' || status === 'graph_building') return 1;
    if (status === 'failed' && projectData?.ontology) return 1;
    if (ontologyProgress?.status === 'completed') return 1;
    return 0;
  })();

  /* -- Poll task status ------------------------------------- */

  const pollTask = useCallback(
    async (taskId: string, onProgress: (t: TaskInfo) => void): Promise<TaskInfo> => {
      return new Promise((resolve, reject) => {
        const poll = async () => {
          if (!mountedRef.current) return;
          try {
            const info = await graphApi.getTaskStatus(taskId);
            if (!mountedRef.current) return;
            onProgress(info);

            const now = Date.now();
            const progressBucket =
              typeof info.progress === 'number'
                ? Math.floor(Math.max(0, info.progress) / TASK_LOG_PROGRESS_STEP)
                : undefined;
            const nextMessage = firstMeaningfulLine(info.message) ?? '';
            const state = taskPollStateRef.current[taskId];

            if (state?.pollErrorLogged) {
              log(`[Task ${taskId.slice(0, 8)}] Status polling recovered.`, 'info');
            }

            const shouldLogUpdate =
              !state ||
              state.lastStatus !== info.status ||
              state.lastMessage !== nextMessage ||
              state.lastProgressBucket !== progressBucket;

            if (shouldLogUpdate) {
              log(summarizeTaskProgress(taskId, info), info.status === 'failed' ? 'error' : 'info');
              taskPollStateRef.current[taskId] = {
                lastStatus: info.status,
                lastMessage: nextMessage,
                lastProgressBucket: progressBucket,
                lastUpdateAt: now,
                stallWarned: false,
                pollErrorLogged: false,
              };
            } else if (
              (info.status === 'pending' || info.status === 'processing') &&
              now - state.lastUpdateAt >= TASK_STALL_WARNING_MS &&
              !state.stallWarned
            ) {
              log(
                `[Task ${taskId.slice(0, 8)}] No visible progress update for 45s. The backend may be waiting on the LLM or a graph operation.`,
                'warn',
              );
              taskPollStateRef.current[taskId] = {
                ...state,
                stallWarned: true,
              };
            }

            if (info.status === 'completed') {
              delete taskPollStateRef.current[taskId];
              resolve(info);
              return;
            }
            if (info.status === 'failed') {
              delete taskPollStateRef.current[taskId];
              reject(new Error(summarizeTaskError(info)));
              return;
            }
            setTimeout(poll, POLL_INTERVAL_MS);
          } catch (err) {
            const state = taskPollStateRef.current[taskId];
            if (!state?.pollErrorLogged) {
              log(
                `[Task ${taskId.slice(0, 8)}] Status polling failed. Retrying in ${POLL_RETRY_DELAY_MS / 1000}s...`,
                'warn',
              );
              taskPollStateRef.current[taskId] = {
                lastStatus: state?.lastStatus,
                lastMessage: state?.lastMessage,
                lastProgressBucket: state?.lastProgressBucket,
                lastUpdateAt: state?.lastUpdateAt ?? Date.now(),
                stallWarned: state?.stallWarned ?? false,
                pollErrorLogged: true,
              };
            }
            if (mountedRef.current) setTimeout(poll, POLL_RETRY_DELAY_MS);
            else reject(err);
          }
        };
        poll();
      });
    },
    [log],
  );

  /* -- Load graph data -------------------------------------- */

  /* -- New project flow ------------------------------------- */

  useEffect(() => {
    if (paramId !== 'new') return;
    clearWorkflowContext();
    setProjectId(null);
    setProjectData(null);
    setGraphData(null);
    setDisplayGraphData(null);
    setGraphLoading(false);
    setSchemaMode(false);
    setOntologyProgress(null);
    setBuildProgress(null);
    setLocalStep('step1');
    setSimulationId(null);
    setLogs([]);
  }, [clearWorkflowContext, paramId]);

  useEffect(() => {
    if (paramId !== 'new') return;
    const resumableProjectId = projectId ?? workspace.projectId ?? readResumableProjectId();

    if (upload.files.length === 0) {
      if (resumableProjectId) {
        navigate(`/process/${resumableProjectId}`, { replace: true });
      } else {
        navigate('/');
      }
      return;
    }

    let cancelled = false;

    async function run() {
      try {
        const requestKey = buildPendingUploadKey(upload.files, upload.requirement);
        let startPromise = newProjectStartPromises.get(requestKey);
        const isNewStart = !startPromise;

        if (isNewStart) {
          log('Starting ontology generation...');
          startPromise = (async () => {
            const ontResult = await graphApi.generateOntology(
              upload.files,
              upload.requirement,
            );
            const buildResult = await graphApi.buildGraph(ontResult.project_id);
            return { ontResult, buildResult };
          })().finally(() => {
            newProjectStartPromises.delete(requestKey);
          });
          newProjectStartPromises.set(requestKey, startPromise);
        }

        if (!startPromise) {
          throw new Error('Failed to initialize the project workflow.');
        }

        const { ontResult, buildResult } = await startPromise;
        if (cancelled) return;

        const pid = ontResult.project_id;
        writeResumableProjectId(pid);
        setProjectId(pid);
        workspace.setProjectId(pid);
        workspace.setCurrentStep(1);

        const proj: Project = {
          project_id: pid,
          name: ontResult.project_name,
          status: 'ontology_generated',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          file_count: ontResult.files.length,
          ontology: ontResult.ontology,
        };
        setProjectData(proj);
        setOntologyProgress({ task_id: '', status: 'completed', message: 'Ontology generated' });
        log(`Ontology generated: ${ontResult.ontology.entity_types.length} entity types, ${ontResult.ontology.edge_types.length} edge types`);

        setBuildProgress({
          task_id: buildResult.task_id,
          status: 'pending',
          progress: 0,
          message: buildResult.message,
        });
        setGraphData(null);
        setDisplayGraphData(null);
        setSchemaMode(false);
        setGraphLoading(true);
        log('Starting graph build...');
        log(`Graph build task started: ${buildResult.task_id}`);
        clearUpload();
        navigate(`/process/${pid}`, { replace: true });
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          setBuildProgress((prev) =>
            prev
              ? { ...prev, status: 'failed', message: firstMeaningfulLine(message) ?? message, error: message }
              : prev,
          );
          log(`Error: ${message}`, 'error');
        }
      }
    }
    run();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramId]);

  useEffect(() => {
    if (paramId !== 'new' || !projectId) return;
    writeResumableProjectId(projectId);
    navigate(`/process/${projectId}`, { replace: true });
  }, [navigate, paramId, projectId]);

  /* -- Existing project flow -------------------------------- */

  useEffect(() => {
    if (paramId === 'new' || !paramId) return;

    let cancelled = false;

    async function load() {
      try {
        log('Loading project...');
        const proj = await graphApi.getProject(paramId!);
        if (cancelled) return;

        setProjectData(proj);
        setProjectId(proj.project_id);
        workspace.setProjectId(proj.project_id);

        if (proj.status === 'graph_building') {
          writeResumableProjectId(proj.project_id);
        } else {
          clearResumableProjectId(proj.project_id);
        }

        if (proj.status === 'failed' && proj.error) {
          setGraphData(null);
          setSchemaMode(false);
          setGraphLoading(false);
          log(`Project failed: ${firstMeaningfulLine(proj.error) ?? proj.error}`, 'error');
          setBuildProgress({
            task_id: proj.graph_build_task_id ?? '',
            status: 'failed',
            progress: 0,
            message: firstMeaningfulLine(proj.error) ?? 'Graph build failed',
            error: proj.error,
          });
        }

        if (
          proj.status === 'graph_completed' ||
          proj.status === 'ontology_generated' ||
          (proj.status === 'failed' && proj.ontology)
        ) {
          setOntologyProgress({ task_id: '', status: 'completed', message: 'Ontology loaded' });
        }

        if (proj.status === 'graph_completed') {
          setBuildProgress({ task_id: '', status: 'completed', progress: 100, message: 'Loaded' });
          workspace.setCurrentStep(1);
          setLocalStep('step1');
          setGraphData(null);
          setDisplayGraphData(null);
          setSchemaMode(false);
          setGraphLoading(Boolean(proj.graph_id));

          if (proj.graph_id) {
            try {
              const baselineGraph = await graphApi.getGraphData(
                proj.graph_id,
                { baseline: true },
              );
              if (!cancelled && baselineGraph && baselineGraph.nodes?.length > 0) {
                setGraphData(baselineGraph);
                log(
                  `Baseline graph loaded: ${baselineGraph.nodes.length} nodes, ${baselineGraph.edges.length} edges`,
                );
                const graphForDisplay =
                  graphDisplayMode === 'focused'
                    ? await graphApi.getGraphData(proj.graph_id, graphDataOpts('focused'))
                    : baselineGraph;
                if (cancelled) return;
                setDisplayGraphData(graphForDisplay);
                setSchemaMode(false);
                setGraphLoading(false);
                workspace.setGraphId(proj.graph_id);
                log(
                  `${graphDisplayMode === 'focused' ? 'Focused display' : 'Baseline display'} loaded: ${graphForDisplay.nodes.length} nodes, ${graphForDisplay.edges.length} edges`,
                );
              }
            } catch (err) {
              if (!cancelled) {
                const message = err instanceof Error ? err.message : String(err);
                setGraphLoading(false);
                log(`Graph data load error: ${message}`, 'warn');
              }
            }
          }
        } else if (proj.status === 'ontology_generated') {
          workspace.setCurrentStep(1);
          // Show ontology schema graph while graph hasn't been built
          if (proj.ontology) {
            const schemaGraph = ontologyToGraph(proj.ontology);
            setGraphData(schemaGraph);
            setDisplayGraphData(schemaGraph);
            setSchemaMode(true);
            log('Showing ontology schema graph');
          }
        } else if (proj.status === 'graph_building') {
          workspace.setCurrentStep(1);
          setGraphData(null);
          setDisplayGraphData(null);
          setSchemaMode(false);
          setGraphLoading(true);
          if (proj.graph_build_task_id) {
            log('Graph build in progress, resuming polling...');
            try {
              await pollTask(proj.graph_build_task_id, (info) => {
                if (mountedRef.current) setBuildProgress(info);
              });
              if (!cancelled) {
                setGraphLoading(false);
                log('Graph build completed');
                const updatedProj = await graphApi.getProject(paramId!);
                if (!cancelled) {
                  setProjectData(updatedProj);
                  if (updatedProj.graph_id) {
                    const baselineGraph = await graphApi.getGraphData(updatedProj.graph_id, {
                      baseline: true,
                    });
                    if (cancelled) return;
                    setGraphData(baselineGraph);
                    log(
                      `Baseline graph loaded: ${baselineGraph.nodes.length} nodes, ${baselineGraph.edges.length} edges`,
                    );
                    const graphForDisplay =
                      graphDisplayMode === 'focused'
                        ? await graphApi.getGraphData(updatedProj.graph_id, graphDataOpts('focused'))
                        : baselineGraph;
                    if (cancelled) return;
                    setDisplayGraphData(graphForDisplay);
                    setGraphLoading(false);
                    log(
                      `${graphDisplayMode === 'focused' ? 'Focused display' : 'Baseline display'} loaded: ${graphForDisplay.nodes.length} nodes, ${graphForDisplay.edges.length} edges`,
                    );
                  }
                }
              }
            } catch (err) {
              if (!cancelled) {
                setGraphLoading(false);
                const message = err instanceof Error ? err.message : String(err);
                failGraphBuild(message);
                log(`Build error: ${message}`, 'error');
              }
            }
          } else {
            setGraphLoading(false);
            log('Graph build in progress, waiting for task ID...', 'warn');
          }
        } else {
          setGraphLoading(false);
          workspace.setCurrentStep(1);
        }

        // Look for existing simulations linked to this project
        try {
          const history = await simulationApi.getSimulationHistory();
          if (!cancelled) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const sim = (history as any[]).find((h: any) => h.project_id === proj.project_id);
            if (sim) {
              setSimulationId(sim.simulation_id);
              workspace.setSimulationId(sim.simulation_id);
              workspace.setReportId(sim.report_id ?? null);
              log(`Found simulation: ${sim.simulation_id} (${sim.status})`);
            } else {
              setSimulationId(null);
              workspace.setSimulationId(null);
              workspace.setReportId(null);
            }
          }
        } catch {
          // Non-critical - simulation history unavailable
        }

        log(`Project loaded: ${proj.name} (${proj.status})`);
      } catch (err) {
        if (!cancelled) {
          log(`Error loading project: ${err instanceof Error ? err.message : String(err)}`, 'error');
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphDataOpts, graphDisplayMode, paramId]);

  /* -- Navigate to env setup -------------------------------- */

  const handleNextStep = useCallback(async () => {
    if (!projectId) return;

    // If we already have a simulation, navigate to it
    if (simulationId) {
      workspace.setCurrentStep(2);
      navigate(`/simulation/${simulationId}`);
      return;
    }

    try {
      log('Creating simulation...');
      const sim = await simulationApi.createSimulation(projectId);
      const simId = sim.simulation_id;
      setSimulationId(simId);
      workspace.setSimulationId(simId);
      workspace.setReportId(null);
      workspace.setCurrentStep(2);
      log(`Simulation created: ${simId}`);
      navigate(`/simulation/${simId}`);
    } catch (err) {
      log(`Error creating simulation: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [projectId, simulationId, log, workspace, navigate]);

  /* -- Step2 callbacks -------------------------------------- */

  const handleStartSimulation = useCallback(
    (maxRounds?: number) => {
      if (simulationId) {
        workspace.setCurrentStep(3);
        navigate(`/simulation/${simulationId}/start${maxRounds ? `?rounds=${maxRounds}` : ''}`);
      }
    },
    [simulationId, workspace, navigate],
  );

  const handleGoBack = useCallback(() => {
    setLocalStep('step1');
    workspace.setCurrentStep(1);
  }, [workspace]);

  /* -- Render ----------------------------------------------- */

  const showStep2 = localStep === 'step2' && simulationId;

  return (
    <WorkflowShell
      graphPanel={
        <GraphPanel
          graphData={displayGraphData ?? graphData}
          loading={graphLoading}
          schemaMode={schemaMode}
          graphMode={graphDisplayMode}
          onGraphModeChange={setGraphDisplayMode}
        />
      }
    >
      {showStep2 ? (
        <Step2EnvSetup
          simulationId={simulationId}
          projectData={projectData}
          systemLogs={logs}
          onStartSimulation={handleStartSimulation}
          onGoBack={handleGoBack}
        />
      ) : (
        <Step1GraphBuild
          currentPhase={phaseNumber}
          projectData={projectData}
          ontologyProgress={ontologyProgress}
          buildProgress={buildProgress}
          graphData={graphData}
          schemaMode={schemaMode}
          systemLogs={logs}
          onNextStep={handleNextStep}
        />
      )}
    </WorkflowShell>
  );
}
