/* ------------------------------------------------------------------ */
/*  PersonaGraph domain types - matches the PersonaGraph Flask backend */
/* ------------------------------------------------------------------ */

// --- Generic API wrapper --------------------------------------------
export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

// --- Project / Graph ------------------------------------------------

export type ProjectStatus =
  | 'created'
  | 'ontology_generating'
  | 'ontology_generated'
  | 'graph_building'
  | 'graph_completed'
  | 'failed';

export interface Project {
  project_id: string;
  name: string;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  file_count: number;
  files?: { filename: string; size?: number }[];
  simulation_requirement?: string | null;
  analysis_summary?: string | null;
  ontology?: Ontology;
  graph_id?: string | null;
  graph_build_task_id?: string | null;
  error?: string | null;
  total_text_length?: number;
  simulations?: SimulationSummary[];
}

export interface ProjectSummary {
  project_id: string;
  name: string;
  status: ProjectStatus;
  created_at: string;
  file_count: number;
}

export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface TaskInfo {
  task_id: string;
  status: TaskStatus;
  progress?: number;
  message?: string;
  result?: unknown;
  error?: string;
  created_at?: string;
  updated_at?: string;
}

export interface Ontology {
  entity_types: EntityType[];
  edge_types: EdgeType[];
  description?: string;
}

export interface EntityType {
  name: string;
  description: string;
  attributes?: Record<string, string>;
}

export interface EdgeType {
  name: string;
  description: string;
  source_types?: string[];
  target_types?: string[];
  source_targets?: { source: string; target: string }[];
}

// --- Graph Data -----------------------------------------------------

export interface GraphNode {
  uuid: string;
  name: string;
  label: string;
  group_id?: number;
  summary?: string;
  attributes?: Record<string, unknown>;
  episode_count?: number;
}

export interface GraphEdge {
  uuid: string;
  source_uuid: string;
  target_uuid: string;
  relation_type: string;
  fact?: string;
  weight?: number;
  episodes?: string[];
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  metadata?: {
    node_count: number;
    edge_count: number;
    entity_types: string[];
    edge_types: string[];
  };
}

export interface GraphSearchResult {
  query: string;
  total_count: number;
  facts: string[];
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// --- Simulation -----------------------------------------------------

export type SimulationStatus =
  | 'created'
  | 'preparing'
  | 'ready'
  | 'running'
  | 'completed'
  | 'failed'
  | 'stopped';

export interface SimulationSummary {
  simulation_id: string;
  status: SimulationStatus;
  created_at: string;
  platforms?: string[];
}

export interface Simulation {
  simulation_id: string;
  project_id: string;
  status: SimulationStatus;
  created_at: string;
  updated_at: string;
  config?: SimulationConfig;
  platforms: PlatformConfig[];
  profiles?: AgentProfile[];
  current_round?: number;
  max_rounds?: number;
  requirement?: string;
}

export interface SimulationConfig {
  max_rounds: number;
  temperature?: number;
  platforms: string[];
  requirement?: string;
}

export interface PlatformConfig {
  platform: 'twitter' | 'reddit';
  enabled: boolean;
  agent_count?: number;
}

export interface AgentProfile {
  agent_id: string;
  name: string;
  username: string;
  platform: 'twitter' | 'reddit';
  persona: string;
  bio?: string;
  profile_pic_url?: string;
  entity_source?: string;
}

export interface SimulationAction {
  action_id: string;
  round: number;
  platform: 'twitter' | 'reddit';
  agent_id: string;
  agent_name: string;
  action_type: string;
  content: string;
  target_id?: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

export interface SimulationTimeline {
  current_round: number;
  max_rounds: number;
  total_actions: number;
  actions: SimulationAction[];
  platforms: {
    twitter: { action_count: number; agent_count: number };
    reddit: { action_count: number; agent_count: number };
  };
}

// --- Report ---------------------------------------------------------

export type ReportStatus =
  | 'pending'
  | 'generating'
  | 'completed'
  | 'failed';

export interface Report {
  report_id: string;
  simulation_id: string;
  project_id: string;
  status: ReportStatus;
  created_at: string;
  updated_at: string;
  title?: string;
  outline?: ReportOutlineItem[];
  sections?: ReportSection[];
  summary?: string;
}

export interface ReportOutlineItem {
  section_id: string;
  title: string;
  status: 'pending' | 'generating' | 'completed';
  order: number;
}

export interface ReportSection {
  section_id: string;
  title: string;
  content: string;
  order: number;
  citations?: Citation[];
}

export interface Citation {
  id: string;
  source: string;
  text: string;
  relevance?: number;
}

// --- Chat / Interaction ---------------------------------------------

export interface ChatMessage {
  message_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  agent_id?: string;
  agent_name?: string;
  citations?: Citation[];
  tool_calls?: ToolCall[];
}

export interface ToolCall {
  tool_name: string;
  arguments: Record<string, unknown>;
  result?: string;
}

export interface ChatRequest {
  message: string;
  agent_id?: string;
  conversation_id?: string;
}

export interface ChatResponse {
  message: ChatMessage;
  conversation_id: string;
}

// --- Interview / Survey ---------------------------------------------

export interface InterviewQuestion {
  question_id: string;
  question: string;
  target_agents: string[];
}

export interface InterviewResponse {
  agent_id: string;
  agent_name: string;
  response: string;
  question_id: string;
}

// --- System Logs ----------------------------------------------------

export interface SystemLog {
  timestamp: string;
  level: 'info' | 'warning' | 'error' | 'debug';
  message: string;
  source?: string;
}

// --- Upload State ---------------------------------------------------

export interface PendingUpload {
  files: File[];
  requirement: string;
}

// --- View / Layout --------------------------------------------------

export type ViewMode = 'graph' | 'split' | 'workbench';

export type WorkflowStep = 1 | 2 | 3 | 4 | 5;

export interface WorkflowState {
  currentStep: WorkflowStep;
  projectId?: string;
  simulationId?: string;
  reportId?: string;
}
