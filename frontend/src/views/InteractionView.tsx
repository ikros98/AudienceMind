import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useWorkspace } from '../store/workspace';
import * as reportApi from '../api/report';
import * as simulationApi from '../api/simulation';
import WorkflowShell from '../components/WorkflowShell';
import Step5Interaction from '../components/steps/Step5Interaction';

interface SectionData {
  index: number;
  title: string;
  content: string;
}

export default function InteractionView() {
  const { reportId } = useParams<{ reportId: string }>();
  const {
    setCurrentStep,
    setReportId,
    setSimulationId: syncSimulationId,
    setProjectId,
  } = useWorkspace();
  const [simulationId, setSimulationId] = useState<string | null>(null);
  const [sections, setSections] = useState<SectionData[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCurrentStep(5);
    if (reportId) setReportId(reportId);
  }, [reportId, setCurrentStep, setReportId]);

  useEffect(() => {
    if (typeof reportId !== 'string') return;
    const activeReportId: string = reportId;
    let cancelled = false;

    const load = async () => {
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
        if (cancelled) return;

        if (entry?.project_id) setProjectId(entry.project_id);
        if (entry?.simulation_id) syncSimulationId(entry.simulation_id);
        if (entry?.report_id) setReportId(entry.report_id);

        const secs = await reportApi.getReportSections(activeReportId);
        if (!cancelled) setSections(secs.sections);
      } catch {
        if (!cancelled) setError('Could not load report data');
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [reportId, setProjectId, setReportId, syncSimulationId]);

  if (!reportId) return null;

  return (
    <WorkflowShell>
      {error ? (
        <div style={{ padding: '2rem', color: 'var(--text-muted)' }}>{error}</div>
      ) : !simulationId ? (
        <div style={{ padding: '2rem', color: 'var(--text-muted)' }}>Loading interaction...</div>
      ) : (
        <Step5Interaction
          reportId={reportId}
          simulationId={simulationId}
          sections={sections}
        />
      )}
    </WorkflowShell>
  );
}
