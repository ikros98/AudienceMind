import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  useEffect,
  type ReactNode,
} from 'react';
import type { ViewMode, WorkflowStep } from '../types';

interface WorkspaceState {
  projectId: string | null;
  simulationId: string | null;
  reportId: string | null;
  graphId: string | null;
  currentStep: WorkflowStep;
  viewMode: ViewMode;
}

interface WorkspaceCtx extends WorkspaceState {
  setProjectId: (id: string | null) => void;
  setSimulationId: (id: string | null) => void;
  setReportId: (id: string | null) => void;
  setGraphId: (id: string | null) => void;
  setCurrentStep: (step: WorkflowStep) => void;
  setViewMode: (mode: ViewMode) => void;
  clearWorkflowContext: () => void;
  reset: () => void;
}

const initial: WorkspaceState = {
  projectId: null,
  simulationId: null,
  reportId: null,
  graphId: null,
  currentStep: 1,
  viewMode: 'split',
};

const WORKSPACE_STORAGE_KEY = 'personagraph.frontendGlass.workspace.v1';

function sanitizeStep(value: unknown): WorkflowStep {
  return value === 2 || value === 3 || value === 4 || value === 5 ? value : 1;
}

function sanitizeViewMode(value: unknown): ViewMode {
  return value === 'graph' || value === 'workbench' ? value : 'split';
}

function readStoredWorkspaceState(): WorkspaceState {
  if (typeof window === 'undefined') return initial;

  try {
    const raw = window.sessionStorage.getItem(WORKSPACE_STORAGE_KEY);
    if (!raw) return initial;
    const parsed = JSON.parse(raw) as Partial<WorkspaceState> | null;
    if (!parsed || typeof parsed !== 'object') return initial;
    return {
      projectId: typeof parsed.projectId === 'string' ? parsed.projectId : null,
      simulationId: typeof parsed.simulationId === 'string' ? parsed.simulationId : null,
      reportId: typeof parsed.reportId === 'string' ? parsed.reportId : null,
      graphId: typeof parsed.graphId === 'string' ? parsed.graphId : null,
      currentStep: sanitizeStep(parsed.currentStep),
      viewMode: sanitizeViewMode(parsed.viewMode),
    };
  } catch {
    return initial;
  }
}

const WorkspaceContext = createContext<WorkspaceCtx | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<WorkspaceState>(readStoredWorkspaceState);

  const setStateField = useCallback(
    <K extends keyof WorkspaceState>(key: K, value: WorkspaceState[K]) => {
      setState((current) => {
        if (Object.is(current[key], value)) return current;
        return { ...current, [key]: value };
      });
    },
    [],
  );

  const reset = useCallback(() => setState(initial), []);
  const setProjectId = useCallback(
    (id: string | null) => setStateField('projectId', id),
    [setStateField],
  );
  const setSimulationId = useCallback(
    (id: string | null) => setStateField('simulationId', id),
    [setStateField],
  );
  const setReportId = useCallback(
    (id: string | null) => setStateField('reportId', id),
    [setStateField],
  );
  const setGraphId = useCallback(
    (id: string | null) => setStateField('graphId', id),
    [setStateField],
  );
  const setCurrentStep = useCallback(
    (step: WorkflowStep) => setStateField('currentStep', step),
    [setStateField],
  );
  const setViewMode = useCallback(
    (mode: ViewMode) => setStateField('viewMode', mode),
    [setStateField],
  );
  const clearWorkflowContext = useCallback(
    () =>
      setState((current) => ({
        ...current,
        projectId: null,
        simulationId: null,
        reportId: null,
        graphId: null,
        currentStep: 1,
      })),
    [],
  );

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.sessionStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify(state));
  }, [state]);

  const value = useMemo(
    () => ({
      ...state,
      setProjectId,
      setSimulationId,
      setReportId,
      setGraphId,
      setCurrentStep,
      setViewMode,
      clearWorkflowContext,
      reset,
    }),
    [
      clearWorkflowContext,
      reset,
      setCurrentStep,
      setGraphId,
      setProjectId,
      setReportId,
      setSimulationId,
      setViewMode,
      state,
    ],
  );

  return (
    <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceCtx {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspace must be used within WorkspaceProvider');
  return ctx;
}
