import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useWorkspace } from '../store/workspace';
import * as reportApi from '../api/report';
import * as simulationApi from '../api/simulation';
import WorkflowShell from '../components/WorkflowShell';
import Step4Report from '../components/steps/Step4Report';

export default function ReportView() {
  const { reportId } = useParams<{ reportId: string }>();
  const navigate = useNavigate();
  const {
    setCurrentStep,
    setReportId,
    setSimulationId: syncSimulationId,
    setProjectId,
  } = useWorkspace();
  const [simulationId, setSimulationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCurrentStep(4);
    if (reportId) setReportId(reportId);
  }, [reportId, setCurrentStep, setReportId]);

  useEffect(() => {
    if (typeof reportId !== 'string') return;
    const activeReportId: string = reportId;

    let cancelled = false;

    async function load() {
      try {
        setError(null);
        const report = await reportApi.getReport(activeReportId);
        if (cancelled) return;

        setSimulationId(report.simulation_id);
        syncSimulationId(report.simulation_id);

        const entry = await simulationApi.findSimulationHistoryEntry({
          reportId: activeReportId,
          simulationId: report.simulation_id,
        });
        if (cancelled || !entry) return;

        if (entry.project_id) setProjectId(entry.project_id);
        if (entry.simulation_id) syncSimulationId(entry.simulation_id);
        if (entry.report_id) setReportId(entry.report_id);
      } catch {
        if (!cancelled) setError('Could not load report data');
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [reportId, setProjectId, setReportId, syncSimulationId]);

  const handleComplete = (nextReportId?: string) => {
    navigate(`/interaction/${nextReportId ?? reportId}`);
  };

  const handleReportIdChange = (nextReportId: string) => {
    if (!nextReportId || nextReportId === reportId) return;
    setReportId(nextReportId);
    navigate(`/report/${nextReportId}`, { replace: true });
  };

  if (!reportId) return null;

  return (
    <WorkflowShell>
      {error ? (
        <div style={{ padding: '2rem', color: 'var(--text-muted)' }}>{error}</div>
      ) : !simulationId ? (
        <div style={{ padding: '2rem', color: 'var(--text-muted)' }}>Loading report...</div>
      ) : (
        <Step4Report
          reportId={reportId}
          simulationId={simulationId}
          onComplete={handleComplete}
          onReportIdChange={handleReportIdChange}
        />
      )}
    </WorkflowShell>
  );
}
