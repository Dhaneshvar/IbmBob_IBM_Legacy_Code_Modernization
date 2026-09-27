const API = ''

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    const err = await r.text()
    throw new Error(`${r.status}: ${err}`)
  }
  return r.json()
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`)
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`)
  return r.json()
}

export function createWsLogs(onMessage: (line: string) => void): WebSocket {
  const ws = new WebSocket(`ws://${location.host}/ws/logs`)
  ws.onmessage = (e) => onMessage(e.data)
  return ws
}

// ── typed API calls ────────────────────────────────────────────────────

export const connect = (body: ConnectRequest) =>
  apiPost<ConnectResponse>('/api/connect', body)

export const listAssets = (asset_type?: string) =>
  apiGet<AssetsResponse>(`/api/assets${asset_type ? `?asset_type=${asset_type}` : ''}`)

export const getSource = (name: string, asset_type = 'COBOL') =>
  apiGet<SourceResponse>(`/api/source/${name}?asset_type=${asset_type}`)

export const parseSource = (body: ParseRequest) =>
  apiPost<ParseResponse>('/api/parse', body)

export const getPrograms = () => apiGet<ProgramsResponse>('/api/programs')

export const getIR = (name: string) => apiGet<unknown>(`/api/ir/${name}`)

export const getGraph = (program?: string) =>
  apiGet<GraphResponse>(`/api/graph${program ? `?program=${program}` : ''}`)

export const queryGraph = (query: string) =>
  apiPost<GraphQueryResponse>('/api/graph/query', { query })

export const migrate = (body: MigrateRequest) =>
  apiPost<MigrateResponse>('/api/migrate', body)

export const migrateAll = (body: BatchMigrateRequest) =>
  apiPost<BatchMigrateResponse>('/api/migrate-all', body)

export const getMigration = (name: string, target_lang = 'java') =>
  apiGet<unknown>(`/api/migrate/${name}?target_lang=${target_lang}`)

export const getMetrics = () => apiGet<Record<string, number>>('/api/metrics')

export const getLogs = () => apiGet<{ logs: string[] }>('/api/logs')

export const getReport = () => apiGet<ReportResponse>('/api/report')

export const getStats = () => apiGet<StatsResponse>('/api/stats')

export const getAgentEvents = () => apiGet<{ events: MigrationEvent[] }>('/api/agent-events')

export const getMigrationState = () =>
  apiGet<MigrationStateResponse>('/api/migration/state')

export const pauseMigration = () =>
  apiPost<{ ok: boolean; paused: boolean }>('/api/migration/pause', {})

export const resumeMigration = () =>
  apiPost<{ ok: boolean; paused: boolean }>('/api/migration/resume', {})

export const stopMigration = () =>
  apiPost<{ ok: boolean; stopped: boolean }>('/api/migration/stop', {})

export const chatWithCodebase = (body: ChatRequest) =>
  apiPost<ChatResponse>('/api/chat', body)

export const emitCode = (body: { program_name: string; target: string }) =>
  apiPost<{ ok: boolean; files: Record<string, string>; file_list: string[] }>('/api/emit', body)

export const emitWorkflow = (body: { job_name: string; target: string }) =>
  apiPost<{ ok: boolean; files: Record<string, string>; file_list: string[] }>('/api/emit/workflow', body)

export const emitWebUI = (body: { screen_name: string }) =>
  apiPost<{ ok: boolean; files: Record<string, string>; file_list: string[] }>('/api/emit/webui', body)

export const emitDatabase = (body: { program_name: string }) =>
  apiPost<{ ok: boolean; files: Record<string, string>; file_list: string[] }>('/api/emit/database', body)

export const emitRestApi = (body: { program_name: string }) =>
  apiPost<{ ok: boolean; files: Record<string, string>; file_list: string[]; patterns: unknown[] }>('/api/emit/rest-api', body)

export const getBusinessRules = (program_name: string) =>
  apiPost<{ ok: boolean; rules: unknown[]; rule_count: number; summary: Record<string, number> }>('/api/analysis/business-rules', { program_name })

export const getTraceability = (program_name: string, target_lang = 'java') =>
  apiPost<{ ok: boolean; entries: unknown[]; entry_count: number; markdown: string; summary: Record<string, unknown> }>('/api/analysis/traceability', { program_name, target_lang })

export const getTestScaffold = (program_name: string, target_lang = 'java') =>
  apiPost<{ ok: boolean; files: Record<string, string> }>('/api/analysis/test-scaffold', { program_name, target_lang })

// ── types ──────────────────────────────────────────────────────────────

