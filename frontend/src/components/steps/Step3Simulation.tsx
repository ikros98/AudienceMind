import { useState, useEffect, useRef, useCallback } from 'react';
import * as simulationApi from '../../api/simulation';
import * as reportApi from '../../api/report';
import SystemLog from '../SystemLog';
import s from '../../styles/step-simulation.module.css';

/* -- Action-type -> badge class mapping --------------------- */

const BADGE_CLASS: Record<string, string> = {
  CREATE_POST: s.badgeCREATE_POST ?? '',
  LIKE_POST: s.badgeLIKE_POST ?? '',
  COMMENT: s.badgeCOMMENT ?? '',
  FOLLOW: s.badgeFOLLOW ?? '',
  UPVOTE: s.badgeUPVOTE ?? '',
  DO_NOTHING: s.badgeDO_NOTHING ?? '',
};

const autoStartRequests = new Map<string, Promise<Awaited<ReturnType<typeof simulationApi.startSimulation>>>>();

function badgeClass(actionType: string): string {
  return BADGE_CLASS[actionType] ?? (s.badgeDEFAULT ?? '');
}

function platformEmoji(platform: string): string {
  return platform === 'twitter' ? 'TW' : 'RD';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function compositeKey(a: Record<string, unknown>): string {
  return `${a.timestamp ?? ''}-${a.platform ?? ''}-${a.round_num ?? a.round ?? ''}-${a.agent_id ?? ''}-${a.action_type ?? ''}`;
}

function fmtTime(ts: unknown): string {
  if (!ts || typeof ts !== 'string') return '';
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return String(ts);
  }
}

function summarizeRunError(error: unknown): string | null {
  if (typeof error !== 'string' || error.trim().length === 0) {
    return null;
  }

  const contextWindowMatch = error.match(
    /The input \((\d+) tokens\) is longer than the model's context length \((\d+) tokens\)/,
  );
  if (contextWindowMatch) {
    return `Model context limit reached: ${contextWindowMatch[1]} tokens sent to a ${contextWindowMatch[2]}-token model window.`;
  }

  const firstLine = error
    .split('\n')
    .map((line) => line.trim())
    .find((line) => line.length > 0);

  return firstLine ? firstLine.slice(0, 240) : null;
}

function actionRound(action: Record<string, unknown>): string {
  const raw = action.round_num ?? action.round;
  if (typeof raw === 'number') return String(raw);
  if (typeof raw === 'string' && raw.trim()) return raw;
  return '?';
}

function actionContent(action: Record<string, unknown>): string | null {
  if (typeof action.content === 'string' && action.content.trim()) {
    return action.content.trim();
  }

  const args = isRecord(action.action_args) ? action.action_args : null;
  const actionType = String(action.action_type ?? '');

  const contentCandidates = args
    ? [
        args.content,
        args.quote_content,
        args.comment_content,
        args.reply_content,
        args.post_content,
        args.original_content,
      ]
    : [];
  const directContent = contentCandidates.find(
    (value): value is string => typeof value === 'string' && value.trim().length > 0,
  );
  if (directContent) {
    return directContent.trim();
  }

  if (!args) return null;

  const targetName = typeof args.post_author_name === 'string'
    ? args.post_author_name
    : typeof args.original_author_name === 'string'
      ? args.original_author_name
      : typeof args.target_agent_name === 'string'
        ? args.target_agent_name
        : 'another agent';

  switch (actionType) {
    case 'LIKE_POST':
      return `Liked a post by ${targetName}.`;
    case 'REPOST':
      return `Reposted content from ${targetName}.`;
    case 'FOLLOW':
      return `Followed ${targetName}.`;
    default:
      return null;
  }
}

/* -- Props -------------------------------------------------- */

interface Props {
  simulationId: string;
  maxRounds?: number;
  projectData: unknown;
  systemLogs: string[];
  onGenerateReport: (reportId: string) => void;
  autoStartEnabled?: boolean;
}

/* -- Component ---------------------------------------------- */

