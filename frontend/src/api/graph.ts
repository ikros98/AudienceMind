import client, { unwrap } from './client';
import type {
  Project,
  TaskInfo,
  GraphData,
  GraphEdge,
  GraphNode,
  GraphSearchResult,
  Ontology,
} from '../types';

/* -- Raw project shape from the backend -------------------- */

export interface RawProject {
  project_id: string;
  name: string;
  status: string;
  created_at: string;
  updated_at: string;
  files: { filename: string; size?: number }[];
  simulation_requirement: string | null;
  analysis_summary: string | null;
  graph_id: string | null;
  graph_build_task_id: string | null;
  ontology: Ontology | null;
  total_text_length: number;
  error: string | null;
}

type RawGraphNode = Partial<GraphNode> & {
  labels?: unknown;
};

type RawGraphData = {
  nodes?: unknown;
  edges?: unknown;
  node_count?: unknown;
  edge_count?: unknown;
  metadata?: unknown;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function pickNodeLabel(raw: RawGraphNode): string {
  if (typeof raw.label === 'string' && raw.label.trim().length > 0) {
    return raw.label;
  }

  if (Array.isArray(raw.labels)) {
    const typed = raw.labels.filter(
      (label): label is string => typeof label === 'string' && label.trim().length > 0,
    );
    const preferred = typed.find((label) => label !== 'Entity' && label !== 'Episodic');
    if (preferred) {
      return preferred;
    }
    if (typed.length > 0) {
      return typed[0]!;
    }
  }

  return 'Entity';
}

function normalizeNode(raw: unknown): GraphNode | null {
  if (!isRecord(raw) || typeof raw.uuid !== 'string' || typeof raw.name !== 'string') {
    return null;
  }

  return {
    uuid: raw.uuid,
    name: raw.name,
    label: pickNodeLabel(raw as RawGraphNode),
    summary: typeof raw.summary === 'string' ? raw.summary : undefined,
    attributes: isRecord(raw.attributes) ? raw.attributes : undefined,
    episode_count: typeof raw.episode_count === 'number' ? raw.episode_count : undefined,
  };
}

function normalizeEdge(raw: unknown): GraphEdge | null {
  if (!isRecord(raw) || typeof raw.uuid !== 'string') {
    return null;
  }

  const sourceUuid =
    typeof raw.source_uuid === 'string'
      ? raw.source_uuid
      : typeof raw.source_node_uuid === 'string'
        ? raw.source_node_uuid
        : null;
  const targetUuid =
    typeof raw.target_uuid === 'string'
      ? raw.target_uuid
      : typeof raw.target_node_uuid === 'string'
        ? raw.target_node_uuid
        : null;
  const relationType =
    typeof raw.relation_type === 'string'
      ? raw.relation_type
      : typeof raw.name === 'string'
        ? raw.name
        : null;

  if (!sourceUuid || !targetUuid || !relationType) {
    return null;
  }

  return {
    uuid: raw.uuid,
    source_uuid: sourceUuid,
    target_uuid: targetUuid,
    relation_type: relationType,
    fact: typeof raw.fact === 'string' ? raw.fact : undefined,
    weight: typeof raw.weight === 'number' ? raw.weight : undefined,
    episodes: Array.isArray(raw.episodes)
      ? raw.episodes.filter((episode): episode is string => typeof episode === 'string')
      : undefined,
  };
}

function normalizeGraphData(raw: unknown): GraphData {
  const data = (isRecord(raw) ? raw : {}) as RawGraphData;
  const nodes = Array.isArray(data.nodes)
    ? data.nodes.map(normalizeNode).filter((node): node is GraphNode => node !== null)
    : [];
  const edges = Array.isArray(data.edges)
    ? data.edges.map(normalizeEdge).filter((edge): edge is GraphEdge => edge !== null)
    : [];

  const entityTypes = [...new Set(nodes.map((node) => node.label))].sort();
  const edgeTypes = [...new Set(edges.map((edge) => edge.relation_type))].sort();

  const metadata = isRecord(data.metadata) ? data.metadata : {};

  return {
    nodes,
    edges,
    metadata: {
      node_count: typeof metadata.node_count === 'number' ? metadata.node_count : Number(data.node_count ?? nodes.length),
      edge_count: typeof metadata.edge_count === 'number' ? metadata.edge_count : Number(data.edge_count ?? edges.length),
      entity_types: Array.isArray(metadata.entity_types)
        ? metadata.entity_types.filter((item): item is string => typeof item === 'string')
        : entityTypes,
      edge_types: Array.isArray(metadata.edge_types)
        ? metadata.edge_types.filter((item): item is string => typeof item === 'string')
        : edgeTypes,
    },
  };
}

function normalizeSearchResult(raw: unknown, query: string): GraphSearchResult {
  const data = isRecord(raw) ? raw : {};
  const graph = normalizeGraphData(data);

  return {
    query: typeof data.query === 'string' ? data.query : query,
    total_count: typeof data.total_count === 'number' ? data.total_count : graph.edges.length,
    facts: Array.isArray(data.facts)
      ? data.facts.filter((fact): fact is string => typeof fact === 'string')
      : [],
    nodes: graph.nodes,
    edges: graph.edges,
  };
}

/* -- Ontology / Project Creation ----------------------------------- */

export async function generateOntology(
  files: File[],
  simulationRequirement: string,
  projectName?: string,
  additionalContext?: string,
): Promise<{
  project_id: string;
  project_name: string;
  ontology: Ontology;
  analysis_summary: string;
  files: { filename: string; size: number }[];
  total_text_length: number;
}> {
  const form = new FormData();
  files.forEach((f) => form.append('files', f));
  form.append('simulation_requirement', simulationRequirement);
  if (projectName) form.append('project_name', projectName);
  if (additionalContext) form.append('additional_context', additionalContext);
  const { data } = await client.post('/api/graph/ontology/generate', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return unwrap(data);
}

/* -- Graph Build --------------------------------------------------- */

export async function buildGraph(
  projectId: string,
  opts?: { graphName?: string; chunkSize?: number; chunkOverlap?: number },
): Promise<{ project_id: string; task_id: string; message: string }> {
  const { data } = await client.post('/api/graph/build', {
    project_id: projectId,
    graph_name: opts?.graphName,
    chunk_size: opts?.chunkSize,
    chunk_overlap: opts?.chunkOverlap,
  });
  return unwrap(data);
}

/* -- Task Polling -------------------------------------------------- */

export async function getTaskStatus(taskId: string): Promise<TaskInfo> {
  const { data } = await client.get(`/api/graph/task/${taskId}`);
  return unwrap(data);
}

/* -- Project ------------------------------------------------------- */

export async function getProject(projectId: string): Promise<Project> {
  const { data } = await client.get(`/api/graph/project/${projectId}`);
  const raw = unwrap<Record<string, unknown>>(data);
  return {
    ...raw,
    file_count: Array.isArray(raw.files) ? (raw.files as unknown[]).length : Number(raw.file_count ?? 0),
  } as unknown as Project;
}

export async function listProjects(): Promise<RawProject[]> {
  const { data } = await client.get('/api/graph/project/list');
  return unwrap(data);
}

/* -- Graph Data ---------------------------------------------------- */

export async function getGraphData(
  graphId: string,
  opts?: { baseline?: boolean; compact?: boolean },
): Promise<GraphData> {
  const { data } = await client.get(`/api/graph/data/${graphId}`, {
    params:
      opts?.baseline || opts?.compact
        ? {
            ...(opts?.baseline ? { baseline: true } : {}),
            ...(opts?.compact ? { compact: true } : {}),
          }
        : undefined,
  });
  return normalizeGraphData(unwrap(data));
}

export async function searchGraph(
  graphId: string,
  query: string,
): Promise<GraphSearchResult> {
  const { data } = await client.post(`/api/graph/data/${graphId}/search`, { query });
  return normalizeSearchResult(unwrap(data), query);
}

/* -- Subgraph ------------------------------------------------------ */

export async function getSubgraph(
  graphId: string,
  opts?: { centerNodeUuid?: string; nodeLabels?: string[]; edgeTypes?: string[] },
): Promise<GraphData> {
  const { data } = await client.post(`/api/graph/data/${graphId}/subgraph`, {
    center_node_uuid: opts?.centerNodeUuid,
    node_labels: opts?.nodeLabels,
    edge_types: opts?.edgeTypes,
  });
  return normalizeGraphData(unwrap(data));
}