export interface ConnectRequest {
  host: string; port: number; user: string; password: string; session_id?: string
}
export interface ConnectResponse {
  ok: boolean; session_id: string; sysinfo: Record<string, string>; message: string
}
export interface AssetsResponse {
  assets: Asset[]; summary?: Record<string, number>
}
export interface Asset {
  name: string; type: string; library?: string; size?: number
  last_modified?: string; description?: string
}
export interface SourceResponse {
  name: string; asset_type: string; source: string
}
export interface ParseRequest {
  name: string; source: string; source_type: string; store?: boolean; push_graph?: boolean
}
export interface ParseResponse {
  ok: boolean; ir_summary: IrSummary
}
export interface IrSummary {
  name: string; dialect?: string; source_lines: number
  functions?: number; variables?: number; unsupported_ops: number; uses_files?: boolean
  type?: string; fields?: number; records?: number; lrecl?: number; recfm?: string; dimensions?: string
  input_fields?: number; output_fields?: number; map_name?: string
  steps?: number; datasets?: number
}
export interface ProgramsResponse {
  programs: ProgramRow[]
}
export interface ProgramRow {
  id: number; name: string; path: string; source_lines: number
  fn_count: number; var_count: number; unsupported_count: number
}
export interface GraphResponse {
  nodes: GraphNode[]
  links: GraphLink[]
  neo4j_connected?: boolean
  backend?: string
  program_filter?: string | null
}
export interface GraphQueryResponse {
  ok: boolean
  nodes?: GraphNode[]
  links?: GraphLink[]
  records?: unknown[]
  error?: string
  summary?: string
  backend?: string
  neo4j_connected?: boolean
}
export interface GraphNode {
  id: string | number
  label: string
  name: string
  complexity?: number
  prog?: string
  dialect?: string
  lines?: number
  is_io?: boolean
  kind?: string
  type?: string
  section?: string
  path?: string
}
export interface GraphLink {
  source: string | number
  target: string | number
  type: string
}
export interface MigrateRequest {
  program_name: string
  target_lang: string
  run_id?: string
  llm_backend?: string
  llm_model?: string
  llm_api_key?: string
  llm_extra?: Record<string, string>
}
export interface MigrateResponse {
  ok: boolean; status: string; program: string; target_lang: string
  files: string[]; agent_rounds: number; explanations: Record<string, string>
  file_contents: Record<string, string>; events: MigrationEvent[]; metrics: Record<string, number>
  llm?: LlmRuntimeInfo
}
export interface BatchMigrateRequest {
  program_names: string[]
  target_lang?: string
  llm_backend?: string
  llm_model?: string
  llm_api_key?: string
  llm_extra?: Record<string, string>
}

export interface BatchMigrateResponse {
  ok: boolean
  results: Array<{
    program: string
    ok: boolean
    status?: string
    files?: string[]
    agent_rounds?: number
    error?: string
    llm?: LlmRuntimeInfo
  }>
  total: number
  succeeded: number
  failed: number
  llm?: LlmRuntimeInfo
}
export interface LlmRuntimeInfo {
  backend: string
  model: string
  ai_generated: boolean
  input_to_ai: string
  uses_raw_cobol: boolean
}
export interface MigrationValidationSummary {
  totalPrograms: number
  passed: number
  failed: number
  progressPct: number
  generatedFiles: number
  coverage: string
}
export interface MigrationEvent {
  event: string; program?: string; function?: string; round?: number
  strategy?: string; risks?: number; effort?: string; notes?: string
  completeness?: number; issues?: string[]; files?: string[]; rounds?: number; error?: string
}
export interface ReportResponse {
  markdown: string; json: Record<string, unknown>
}
export interface StatsResponse {
  programs: number; functions: number; variables: number
  unsupported_ops: number; jobs: number; migrations_done: number
}

export function createAgentStream(onEvent: (ev: MigrationEvent) => void): EventSource {
  const es = new EventSource('/api/agent-stream')
  es.onmessage = (e) => {
    try { onEvent(JSON.parse(e.data)) } catch { /* skip ping */ }
  }
  return es
}

export interface MigrationStateResponse {
  ok: boolean
  status: string
  program?: string | null
  target_lang?: string
  paused: boolean
  stopped: boolean
  progress_pct: number
  current_step: string
  completed_functions: number
  total_functions: number
  events: MigrationEvent[]
  error?: string | null
}

export interface ChatRequest {
  question: string
  context_asset?: string
  target_lang?: string
}

export interface ChatResponse {
  ok: boolean
  answer: string
  context_asset?: string | null
  backend: string
  model: string
}
