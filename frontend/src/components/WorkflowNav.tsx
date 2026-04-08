import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useWorkspace } from '../store/workspace';
import type { WorkflowStep } from '../types';
import * as simulationApi from '../api/simulation';
import * as reportApi from '../api/report';
import s from '../styles/workflow-nav.module.css';

const STEPS: { num: WorkflowStep; label: string }[] = [
  { num: 1, label: 'Graph' },
  { num: 2, label: 'Setup' },
  { num: 3, label: 'Simulate' },
  { num: 4, label: 'Report' },
  { num: 5, label: 'Interact' },
];

export default function WorkflowNav() {
  const navigate = useNavigate();
  const location = useLocation();
  const params = useParams<{
    projectId?: string;
    simulationId?: string;
    reportId?: string;
  }>();
  const workspace = useWorkspace();
  const { currentStep, projectId, simulationId, reportId } = workspace;
  const [resolvingStep, setResolvingStep] = useState<WorkflowStep | null>(null);
  const isFreshAnalysisRoute =
    location.pathname === '/' ||
    location.pathname === '/demo' ||
    location.pathname === '/process/new';
  const activeProjectId = isFreshAnalysisRoute ? null : projectId ?? params.projectId ?? null;
  const activeSimulationId = isFreshAnalysisRoute ? null : simulationId ?? params.simulationId ?? null;
  const activeReportId = isFreshAnalysisRoute ? null : reportId ?? params.reportId ?? null;
  const activeStep = useMemo<WorkflowStep>(() => {
    if (isFreshAnalysisRoute) return 1;
    if (location.pathname.startsWith('/interaction/')) return 5;
    if (location.pathname.startsWith('/report/')) return 4;
    if (location.pathname.includes('/simulation/') && location.pathname.endsWith('/start')) return 3;
    if (location.pathname.startsWith('/simulation/')) return 2;
    if (location.pathname.startsWith('/process/')) {
      return currentStep === 2 ? 2 : 1;
    }
    return currentStep;
  }, [currentStep, isFreshAnalysisRoute, location.pathname]);

  const maxReachable = (() => {
    if (isFreshAnalysisRoute) return 1;
    if (activeReportId) return 5;
    if (activeSimulationId) return 3;
    if (activeProjectId) return 2;
    return 1;
  })();

  const completedThrough = useMemo(() => {
    if (isFreshAnalysisRoute) return 0;
    if (location.pathname.startsWith('/interaction/')) return 5;
    if (activeReportId) return 4;
    if (location.pathname.includes('/simulation/') && location.pathname.endsWith('/start')) return 3;
    if (activeSimulationId) return 2;
    if (activeProjectId) return 1;
    return 1;
  }, [activeProjectId, activeReportId, activeSimulationId, isFreshAnalysisRoute, location.pathname]);

  const resolveWorkflowContext = useCallback(async () => {
    let nextProjectId = activeProjectId;
    let nextSimulationId = activeSimulationId;
    let nextReportId = activeReportId;

    if (!nextSimulationId && nextReportId) {
      const report = await reportApi.getReport(nextReportId);
      nextSimulationId = report.simulation_id;
      workspace.setSimulationId(nextSimulationId);
    }

    if (nextSimulationId && (!nextProjectId || !nextReportId)) {
      const entry = await simulationApi.findSimulationHistoryEntry({
        simulationId: nextSimulationId,
        reportId: nextReportId ?? undefined,
      });
      if (entry?.project_id && !nextProjectId) {
        nextProjectId = entry.project_id;
        workspace.setProjectId(nextProjectId);
      }
      if (entry?.report_id && !nextReportId) {
        nextReportId = entry.report_id;
        workspace.setReportId(nextReportId);
      }
    }

    if (nextProjectId && (!nextSimulationId || !nextReportId)) {
      const history = await simulationApi.getSimulationHistory();
      const entries = history.filter((entry) => entry.project_id === nextProjectId);
      const preferred =
        entries.find((entry) => entry.report_id) ??
        entries.find((entry) => entry.status === 'completed' || entry.status === 'running') ??
        entries[0];

      if (preferred?.simulation_id && !nextSimulationId) {
        nextSimulationId = preferred.simulation_id;
        workspace.setSimulationId(nextSimulationId);
      }
      if (preferred?.report_id && !nextReportId) {
        nextReportId = preferred.report_id;
        workspace.setReportId(nextReportId);
      }
      if (preferred?.graph_id && !workspace.graphId) {
        workspace.setGraphId(preferred.graph_id);
      }
    }

    return {
      projectId: nextProjectId,
      simulationId: nextSimulationId,
      reportId: nextReportId,
    };
  }, [
    activeProjectId,
    activeReportId,
    activeSimulationId,
    workspace,
  ]);

  useEffect(() => {
    if (isFreshAnalysisRoute) return;
    if (!activeProjectId) return;
    if (activeSimulationId && activeReportId) return;

    void resolveWorkflowContext().catch(() => {
      // Route views already surface user-facing loading/error states.
      // This silent hydration keeps finished workflow navigation stable.
    });
  }, [activeProjectId, activeReportId, activeSimulationId, isFreshAnalysisRoute, resolveWorkflowContext]);

  async function handleClick(step: WorkflowStep) {
    if (step === activeStep) return;
    if (step > maxReachable) return;
    if (resolvingStep != null) return;

    setResolvingStep(step);

    let nextRoute: string | null = null;
    try {
      const resolved = await resolveWorkflowContext();

      switch (step) {
        case 1:
          if (!resolved.projectId) return;
          nextRoute = `/process/${resolved.projectId}`;
          break;
        case 2:
          if (resolved.simulationId) {
            nextRoute = `/simulation/${resolved.simulationId}`;
          } else if (!resolved.projectId) {
            return;
          }
          break;
        case 3:
          if (!resolved.simulationId) return;
          nextRoute = `/simulation/${resolved.simulationId}/start`;
          break;
        case 4:
          if (!resolved.reportId) return;
          nextRoute = `/report/${resolved.reportId}`;
          break;
        case 5:
          if (!resolved.reportId) return;
          nextRoute = `/interaction/${resolved.reportId}`;
          break;
      }

      workspace.setCurrentStep(step);
      if (nextRoute) {
        navigate(nextRoute);
      }
    } finally {
      setResolvingStep(null);
    }
  }

  return (
    <nav className={s.nav}>
      {STEPS.map((step, i) => {
        const isActive = step.num === activeStep;
        const isCompleted = step.num <= completedThrough && !isActive;
        const reachable = step.num <= maxReachable;
        const cls = [
          s.pill,
          isActive && s.active,
          isCompleted && s.done,
          resolvingStep === step.num && s.resolving,
          !reachable && !isActive && s.locked,
        ]
          .filter(Boolean)
          .join(' ');
        const lineCls = [
          s.line,
          i > 0 && completedThrough >= step.num && s.lineDone,
        ].filter(Boolean).join(' ');

        return (
          <div key={step.num} className={s.item}>
            {i > 0 && <span className={lineCls} />}
            <div
              role="button"
              tabIndex={0}
              className={cls}
              onClick={() => handleClick(step.num)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  void handleClick(step.num);
                }
              }}
            >
              <span className={s.dot} />
              <span className={s.label}>{step.label}</span>
            </div>
          </div>
        );
      })}
    </nav>
  );
}
