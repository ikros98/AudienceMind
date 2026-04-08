import { useState, useEffect, useRef, useCallback } from 'react';
import * as simulationApi from '../../api/simulation';
import type { AgentProfile } from '../../types';
import StatusIndicator from '../StatusIndicator';
import SystemLog from '../SystemLog';
import shared from '../../styles/shared.module.css';
import s from '../../styles/steps.module.css';

interface Props {
  simulationId: string;
  projectData: { project_id?: string; name?: string } | null;
  systemLogs: string[];
  onStartSimulation: (maxRounds?: number) => void;
  onGoBack: () => void;
}

type Stage = 'idle' | 'preparing' | 'profiles' | 'config' | 'ready';

type SimulationProfile = AgentProfile & {
  profession?: string;
  interested_topics?: string[];
  entity_type?: string;
  bio?: string;
  description?: string;
};

type TimeConfig = {
  total_simulation_hours?: number;
  minutes_per_round?: number;
  agents_per_hour_min?: number;
  agents_per_hour_max?: number;
  peak_hours?: number[];
  peak_activity_multiplier?: number;
  off_peak_hours?: number[];
  off_peak_activity_multiplier?: number;
  morning_hours?: number[];
  morning_activity_multiplier?: number;
  work_hours?: number[];
  work_activity_multiplier?: number;
};

type PlatformAlgoConfig = {
  platform: 'twitter' | 'reddit';
  recency_weight?: number;
  popularity_weight?: number;
  relevance_weight?: number;
  viral_threshold?: number;
  echo_chamber_strength?: number;
};

type EventConfig = {
  narrative_direction?: string;
  hot_topics: string[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function readString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function readNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function readStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    : [];
}

function readNumberArray(value: unknown): number[] {
  return Array.isArray(value)
    ? value
        .map((item) => readNumber(item))
        .filter((item): item is number => typeof item === 'number')
    : [];
}

function normalizeProfiles(
  redditProfiles: Record<string, unknown>[],
  twitterProfiles: Record<string, unknown>[],
): SimulationProfile[] {
  const byUsername = new Map<string, SimulationProfile>();

  const applyProfiles = (
    items: Record<string, unknown>[],
    platform: 'reddit' | 'twitter',
  ) => {
    for (const raw of items) {
      const username =
        readString(raw.username) ??
        (readNumber(raw.user_id) !== undefined ? `agent_${readNumber(raw.user_id)}` : undefined);
      if (!username) continue;

      const current = byUsername.get(username);
      const next: SimulationProfile = {
        agent_id: readString(raw.agent_id) ?? current?.agent_id ?? username,
        name: readString(raw.name) ?? current?.name ?? username,
        username,
        platform: platform === 'reddit' ? 'reddit' : current?.platform ?? 'twitter',
        persona:
          readString(raw.persona) ??
          current?.persona ??
          readString(raw.description) ??
          '',
        bio:
          readString(raw.bio) ??
          current?.bio ??
          readString(raw.description),
        description:
          readString(raw.description) ??
          current?.description,
        profession:
          readString(raw.profession) ??
          current?.profession,
        entity_source:
          readString(raw.entity_source) ??
          current?.entity_source,
        entity_type:
          readString(raw.entity_type) ??
          current?.entity_type,
        interested_topics:
          readStringArray(raw.interested_topics).length > 0
            ? readStringArray(raw.interested_topics)
            : current?.interested_topics,
        profile_pic_url: current?.profile_pic_url,
      };

      byUsername.set(username, next);
    }
  };

  applyProfiles(twitterProfiles, 'twitter');
  applyProfiles(redditProfiles, 'reddit');

  return Array.from(byUsername.values()).sort((a, b) => a.username.localeCompare(b.username));
}

function parseTimeConfig(value: unknown): TimeConfig | null {
  if (!isRecord(value)) return null;
  return {
    total_simulation_hours: readNumber(value.total_simulation_hours),
    minutes_per_round: readNumber(value.minutes_per_round),
    agents_per_hour_min: readNumber(value.agents_per_hour_min),
    agents_per_hour_max: readNumber(value.agents_per_hour_max),
    peak_hours: readNumberArray(value.peak_hours),
    peak_activity_multiplier: readNumber(value.peak_activity_multiplier),
    off_peak_hours: readNumberArray(value.off_peak_hours),
    off_peak_activity_multiplier: readNumber(value.off_peak_activity_multiplier),
    morning_hours: readNumberArray(value.morning_hours),
    morning_activity_multiplier: readNumber(value.morning_activity_multiplier),
    work_hours: readNumberArray(value.work_hours),
    work_activity_multiplier: readNumber(value.work_activity_multiplier),
  };
}

function parsePlatformConfig(
  value: unknown,
  platform: 'twitter' | 'reddit',
): PlatformAlgoConfig | null {
  if (!isRecord(value)) return null;
  return {
    platform,
    recency_weight: readNumber(value.recency_weight),
    popularity_weight: readNumber(value.popularity_weight),
    relevance_weight: readNumber(value.relevance_weight),
    viral_threshold: readNumber(value.viral_threshold),
    echo_chamber_strength: readNumber(value.echo_chamber_strength),
  };
}

function parseEventConfig(value: unknown): EventConfig | null {
  if (!isRecord(value)) return null;
  return {
    narrative_direction: readString(value.narrative_direction),
    hot_topics: readStringArray(value.hot_topics),
  };
}

function formatHourRange(hours?: number[]): string {
  if (!hours || hours.length === 0) return '-';
  return hours.map((hour) => `${hour}:00`).join(', ');
}

function formatMultiplier(value?: number): string {
  return value !== undefined ? `x${value}` : '-';
}

function roundLabel(value?: number, suffix = ''): string {
  return value !== undefined ? `${value}${suffix}` : '-';
}

function formatDurationEstimate(totalMinutes: number | null): string {
  if (totalMinutes === null || !Number.isFinite(totalMinutes) || totalMinutes <= 0) return '-';
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours > 0 && minutes > 0) return `~${hours}h ${minutes}m`;
  if (hours > 0) return `~${hours}h`;
  return `~${minutes} min`;
}

