import { useState, useEffect, useRef, useCallback } from 'react';
import * as reportApi from '../../api/report';
import SystemLog from '../SystemLog';
import MarkdownRenderer from '../MarkdownRenderer';
import StatusIndicator from '../StatusIndicator';
import s from '../../styles/step-report.module.css';

interface Props {
  reportId: string;
  simulationId: string;
  onComplete: (reportId?: string) => void;
  onReportIdChange?: (reportId: string) => void;
}

export default function Step4Report({
  reportId,
  simulationId,
  onComplete,
  onReportIdChange,
}: Props) {
  const sectionsPanelRef = useRef<HTMLDivElement>(null);
  const sectionRefs = useRef(new Map<number, HTMLDivElement>());
  const [reportData, setReportData] = useState<{
    title?: string;
    summary?: string;
    status?: string;
    sectionCount?: number;
    outlineSections?: { index: number; title: string }[];
    evidenceSummary?: {
      graph?: { node_count?: number; edge_count?: number };
      runtime?: { actions?: number; rounds?: number };
      topics?: string[];
    };
  } | null>(null);
  const [sections, setSections] = useState<
    Record<number, { title: string; content: string }>
  >({});
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const [agentEntries, setAgentEntries] = useState<reportApi.AgentLogEntry[]>([]);
  const [consoleLines, setConsoleLines] = useState<string[]>([]);
  const [activeLogTab, setActiveLogTab] = useState<'agent' | 'console'>('agent');
  const [isComplete, setIsComplete] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('Initializing...');
  const [currentSection, setCurrentSection] = useState<number | null>(null);
  const [completedSections, setCompletedSections] = useState<number[]>([]);
  const [activeReportId, setActiveReportId] = useState(reportId);
  const [focusedSection, setFocusedSection] = useState<number | null>(null);

  const agentLineRef = useRef(0);
  const consoleLineRef = useRef(0);
  const startTimeRef = useRef(Date.now());
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    setActiveReportId(reportId);
  }, [reportId]);

  useEffect(() => {
    agentLineRef.current = 0;
    consoleLineRef.current = 0;
    startTimeRef.current = Date.now();
    setElapsed(0);
    setAgentEntries([]);
    setConsoleLines([]);
    setSections({});
    setReportData(null);
    setIsComplete(false);
    setCurrentSection(null);
    setCompletedSections([]);
    setFocusedSection(null);
    sectionRefs.current.clear();
  }, [activeReportId]);

  // Elapsed timer
  useEffect(() => {
    const t = setInterval(() => setElapsed(Date.now() - startTimeRef.current), 1000);
    return () => clearInterval(t);
  }, []);

  const formatElapsed = useCallback((ms: number) => {
    const totalSec = Math.floor(ms / 1000);
    const m = Math.floor(totalSec / 60);
    const sec = totalSec % 60;
    return `${m}m ${sec.toString().padStart(2, '0')}s`;
  }, []);

  // Fetch full report + sections when complete
  const fetchFullReport = useCallback(async (nextReportId?: string) => {
    const targetReportId = nextReportId ?? activeReportId;
    try {
      const report = await reportApi.getReport(targetReportId);
      const secs = await reportApi.getReportSections(targetReportId);
      const map: Record<number, { title: string; content: string }> = {};
      for (const sec of secs.sections) {
        map[sec.index] = { title: sec.title, content: sec.content };
      }
      setReportData({
        title: report.outline?.title,
        summary: report.outline?.summary,
        status: report.status,
        sectionCount: report.outline?.sections?.length ?? secs.sections.length,
        evidenceSummary: report.evidence_summary ?? undefined,
        outlineSections: (report.outline?.sections ?? []).map((section, index) => ({
          index: index + 1,
          title: section.title,
        })),
      });
      setSections(map);
    } catch {
      // ignore - data may not be ready yet
    }
  }, [activeReportId]);

  // Poll generation status
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const st = await reportApi.getGenerateStatus(undefined, simulationId);
        if (cancelled) return;
        const nextReportId = st.report_id || activeReportId;
        if (nextReportId !== activeReportId) {
          setActiveReportId(nextReportId);
          onReportIdChange?.(nextReportId);
        }
        setProgress(st.progress ?? 0);
        setStatusMessage(st.message ?? 'Generating...');
        setCurrentSection(typeof st.current_section === 'number' ? st.current_section : null);
        setCompletedSections(Array.isArray(st.completed_sections) ? st.completed_sections : []);
        await fetchFullReport(nextReportId);

        if (st.status === 'completed' || st.already_completed) {
          setIsComplete(true);
          await fetchFullReport(nextReportId);
          return;
        }
      } catch {
        // ignore transient errors
      }
      if (!cancelled) {
        setTimeout(poll, 3000);
      }
    };
    poll();
    return () => { cancelled = true; };
  }, [simulationId, activeReportId, fetchFullReport, onReportIdChange]);

  // Poll agent log
  useEffect(() => {
    if (isComplete) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await reportApi.getAgentLogEntries(activeReportId, agentLineRef.current);
        if (cancelled) return;
        if (res.logs.length > 0) {
          agentLineRef.current = res.to_line;
          setAgentEntries((prev) => [...prev, ...res.logs]);
        }
      } catch { /* ignore */ }
      if (!cancelled) setTimeout(poll, 5000);
    };
    poll();
    return () => { cancelled = true; };
  }, [activeReportId, isComplete]);

  // Poll console log
  useEffect(() => {
    if (isComplete) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await reportApi.getConsoleLog(activeReportId, consoleLineRef.current);
        if (cancelled) return;
        if (res.lines.length > 0) {
          consoleLineRef.current = res.to_line;
          setConsoleLines((prev) => [...prev, ...res.lines]);
        }
      } catch { /* ignore */ }
      if (!cancelled) setTimeout(poll, 10000);
    };
    poll();
    return () => { cancelled = true; };
  }, [activeReportId, isComplete]);

  const toggleSection = (idx: number) => {
    const shouldOpen = collapsed.has(idx);
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (shouldOpen) next.delete(idx);
      else next.add(idx);
      return next;
    });
    setFocusedSection(idx);
    if (shouldOpen) {
      window.requestAnimationFrame(() => {
        const container = sectionsPanelRef.current;
        const sectionEl = sectionRefs.current.get(idx);
        if (!container || !sectionEl) return;
        const containerBox = container.getBoundingClientRect();
        const sectionBox = sectionEl.getBoundingClientRect();
        container.scrollTo({
          top: container.scrollTop + sectionBox.top - containerBox.top - 18,
          behavior: 'smooth',
        });
      });
    }
  };

  const sectionKeys = Object.keys(sections)
    .map(Number)
    .sort((a, b) => a - b);

  const outlineSections = reportData?.outlineSections ?? sectionKeys.map((index) => ({
    index,
    title: sections[index]?.title ?? `Section ${index}`,
  }));
  const completedCount = Math.max(completedSections.length, sectionKeys.length);
  const totalSections = Math.max(reportData?.sectionCount ?? outlineSections.length, completedCount, 1);
  const topicPreview = reportData?.evidenceSummary?.topics?.slice(0, 5) ?? [];

  const jumpToSection = useCallback((idx: number) => {
    setCollapsed((prev) => {
      if (!prev.has(idx)) return prev;
      const next = new Set(prev);
      next.delete(idx);
      return next;
    });
    setFocusedSection(idx);
    window.requestAnimationFrame(() => {
      const container = sectionsPanelRef.current;
      const sectionEl = sectionRefs.current.get(idx);
      if (!container || !sectionEl) return;
      const containerBox = container.getBoundingClientRect();
      const sectionBox = sectionEl.getBoundingClientRect();
      container.scrollTo({
        top: container.scrollTop + sectionBox.top - containerBox.top - 18,
        behavior: 'smooth',
      });
    });
  }, []);

  useEffect(() => {
    if (currentSection != null && !isComplete) {
      setFocusedSection(currentSection);
      return;
    }
    if (focusedSection == null && outlineSections[0]) {
      setFocusedSection(outlineSections[0].index);
    }
  }, [currentSection, focusedSection, isComplete, outlineSections]);

  useEffect(() => {
    const container = sectionsPanelRef.current;
    if (!container) return;

    let frame: number | null = null;
    const updateFocused = () => {
      frame = null;
      const anchor = container.getBoundingClientRect().top + 156;
      let nextFocused: number | null = null;
      let minDistance = Number.POSITIVE_INFINITY;

      for (const { index } of outlineSections) {
        const sectionEl = sectionRefs.current.get(index);
        if (!sectionEl) continue;
        const distance = Math.abs(sectionEl.getBoundingClientRect().top - anchor);
        if (distance < minDistance) {
          minDistance = distance;
          nextFocused = index;
        }
      }

      if (nextFocused != null) {
        setFocusedSection((prev) => (prev === nextFocused ? prev : nextFocused));
      }
    };

    const handleScroll = () => {
      if (frame != null) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(updateFocused);
    };

    handleScroll();
    container.addEventListener('scroll', handleScroll, { passive: true });
    window.addEventListener('resize', handleScroll);
    return () => {
      if (frame != null) window.cancelAnimationFrame(frame);
      container.removeEventListener('scroll', handleScroll);
      window.removeEventListener('resize', handleScroll);
    };
  }, [outlineSections, sections]);

  const formatActionLabel = (entry: reportApi.AgentLogEntry) => {
    switch (entry.action) {
      case 'report_start':
        return 'Report Started';
      case 'planning_start':
        return 'Planning Outline';
      case 'planning_complete':
        return 'Outline Ready';
      case 'section_start':
        return `Starting ${entry.section_title ?? 'Section'}`;
      case 'section_content':
        return `Drafted ${entry.section_title ?? 'Section'}`;
      case 'section_complete':
        return `Completed ${entry.section_title ?? 'Section'}`;
      case 'tool_call':
        return `Tool Call: ${entry.details?.tool_name ?? 'tool'}`;
      case 'report_complete':
        return 'Report Complete';
      default:
        return entry.details?.message ?? entry.action ?? 'Log';
    }
  };

  return (
    <div className={s.reportLayout}>
      {/* -- Left: report sections -- */}
      <div className={s.sectionsPanel} ref={sectionsPanelRef}>
        <div className={s.reportHero}>
          <div className={s.reportMetaRow}>
            <span className={s.reportTag}>Prediction Report</span>
            <span className={s.reportMetaItem}>ID {activeReportId}</span>
            <span className={s.reportMetaItem}>{completedCount}/{totalSections} sections</span>
          </div>
          {reportData?.title && (
            <div className={s.reportTitleBlock}>
              <div className={s.reportTitle}>{reportData.title}</div>
              {reportData.summary && (
                <div className={s.reportSummary}>{reportData.summary}</div>
              )}
            </div>
          )}
          <div className={s.heroMetrics}>
            <div className={s.heroMetric}>
              <span className={s.heroMetricLabel}>Graph</span>
              <span className={s.heroMetricValue}>
                {reportData?.evidenceSummary?.graph?.node_count ?? 0} / {reportData?.evidenceSummary?.graph?.edge_count ?? 0}
              </span>
            </div>
            <div className={s.heroMetric}>
              <span className={s.heroMetricLabel}>Runtime</span>
              <span className={s.heroMetricValue}>
                {reportData?.evidenceSummary?.runtime?.actions ?? 0} actions
              </span>
            </div>
            <div className={s.heroMetric}>
              <span className={s.heroMetricLabel}>Rounds</span>
              <span className={s.heroMetricValue}>
                {reportData?.evidenceSummary?.runtime?.rounds ?? 0}
              </span>
            </div>
            <div className={s.heroMetric}>
              <span className={s.heroMetricLabel}>Elapsed</span>
              <span className={s.heroMetricValue}>{formatElapsed(elapsed)}</span>
            </div>
          </div>
          {topicPreview.length > 0 && (
            <div className={s.topicRail}>
              {topicPreview.map((topic) => (
                <span key={topic} className={s.topicChip}>{topic}</span>
              ))}
            </div>
          )}
        </div>

        <div className={s.sectionStack}>
          {outlineSections.map(({ index: idx, title }) => {
          const sec = sections[idx];
          const isCompleted = completedSections.includes(idx) || Boolean(sec);
          const isActive = currentSection === idx && !isComplete;
          const isOpen = !collapsed.has(idx);
          return (
            <div
              key={idx}
              ref={(node) => {
                if (node) sectionRefs.current.set(idx, node);
                else sectionRefs.current.delete(idx);
              }}
              className={[
                s.sectionItem,
                isCompleted ? s.sectionItemCompleted : s.sectionItemPending,
                isActive ? s.sectionItemActive : '',
                focusedSection === idx ? s.sectionItemFocused : '',
              ].filter(Boolean).join(' ')}
            >
              <button
                type="button"
                className={s.sectionHeader}
                onClick={() => (sec ? toggleSection(idx) : jumpToSection(idx))}
              >
                <span className={s.sectionNumber}>
                  {String(idx).padStart(2, '0')}
                </span>
                <span className={s.sectionTitleGroup}>
                  <span className={s.sectionName}>{sec?.title ?? title}</span>
                  <span className={s.sectionHint}>
                    {sec
                      ? isOpen
                        ? 'Collapse section'
                        : 'Open and jump to this section'
                      : isActive
                        ? 'Drafting in progress'
                        : 'Waiting in queue'}
                  </span>
                </span>
                <span className={`${s.sectionState} ${isCompleted ? s.sectionStateDone : isActive ? s.sectionStateLive : s.sectionStateQueued}`}>
                  {isCompleted ? 'Done' : isActive ? 'Live' : 'Queued'}
                </span>
                <span className={`${s.sectionToggle} ${isOpen ? s.sectionToggleOpen : ''}`}>
                  v
                </span>
              </button>
              {sec ? (
                <div className={`${s.sectionContent} ${isOpen ? s.sectionContentOpen : ''}`}>
                  <MarkdownRenderer content={sec.content} className={s.reportMarkdown} />
                </div>
              ) : isActive ? (
                <div className={s.sectionLoading}>
                  <span className={s.spinner} />
                  Drafting {title}...
                </div>
              ) : (
                <div className={s.sectionWaiting}>Waiting for this section to start.</div>
              )}
            </div>
          );
          })}
        </div>

        {!isComplete && outlineSections.length === 0 && (
          <div className={s.sectionLoading}>
            <span className={s.spinner} />
            Generating report sections...
          </div>
        )}
      </div>

      {/* -- Right: status + logs -- */}
      <div className={s.statusPanel}>
        <div className={s.navigatorCard}>
          <div className={s.cardEyebrow}>Reading Guide</div>
          <div className={s.navigatorTitle}>Jump into the report</div>
          <div className={s.navigatorHint}>
            Click any section here to open it in the reading column and keep your place.
          </div>
          <div className={s.navigatorList}>
            {outlineSections.map(({ index: idx, title }) => {
              const sec = sections[idx];
              const isCompleted = completedSections.includes(idx) || Boolean(sec);
              const isActive = currentSection === idx && !isComplete;
              return (
                <button
                  key={`nav-${idx}`}
                  type="button"
                  className={[
                    s.navigatorItem,
                    focusedSection === idx ? s.navigatorItemFocused : '',
                    isActive ? s.navigatorItemActive : '',
                  ].filter(Boolean).join(' ')}
                  onClick={() => jumpToSection(idx)}
                >
                  <span className={s.navigatorNumber}>{String(idx).padStart(2, '0')}</span>
                  <span className={s.navigatorCopy}>
                    <span className={s.navigatorLabel}>{sec?.title ?? title}</span>
                    <span className={s.navigatorSubcopy}>
                      {isCompleted ? 'Open section' : isActive ? 'Writing now' : 'Queued'}
                    </span>
                  </span>
                  <span className={`${s.navigatorState} ${isCompleted ? s.sectionStateDone : isActive ? s.sectionStateLive : s.sectionStateQueued}`}>
                    {isCompleted ? 'Done' : isActive ? 'Live' : 'Queued'}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div className={s.statusCard}>
          <div className={s.cardEyebrow}>Workflow</div>
          <div className={s.statusRow}>
            <span className={s.statusLabel}>Status</span>
            <StatusIndicator status={isComplete ? 'completed' : 'generating'} />
          </div>
          <div className={s.statusRow}>
            <span className={s.statusLabel}>Progress</span>
            <span className={s.statusValue}>
              {completedCount > 0 || isComplete
                ? `${completedCount}/${totalSections} sections`
                : `${Math.min(progress, 100)}%`}
            </span>
          </div>
          {currentSection != null && !isComplete && (
            <div className={s.statusRow}>
              <span className={s.statusLabel}>Current Section</span>
              <span className={s.statusValue}>#{currentSection}</span>
            </div>
          )}
          {reportData?.evidenceSummary?.graph && (
            <div className={s.statusRow}>
              <span className={s.statusLabel}>Graph</span>
              <span className={s.statusValue}>
                {reportData.evidenceSummary.graph.node_count ?? 0} nodes / {reportData.evidenceSummary.graph.edge_count ?? 0} edges
              </span>
            </div>
          )}
          {reportData?.evidenceSummary?.runtime && (
            <div className={s.statusRow}>
              <span className={s.statusLabel}>Runtime</span>
              <span className={s.statusValue}>
                {reportData.evidenceSummary.runtime.actions ?? 0} actions / {reportData.evidenceSummary.runtime.rounds ?? 0} rounds
              </span>
            </div>
          )}
          {(reportData?.evidenceSummary?.topics?.length ?? 0) > 0 && (
            <div className={s.statusRow}>
              <span className={s.statusLabel}>Topics</span>
              <span className={s.statusValue}>
                {reportData?.evidenceSummary?.topics?.slice(0, 3).join(', ')}
              </span>
            </div>
          )}
          <div className={s.statusRow}>
            <span className={s.statusLabel}>Elapsed</span>
            <span className={s.statusValue}>{formatElapsed(elapsed)}</span>
          </div>
          <div className={s.progressBar}>
            <div
              className={s.progressFill}
              style={{ width: `${Math.min(progress, 100)}%` }}
            />
          </div>
          <div className={s.currentStep}>{statusMessage}</div>
          {isComplete && (
            <button className={s.completeBtn} onClick={() => onComplete(activeReportId)}>
              Go to Interaction
            </button>
          )}
        </div>

        {/* Log tabs */}
        <div className={s.logTabs}>
          <button
            className={`${s.logTab} ${activeLogTab === 'agent' ? s.logTabActive : ''}`}
            onClick={() => setActiveLogTab('agent')}
          >
            Agent Log
          </button>
          <button
            className={`${s.logTab} ${activeLogTab === 'console' ? s.logTabActive : ''}`}
            onClick={() => setActiveLogTab('console')}
          >
            Console Log
          </button>
        </div>
        <div className={s.logWrapper}>
          {activeLogTab === 'agent' ? (
            <div className={s.timelineList}>
              {agentEntries.length === 0 ? (
                <div className={s.emptyTimeline}>Structured report events will appear here.</div>
              ) : (
                agentEntries.map((entry, index) => (
                  <div key={`${entry.timestamp ?? 'entry'}-${index}`} className={s.timelineCard}>
                    <div className={s.timelineMeta}>
                      <span className={s.timelineAction}>{formatActionLabel(entry)}</span>
                      <span className={s.timelineTime}>
                        {entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : ''}
                      </span>
                    </div>
                    {(entry.section_index != null || entry.stage) && (
                      <div className={s.timelineSubmeta}>
                        {entry.section_index != null ? `Section ${entry.section_index}` : ''}
                        {entry.section_index != null && entry.stage ? ' | ' : ''}
                        {entry.stage ?? ''}
                      </div>
                    )}
                    {entry.details?.message && (
                      <div className={s.timelineBody}>{entry.details.message}</div>
                    )}
                  </div>
                ))
              )}
            </div>
          ) : (
            <SystemLog lines={consoleLines} title="Console Log" maxHeight="320px" />
          )}
        </div>
      </div>
    </div>
  );
}
