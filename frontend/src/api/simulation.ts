import client, { unwrap } from './client';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/* -- List / History ------------------------------------------------- */

export interface SimulationHistoryEntry {
  simulation_id: string;
  project_id?: string | null;
  report_id?: string | null;
  graph_id?: string | null;
  status?: string;
  [key: string]: unknown;
}

export async function getSimulationHistory(): Promise<SimulationHistoryEntry[]> {
  const { data } = await client.get('/api/simulation/history');
  return unwrap(data);
}

export async function findSimulationHistoryEntry(
  opts: { simulationId?: string; reportId?: string },
): Promise<SimulationHistoryEntry | undefined> {
  const history = await getSimulationHistory();

  return history.find((entry) => {
    if (opts.reportId && entry.report_id === opts.reportId) return true;
    if (opts.simulationId && entry.simulation_id === opts.simulationId) return true;
    return false;
  });
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function getSimulationList(): Promise<any[]> {
  const { data } = await client.get('/api/simulation/list');
  return unwrap(data);
}

/* -- Create --------------------------------------------------------- */

export async function createSimulation(
  projectId: string,
  opts?: { graphId?: string; enableTwitter?: boolean; enableReddit?: boolean },
): Promise<{
  simulation_id: string;
  project_id: string;
  graph_id: string;
  status: string;
  enable_twitter: boolean;
  enable_reddit: boolean;
  created_at: string;
}> {
  const { data } = await client.post('/api/simulation/create', {
    project_id: projectId,
    graph_id: opts?.graphId,
    enable_twitter: opts?.enableTwitter ?? true,
    enable_reddit: opts?.enableReddit ?? true,
  });
  return unwrap(data);
}

/* -- Prepare (generate profiles & config) --------------------------- */

export async function prepareSimulation(
  simulationId: string,
  opts?: {
    entityTypes?: string[];
    useLlmForProfiles?: boolean;
    parallelProfileCount?: number;
    forceRegenerate?: boolean;
  },
): Promise<{
  simulation_id: string;
  task_id?: string;
  status: string;
  message: string;
  already_prepared: boolean;
  expected_entities_count?: number;
}> {
  const { data } = await client.post('/api/simulation/prepare', {
    simulation_id: simulationId,
    entity_types: opts?.entityTypes,
    use_llm_for_profiles: opts?.useLlmForProfiles ?? true,
    parallel_profile_count: opts?.parallelProfileCount ?? 5,
    force_regenerate: opts?.forceRegenerate ?? false,
  });
  return unwrap(data);
}

/* -- Preparation status --------------------------------------------- */

export async function getPrepareStatus(
  taskId?: string,
  simulationId?: string,
): Promise<{
  task_id: string;
  simulation_id: string;
  status: string;
  progress: number;
  message: string;
  progress_detail?: {
    current_stage: string;
    current_stage_name: string;
    stage_index: number;
    total_stages: number;
    stage_progress: number;
    current_item: number;
    total_items: number;
    item_description: string;
  };
  already_prepared: boolean;
}> {
  const { data } = await client.post('/api/simulation/prepare/status', {
    task_id: taskId,
    simulation_id: simulationId,
  });
  return unwrap(data);
}

/* -- Profiles ------------------------------------------------------- */

export async function getProfiles(
  simulationId: string,
  platform: 'reddit' | 'twitter' = 'reddit',
): Promise<{
  platform: string;
  count: number;
  profiles: Record<string, unknown>[];
}> {
  const { data } = await client.get(
    `/api/simulation/${simulationId}/profiles`,
    { params: { platform } },
  );
  return unwrap(data);
}

export async function getProfilesRealtime(
  simulationId: string,
  platform: 'reddit' | 'twitter' = 'reddit',
): Promise<{
  platform: string;
  count: number;
  generated_count: number;
  total_expected: number | null;
  profiles: Record<string, unknown>[];
  generation_active: boolean;
  file_mtime: number;
}> {
  const { data } = await client.get(
    `/api/simulation/${simulationId}/profiles/realtime`,
    { params: { platform } },
  );
  const raw = unwrap<unknown>(data);
  const parsed = isRecord(raw) ? raw : {};
  const fileModifiedAt =
    typeof parsed.file_modified_at === 'string' ? Date.parse(parsed.file_modified_at) : 0;
  return {
    platform: typeof parsed.platform === 'string' ? parsed.platform : platform,
    count: typeof parsed.count === 'number' ? parsed.count : 0,
    generated_count:
      typeof parsed.generated_count === 'number'
        ? parsed.generated_count
        : typeof parsed.count === 'number'
          ? parsed.count
          : 0,
    total_expected:
      typeof parsed.total_expected === 'number' ? parsed.total_expected : null,
    profiles: Array.isArray(parsed.profiles)
      ? parsed.profiles.filter((item): item is Record<string, unknown> => isRecord(item))
      : [],
    generation_active:
      typeof parsed.generation_active === 'boolean'
        ? parsed.generation_active
        : Boolean(parsed.is_generating),
    file_mtime:
      typeof parsed.file_mtime === 'number'
        ? parsed.file_mtime
        : Number.isFinite(fileModifiedAt)
          ? fileModifiedAt
          : 0,
  };
}

/* -- Config --------------------------------------------------------- */

export async function getConfig(
  simulationId: string,
): Promise<Record<string, unknown>> {
  const { data } = await client.get(
    `/api/simulation/${simulationId}/config`,
  );
  return unwrap(data);
}

export async function getConfigRealtime(
  simulationId: string,
): Promise<{ config: Record<string, unknown>; generation_active: boolean; file_mtime: number }> {
  const { data } = await client.get(
    `/api/simulation/${simulationId}/config/realtime`,
  );
  const raw = unwrap<unknown>(data);
  const parsed = isRecord(raw) ? raw : {};
  const fileModifiedAt =
    typeof parsed.file_modified_at === 'string' ? Date.parse(parsed.file_modified_at) : 0;
  return {
    config: isRecord(parsed.config) ? parsed.config : {},
    generation_active:
      typeof parsed.generation_active === 'boolean'
        ? parsed.generation_active
        : Boolean(parsed.is_generating),
    file_mtime:
      typeof parsed.file_mtime === 'number'
        ? parsed.file_mtime
        : Number.isFinite(fileModifiedAt)
          ? fileModifiedAt
          : 0,
  };
}

/* -- Start / Stop --------------------------------------------------- */

export async function startSimulation(
  simulationId: string,
  opts?: {
    platform?: 'twitter' | 'reddit' | 'parallel';
    maxRounds?: number;
    enableGraphMemoryUpdate?: boolean;
    force?: boolean;
  },
): Promise<{
  simulation_id: string;
  runner_status: string;
  process_pid: number;
  twitter_running: boolean;
  reddit_running: boolean;
  started_at: string;
  platform?: string;
  max_rounds_applied?: number;
}> {
  const { data } = await client.post('/api/simulation/start', {
    simulation_id: simulationId,
    platform: opts?.platform ?? 'parallel',
    max_rounds: opts?.maxRounds,
    enable_graph_memory_update: opts?.enableGraphMemoryUpdate ?? false,
    force: opts?.force ?? false,
  });
  return unwrap(data);
}

export async function stopSimulation(
  simulationId: string,
): Promise<{
  simulation_id: string;
  runner_status: string;
  stopped_at: string;
  final_round: number;
  total_rounds: number;
}> {
  const { data } = await client.post('/api/simulation/stop', {
    simulation_id: simulationId,
  });
  return unwrap(data);
}

/* -- Run status ----------------------------------------------------- */

export async function getRunStatus(
  simulationId: string,
): Promise<{
  simulation_id: string;
  runner_status: string;
  current_round: number;
  total_rounds: number;
  minutes_per_round?: number;
  simulated_hours?: number;
  total_simulation_hours?: number;
  progress_percent: number;
  twitter_current_round?: number;
  reddit_current_round?: number;
  twitter_simulated_hours?: number;
  reddit_simulated_hours?: number;
  twitter_running: boolean;
  reddit_running: boolean;
  twitter_completed?: boolean;
  reddit_completed?: boolean;
  twitter_actions_count?: number;
  reddit_actions_count?: number;
  total_actions_count?: number;
  started_at?: string;
  completed_at?: string;
  process_pid?: number;
  error?: string;
}> {
  const { data } = await client.get(
    `/api/simulation/${simulationId}/run-status`,
  );
  return unwrap(data);
}

export async function getRunStatusDetail(
  simulationId: string,
): Promise<{
  simulation_id: string;
  runner_status: string;
  current_round: number;
  total_rounds: number;
  minutes_per_round?: number;
  simulated_hours?: number;
  twitter_current_round?: number;
  reddit_current_round?: number;
  progress_percent: number;
  recent_actions: Record<string, unknown>[];
}> {
  const { data } = await client.get(
    `/api/simulation/${simulationId}/run-status/detail`,
  );
  const raw = unwrap<unknown>(data);
  const parsed = isRecord(raw) ? raw : {};
  const recentActions = Array.isArray(parsed.recent_actions)
    ? parsed.recent_actions
    : [];
  const allActions = Array.isArray(parsed.all_actions)
    ? parsed.all_actions
    : [];
  const visibleActions = recentActions.length > 0
    ? recentActions
    : allActions.slice(-50);
  return {
    simulation_id:
      typeof parsed.simulation_id === 'string' ? parsed.simulation_id : simulationId,
    runner_status:
      typeof parsed.runner_status === 'string' ? parsed.runner_status : 'idle',
    current_round:
      typeof parsed.current_round === 'number' ? parsed.current_round : 0,
    total_rounds:
      typeof parsed.total_rounds === 'number' ? parsed.total_rounds : 0,
    progress_percent:
      typeof parsed.progress_percent === 'number' ? parsed.progress_percent : 0,
    recent_actions: visibleActions.filter(
      (item): item is Record<string, unknown> => isRecord(item),
    ),
  };
}

/* -- Posts / Comments / Actions -------------------------------------- */

export async function getPosts(
  simulationId: string,
  opts?: { platform?: string; limit?: number; offset?: number },
): Promise<{ count: number; total: number; posts: Record<string, unknown>[] }> {
  const { data } = await client.get(
    `/api/simulation/${simulationId}/posts`,
    { params: { platform: opts?.platform ?? 'reddit', limit: opts?.limit ?? 50, offset: opts?.offset ?? 0 } },
  );
  return unwrap(data);
}

export async function getComments(
  simulationId: string,
  opts?: { platform?: string; limit?: number; offset?: number },
): Promise<{ count: number; total: number; comments: Record<string, unknown>[] }> {
  const { data } = await client.get(
    `/api/simulation/${simulationId}/comments`,
    { params: { platform: opts?.platform ?? 'reddit', limit: opts?.limit ?? 50, offset: opts?.offset ?? 0 } },
  );
  return unwrap(data);
}

export async function getActions(
  simulationId: string,
  opts?: { limit?: number; offset?: number; platform?: string; agentId?: string; roundNum?: number },
): Promise<{ count: number; total: number; actions: Record<string, unknown>[] }> {
  const { data } = await client.get(
    `/api/simulation/${simulationId}/actions`,
    {
      params: {
        limit: opts?.limit ?? 50,
        offset: opts?.offset ?? 0,
        platform: opts?.platform,
        agent_id: opts?.agentId,
        round_num: opts?.roundNum,
      },
    },
  );
  return unwrap(data);
}

/* -- Timeline / Agent stats ----------------------------------------- */

export async function getTimeline(
  simulationId: string,
  opts?: { startRound?: number; endRound?: number },
): Promise<{ timeline: Record<string, unknown>[] }> {
  const { data } = await client.get(
    `/api/simulation/${simulationId}/timeline`,
    { params: { start_round: opts?.startRound ?? 0, end_round: opts?.endRound } },
  );
  return unwrap(data);
}

export async function getAgentStats(
  simulationId: string,
): Promise<{ total_agents: number; agents: Record<string, unknown>[] }> {
  const { data } = await client.get(
    `/api/simulation/${simulationId}/agent-stats`,
  );
  return unwrap(data);
}

/* -- Interview ------------------------------------------------------ */

export async function interviewBatch(
  simulationId: string,
  interviews: { agent_id: string; prompt: string; platform?: 'twitter' | 'reddit' }[],
  opts?: { platform?: 'twitter' | 'reddit' },
): Promise<{
  simulation_id: string;
  interview_results: {
    agent_id: string;
    agent_name?: string;
    platform?: string;
    response: string;
    confidence: number;
  }[];
}> {
  const { data } = await client.post('/api/simulation/interview/batch', {
    simulation_id: simulationId,
    interviews,
    platform: opts?.platform,
  });
  return unwrap(data);
}

export async function interviewSingle(
  simulationId: string,
  payload: { agent_id: string; prompt: string; platform?: 'twitter' | 'reddit' },
): Promise<Record<string, unknown>> {
  const { data } = await client.post('/api/simulation/interview', {
    simulation_id: simulationId,
    ...payload,
  });
  return unwrap(data);
}

export async function interviewAll(
  simulationId: string,
  payload: { prompt: string; platform?: 'twitter' | 'reddit' },
): Promise<Record<string, unknown>> {
  const { data } = await client.post('/api/simulation/interview/all', {
    simulation_id: simulationId,
    ...payload,
  });
  return unwrap(data);
}

export async function getInterviewHistory(
  simulationId: string,
  opts?: { platform?: 'twitter' | 'reddit'; agentId?: string; limit?: number },
): Promise<{ count: number; history: Record<string, unknown>[] }> {
  const { data } = await client.post('/api/simulation/interview/history', {
    simulation_id: simulationId,
    platform: opts?.platform,
    agent_id: opts?.agentId,
    limit: opts?.limit ?? 100,
  });
  return unwrap(data);
}

/* -- Entity inspection --------------------------------------------- */

export interface GraphEntity {
  uuid: string;
  name: string;
  labels: string[];
  summary?: string;
  attributes?: Record<string, unknown>;
  related_edges?: Record<string, unknown>[];
  related_nodes?: Record<string, unknown>[];
}

export async function getGraphEntities(
  graphId: string,
  opts?: { entityTypes?: string[]; enrich?: boolean },
): Promise<{
  entities: GraphEntity[];
  entity_types: string[];
  total_count: number;
  filtered_count: number;
}> {
  const { data } = await client.get(`/api/simulation/entities/${graphId}`, {
    params: {
      entity_types: opts?.entityTypes?.join(','),
      enrich: opts?.enrich ?? true,
    },
  });
  return unwrap(data);
}

export async function getGraphEntityDetail(
  graphId: string,
  entityUuid: string,
): Promise<GraphEntity> {
  const { data } = await client.get(`/api/simulation/entities/${graphId}/${entityUuid}`);
  return unwrap(data);
}

export async function getGraphEntitiesByType(
  graphId: string,
  entityType: string,
): Promise<{
  entities: GraphEntity[];
  entity_types: string[];
  total_count: number;
  filtered_count: number;
}> {
  const { data } = await client.get(`/api/simulation/entities/${graphId}/by-type/${entityType}`);
  return unwrap(data);
}