function ProfileModal({
  profile,
  onClose,
}: {
  profile: SimulationProfile;
  onClose: () => void;
}) {
  const persona = profile.persona || profile.description || 'No persona available';

  return (
    <div className={s.modalOverlay} onClick={onClose}>
      <div className={s.modal} onClick={(e) => e.stopPropagation()}>
        <div className={s.modalClose}>
          <button className={s.modalCloseBtn} onClick={onClose}>
            x
          </button>
        </div>
        <div className={s.profileAvatar} style={{ width: 48, height: 48, fontSize: '1rem' }}>
          {profile.name.charAt(0).toUpperCase()}
        </div>
        <div className={s.modalName}>{profile.name}</div>
        <div className={s.modalUsername}>@{profile.username}</div>

        <div className={s.modalLabel}>Source</div>
        <div className={s.modalText}>{profile.platform}</div>

        {profile.profession && (
          <>
            <div className={s.modalLabel}>Profession</div>
            <div className={s.modalText}>{profile.profession}</div>
          </>
        )}

        <div className={s.modalLabel}>Persona</div>
        <div className={s.modalText}>{persona}</div>

        {profile.bio && (
          <>
            <div className={s.modalLabel}>Bio</div>
            <div className={s.modalText}>{profile.bio}</div>
          </>
        )}

        {profile.interested_topics && profile.interested_topics.length > 0 && (
          <>
            <div className={s.modalLabel}>Topics</div>
            <div className={s.tagList}>
              {profile.interested_topics.map((topic) => (
                <span key={topic} className={`${s.tag} ${s.tagEntity}`}>
                  {topic}
                </span>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function Step2EnvSetup({
  simulationId,
  projectData,
  systemLogs,
  onStartSimulation,
  onGoBack,
}: Props) {
  const [stage, setStage] = useState<Stage>('idle');
  const [prepareProgress, setPrepareProgress] = useState(0);
  const [prepareMessage, setPrepareMessage] = useState('');
  const [profiles, setProfiles] = useState<SimulationProfile[]>([]);
  const [expectedProfileCount, setExpectedProfileCount] = useState<number | null>(null);
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [selectedProfile, setSelectedProfile] = useState<SimulationProfile | null>(null);
  const [showProfilesDetail, setShowProfilesDetail] = useState(false);
  const [customRounds, setCustomRounds] = useState(false);
  const [roundCount, setRoundCount] = useState(40);
  const [error, setError] = useState<string | null>(null);

  const taskIdRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const pollPrepareStatus = useCallback(async (taskId: string) => {
    const poll = async () => {
      if (!mountedRef.current) return;
      try {
        const status = await simulationApi.getPrepareStatus(taskId, simulationId);
        if (!mountedRef.current) return;

        setPrepareProgress(status.progress);
        setPrepareMessage(status.message);

        if (
          status.status === 'completed' ||
          status.status === 'ready' ||
          status.already_prepared ||
          status.progress >= 100
        ) {
          setStage('profiles');
          return;
        }
        if (status.status === 'failed') {
          setError(status.message || 'Preparation failed');
          return;
        }

        const currentStage = status.progress_detail?.current_stage_name ?? '';
        if (currentStage.toLowerCase().includes('profile')) {
          setStage('profiles');
        }

        setTimeout(poll, 2000);
      } catch {
        if (mountedRef.current) setTimeout(poll, 3000);
      }
    };
    poll();
  }, [simulationId]);

  const pollProfiles = useCallback(async () => {
    const poll = async () => {
      if (!mountedRef.current) return;
      try {
        const [reddit, twitter] = await Promise.all([
          simulationApi.getProfilesRealtime(simulationId, 'reddit'),
          simulationApi.getProfilesRealtime(simulationId, 'twitter'),
        ]);
        if (!mountedRef.current) return;

        const canonicalProfiles = normalizeProfiles(reddit.profiles, twitter.profiles);
        setProfiles(canonicalProfiles);
        setExpectedProfileCount(
          reddit.total_expected ??
            twitter.total_expected ??
            canonicalProfiles.length,
        );

        if (!reddit.generation_active && !twitter.generation_active) {
          setStage('config');
          return;
        }
        setTimeout(poll, 3000);
      } catch {
        if (mountedRef.current) setTimeout(poll, 3000);
      }
    };
    poll();
  }, [simulationId]);

  const pollConfig = useCallback(async () => {
    const poll = async () => {
      if (!mountedRef.current) return;
      try {
        const result = await simulationApi.getConfigRealtime(simulationId);
        if (!mountedRef.current) return;

        setConfig(result.config);
        if (!result.generation_active) {
          setStage('ready');
          return;
        }
        setTimeout(poll, 5000);
      } catch {
        if (mountedRef.current) setTimeout(poll, 5000);
      }
    };
    poll();
  }, [simulationId]);

  useEffect(() => {
    if (stage === 'profiles') pollProfiles();
  }, [stage, pollProfiles]);

  useEffect(() => {
    if (stage === 'config') pollConfig();
  }, [stage, pollConfig]);

  useEffect(() => {
    let cancelled = false;

    async function start() {
      try {
        setStage('preparing');
        const res = await simulationApi.prepareSimulation(simulationId);
        if (cancelled) return;

        if (res.expected_entities_count !== undefined) {
          setExpectedProfileCount(res.expected_entities_count);
        }

        if (res.already_prepared || res.status === 'ready') {
          setStage('profiles');
          return;
        }

        if (res.task_id) {
          taskIdRef.current = res.task_id;
          pollPrepareStatus(res.task_id);
        } else {
          setStage('profiles');
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to start preparation');
        }
      }
    }

    start();
    return () => {
      cancelled = true;
    };
  }, [simulationId, pollPrepareStatus]);

  const timeConfig = parseTimeConfig(config?.time_config);
  const twitterConfig = parsePlatformConfig(config?.twitter_config, 'twitter');
  const redditConfig = parsePlatformConfig(config?.reddit_config, 'reddit');
  const eventConfig = parseEventConfig(config?.event_config);
  const configReasoning = readString(config?.generation_reasoning);

  const derivedRounds =
    timeConfig?.total_simulation_hours && timeConfig?.minutes_per_round
      ? Math.floor(
          (timeConfig.total_simulation_hours * 60) / timeConfig.minutes_per_round,
        )
      : null;
  const previewSuggestedRounds =
    derivedRounds !== null ? Math.max(10, Math.min(derivedRounds, 40)) : 40;
  const maxCustomRounds =
    derivedRounds !== null ? Math.max(derivedRounds, 10) : 100;
  const platformCount = Number(Boolean(twitterConfig)) + Number(Boolean(redditConfig));
  const totalTopicsCount = profiles.reduce(
    (sum, profile) => sum + (profile.interested_topics?.length ?? 0),
    0,
  );
  const selectedRounds = customRounds ? roundCount : derivedRounds;
  const currentAgentEstimateMinutes =
    selectedRounds !== null && profiles.length > 0
      ? Math.max(1, Math.round((selectedRounds * 0.6 * profiles.length) / 100))
      : null;
  const standardBaselineEstimateMinutes =
    selectedRounds !== null
      ? Math.max(1, Math.round(selectedRounds * 0.6))
      : null;

  useEffect(() => {
    if (derivedRounds === null) return;
    setRoundCount((current) => Math.min(Math.max(current, 10), maxCustomRounds));
  }, [derivedRounds, maxCustomRounds]);

  const showConfig = (stage === 'config' || stage === 'ready') && config;

  return (
    <div className={s.stepContainer}>
      <div className={s.stepCard}>
        <div className={s.stepHeader}>
          <span className={s.stepNumber}>01</span>
          <span className={s.stepTitle}>Simulation Instance</span>
          <StatusIndicator status="completed" />
        </div>
        <div className={s.stepBody}>
          <div className={s.idRow}>
            <span className={s.idLabel}>Project</span>
            <span className={s.idValue}>{projectData?.project_id ?? '-'}</span>
          </div>
          <div className={s.idRow}>
            <span className={s.idLabel}>Simulation</span>
            <span className={s.idValue}>{simulationId}</span>
          </div>
        </div>
      </div>

      {stage !== 'idle' && (
        <div className={s.stepCard}>
          <div className={s.stepHeader}>
            <span className={s.stepNumber}>02</span>
            <span className={s.stepTitle}>Agent Profiles</span>
            <StatusIndicator
              status={
                stage === 'preparing'
                  ? 'processing'
                  : stage === 'profiles'
                    ? 'processing'
                    : 'completed'
              }
            />
          </div>
          <div className={s.stepBody}>
            {stage === 'preparing' && (
              <>
                <div className={shared.progressBar}>
                  <div
                    className={shared.progressFill}
                    style={{ width: `${prepareProgress}%` }}
                  />
                </div>
                <div className={s.progressMessage}>
                  <span className={s.progressPercent}>{prepareProgress}%</span>
                  <span>{prepareMessage || 'Preparing simulation...'}</span>
                </div>
              </>
            )}

            {profiles.length > 0 && (
              <>
                <div className={s.statsGrid}>
                  <div className={s.statCard}>
                    <div className={s.statValue}>{profiles.length}</div>
                    <div className={s.statLabel}>Personas</div>
                  </div>
                  <div className={s.statCard}>
                    <div className={s.statValue}>{expectedProfileCount ?? profiles.length}</div>
                    <div className={s.statLabel}>Expected</div>
                  </div>
                  <div className={s.statCard}>
                    <div className={s.statValue}>{totalTopicsCount}</div>
                    <div className={s.statLabel}>Related Topics</div>
                  </div>
                </div>

                <div className={s.sectionHeader}>
                  <div>
                    <div className={s.sectionTitle}>Generated Personas</div>
                    <div className={s.sectionSubtitle}>
                      Hidden by default. Expand only when you want to inspect individual profiles.
                    </div>
                  </div>
                  <button
                    type="button"
                    className={s.expandButton}
                    aria-expanded={showProfilesDetail}
                    onClick={() => setShowProfilesDetail((value) => !value)}
                  >
                    <span>{showProfilesDetail ? 'Hide Profiles' : 'Show Profiles'}</span>
                    <svg
                      className={`${s.expandIcon} ${showProfilesDetail ? s.expandIconOpen : ''}`}
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </button>
                </div>

                {showProfilesDetail && (
                  <div className={`${s.collapsiblePanel} ${s.collapsiblePanelOpen}`}>
                    <div className={s.collapsibleInner}>
                      <div className={s.profilesHint}>
                        Click any card to inspect the full persona definition.
                      </div>
                      <div className={s.profilesScroller}>
                        <div className={s.profileGrid}>
                          {profiles.map((profile) => (
                            <div
                              key={profile.agent_id ?? profile.username}
                              className={s.profileCard}
                              onClick={() => setSelectedProfile(profile)}
                            >
                              <div className={s.profileAvatar}>
                                {profile.name.charAt(0).toUpperCase()}
                              </div>
                              <div className={s.profilePlatform}>
                                {profile.entity_type ?? 'Persona'}
                              </div>
                              <div className={s.profileName}>{profile.name}</div>
                              <div className={s.profileUsername}>@{profile.username}</div>
                              {profile.profession && (
                                <div className={s.profileProfession}>{profile.profession}</div>
                              )}
                              <div className={s.profilePersona}>
                                {profile.bio || profile.persona || profile.description || 'No bio available'}
                              </div>
                              {profile.interested_topics && profile.interested_topics.length > 0 && (
                                <div className={s.profileTopics}>
                                  {profile.interested_topics.slice(0, 3).map((topic) => (
                                    <span key={topic} className={s.topicChip}>
                                      {topic}
                                    </span>
                                  ))}
                                  {profile.interested_topics.length > 3 && (
                                    <span className={s.topicMore}>
                                      +{profile.interested_topics.length - 3}
                                    </span>
                                  )}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {showConfig && (
        <div className={s.stepCard}>
          <div className={s.stepHeader}>
            <span className={s.stepNumber}>03</span>
            <span className={s.stepTitle}>Simulation Config</span>
            <StatusIndicator status={stage === 'ready' ? 'completed' : 'processing'} />
          </div>
          <div className={s.stepBody}>
            <div className={s.statsGrid}>
              <div className={s.statCard}>
                <div className={s.statValue}>{roundLabel(timeConfig?.total_simulation_hours)}</div>
                <div className={s.statLabel}>Hours</div>
              </div>
              <div className={s.statCard}>
                <div className={s.statValue}>{roundLabel(timeConfig?.minutes_per_round)}</div>
                <div className={s.statLabel}>Minutes / Round</div>
              </div>
              <div className={s.statCard}>
                <div className={s.statValue}>{derivedRounds ?? '-'}</div>
                <div className={s.statLabel}>Total Rounds</div>
              </div>
              <div className={s.statCard}>
                <div className={s.statValue}>
                  {timeConfig?.agents_per_hour_min !== undefined &&
                  timeConfig?.agents_per_hour_max !== undefined
                    ? `${timeConfig.agents_per_hour_min}-${timeConfig.agents_per_hour_max}`
                    : '-'}
                </div>
                <div className={s.statLabel}>Agents / Hour</div>
              </div>
            </div>

            <div className={s.configSection}>
              <div className={s.configRow}>
                <span className={s.configLabel}>Peak Hours</span>
                <span className={s.configValue}>
                  {formatHourRange(timeConfig?.peak_hours)} / {formatMultiplier(timeConfig?.peak_activity_multiplier)}
                </span>
              </div>
              <div className={s.configRow}>
                <span className={s.configLabel}>Work Hours</span>
                <span className={s.configValue}>
                  {formatHourRange(timeConfig?.work_hours)} / {formatMultiplier(timeConfig?.work_activity_multiplier)}
                </span>
              </div>
              <div className={s.configRow}>
                <span className={s.configLabel}>Morning Hours</span>
                <span className={s.configValue}>
                  {formatHourRange(timeConfig?.morning_hours)} / {formatMultiplier(timeConfig?.morning_activity_multiplier)}
                </span>
              </div>
              <div className={s.configRow}>
                <span className={s.configLabel}>Off-Peak Hours</span>
                <span className={s.configValue}>
                  {formatHourRange(timeConfig?.off_peak_hours)} / {formatMultiplier(timeConfig?.off_peak_activity_multiplier)}
                </span>
              </div>
            </div>

            <div className={s.platformGrid}>
              {twitterConfig && (
                <div className={s.platformCard}>
                  <div className={s.platformName}>
                    <span className={s.platformIcon}>X</span> Twitter
                  </div>
                  <div className={s.platformConfigRows}>
                    <div className={s.configRow}>
                      <span className={s.configLabel}>Recency</span>
                      <span className={s.configValue}>{roundLabel(twitterConfig.recency_weight)}</span>
                    </div>
                    <div className={s.configRow}>
                      <span className={s.configLabel}>Popularity</span>
                      <span className={s.configValue}>{roundLabel(twitterConfig.popularity_weight)}</span>
                    </div>
                    <div className={s.configRow}>
                      <span className={s.configLabel}>Relevance</span>
                      <span className={s.configValue}>{roundLabel(twitterConfig.relevance_weight)}</span>
                    </div>
                    <div className={s.configRow}>
                      <span className={s.configLabel}>Viral Threshold</span>
                      <span className={s.configValue}>{roundLabel(twitterConfig.viral_threshold)}</span>
                    </div>
                    <div className={s.configRow}>
                      <span className={s.configLabel}>Echo Chamber</span>
                      <span className={s.configValue}>{roundLabel(twitterConfig.echo_chamber_strength)}</span>
                    </div>
                  </div>
                </div>
              )}

              {redditConfig && (
                <div className={s.platformCard}>
                  <div className={s.platformName}>
                    <span className={s.platformIcon}>R</span> Reddit
                  </div>
                  <div className={s.platformConfigRows}>
                    <div className={s.configRow}>
                      <span className={s.configLabel}>Recency</span>
                      <span className={s.configValue}>{roundLabel(redditConfig.recency_weight)}</span>
                    </div>
                    <div className={s.configRow}>
                      <span className={s.configLabel}>Popularity</span>
                      <span className={s.configValue}>{roundLabel(redditConfig.popularity_weight)}</span>
                    </div>
                    <div className={s.configRow}>
                      <span className={s.configLabel}>Relevance</span>
                      <span className={s.configValue}>{roundLabel(redditConfig.relevance_weight)}</span>
                    </div>
                    <div className={s.configRow}>
                      <span className={s.configLabel}>Viral Threshold</span>
                      <span className={s.configValue}>{roundLabel(redditConfig.viral_threshold)}</span>
                    </div>
                    <div className={s.configRow}>
                      <span className={s.configLabel}>Echo Chamber</span>
                      <span className={s.configValue}>{roundLabel(redditConfig.echo_chamber_strength)}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {eventConfig?.narrative_direction && (
              <div className={s.narrativePanel}>
                <div className={s.sectionTitle}>Narrative Direction</div>
                <div className={s.sectionSubtitle}>{eventConfig.narrative_direction}</div>
              </div>
            )}

            {eventConfig?.hot_topics && eventConfig.hot_topics.length > 0 && (
              <div className={s.topicSection}>
                <div className={s.sectionTitle}>Hot Topics</div>
                <div className={s.profileTopics}>
                  {eventConfig.hot_topics.map((topic) => (
                    <span key={topic} className={s.topicChip}>
                      #{topic}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {configReasoning && (
              <div className={s.configSection}>
                <div className={s.sectionTitle}>LLM Reasoning</div>
                <div className={s.sectionSubtitle}>
                  {configReasoning.split('|').slice(0, 2).map((part) => part.trim()).join(' | ')}
                </div>
              </div>
            )}

            <div className={s.configSection}>
              <div className={s.toggleRow}>
                <button
                  type="button"
                  className={s.toggle}
                  data-active={customRounds}
                  onClick={() => {
                    setCustomRounds((value) => !value);
                    setRoundCount((current) =>
                      Math.min(Math.max(current, 10), maxCustomRounds || previewSuggestedRounds),
                    );
                  }}
                  aria-pressed={customRounds}
                >
                  <span className={s.toggleKnob} />
                </button>
                <div>
                  <div className={s.sectionTitle}>Custom Round Cap</div>
                  <div className={s.sectionSubtitle}>
                    {derivedRounds !== null
                      ? `Auto mode follows the generated plan of ${derivedRounds} rounds from ${timeConfig?.total_simulation_hours ?? '-'} simulated hours at ${timeConfig?.minutes_per_round ?? '-'} minutes per round. The preview baseline typically highlights ${previewSuggestedRounds} rounds as the quick cap.`
                      : 'Use a custom round cap only when you want a shorter preview run.'}
                  </div>
                </div>
              </div>

              <div className={s.configSection}>
                <div className={s.configRow}>
                  <span className={s.configLabel}>Preview Suggestion</span>
                  <span className={s.configValue}>{previewSuggestedRounds} rounds</span>
                </div>
                <div className={s.configRow}>
                  <span className={s.configLabel}>Current Runtime Estimate</span>
                  <span className={s.configValue}>
                    {formatDurationEstimate(currentAgentEstimateMinutes)}
                    {profiles.length > 0 ? ` for ${profiles.length} personas` : ''}
                  </span>
                </div>
                <div className={s.configRow}>
                  <span className={s.configLabel}>100-Persona Baseline</span>
                  <span className={s.configValue}>
                    {formatDurationEstimate(standardBaselineEstimateMinutes)} for 100 personas
                  </span>
                </div>
              </div>

              {customRounds ? (
                <>
                  <div className={s.progressMessage}>
                    <span className={s.progressPercent}>{roundCount}</span>
                    <span>
                      Recommended for first runs: {previewSuggestedRounds} rounds
                    </span>
                  </div>
                  <div className={s.toggleRow}>
                    <input
                      type="range"
                      min="10"
                      max={String(maxCustomRounds)}
                      step="5"
                      className={s.slider}
                      value={roundCount}
                      onChange={(e) => setRoundCount(Number(e.target.value))}
                    />
                    <span className={s.sliderValue}>{roundCount}</span>
                  </div>
                </>
              ) : (
                <div className={s.progressMessage}>
                  <span className={s.progressPercent}>{derivedRounds ?? 'Auto'}</span>
                  <span>
                    Start with the generated simulation plan. Rough runtime: {formatDurationEstimate(currentAgentEstimateMinutes)}.
                  </span>
                </div>
              )}
            </div>

            <div className={s.buttonRow}>
              <button className={s.secondaryBtn} onClick={onGoBack}>
                Back
              </button>
              <button
                className={s.primaryBtn}
                onClick={() => onStartSimulation(customRounds ? roundCount : undefined)}
                disabled={platformCount === 0}
              >
                Start Simulation
              </button>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className={s.stepCard} style={{ borderColor: '#f87171' }}>
          <div className={s.stepBody} style={{ color: '#f87171' }}>
            {error}
          </div>
        </div>
      )}

      <SystemLog lines={systemLogs} />

      {selectedProfile && (
        <ProfileModal
          profile={selectedProfile}
          onClose={() => setSelectedProfile(null)}
        />
      )}
    </div>
  );
}
