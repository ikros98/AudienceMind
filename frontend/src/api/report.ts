import client, { unwrap } from './client';

function extractSectionTitle(markdown: string, fallback: string): string {
  const heading = markdown.match(/^##\s+(.+)$/m);
  return heading?.[1]?.trim() || fallback;
}

function stripLeadingSectionHeading(markdown: string, title: string): string {
  return markdown
    .replace(
      new RegExp(`^##\\s+${title.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\$&')}\\s*\\n+`),
      '',
    )
    .trim();
}

function formatAgentLogLine(entry: {
  timestamp?: string;
  action?: string;
  stage?: string;
  section_title?: string;
  section_index?: number | null;
  details?: {
    message?: string;
    tool_name?: string;
    error?: string;
  };
}): string {
  const timestamp = entry.timestamp
    ? new Date(entry.timestamp).toLocaleTimeString()
    : '';
  const prefix = timestamp ? `[${timestamp}] ` : '';
  const sectionPrefix =
    entry.section_index != null ? `Section ${entry.section_index}: ` : '';
  const message = entry.details?.message?.trim();

  if (message) return `${prefix}${sectionPrefix}${message}`;
  if (entry.action === 'tool_call' && entry.details?.tool_name) {
    return `${prefix}${sectionPrefix}Calling tool ${entry.details.tool_name}`;
  }
  if (entry.action === 'error' && entry.details?.error) {
    return `${prefix}${sectionPrefix}${entry.details.error}`;
  }
  return `${prefix}${sectionPrefix}${entry.action ?? 'log'}`;
}

export interface AgentLogEntry {
  timestamp?: string;
  action?: string;
  stage?: string;
  section_title?: string;
  section_index?: number | null;
  details?: {
    message?: string;
    tool_name?: string;
    error?: string;
    outline?: {
      title?: string;
      summary?: string;
      sections?: { index?: number; title?: string }[];
    };
    content?: string;
  };
}

/* -- Generate Report ------------------------------------------------ */

export async function generateReport(
  simulationId: string,
  forceRegenerate = false,
): Promise<{
  simulation_id: string;
  report_id: string;
  task_id?: string;
  status: string;
  message: string;
  already_generated: boolean;
}> {
  const { data } = await client.post('/api/report/generate', {
    simulation_id: simulationId,
    force_regenerate: forceRegenerate,
  });
  return unwrap(data);
}

/* -- Generation status ---------------------------------------------- */

export async function getGenerateStatus(
  taskId?: string,
  simulationId?: string,
): Promise<{
  task_id: string;
  report_id: string;
  simulation_id: string;
  status: string;
  progress: number;
  message: string;
  already_completed: boolean;
  outline_ready?: boolean;
  current_section?: number;
  completed_sections?: number[];
  evidence_summary?: {
    graph?: { node_count?: number; edge_count?: number };
    runtime?: { actions?: number };
    topics?: string[];
  };
}> {
  const { data } = await client.post('/api/report/generate/status', {
    task_id: taskId,
    simulation_id: simulationId,
  });
  return unwrap(data);
}

/* -- Report data ---------------------------------------------------- */

export async function getReport(
  reportId: string,
): Promise<{
  report_id: string;
  simulation_id: string;
  status: string;
  outline?: {
    title: string;
    summary: string;
    sections: { title: string; content?: string }[];
  } | null;
  evidence_summary?: {
    graph?: {
      node_count?: number;
      edge_count?: number;
      entity_types?: string[];
      signals?: string[];
    };
    runtime?: {
      actions?: number;
      rounds?: number;
      twitter_posts?: number;
      reddit_posts?: number;
      comments?: number;
      platform_focus?: string;
    };
    topics?: string[];
  } | null;
  markdown_content: string;
  created_at: string;
  completed_at: string;
  error?: string | null;
}> {
  const { data } = await client.get(`/api/report/${reportId}`);
  return unwrap(data);
}

export async function getReportSections(
  reportId: string,
): Promise<{
  report_id: string;
  sections: { index: number; title: string; content: string }[];
}> {
  const { data } = await client.get(`/api/report/${reportId}/sections`);
  const payload = unwrap(data) as {
    report_id: string;
    sections?: {
      section_index?: number;
      title?: string;
      content: string;
      filename?: string;
    }[];
  };
  return {
    report_id: payload.report_id,
    sections: (payload.sections ?? []).map((section, offset) => {
      const fallbackTitle = section.title ?? section.filename ?? `Section ${offset + 1}`;
      const title = extractSectionTitle(section.content, fallbackTitle);
      return {
        index: section.section_index ?? offset + 1,
        title,
        content: stripLeadingSectionHeading(section.content, title),
      };
    }),
  };
}

export async function getReportSection(
  reportId: string,
  sectionIndex: number,
): Promise<{
  report_id: string;
  section_index: number;
  title: string;
  content: string;
}> {
  const { data } = await client.get(
    `/api/report/${reportId}/section/${sectionIndex}`,
  );
  const payload = unwrap(data) as {
    report_id?: string;
    section_index: number;
    title?: string;
    content: string;
    filename?: string;
  };
  const fallbackTitle = payload.title ?? payload.filename ?? `Section ${sectionIndex}`;
  const title = extractSectionTitle(payload.content, fallbackTitle);
  return {
    report_id: payload.report_id ?? reportId,
    section_index: payload.section_index,
    title,
    content: stripLeadingSectionHeading(payload.content, title),
  };
}

/* -- Logs ----------------------------------------------------------- */

export async function getAgentLog(
  reportId: string,
  fromLine = 0,
): Promise<{
  lines: string[];
  total_lines: number;
  from_line: number;
  to_line: number;
}> {
  const { data } = await client.get(
    `/api/report/${reportId}/agent-log`,
    { params: { from_line: fromLine } },
  );
  const payload = unwrap(data) as {
    logs?: Array<{
      timestamp?: string;
      action?: string;
      section_index?: number | null;
      details?: { message?: string; tool_name?: string; error?: string };
    }>;
    total_lines?: number;
    from_line?: number;
  };
  const total = payload.total_lines ?? fromLine;
  return {
    lines: (payload.logs ?? []).map(formatAgentLogLine),
    total_lines: total,
    from_line: payload.from_line ?? fromLine,
    to_line: total,
  };
}

export async function getAgentLogEntries(
  reportId: string,
  fromLine = 0,
): Promise<{
  logs: AgentLogEntry[];
  total_lines: number;
  from_line: number;
  to_line: number;
}> {
  const { data } = await client.get(
    `/api/report/${reportId}/agent-log`,
    { params: { from_line: fromLine } },
  );
  const payload = unwrap(data) as {
    logs?: AgentLogEntry[];
    total_lines?: number;
    from_line?: number;
  };
  const total = payload.total_lines ?? fromLine;
  return {
    logs: payload.logs ?? [],
    total_lines: total,
    from_line: payload.from_line ?? fromLine,
    to_line: total,
  };
}

export async function getConsoleLog(
  reportId: string,
  fromLine = 0,
): Promise<{
  lines: string[];
  total_lines: number;
  from_line: number;
  to_line: number;
}> {
  const { data } = await client.get(
    `/api/report/${reportId}/console-log`,
    { params: { from_line: fromLine } },
  );
  const payload = unwrap(data) as {
    logs?: string[];
    total_lines?: number;
    from_line?: number;
  };
  const total = payload.total_lines ?? fromLine;
  return {
    lines: payload.logs ?? [],
    total_lines: total,
    from_line: payload.from_line ?? fromLine,
    to_line: total,
  };
}

export async function getReportCheck(
  simulationId: string,
): Promise<{
  simulation_id: string;
  has_report: boolean;
  report_status?: string | null;
  report_id?: string | null;
  interview_unlocked: boolean;
}> {
  const { data } = await client.get(`/api/report/check/${simulationId}`);
  return unwrap(data);
}

export async function getAgentLogStream(
  reportId: string,
): Promise<{ logs: AgentLogEntry[]; count: number }> {
  const { data } = await client.get(`/api/report/${reportId}/agent-log/stream`);
  return unwrap(data);
}

export async function getConsoleLogStream(
  reportId: string,
): Promise<{ logs: string[]; count: number }> {
  const { data } = await client.get(`/api/report/${reportId}/console-log/stream`);
  return unwrap(data);
}

export async function searchTool(
  graphId: string,
  query: string,
): Promise<Record<string, unknown>> {
  const { data } = await client.post('/api/report/tools/search', {
    graph_id: graphId,
    query,
  });
  return unwrap(data);
}

export async function statisticsTool(
  graphId: string,
): Promise<Record<string, unknown>> {
  const { data } = await client.post('/api/report/tools/statistics', {
    graph_id: graphId,
  });
  return unwrap(data);
}

/* -- Chat ----------------------------------------------------------- */

export async function chat(
  simulationId: string,
  message: string,
  chatHistory?: { role: string; content: string }[],
): Promise<{
  simulation_id: string;
  response: string;
  tool_calls?: { name: string; status: string }[];
  sources?: string[];
}> {
  const { data } = await client.post('/api/report/chat', {
    simulation_id: simulationId,
    message,
    chat_history: chatHistory ?? [],
  });
  return unwrap(data);
}