export default function Step3Simulation({
  simulationId,
  maxRounds,
  systemLogs,
  onGenerateReport,
  autoStartEnabled = true,
}: Props) {
  const [phase, setPhase] = useState<0 | 1 | 2>(0);
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [runStatus, setRunStatus] = useState<Record<string, unknown>>({});
  const [actions, setActions] = useState<Record<string, unknown>[]>([]);
  const actionIdsRef = useRef(new Set<string>());
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const autoStartRequestKey = `${simulationId}:${maxRounds ?? 'default'}`;

  const mergeActions = useCallback((incoming: Record<string, unknown>[]) => {
    setActions((prev) => {
      const newItems: Record<string, unknown>[] = [];
      for (const action of incoming) {
        const key = compositeKey(action);
        if (!actionIdsRef.current.has(key)) {
          actionIdsRef.current.add(key);
          newItems.push(action);
        }
      }
      if (newItems.length === 0) return prev;
      return [...prev, ...newItems].sort(
        (left, right) => String(left.timestamp ?? '').localeCompare(String(right.timestamp ?? '')),
      );
    });
  }, []);

  const hydrateActions = useCallback(async (preferFullList = false) => {
    const detail = await simulationApi.getRunStatusDetail(simulationId);
    const detailActions = (detail.recent_actions ?? []) as Record<string, unknown>[];

    if (!preferFullList && detailActions.length > 0) {
      mergeActions(detailActions);
      return;
    }

    const actionPayload = await simulationApi.getActions(simulationId, { limit: 50 });
    const recentActions = actionPayload.actions.filter(
      (item): item is Record<string, unknown> => isRecord(item),
    );
    mergeActions(recentActions);
  }, [mergeActions, simulationId]);

  /* -- Derived status helpers ------------------------------ */

  const twitterRunning = Boolean(runStatus.twitter_running);
  const redditRunning = Boolean(runStatus.reddit_running);
  const currentRound = Number(runStatus.current_round ?? 0);
  const twitterRound = Number(runStatus.twitter_current_round ?? currentRound);
  const redditRound = Number(runStatus.reddit_current_round ?? currentRound);
  const totalRounds = Number(runStatus.total_rounds ?? maxRounds ?? 0);
  const progressPct = Number(runStatus.progress_percent ?? 0);
  const runnerState = String(runStatus.runner_status ?? 'idle');
  const errorSummary = summarizeRunError(runStatus.error);

  const twitterActions = Number(runStatus.twitter_actions_count ?? actions.filter((a) => a.platform === 'twitter').length);
  const redditActions = Number(runStatus.reddit_actions_count ?? actions.filter((a) => a.platform === 'reddit').length);

  /* -- Auto-scroll ----------------------------------------- */

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [actions.length]);

  /* -- Start simulation on mount --------------------------- */

  useEffect(() => {
    let cancelled = false;

    async function start() {
      if (!autoStartEnabled || phase !== 0 || isStarting) return;

      try {
        const existingStatus = await simulationApi.getRunStatus(simulationId);
        if (cancelled) return;

        setRunStatus(existingStatus as unknown as Record<string, unknown>);

        const runnerState = String(existingStatus.runner_status ?? '');
        const platformsRunning =
          Boolean(existingStatus.twitter_running) || Boolean(existingStatus.reddit_running);
        const hasRunProgress =
          Number(existingStatus.current_round ?? 0) > 0
          || Number(existingStatus.total_actions_count ?? 0) > 0;

        if (platformsRunning || runnerState === 'running' || runnerState === 'starting') {
          setPhase(1);
          return;
        }

        if (hasRunProgress && ['completed', 'failed', 'stopped'].includes(runnerState)) {
          setPhase(2);
          return;
        }
      } catch (err) {
        if (!cancelled) {
          console.error('[Step3] preflight status check failed', err);
        }
      }

      setIsStarting(true);

      let startRequest = autoStartRequests.get(autoStartRequestKey);
      if (!startRequest) {
        startRequest = simulationApi.startSimulation(simulationId, {
          maxRounds,
          enableGraphMemoryUpdate: true,
          force: true,
        }).finally(() => {
          autoStartRequests.delete(autoStartRequestKey);
        });
        autoStartRequests.set(autoStartRequestKey, startRequest);
      }

      try {
        const started = await startRequest;
        if (!cancelled) {
          setRunStatus(started as unknown as Record<string, unknown>);
          setPhase(1);
        }
      } catch (err) {
        console.error('[Step3] start failed', err);
      } finally {
        if (!cancelled) setIsStarting(false);
      }
    }

    start();
    return () => { cancelled = true; };
  }, [autoStartEnabled, autoStartRequestKey, isStarting, maxRounds, phase, simulationId]);

  /* -- Polling --------------------------------------------- */

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const status = await simulationApi.getRunStatus(simulationId);
        if (cancelled) return;

        setRunStatus(status as unknown as Record<string, unknown>);

        const runnerState = String(status.runner_status ?? '');
        const platformsRunning = Boolean(status.twitter_running) || Boolean(status.reddit_running);

        if (platformsRunning || runnerState === 'running' || runnerState === 'starting') {
          setPhase(1);
          setIsStarting(false);

          await hydrateActions();
          if (cancelled) return;
          return;
        }

        const hasVisibleRunOutput =
          Number(status.current_round ?? 0) > 0 || Number(status.total_actions_count ?? 0) > 0;
        if (hasVisibleRunOutput && actionIdsRef.current.size === 0) {
          await hydrateActions(true);
          if (cancelled) return;
        }

        if (!isStarting && ['completed', 'failed', 'stopped'].includes(runnerState)) {
          setPhase(2);
        }
      } catch (err) {
        if (!cancelled) {
          console.error('[Step3] poll error', err);
        }
      }
    };

    void poll();
    const intervalId = setInterval(() => {
      void poll();
    }, 2000);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [hydrateActions, isStarting, simulationId]);

  /* -- Stop simulation ------------------------------------- */

  const handleStop = useCallback(async () => {
    setIsStopping(true);
    try {
      await simulationApi.stopSimulation(simulationId);
      setPhase(2);
    } catch (err) {
      console.error('[Step3] stop failed', err);
    } finally {
      setIsStopping(false);
    }
  }, [simulationId]);

  /* -- Generate report ------------------------------------- */

  const handleGenerateReport = useCallback(async () => {
    setIsGenerating(true);
    try {
      const res = await reportApi.generateReport(simulationId);
      onGenerateReport(res.report_id);
    } catch (err) {
      console.error('[Step3] generate report failed', err);
    } finally {
      setIsGenerating(false);
    }
  }, [simulationId, onGenerateReport]);

  /* -- Platform card renderer ------------------------------ */

  function renderPlatformCard(
    name: string,
    icon: string,
    roundValue: number,
    running: boolean,
    actionCount: number,
  ) {
    const statusLabel = runnerState === 'failed'
      ? 'failed'
      : runnerState === 'stopped'
        ? 'stopped'
        : phase === 2
          ? 'completed'
          : running
            ? 'running'
            : 'idle';
    const dotClass =
      runnerState === 'failed'
        ? s.statusDotFailed
        : phase === 2 || runnerState === 'stopped'
          ? s.statusDotCompleted
          : running
            ? s.statusDotRunning
            : s.statusDotIdle;

    return (
      <div className={s.platformCard}>
        <div className={s.platformHeader}>
          <span className={s.platformIcon}>{icon}</span>
          <span className={s.platformName}>{name}</span>
          <span className={`${s.statusDot} ${dotClass}`} title={statusLabel} />
        </div>

        <div className={s.platformProgress}>
          <div className={s.progressTrack}>
            <div className={s.progressFill} style={{ width: `${Math.min(progressPct, 100)}%` }} />
          </div>
          <span className={s.progressPct}>{Math.round(progressPct)}%</span>
        </div>

        <div className={s.platformStats}>
          <div className={s.statItem}>
            <span className={s.statLabel}>Round</span>
            <span className={s.statValue}>{roundValue}/{totalRounds || '?'}</span>
          </div>
          <div className={s.statItem}>
            <span className={s.statLabel}>Actions</span>
            <span className={s.statValue}>{actionCount}</span>
          </div>
        </div>
      </div>
    );
  }

  /* -- Render ----------------------------------------------- */

  return (
    <div className={s.wrapper}>
      {/* Control bar */}
      <div className={s.controlBar}>
        {renderPlatformCard('Twitter', 'TW', twitterRound, twitterRunning, twitterActions)}
        {renderPlatformCard('Reddit', 'RD', redditRound, redditRunning, redditActions)}

        <div className={s.controlActions}>
          {phase === 1 && (
            <button
              className={s.dangerBtn}
              onClick={handleStop}
              disabled={isStopping}
            >
              {isStopping ? 'Stopping...' : 'Stop'}
            </button>
          )}
          {phase === 2 && runnerState === 'completed' && (
            <button
              className={s.successBtn}
              onClick={handleGenerateReport}
              disabled={isGenerating}
            >
              {isGenerating ? 'Generating...' : 'Generate Report ->'}
            </button>
          )}
          {phase === 2 && runnerState !== 'completed' && (
            <button className={s.dangerBtn} disabled>
              {runnerState === 'failed' ? 'Run Failed' : 'Stopped'}
            </button>
          )}
          {phase === 0 && (
            <button className={s.successBtn} disabled>
              {isStarting ? 'Starting...' : 'Waiting...'}
            </button>
          )}
        </div>
      </div>

      {errorSummary && ['failed', 'stopped'].includes(runnerState) && (
        <div className={s.errorBanner}>
          <div className={s.errorTitle}>Simulation stopped</div>
          <div className={s.errorText}>{errorSummary}</div>
        </div>
      )}

      {/* Action timeline */}
      <div className={s.timeline} ref={scrollRef}>
        {actions.length === 0 && (
          <div className={s.timelineEmpty}>
            {phase === 0
              ? 'Preparing simulation...'
              : errorSummary && ['failed', 'stopped'].includes(runnerState)
                ? 'Simulation stopped before more actions could be processed.'
                : 'Waiting for actions...'}
          </div>
        )}
        {actions.map((a, i) => {
          const key = compositeKey(a) || String(i);
          const actionType = String(a.action_type ?? '');
          return (
            <div key={key} className={s.actionItem}>
              <span className={s.roundBadge}>R{actionRound(a)}</span>
              <span className={s.platformEmoji}>{platformEmoji(String(a.platform ?? ''))}</span>
              <div className={s.actionMeta}>
                <div className={s.actionTop}>
                  <span className={s.agentName}>{String(a.agent_name ?? a.agent_id ?? 'Agent')}</span>
                  <span className={`${s.actionBadge} ${badgeClass(actionType)}`}>
                    {actionType.replace(/_/g, ' ')}
                  </span>
                </div>
                {actionContent(a) && (
                  <div className={s.actionContent}>{actionContent(a)}</div>
                )}
              </div>
              <span className={s.actionTimestamp}>{fmtTime(a.timestamp)}</span>
            </div>
          );
        })}
      </div>

      {/* System logs */}
      <SystemLog lines={systemLogs} maxHeight="180px" />
    </div>
  );
}
