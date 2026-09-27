import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend
} from 'recharts'
import {
  getMetrics, getLogs, getGraph, getReport, createWsLogs,
  getMigrationState, pauseMigration, resumeMigration, stopMigration,
  chatWithCodebase, migrate, createAgentStream
} from '../api/client'
import type { AppState } from '../App'
import type { GraphNode, GraphLink, MigrationEvent } from '../api/client'

interface Props { state: AppState; update: (p: Partial<AppState>) => void }

interface LogLine { ts: string; span: string; status: string; duration_ms?: number; attrs?: Record<string, unknown>; error?: string }
interface Metrics { [key: string]: number }

function parseLogLine(raw: string): LogLine | null {
  try { return JSON.parse(raw) } catch { return null }
}

function statusColor(status: string): string {
  if (status === 'ok') return 'log-ok'
  if (status === 'error') return 'log-error'
  if (status === 'running') return 'log-info'
  return 'log-warn'
}

export default function LiveOpsPage({ state, update }: Props) {
  const nav = useNavigate()
  const [logs, setLogs] = useState<LogLine[]>([])
  const [metrics, setMetrics] = useState<Metrics>({})
  const [graphData, setGraphData] = useState<{ nodes: GraphNode[]; links: GraphLink[] }>({ nodes: [], links: [] })
  const [report, setReport] = useState('')
  const [copiedReport, setCopiedReport] = useState(false)
  const [activeTab, setActiveTab] = useState<'logs' | 'telemetry' | 'graph' | 'report' | 'chat'>('logs')
  const wsRef = useRef<WebSocket | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)

  // Migration Live State & Controls
  const [migState, setMigState] = useState<{
    status: string
    program?: string | null
    target_lang?: string
    paused: boolean
    stopped: boolean
    progress_pct: number
    current_step: string
  }>({
    status: 'idle',
    program: null,
    target_lang: 'java',
    paused: false,
    stopped: false,
    progress_pct: 0,
    current_step: 'Idle',
  })
  const [isControlling, setIsControlling] = useState(false)
  const [selectedProgToRun, setSelectedProgToRun] = useState('PAYROLL')

  // Chat with Codebase state
  interface ChatMsg {
    id: string
    sender: 'user' | 'assistant'
    text: string
    time: string
    model?: string
  }
  const [chatMessages, setChatMessages] = useState<ChatMsg[]>([
    {
      id: 'welcome',
      sender: 'assistant',
      text: "👋 **Welcome to the Mainframe AI Codebase Mentor!**\n\nI can explain the parsed **COBOL source code**, **JCL batch execution flows**, **BMS 3270 screen maps**, and **Neo4j knowledge graph relationships** to help developers and freshers onboard seamlessly.\n\n*Click any prompt chip below or ask any question!*",
      time: new Date().toLocaleTimeString(),
      model: 'ibm/granite-3-8b-instruct',
    }
  ])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [chatAssetFocus, setChatAssetFocus] = useState('')
  const chatEndRef = useRef<HTMLDivElement>(null)

  const buildMigrationOptions = () => {
    if (state.llmBackend === 'mock') {
      throw new Error('The Mock backend is deterministic only. Choose a real AI backend in Configure first.')
    }
    if (state.llmBackend === 'granite' && state.executionMode === 'accelerated') {
      throw new Error('Granite Accelerated is deterministic. Switch to watsonx.ai Live in Configure for real AI-generated output.')
    }
    if (state.llmBackend === 'granite' && state.executionMode === 'live') {
      if (!state.llmApiKey.trim()) throw new Error('Missing IBM Cloud API key for Granite Live.')
      if (!state.watsonxProjectId.trim()) throw new Error('Missing watsonx.ai project ID for Granite Live.')
    }
    if (state.llmBackend !== 'ollama' && !state.llmApiKey.trim()) {
      throw new Error(`Missing API key for ${state.llmBackend}.`)
    }

    const extras: Record<string, string> = {}
    if (state.llmBackend === 'granite' && state.executionMode === 'live') {
      extras.watsonx_project_id = state.watsonxProjectId
      extras.watsonx_url = `https://${state.watsonxRegion}.ml.cloud.ibm.com`
    }
    if (state.llmBackend === 'ollama') {
      extras.ollama_url = state.ollamaUrl
    }

    return {
      llm_backend: state.llmBackend,
      llm_model: state.llmModel,
      llm_api_key: state.llmBackend === 'ollama' ? undefined : (state.llmApiKey || undefined),
      llm_extra: Object.keys(extras).length ? extras : undefined,
    }
  }

  useEffect(() => {
    // Initial fetch of migration state
    getMigrationState().then(r => {
      if (r.ok) {
        setMigState({
          status: r.status,
          program: r.program,
          target_lang: r.target_lang || 'java',
          paused: r.paused,
          stopped: r.stopped,
          progress_pct: r.progress_pct,
          current_step: r.current_step,
        })
      }
    }).catch(() => {})

    // Real-time SSE stream for migration events
    const es = createAgentStream((ev: MigrationEvent) => {
      setMigState(prev => {
        const evAny = ev as unknown as Record<string, unknown>
        const isDone = ev.event === 'done'
        const isStopped = ev.event === 'stopped'
        const isPaused = ev.event === 'paused'
        const nextStatus = isDone ? 'done' : isStopped ? 'stopped' : isPaused ? 'paused' : 'running'
        const nextPct = isDone ? 100 : (typeof evAny.progress_pct === 'number' ? evAny.progress_pct : prev.progress_pct)
        const nextStep = String(evAny.current_step || evAny.status_text || ev.notes || ev.event)
        return {
          ...prev,
          status: nextStatus,
          program: ev.program || prev.program,
          progress_pct: nextPct,
          current_step: nextStep,
          paused: isPaused,
          stopped: isStopped,
        }
      })
    })

    return () => es.close()
  }, [])

  const handlePause = async () => {
    setIsControlling(true)
    try {
      await pauseMigration()
      setMigState(prev => ({ ...prev, paused: true, status: 'paused', current_step: 'Migration Paused by Operator' }))
    } finally {
      setIsControlling(false)
    }
  }

  const handleResume = async () => {
    setIsControlling(true)
    try {
      await resumeMigration()
      setMigState(prev => ({ ...prev, paused: false, status: 'running', current_step: 'Resuming Migration Loop...' }))
    } finally {
      setIsControlling(false)
    }
  }

  const handleStop = async () => {
    setIsControlling(true)
    try {
      await stopMigration()
      setMigState(prev => ({ ...prev, stopped: true, status: 'stopped', current_step: 'Migration Stopped by Operator' }))
    } finally {
      setIsControlling(false)
    }
  }

  const handleLaunchMigration = async () => {
    if (!selectedProgToRun) return
    setIsControlling(true)
    try {
      const migrationOptions = buildMigrationOptions()
      setMigState({
        status: 'running',
        program: selectedProgToRun,
        target_lang: 'java',
        paused: false,
        stopped: false,
        progress_pct: 5,
        current_step: `Starting migration for ${selectedProgToRun}...`,
      })
      const res = await migrate({ program_name: selectedProgToRun, target_lang: 'java', ...migrationOptions })
      if (res.ok) {
        update({ migrateResult: res })
        setMigState(prev => ({ ...prev, status: 'done', progress_pct: 100, current_step: 'Migration Completed Successfully!' }))
      }
    } catch (e) {
      setMigState(prev => ({ ...prev, status: 'error', current_step: `Error: ${e instanceof Error ? e.message : String(e)}` }))
    } finally {
      setIsControlling(false)
    }
  }

  const sendChatMessage = async (qText?: string) => {
    const q = qText || chatInput
    if (!q.trim() || chatLoading) return

    const userMessage: ChatMsg = {
      id: String(Date.now()),
      sender: 'user',
      text: q,
      time: new Date().toLocaleTimeString(),
    }
    setChatMessages(prev => [...prev, userMessage])
    setChatInput('')
    setChatLoading(true)

    try {
      const res = await chatWithCodebase({
        question: q,
        context_asset: chatAssetFocus || undefined,
      })
      const botMessage: ChatMsg = {
        id: String(Date.now() + 1),
        sender: 'assistant',
        text: res.answer,
        time: new Date().toLocaleTimeString(),
        model: res.model || 'ibm/granite-3-8b-instruct',
      }
      setChatMessages(prev => [...prev, botMessage])
    } catch (err) {
      const errMsg: ChatMsg = {
        id: String(Date.now() + 1),
        sender: 'assistant',
        text: `⚠️ **Unable to process query:** ${err instanceof Error ? err.message : String(err)}`,
        time: new Date().toLocaleTimeString(),
      }
      setChatMessages(prev => [...prev, errMsg])
    } finally {
      setChatLoading(false)
      setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
    }
  }

  useEffect(() => {
    // Initial data load
    getLogs().then(r => {
      const parsed = r.logs.map(parseLogLine).filter(Boolean) as LogLine[]
      setLogs(parsed)
    })
    getMetrics().then(setMetrics)
    getGraph().then(setGraphData)

    // WebSocket live logs
    wsRef.current = createWsLogs((raw) => {
      const line = parseLogLine(raw)
      if (line) setLogs(prev => [...prev.slice(-200), line])
    })

    // Poll metrics every 3s
    const metricTimer = setInterval(() => getMetrics().then(setMetrics), 3000)

    return () => {
      wsRef.current?.close()
      clearInterval(metricTimer)
    }
  }, [])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  useEffect(() => {
    if (activeTab === 'report') {
      getReport().then(r => setReport(r.markdown))
    }
    if (activeTab === 'graph') {
      getGraph().then(setGraphData)
    }
  }, [activeTab])

  const copyReportToClipboard = () => {
    navigator.clipboard.writeText(report)
    setCopiedReport(true)
    setTimeout(() => setCopiedReport(false), 2000)
  }

  const downloadReport = () => {
    const blob = new Blob([report], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `AI-Ops-Migration-Report-${new Date().toISOString().slice(0, 10)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  // Generate chart data from logs & metrics
  const spanChartData = logs
    .filter(l => l.duration_ms != null && l.duration_ms > 0)
    .slice(-25)
    .map((l, idx) => ({
      name: `#${idx + 1} ${l.span.slice(0, 12)}`,
      duration: l.duration_ms,
      status: l.status,
    }))

  const breakdownData = [
    { name: 'Programs', count: metrics.programs_parsed ?? 0, fill: '#38bdf8' },
    { name: 'Functions', count: metrics.ir_functions_total ?? 0, fill: '#818cf8' },
    { name: 'Variables', count: metrics.ir_vars_total ?? 0, fill: '#34d399' },
    { name: 'Unsupported', count: metrics.unsupported_ops ?? 0, fill: '#fbbf24' },
    { name: 'Critic Passes', count: metrics.critic_passes ?? 0, fill: '#10b981' },
    { name: 'Agent Rounds', count: metrics.agent_rounds_total ?? 0, fill: '#c084fc' },
  ]

  const metricCards = [
    { label: 'Programs', value: metrics.programs_parsed ?? 0, icon: '📄' },
    { label: 'Functions', value: metrics.ir_functions_total ?? 0, icon: '⚙️' },
    { label: 'Variables', value: metrics.ir_vars_total ?? 0, icon: '📦' },
    { label: 'Unsupported', value: metrics.unsupported_ops ?? 0, icon: '⚠️' },
    { label: 'Agent Rounds', value: metrics.agent_rounds_total ?? 0, icon: '🤖' },
    { label: 'Critic Passes', value: metrics.critic_passes ?? 0, icon: '✅' },
    { label: 'Lines Emitted', value: metrics.lines_emitted ?? 0, icon: '📝' },
    { label: 'Duration (ms)', value: Math.round(metrics.total_duration_ms ?? 0), icon: '⏱️' },
  ]

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <h1 className="page-title">Live AI-Ops Dashboard</h1>
          <p className="page-subtitle">Real-time pipeline observability — spans, metrics, and dependency graph</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-ghost" onClick={() => nav('/graph')}>
            🕸️ Open Neo4j Graph
          </button>
          {!!state.migrateResult && (
            <button className="btn btn-success" onClick={() => nav('/result')}>
              View Results →
            </button>
          )}
        </div>
      </div>

      {/* Metrics row */}
      <div className="metric-grid" style={{ marginBottom: 16 }}>
        {metricCards.map(c => (
          <div key={c.label} className="metric-card">
            <div style={{ fontSize: 20 }}>{c.icon}</div>
            <div className="metric-value">{c.value}</div>
            <div className="metric-label">{c.label}</div>
          </div>
        ))}
      </div>

      {/* Live Migration Process Controller & Progress Monitor */}
      <div className="card" style={{
        marginBottom: 16, padding: '16px 20px',
        background: 'linear-gradient(135deg, rgba(15,98,254,0.06), rgba(24,28,48,0.6))',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 18 }}>🚀</span>
            <div>
              <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>
                Active Migration Pipeline Controller
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                {migState.program ? `Target Program: ${migState.program} (${migState.target_lang?.toUpperCase()})` : 'System idle — ready for modernization run'}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {/* Status Chip */}
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '4px 10px', borderRadius: 20, fontSize: 11, fontWeight: 700,
              textTransform: 'uppercase', letterSpacing: '0.04em',
              background: migState.status === 'running' ? 'rgba(52,211,153,0.15)' :
                          migState.status === 'paused' ? 'rgba(251,191,36,0.15)' :
                          migState.status === 'stopped' ? 'rgba(248,113,113,0.15)' :
                          migState.status === 'done' ? 'rgba(99,102,241,0.15)' : 'var(--surface2)',
              color: migState.status === 'running' ? '#34d399' :
                     migState.status === 'paused' ? '#fbbf24' :
                     migState.status === 'stopped' ? '#f87171' :
                     migState.status === 'done' ? '#a5b4fc' : 'var(--muted)',
              border: `1px solid ${
                migState.status === 'running' ? 'rgba(52,211,153,0.3)' :
                migState.status === 'paused' ? 'rgba(251,191,36,0.3)' :
                migState.status === 'stopped' ? 'rgba(248,113,113,0.3)' :
                migState.status === 'done' ? 'rgba(99,102,241,0.3)' : 'var(--border)'
              }`,
            }}>
              <span style={{
                width: 6, height: 6, borderRadius: '50%',
                background: migState.status === 'running' ? '#34d399' :
                            migState.status === 'paused' ? '#fbbf24' :
                            migState.status === 'stopped' ? '#f87171' :
                            migState.status === 'done' ? '#a5b4fc' : 'var(--muted)',
                boxShadow: migState.status === 'running' ? '0 0 8px #34d399' : undefined
              }} />
              {migState.status}
            </span>

            {/* Controls: Pause / Resume / Stop */}
            {migState.status === 'running' && (
              <button
                className="btn btn-ghost"
                onClick={handlePause}
                disabled={isControlling}
                style={{ padding: '4px 12px', fontSize: 12, borderColor: 'rgba(251,191,36,0.4)', color: '#fbbf24' }}
              >
                ⏸️ Pause
              </button>
            )}

            {migState.status === 'paused' && (
              <button
                className="btn btn-ghost"
                onClick={handleResume}
                disabled={isControlling}
                style={{ padding: '4px 12px', fontSize: 12, borderColor: 'rgba(52,211,153,0.4)', color: '#34d399' }}
              >
                ▶️ Resume
              </button>
            )}

            {(migState.status === 'running' || migState.status === 'paused') && (
              <button
                className="btn btn-ghost"
                onClick={handleStop}
                disabled={isControlling}
                style={{ padding: '4px 12px', fontSize: 12, borderColor: 'rgba(248,113,113,0.4)', color: '#f87171' }}
              >
                ⏹️ Stop
              </button>
            )}

            {/* Quick launcher when idle */}
            {migState.status !== 'running' && migState.status !== 'paused' && (
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <select
                  value={selectedProgToRun}
                  onChange={e => setSelectedProgToRun(e.target.value)}
                  style={{
                    padding: '5px 8px', fontSize: 11, background: 'var(--surface2)',
                    border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text)',
                    fontFamily: 'var(--font-mono)'
                  }}
                >
                  <option value="PAYROLL">PAYROLL (COBOL)</option>
                  <option value="ORDPRCS">ORDPRCS (COBOL)</option>
                  <option value="INVNTRY">INVNTRY (COBOL)</option>
                </select>
                <button
                  className="btn btn-primary"
                  onClick={handleLaunchMigration}
                  disabled={isControlling}
                  style={{ padding: '5px 12px', fontSize: 12 }}
                >
                  🚀 Launch Migration
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Progress Bar & Current Status */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
            <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
              Step: <strong>{migState.current_step}</strong>
            </span>
            <span style={{ fontWeight: 700, color: 'var(--accent-light)', fontFamily: 'var(--font-mono)' }}>
              {migState.progress_pct}% Migrated
            </span>
          </div>

          <div style={{
            width: '100%', height: 8, background: 'var(--surface2)',
            borderRadius: 4, overflow: 'hidden', border: '1px solid var(--border)'
          }}>
            <div style={{
              width: `${Math.min(Math.max(migState.progress_pct, 0), 100)}%`,
              height: '100%',
              background: migState.status === 'paused' ? '#fbbf24' :
                          migState.status === 'stopped' ? '#f87171' :
                          migState.status === 'done' ? '#10b981' :
                          'linear-gradient(90deg, #38bdf8, #818cf8, #c084fc)',
              borderRadius: 4,
              transition: 'width 0.4s ease',
            }} />
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div className="file-tabs" style={{ marginBottom: 12 }}>
        {(['logs', 'telemetry', 'graph', 'report', 'chat'] as const).map(t => (
          <button key={t} className={`file-tab ${activeTab === t ? 'active' : ''}`}
            onClick={() => setActiveTab(t)}>
            {t === 'logs' ? '📋 Live Logs' :
             t === 'telemetry' ? '📈 Live Telemetry' :
             t === 'graph' ? '🕸️ Dependency Graph' :
             t === 'report' ? '📊 AI-Ops Report' :
             '💬 Codebase AI Mentor'}
          </button>
        ))}
      </div>

      {activeTab === 'logs' && (
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
            <div className="card-title">Pipeline Spans (Loki-style)</div>
            <span style={{ fontSize: 11, color: 'var(--green)' }}>● Live WebSocket</span>
          </div>
          <div className="ops-log">
            {logs.length === 0 && (
              <div style={{ color: 'var(--muted)', textAlign: 'center', padding: 20 }}>
                Waiting for pipeline events... Run a migration to see live logs.
              </div>
            )}
            {[...logs].reverse().map((l, i) => (
              <div key={i} className={`log-line ${statusColor(l.status)}`}>
                <span style={{ color: 'var(--muted)', marginRight: 8 }}>
                  {l.ts ? new Date(l.ts).toLocaleTimeString() : ''}
                </span>
                <span style={{ fontWeight: 600, marginRight: 8 }}>{l.span}</span>
                {l.duration_ms ? <span style={{ color: 'var(--muted)' }}>{l.duration_ms}ms </span> : null}
                {l.attrs && Object.entries(l.attrs).filter(([k]) => k !== 'service').map(([k, v]) => (
                  <span key={k} style={{ color: 'var(--muted)', marginLeft: 6 }}>
                    {k}=<span style={{ color: 'var(--text)' }}>{String(v)}</span>
                  </span>
                ))}
                {l.error && <span style={{ color: 'var(--red)', marginLeft: 8 }}>ERROR: {l.error}</span>}
              </div>
            ))}
            <div ref={logEndRef} />
          </div>
        </div>
      )}

      {activeTab === 'telemetry' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="card" style={{ padding: '16px 20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <div>
                <div className="card-title" style={{ margin: 0 }}>Pipeline Span Latency (ms)</div>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>Execution duration across recent trace spans</div>
              </div>
              <span className="badge badge-blue">Time Series</span>
            </div>

            <div style={{ width: '100%', height: 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={spanChartData.length > 0 ? spanChartData : [{ name: 'Init', duration: 12 }]}>
                  <defs>
                    <linearGradient id="latencyGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#6366f1" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#6366f1" stopOpacity={0.0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="name" stroke="#64748b" fontSize={10} />
                  <YAxis stroke="#64748b" fontSize={10} />
                  <Tooltip
                    contentStyle={{ background: '#0d121f', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontSize: 12 }}
                  />
                  <Area type="monotone" dataKey="duration" stroke="#818cf8" strokeWidth={2} fillOpacity={1} fill="url(#latencyGrad)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card" style={{ padding: '16px 20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <div>
                <div className="card-title" style={{ margin: 0 }}>IR Object Inventory & Critic Validations</div>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>Extracted artifacts across parsed programs and agent rounds</div>
              </div>
              <span className="badge badge-green">Prometheus Counters</span>
            </div>

            <div style={{ width: '100%', height: 240 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={breakdownData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="name" stroke="#64748b" fontSize={10} />
                  <YAxis stroke="#64748b" fontSize={10} />
                  <Tooltip
                    contentStyle={{ background: '#0d121f', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontSize: 12 }}
                  />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'graph' && (
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div className="card-title" style={{ margin: 0 }}>Dependency Graph (Neo4j-style)</div>
            <button className="btn btn-primary" style={{ padding: '6px 14px', fontSize: 12 }} onClick={() => nav('/graph')}>
              ⚡ Open Full Neo4j Explorer →
            </button>
          </div>
          <ForceGraph nodes={graphData.nodes} links={graphData.links} />
        </div>
      )}

      {activeTab === 'report' && (
        <div className="card" style={{ padding: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18, borderBottom: '1px solid var(--border)', paddingBottom: 14 }}>
            <div>
              <div className="card-title" style={{ margin: 0 }}>AI-Ops Migration Report</div>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
                Comprehensive automated migration audit trail, risk analysis, and IR inventory
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn btn-ghost" style={{ padding: '4px 12px', fontSize: 12 }} onClick={copyReportToClipboard}>
                {copiedReport ? '✓ Copied' : '📋 Copy Markdown'}
              </button>
              <button className="btn btn-primary" style={{ padding: '4px 14px', fontSize: 12 }} onClick={downloadReport}>
                📥 Download Report (.md)
              </button>
            </div>
          </div>

          <div className="markdown-report" style={{
            fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--text)',
            maxHeight: '75vh', overflowY: 'auto', lineHeight: 1.7, paddingRight: 10
          }}>
            {report ? (
              <ReactMarkdown>{report}</ReactMarkdown>
            ) : (
              <div style={{ textAlign: 'center', padding: 40, color: 'var(--muted)' }}>
                Loading AI-Ops report...
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Lightweight force-directed graph ──────────────────────────────────────

interface ForceGraphProps { nodes: GraphNode[]; links: GraphLink[] }

const NODE_COLORS: Record<string, string> = {
  Program: '#4f9cf9', Function: '#7c5cd8', Variable: '#34d399', Dataset: '#fbbf24', Job: '#f87171'
}

function ForceGraph({ nodes, links }: ForceGraphProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const posRef = useRef<Record<string | number, { x: number; y: number; vx: number; vy: number }>>({})
  const rafRef = useRef<number>(0)
  const [hovered, setHovered] = useState<GraphNode | null>(null)
  const [dims, setDims] = useState({ w: 800, h: 400 })

  const containerRef = useCallback((node: HTMLDivElement | null) => {
    if (node) setDims({ w: node.clientWidth, h: 400 })
  }, [])

  useEffect(() => {
    if (!nodes.length) return
    const { w, h } = dims

    // Init positions
    nodes.forEach(n => {
      if (!posRef.current[n.id]) {
        posRef.current[n.id] = {
          x: Math.random() * w, y: Math.random() * h, vx: 0, vy: 0
        }
      }
    })

    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    canvas.width = w; canvas.height = h

    const simulate = () => {
      const pos = posRef.current

      // Repulsion
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = pos[nodes[i].id], b = pos[nodes[j].id]
          if (!a || !b) continue
          const dx = a.x - b.x, dy = a.y - b.y
          const dist = Math.sqrt(dx * dx + dy * dy) || 1
          const force = 2000 / (dist * dist)
          a.vx += dx / dist * force; a.vy += dy / dist * force
          b.vx -= dx / dist * force; b.vy -= dy / dist * force
        }
      }

      // Attraction along links
      links.forEach(l => {
        const a = pos[l.source], b = pos[l.target]
        if (!a || !b) return
        const dx = b.x - a.x, dy = b.y - a.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const force = (dist - 100) * 0.01
        a.vx += dx / dist * force; a.vy += dy / dist * force
        b.vx -= dx / dist * force; b.vy -= dy / dist * force
      })

      // Centre gravity
      nodes.forEach(n => {
        const p = pos[n.id]; if (!p) return
        p.vx += (w / 2 - p.x) * 0.002
        p.vy += (h / 2 - p.y) * 0.002
        p.vx *= 0.85; p.vy *= 0.85
        p.x += p.vx; p.y += p.vy
        p.x = Math.max(20, Math.min(w - 20, p.x))
        p.y = Math.max(20, Math.min(h - 20, p.y))
      })

      // Draw
      ctx.clearRect(0, 0, w, h)

      // Links
      ctx.strokeStyle = '#2d3148'; ctx.lineWidth = 1
      links.forEach(l => {
        const a = pos[l.source], b = pos[l.target]
        if (!a || !b) return
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke()
      })

      // Nodes
      nodes.forEach(n => {
        const p = pos[n.id]; if (!p) return
        const color = NODE_COLORS[n.label] || '#888'
        ctx.beginPath()
        ctx.arc(p.x, p.y, n.label === 'Program' ? 12 : 8, 0, Math.PI * 2)
        ctx.fillStyle = color + '33'
        ctx.fill()
        ctx.strokeStyle = color; ctx.lineWidth = 2
        ctx.stroke()
        ctx.fillStyle = color; ctx.font = '10px monospace'
        ctx.fillText(n.name.slice(0, 12), p.x + 14, p.y + 4)
      })

      rafRef.current = requestAnimationFrame(simulate)
    }
    rafRef.current = requestAnimationFrame(simulate)
    return () => cancelAnimationFrame(rafRef.current)
  }, [nodes, links, dims])

  return (
    <div ref={containerRef} className="graph-container" style={{ position: 'relative' }}>
      <canvas ref={canvasRef} style={{ display: 'block' }} />
      <div style={{ position: 'absolute', bottom: 8, left: 8, display: 'flex', gap: 12, fontSize: 11 }}>
        {Object.entries(NODE_COLORS).map(([label, color]) => (
          <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block' }} />
            {label}
          </span>
        ))}
      </div>
      {nodes.length === 0 && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)' }}>
          Parse programs first to see the dependency graph
        </div>
      )}
    </div>
  )
}
