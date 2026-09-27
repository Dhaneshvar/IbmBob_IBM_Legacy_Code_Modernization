import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  listAssets, getSource, parseSource, getIR, getGraph,
  migrate, createAgentStream, getAgentEvents,
} from '../api/client'
import type { AppState } from '../App'
import type { Asset, IrSummary, GraphResponse, MigrationEvent } from '../api/client'

interface Props { state: AppState; update: (p: Partial<AppState>) => void }

/* ─── types ──────────────────────────────────────────────────────────────── */
type ParseStatus = 'idle' | 'parsing' | 'done' | 'error'
type IRTab = 'summary' | 'functions' | 'variables' | 'graph' | 'raw'

interface AssetState {
  status: ParseStatus
  summary: IrSummary | null
  error: string
  source: string
  irJson: unknown
  graphData: GraphResponse | null
  editedSource: string
  refinements: number
}

const blank = (): AssetState => ({
  status: 'idle', summary: null, error: '', source: '',
  irJson: null, graphData: null, editedSource: '', refinements: 0,
})

/* ─── agent event shape ──────────────────────────────────────────────────── */
interface AgentStep {
  event: string
  function?: string
  round?: number
  strategy?: string
  effort?: string
  risks?: number
  notes?: string
  completeness?: number
  issues?: string[]
  files?: string[]
  rounds?: number
  error?: string
  ts: string
}

const AGENT_LABEL: Record<string, { icon: string; label: string; color: string }> = {
  parse_start:    { icon: '🔍', label: 'Parsing asset',        color: '#38bdf8' },
  parse_done:     { icon: '📊', label: 'IR generated',         color: '#34d399' },
  migrate_start:  { icon: '🚀', label: 'Migration started',    color: '#818cf8' },
  plan_start:     { icon: '📋', label: 'Planner started',      color: '#4f9cf9' },
  plan_done:      { icon: '✅', label: 'Plan ready',           color: '#34d399' },
  execute_start:  { icon: '⚙️', label: 'Executor running',     color: '#fbbf24' },
  critic_start:   { icon: '🔎', label: 'Critic reviewing',     color: '#a78bfa' },
  critic_pass:    { icon: '✅', label: 'Critic passed',        color: '#34d399' },
  critic_fail:    { icon: '❌', label: 'Critic failed',        color: '#f87171' },
  done:           { icon: '🎉', label: 'Migration complete',   color: '#34d399' },
  error:          { icon: '🔥', label: 'Error',                color: '#f87171' },
  ping:           { icon: '·',  label: 'keepalive',            color: '#2d3148' },
}

/* ─── helpers ────────────────────────────────────────────────────────────── */
const TYPE_ICONS: Record<string, string> = { COBOL: '📄', JCL: '⚙️', BMS: '🖥️', DATASET: '🗄️' }
const PARSEABLE = ['COBOL', 'JCL', 'BMS', 'DATASET']
const now = () => new Date().toLocaleTimeString('en', { hour12: false })
const FALLBACK_ASSETS: Asset[] = [
  { name: 'PAYROLL', type: 'COBOL', library: 'HLQ.COBOL.SRC', last_modified: '2024-01-10' },
  { name: 'ORDPRCS', type: 'COBOL', library: 'HLQ.COBOL.SRC', last_modified: '2024-01-10' },
  { name: 'INVNTRY', type: 'COBOL', library: 'HLQ.COBOL.SRC', last_modified: '2024-01-10' },
  { name: 'PAYJOB', type: 'JCL', library: 'HLQ.JCL', last_modified: '2024-01-12' },
  { name: 'ORDJOB', type: 'JCL', library: 'HLQ.JCL', last_modified: '2024-01-12' },
  { name: 'PAYINQ', type: 'BMS', library: 'HLQ.BMS.SRC', description: 'Payroll Inquiry Screen', last_modified: '2024-01-08' },
  { name: 'ORDINQ', type: 'BMS', library: 'HLQ.BMS.SRC', description: 'Order Inquiry Screen', last_modified: '2024-01-08' },
  { name: 'HLQ.PAYROLL.INPUT', type: 'DATASET', library: 'HLQ.DATASET' },
  { name: 'HLQ.PAYROLL.OUTPUT', type: 'DATASET', library: 'HLQ.DATASET' },
  { name: 'HLQ.ORDER.INPUT', type: 'DATASET', library: 'HLQ.DATASET' },
  { name: 'HLQ.ORDER.OUTPUT', type: 'DATASET', library: 'HLQ.DATASET' },
  { name: 'HLQ.INVENTORY.WORK', type: 'DATASET', library: 'HLQ.DATASET' },
]

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN COMPONENT
═══════════════════════════════════════════════════════════════════════════ */
export default function AssetBrowserPage({ state, update }: Props) {
  const nav = useNavigate()

  const [assets, setAssets]         = useState<Asset[]>([])
  const [filter, setFilter]         = useState('ALL')
  const [selected, setSelected]     = useState<string[]>(state.selectedAssets)
  const [active, setActive]         = useState<Asset | null>(null)
  const [assetStates, setAssetStates] = useState<Record<string, AssetState>>({})
  const assetStatesRef              = useRef<Record<string, AssetState>>({})
  const [irTab, setIRTab]           = useState<IRTab>('summary')
  const [editMode, setEditMode]     = useState(false)
  const [bulkParsing, setBulkParsing] = useState(false)
  const [bulkProgress, setBulkProgress] = useState({ done: 0, total: 0 })
  const [bmsMode, setBmsMode]       = useState<'terminal' | 'source'>('terminal')

  /* agent status panel */
  const [agentSteps, setAgentSteps] = useState<AgentStep[]>([])
  const [migrating, setMigrating]   = useState(false)
  const [migratingProg, setMigratingProg] = useState('')
  const esRef = useRef<EventSource | null>(null)
  const agentEndRef = useRef<HTMLDivElement>(null)

  /* Keep assetStatesRef synchronized for immediate reading in async operations */
  useEffect(() => {
    assetStatesRef.current = assetStates
  }, [assetStates])

  /* ── load assets and connect real-time event stream ─────────────────────── */
  useEffect(() => {
    listAssets()
      .then(r => {
        const nextAssets = r.assets && r.assets.length > 0 ? r.assets : FALLBACK_ASSETS
        setAssets(nextAssets)
      })
      .catch(() => setAssets(FALLBACK_ASSETS))

    // Open real-time SSE stream on mount for live updates
    const es = createAgentStream((ev: MigrationEvent) => {
      if (ev.event === 'ping') return
      setAgentSteps(prev => [...prev, { ...ev, ts: now() } as AgentStep])
    })
    esRef.current = es

    return () => {
      es.close()
    }
  }, [])

  /* auto-scroll agent log */
  useEffect(() => {
    agentEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [agentSteps])

  /* ── state helpers ────────────────────────────────────────────────────── */
  const getAS = useCallback((n: string) => assetStatesRef.current[n] ?? assetStates[n] ?? blank(), [assetStates])
  
  const setAS = useCallback((n: string, p: Partial<AssetState>) => {
    setAssetStates(prev => {
      const updated = { ...prev, [n]: { ...(prev[n] ?? blank()), ...p } }
      assetStatesRef.current = updated
      return updated
    })
  }, [])

  /* ── click asset in tree ──────────────────────────────────────────────── */
  const activateAsset = async (asset: Asset) => {
    setActive(asset)
    setEditMode(false)
    setIRTab('summary')
    const existing = assetStatesRef.current[asset.name]?.source
    if (existing && !existing.includes('Could not load') && !existing.includes('404')) return
    try {
      const r = await getSource(asset.name, asset.type)
      setAS(asset.name, { source: r.source, editedSource: r.source, error: '' })
    } catch {
      setAS(asset.name, { source: '      * Could not load source', editedSource: '' })
    }
  }

  /* ── parse one asset in real-time ─────────────────────────────────────── */
  const parseOne = useCallback(async (asset: Asset, srcOverride?: string): Promise<void> => {
    if (!PARSEABLE.includes(asset.type)) return
    
    // Set status to parsing immediately
    setAS(asset.name, { status: 'parsing', error: '' })
    setAgentSteps(prev => [...prev, {
      event: 'parse_start', ts: now(), notes: `Parsing ${asset.type} ${asset.name}...`
    }])

    try {
      let src = srcOverride || assetStatesRef.current[asset.name]?.source
      if (!src || src.includes('Could not load') || src.includes('404')) {
        const r = await getSource(asset.name, asset.type)
        src = r.source
      }

      const res = await parseSource({
        name: asset.name,
        source: src,
        source_type: asset.type,
        store: true,
        push_graph: true,
      })

      const summary = res.ir_summary as IrSummary
      let irJson: unknown = null
      let graphData: GraphResponse | null = null
      try { irJson = await getIR(asset.name) } catch { /**/ }
      try { graphData = await getGraph(asset.name) } catch { /**/ }

      const prev = assetStatesRef.current[asset.name] ?? blank()
      setAS(asset.name, {
        status: 'done',
        summary,
        irJson,
        graphData,
        source: src,
        editedSource: prev.editedSource || src,
        error: '',
        refinements: prev.refinements + (srcOverride ? 1 : 0),
      })

      // Synchronize selection
      setSelected(s => {
        const updated = s.includes(asset.name) ? s : [...s, asset.name]
        update({ selectedAssets: updated })
        return updated
      })

      const metricStr = asset.type === 'BMS'
        ? `${summary.fields ?? 0} fields, ${summary.dimensions || '24x80'}`
        : asset.type === 'DATASET'
        ? `${summary.records ?? 0} records, LRECL=${summary.lrecl || 80}`
        : asset.type === 'JCL'
        ? `${summary.steps ?? 0} steps, ${summary.datasets ?? 0} datasets`
        : `${summary.functions ?? 0} fns, ${summary.variables ?? 0} vars`

      setAgentSteps(prev => [...prev, {
        event: 'parse_done',
        ts: now(),
        notes: `IR Ready: ${asset.type} ${asset.name} (${metricStr})`
      }])
    } catch (e) {
      const errStr = e instanceof Error ? e.message : String(e)
      setAS(asset.name, { status: 'error', error: errStr })
      setAgentSteps(prev => [...prev, {
        event: 'critic_fail',
        ts: now(),
        notes: `Parse error on ${asset.name}: ${errStr}`
      }])
    }
  }, [setAS, update])

  /* ── parse ALL in real-time with visual step-by-step progress ─────────── */
  const parseAll = async (targetAssets?: Asset[]) => {
    const targets = targetAssets || (selected.length > 0
      ? assets.filter(a => selected.includes(a.name) && PARSEABLE.includes(a.type))
      : assets.filter(a => PARSEABLE.includes(a.type)))

    if (targets.length === 0) return

    setBulkParsing(true)
    setBulkProgress({ done: 0, total: targets.length })

    setAgentSteps(prev => [...prev, {
      event: 'plan_start',
      ts: now(),
      notes: `Batch parse started for ${targets.length} mainframe assets (${targets.map(t => `${t.type}:${t.name}`).join(', ')})...`
    }])

    for (let i = 0; i < targets.length; i++) {
      const a = targets[i]
      setActive(a)
      setAS(a.name, { status: 'parsing', error: '' })

      try {
        let src = assetStatesRef.current[a.name]?.source
        if (!src || src.includes('Could not load') || src.includes('404')) {
          const r = await getSource(a.name, a.type)
          src = r.source
        }

        const res = await parseSource({
          name: a.name,
          source: src,
          source_type: a.type,
          store: true,
          push_graph: true,
        })

        const summary = res.ir_summary as IrSummary
        let irJson: unknown = null
        let graphData: GraphResponse | null = null
        try { irJson = await getIR(a.name) } catch { /**/ }
        try { graphData = await getGraph(a.name) } catch { /**/ }

        const prev = assetStatesRef.current[a.name] ?? blank()
        setAS(a.name, {
          status: 'done',
          source: src,
          editedSource: prev.editedSource || src,
          summary,
          irJson,
          graphData,
        })

        setSelected(s => {
          const next = s.includes(a.name) ? s : [...s, a.name]
          update({ selectedAssets: next })
          return next
        })

        const metricStr = a.type === 'BMS'
          ? `${summary.fields ?? 0} fields, ${summary.dimensions || '24x80'}`
          : a.type === 'DATASET'
          ? `${summary.records ?? 0} records, LRECL=${summary.lrecl || 80}`
          : a.type === 'JCL'
          ? `${summary.steps ?? 0} steps, ${summary.datasets ?? 0} datasets`
          : `${summary.functions ?? 0} fns, ${summary.variables ?? 0} vars`

        setAgentSteps(prev => [...prev, {
          event: 'parse_done',
          ts: now(),
          notes: `[${i + 1}/${targets.length}] Parsed ${a.type} ${a.name} (${metricStr})`
        }])
      } catch (err) {
        const errStr = err instanceof Error ? err.message : String(err)
        setAS(a.name, { status: 'error', error: errStr })
        setAgentSteps(prev => [...prev, {
          event: 'critic_fail',
          ts: now(),
          notes: `Failed to parse ${a.name}: ${errStr}`
        }])
      }

      setBulkProgress({ done: i + 1, total: targets.length })
      // Brief aesthetic pause for smooth real-time visual step-through
      await new Promise(r => setTimeout(r, 160))
    }

    setBulkParsing(false)
    setAgentSteps(prev => [...prev, {
      event: 'done',
      ts: now(),
      notes: `Batch parse complete. All ${targets.length} mainframe assets parsed into normalized IR.`
    }])
  }

  /* ── refinement: re-parse edited source ──────────────────────────────── */
  const refine = async () => {
    if (!active) return
    await parseOne(active, getAS(active.name).editedSource)
    setEditMode(false)
    setIRTab('summary')
  }

  /* ── start migration with live agent stream ───────────────────────────── */
  const startMigrate = async (progName: string) => {
    if (migrating) return
    setMigrating(true)
    setMigratingProg(progName)
    setAgentSteps(prev => [...prev, { event: 'migrate_start', ts: now(), notes: `Launching agentic pipeline for ${progName}` }])

    try {
      const result = await migrate({ program_name: progName, target_lang: 'java', run_id: progName })
      update({ migrateResult: result, selectedAssets: [progName] })
      setMigrating(false)
      nav('/result')
    } catch (e) {
      setAgentSteps(prev => [...prev, { event: 'error', error: String(e), ts: now() } as AgentStep])
      setMigrating(false)
    }
  }

  /* ── selection helpers ─────────────────────────────────────────────────── */
  const toggleSel = (n: string) => {
    const next = selected.includes(n) ? selected.filter(x => x !== n) : [...selected, n]
    setSelected(next)
    update({ selectedAssets: next })
  }

  const selectAllEverything = () => {
    const allNames = assets.map(a => a.name)
    setSelected(allNames)
    update({ selectedAssets: allNames })
  }

  const toggleSelectAll = () => {
    const visibleNames = filtered.map(a => a.name)
    const allSelected = visibleNames.length > 0 && visibleNames.every(name => selected.includes(name))
    let next: string[]
    if (allSelected) {
      // Deselect all visible
      next = selected.filter(n => !visibleNames.includes(n))
    } else {
      // Select all visible
      const toAdd = visibleNames.filter(n => !selected.includes(n))
      next = [...selected, ...toAdd]
    }
    setSelected(next)
    update({ selectedAssets: next })
  }

  const selectAllCobol = () => {
    const cobolNames = assets.filter(a => a.type === 'COBOL').map(a => a.name)
    const next = Array.from(new Set([...selected, ...cobolNames]))
    setSelected(next)
    update({ selectedAssets: next })
  }

  const deselectAll = () => {
    setSelected([])
    update({ selectedAssets: [] })
  }

  /* ── derived ──────────────────────────────────────────────────────────── */
  const filtered = filter === 'ALL' ? assets : assets.filter(a => a.type === filter)
  const grouped = filtered.reduce<Record<string, Asset[]>>((acc, a) => {
    acc[a.type] = acc[a.type] || []; acc[a.type].push(a); return acc
  }, {})
  const parseableAssets = assets.filter(a => PARSEABLE.includes(a.type))
  const parsedCount = parseableAssets.filter(a => (assetStatesRef.current[a.name]?.status || assetStates[a.name]?.status) === 'done').length
  const activeAS = active ? getAS(active.name) : null
  const allVisibleSelected = filtered.length > 0 && filtered.every(a => selected.includes(a.name))

  /* ── render ──────────────────────────────────────────────────────────── */
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 80px)' }}>

      {/* ══ TOP TOOLBAR ══════════════════════════════════════════════════ */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 0 12px', flexShrink: 0, gap: 12, flexWrap: 'wrap',
      }}>
        {/* left: title & breadcrumb */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 16 }}>⚡</span>
            <h1 style={{ fontSize: 18, fontWeight: 600, margin: 0, letterSpacing: '-0.01em', color: 'var(--text)' }}>
              Enterprise Catalog
            </h1>
            <span style={{
              fontSize: 10, padding: '2px 8px', borderRadius: 999,
              background: 'rgba(36,161,72,.12)', color: '#24a148', border: '1px solid rgba(36,161,72,.25)',
              fontFamily: 'var(--mono)', fontWeight: 600
            }}>
              ● LIVE Z/OS 2.5
            </span>
          </div>
          <p style={{ fontSize: 11, color: 'var(--muted)', margin: '3px 0 0' }}>
            Mainframe modernizer: parse COBOL, JCL, BMS 3270 screens, and Datasets into normalized IR.
          </p>
        </div>

        {/* right: actions */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {/* Quick select pills */}
          <div style={{ display: 'flex', alignItems: 'center', background: 'var(--surface2)', borderRadius: 6, padding: '2px 4px', border: '1px solid var(--border)' }}>
            <button
              onClick={selectAllEverything}
              style={{
                background: allVisibleSelected ? 'var(--accent)' : 'transparent',
                color: allVisibleSelected ? '#fff' : 'var(--text-secondary)',
                border: 'none', padding: '4px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                fontWeight: 500, transition: 'var(--transition-smooth)'
              }}
            >
              Select All ({assets.length})
            </button>
            {selected.length > 0 && (
              <button
                onClick={deselectAll}
                style={{
                  background: 'transparent', color: 'var(--muted)',
                  border: 'none', padding: '4px 8px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
                  fontWeight: 500, transition: 'var(--transition-smooth)'
                }}
              >
                Clear ({selected.length})
              </button>
            )}
          </div>

          <button
            onClick={() => nav('/graph', { state: { asset: active?.name } })}
            style={{
              padding: '6px 14px', fontSize: 12, borderRadius: 6, cursor: 'pointer',
              background: 'var(--surface2)', color: 'var(--text-secondary)', border: '1px solid var(--border)',
              display: 'flex', alignItems: 'center', gap: 6, fontWeight: 500, transition: 'var(--transition-smooth)'
            }}
            title="Open Interactive Neo4j Property Graph Explorer"
          >
            <span>🕸️</span> Neo4j Graph ↗
          </button>

          <button
            onClick={() => parseAll()}
            disabled={bulkParsing}
            style={{
              padding: '6px 16px', fontSize: 12, borderRadius: 6, cursor: bulkParsing ? 'wait' : 'pointer',
              background: 'rgba(241,194,27,.12)',
              color: '#f1c21b', border: '1px solid rgba(241,194,27,.35)', display: 'flex', alignItems: 'center', gap: 6,
              fontWeight: 600, transition: 'var(--transition-smooth)'
            }}
          >
            {bulkParsing
              ? <><span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} /> Parsing [{bulkProgress.done}/{bulkProgress.total}]…</>
              : (selected.length > 0 ? `⚡ Realtime Parse (${selected.length})` : `⚡ Realtime Parse All (${assets.length})`)}
          </button>

          <button
            onClick={() => { update({ selectedAssets: selected }); nav('/wizard') }}
            disabled={parsedCount === 0 || selected.length === 0}
            style={{
              padding: '6px 16px', fontSize: 12, borderRadius: 6,
              background: (parsedCount > 0 && selected.length > 0) ? 'var(--accent)' : 'var(--surface2)',
              color: (parsedCount > 0 && selected.length > 0) ? '#fff' : 'var(--muted)',
              border: 'none', cursor: (parsedCount > 0 && selected.length > 0) ? 'pointer' : 'not-allowed',
              opacity: (parsedCount > 0 && selected.length > 0) ? 1 : 0.45,
              fontWeight: 600, transition: 'var(--transition-smooth)'
            }}
          >
            Migrate Selected ({selected.length}) →
          </button>
        </div>
      </div>

      {/* ── bulk progress banner ─────────────────────────────────────────── */}
      {bulkParsing && (
        <div style={{
          background: 'rgba(241, 194, 27, 0.08)', border: '1px solid rgba(241, 194, 27, 0.25)',
          borderRadius: 8, padding: '8px 14px', marginBottom: 10, flexShrink: 0,
          display: 'flex', flexDirection: 'column', gap: 6
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11 }}>
            <span style={{ color: '#f1c21b', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className="spinner" style={{ width: 11, height: 11, borderWidth: 2 }} />
              Real-Time Batch Parsing :: Processing {bulkProgress.done} of {bulkProgress.total} Assets
              {active ? ` (${active.type}: ${active.name})` : ''}
            </span>
            <span style={{ color: 'var(--muted)', fontFamily: 'var(--mono)' }}>
              {Math.round((bulkProgress.done / Math.max(bulkProgress.total, 1)) * 100)}%
            </span>
          </div>
          <div style={{ height: 4, background: 'rgba(255,255,255,0.06)', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{
              height: '100%', borderRadius: 2,
              background: 'linear-gradient(90deg, #f1c21b, #4589ff)',
              width: `${(bulkProgress.done / Math.max(bulkProgress.total, 1)) * 100}%`,
              transition: 'width 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
            }} />
          </div>
        </div>
      )}

      {/* ── category filter row ────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10, flexShrink: 0 }}>
        <div style={{
          display: 'inline-flex', background: 'var(--surface2)', borderRadius: 8, padding: 3,
          border: '1px solid var(--border)', gap: 2
        }}>
          {[
            { id: 'ALL', label: 'All', count: assets.length },
            { id: 'COBOL', label: 'COBOL', count: assets.filter(a => a.type === 'COBOL').length },
            { id: 'JCL', label: 'JCL', count: assets.filter(a => a.type === 'JCL').length },
            { id: 'BMS', label: 'BMS Screens', count: assets.filter(a => a.type === 'BMS').length },
            { id: 'DATASET', label: 'Datasets', count: assets.filter(a => a.type === 'DATASET').length },
          ].map(t => (
            <button
              key={t.id}
              onClick={() => setFilter(t.id)}
              style={{
                padding: '4px 12px', fontSize: 11, borderRadius: 6, cursor: 'pointer', border: 'none',
                background: filter === t.id ? 'var(--surface)' : 'transparent',
                color: filter === t.id ? 'var(--text)' : 'var(--muted)',
                fontWeight: filter === t.id ? 600 : 400,
                boxShadow: filter === t.id ? '0 1px 4px rgba(0,0,0,0.2)' : 'none',
                transition: 'var(--transition-smooth)',
                display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              <span>{t.label}</span>
              <span style={{
                fontSize: 10, opacity: 0.7,
                background: filter === t.id ? 'var(--surface2)' : 'rgba(255,255,255,0.04)',
                padding: '1px 5px', borderRadius: 10
              }}>
                {t.count}
              </span>
            </button>
          ))}
        </div>

        {/* Parsed count pill */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
          <span style={{ color: 'var(--muted)' }}>Parsed IR:</span>
          <span style={{
            fontFamily: 'var(--mono)', fontWeight: 600,
            color: parsedCount === parseableAssets.length ? '#24a148' : '#fbbf24'
          }}>
            {parsedCount} of {parseableAssets.length}
          </span>
        </div>
      </div>

      {/* ══ MAIN 4-PANEL GRID ═══════════════════════════════════════════ */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '200px 1fr 1fr',
        gridTemplateRows: 'minmax(0,1fr) 200px',
        gap: 8, flex: 1, minHeight: 0,
      }}>

        {/* ── Panel A: Asset tree (spans both rows) ─────────────────── */}
        <div style={{
          gridRow: '1 / 3',
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 8, overflow: 'hidden', display: 'flex', flexDirection: 'column',
        }}>
          {/* tree header */}
          <div style={{
            padding: '8px 10px', background: '#0a0c14',
            borderBottom: '1px solid var(--border)', fontSize: 11,
            fontFamily: 'var(--mono)', color: '#34d399',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input
                type="checkbox"
                checked={allVisibleSelected}
                onChange={toggleSelectAll}
                title="Toggle Select All"
                style={{ accentColor: 'var(--accent)', cursor: 'pointer' }}
              />
              <span>HLQ.LIBRARY</span>
            </div>
            <span style={{ fontSize: 10, color: 'var(--muted)' }}>
              {selected.length}/{assets.length}
            </span>
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {Object.entries(grouped).map(([type, list]) => {
              const allGroupSelected = list.every(a => selected.includes(a.name))
              const toggleGroup = (e: React.MouseEvent) => {
                e.stopPropagation()
                const names = list.map(a => a.name)
                let next: string[]
                if (allGroupSelected) {
                  next = selected.filter(n => !names.includes(n))
                } else {
                  next = Array.from(new Set([...selected, ...names]))
                }
                setSelected(next)
                update({ selectedAssets: next })
              }
              return (
                <div key={type}>
                  <div style={{
                    fontSize: 10, color: 'var(--text-secondary)', fontWeight: 600,
                    letterSpacing: '.05em', textTransform: 'uppercase',
                    padding: '8px 10px 4px', background: 'rgba(255,255,255,.02)',
                    borderBottom: '1px solid var(--border)',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center'
                  }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span>{TYPE_ICONS[type]}</span>
                      <span>{type}</span>
                      <span style={{ fontSize: 9, color: 'var(--muted)', background: 'var(--surface2)', padding: '1px 5px', borderRadius: 4 }}>
                        {list.length}
                      </span>
                    </span>
                    <button
                      type="button"
                      onClick={toggleGroup}
                      style={{
                        background: allGroupSelected ? 'rgba(15,98,254,0.12)' : 'transparent',
                        border: `1px solid ${allGroupSelected ? 'rgba(15,98,254,0.3)' : 'var(--border)'}`,
                        color: allGroupSelected ? '#4589ff' : 'var(--muted)',
                        fontSize: 9, cursor: 'pointer', padding: '1px 6px', borderRadius: 4,
                        textTransform: 'none', fontWeight: 500, transition: 'var(--transition-smooth)'
                      }}
                    >
                      {allGroupSelected ? 'Deselect' : 'Select all'}
                    </button>
                  </div>
                  {list.map(a => <AssetRow
                    key={a.name} asset={a}
                    as={getAS(a.name)}
                    isActive={active?.name === a.name}
                    isSelected={selected.includes(a.name)}
                    onCheck={() => toggleSel(a.name)}
                    onClick={() => activateAsset(a)}
                  />)}
                </div>
              )
            })}
          </div>
        </div>

        {/* ── Panel B: Source viewer / editor ────────────────────────── */}
        <div style={{
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 8, display: 'flex', flexDirection: 'column', overflow: 'hidden',
        }}>
          {active ? <>
            {/* source header */}
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '6px 12px', background: '#0a0c14',
              borderBottom: '1px solid var(--border)', flexShrink: 0,
            }}>
              <span style={{
                fontFamily: 'var(--mono)', fontSize: 12, color: '#67e8f9',
                display: 'flex', alignItems: 'center', gap: 6,
              }}>
                <span style={{ color: 'var(--muted)' }}>
                  {active.type === 'DATASET' ? 'HLQ.DATASET' : active.type === 'BMS' ? 'HLQ.BMS.MAP' : active.type === 'JCL' ? 'HLQ.CNTL.JCL' : 'HLQ.COBOL.SRC'}
                </span>
                <span style={{ color: '#fbbf24' }}>({active.name})</span>
                {activeAS?.refinements ? <span style={{ color: 'var(--accent2)', fontSize: 10 }}>✏️×{activeAS.refinements}</span> : null}
              </span>
              <div style={{ display: 'flex', gap: 5 }}>
                {active.type === 'BMS' && (
                  <div style={{ display: 'flex', background: 'var(--surface2)', borderRadius: 5, padding: 2, border: '1px solid var(--border)' }}>
                    <button
                      onClick={() => setBmsMode('terminal')}
                      style={{
                        padding: '2px 8px', fontSize: 10, borderRadius: 3, border: 'none', cursor: 'pointer',
                        background: bmsMode === 'terminal' ? '#22c55e' : 'transparent',
                        color: bmsMode === 'terminal' ? '#000' : 'var(--muted)',
                        fontWeight: 600,
                      }}
                    >
                      🖥️ 3270 Screen
                    </button>
                    <button
                      onClick={() => setBmsMode('source')}
                      style={{
                        padding: '2px 8px', fontSize: 10, borderRadius: 3, border: 'none', cursor: 'pointer',
                        background: bmsMode === 'source' ? 'var(--accent)' : 'transparent',
                        color: bmsMode === 'source' ? '#fff' : 'var(--muted)',
                        fontWeight: 600,
                      }}
                    >
                      📄 BMS Source
                    </button>
                  </div>
                )}
                {PARSEABLE.includes(active.type) && (editMode ? <>
                  <SmBtn onClick={() => { setEditMode(false); setAS(active.name, { editedSource: activeAS?.source || '' }) }} color="var(--muted)" label="✕ Cancel" />
                  <SmBtn onClick={refine} color="var(--accent2)" label={activeAS?.status === 'parsing' ? '⏳ Re-parsing…' : '🔄 Re-parse'} disabled={activeAS?.status === 'parsing'} />
                </> : <>
                  {activeAS?.status === 'done' && <SmBtn onClick={() => setEditMode(true)} color="var(--accent2)" label="✏️ Refine" />}
                  <SmBtn
                    onClick={() => parseOne(active)}
                    color="var(--accent)"
                    label={activeAS?.status === 'parsing' ? '⏳ Parsing…' : activeAS?.status === 'done' ? '🔁 Re-parse' : '🔍 Parse → IR'}
                    disabled={activeAS?.status === 'parsing'}
                  />
                </>)}
              </div>
            </div>
            {/* status strip */}
            {activeAS?.status === 'done' && !editMode && (
              <div style={{
                padding: '4px 12px', background: 'rgba(52,211,153,.07)',
                borderBottom: '1px solid rgba(52,211,153,.15)', fontSize: 11,
                display: 'flex', gap: 12, flexShrink: 0, alignItems: 'center',
              }}>
                <span style={{ color: '#34d399', fontWeight: 600 }}>✅ IR Built</span>
                <span style={{ color: 'var(--muted)' }}>{activeAS.summary?.functions} fns · {activeAS.summary?.variables} vars · {activeAS.summary?.source_lines} lines</span>
                {(activeAS.summary?.unsupported_ops ?? 0) > 0 && (
                  <span style={{ color: '#fbbf24' }}>⚠️ {activeAS.summary?.unsupported_ops} unsupported</span>
                )}
              </div>
            )}
            {activeAS?.status === 'error' && (
              <div style={{ padding: '4px 12px', background: 'rgba(248,113,113,.08)', borderBottom: '1px solid rgba(248,113,113,.2)', fontSize: 11, color: '#f87171', flexShrink: 0 }}>
                ❌ {activeAS.error}
              </div>
            )}
            {editMode && (
              <div style={{ padding: '3px 12px', background: 'rgba(124,92,216,.1)', borderBottom: '1px solid rgba(124,92,216,.2)', fontSize: 10, color: 'var(--accent2)', flexShrink: 0 }}>
                ✏️ Edit COBOL source below → click Re-parse to update IR and graph
              </div>
            )}
            {/* source body */}
            <div style={{ flex: 1, overflow: 'hidden' }}>
              {activeAS?.status === 'parsing' ? (
                <div style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                  height: '100%', gap: 16, background: '#0a0d18', padding: 24, textAlign: 'center'
                }}>
                  <div style={{ position: 'relative', width: 68, height: 68 }}>
                    <div className="spinner" style={{ width: 68, height: 68, borderWidth: 3, borderColor: 'rgba(15, 98, 254, 0.2)', borderTopColor: '#0f62fe' }} />
                    <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 24 }}>
                      {TYPE_ICONS[active.type] || '📄'}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.01em', marginBottom: 4 }}>
                      Parsing {active.type} Asset: {active.name}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--muted)', fontFamily: 'var(--mono)', maxWidth: 360, margin: '0 auto', lineHeight: 1.5 }}>
                      Extracting AST, normalizing control flows, and projecting metadata to Neo4j knowledge graph…
                    </div>
                  </div>
                  <div style={{
                    display: 'flex', gap: 6, alignItems: 'center', background: 'rgba(15, 98, 254, 0.08)',
                    border: '1px solid rgba(15, 98, 254, 0.2)', padding: '6px 14px', borderRadius: 999,
                    fontSize: 11, color: '#4589ff'
                  }}>
                    <span className="spinner" style={{ width: 10, height: 10, borderWidth: 2 }} />
                    <span>Real-time AST Lowering Engine</span>
                  </div>
                </div>
              ) : active.type === 'BMS' && bmsMode === 'terminal' ? (
                <Terminal3270View screenName={active.name} bmsSource={activeAS?.source || ''} />
              ) : active.type === 'DATASET' ? (
                <DatasetView datasetName={active.name} rawData={activeAS?.source || ''} />
              ) : editMode ? (
                <textarea
                  value={activeAS?.editedSource || ''}
                  onChange={e => setAS(active.name, { editedSource: e.target.value })}
                  spellCheck={false}
                  style={{
                    width: '100%', height: '100%', padding: '12px 14px',
                    fontFamily: 'var(--mono)', fontSize: 12, lineHeight: 1.6,
                    background: '#0a0d18', color: 'var(--text)',
                    border: 'none', outline: 'none', resize: 'none',
                    borderTop: '2px solid var(--accent2)',
                  }}
                />
              ) : (
                <CobolSourceView source={activeAS?.source || ''} />
              )}
            </div>
          </> : (
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              justifyContent: 'center', height: '100%', gap: 10, color: 'var(--muted)',
            }}>
              <div style={{
                fontFamily: 'var(--mono)', fontSize: 12, color: '#2d3148',
                lineHeight: 1.8, textAlign: 'center',
              }}>
                {`IBM z/OS V2.5\n────────────────────────\nSYSPLEX: PLEX01 LPAR: PROD01\n────────────────────────\n`}
                <span style={{ color: 'var(--muted)' }}>Select a member from the<br/>library browser on the left</span>
              </div>
            </div>
          )}
        </div>

        {/* ── Panel C: IR / Asset Metadata Inspector ──────────────────── */}
        <div style={{
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 8, display: 'flex', flexDirection: 'column', overflow: 'hidden',
        }}>
          {activeAS?.status === 'parsing' ? (
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              height: '100%', gap: 14, padding: 24, textAlign: 'center'
            }}>
              <span className="spinner" style={{ width: 32, height: 32, borderWidth: 3, borderColor: 'rgba(15, 98, 254, 0.2)', borderTopColor: 'var(--accent)' }} />
              <div>
                <p style={{ color: 'var(--text)', fontSize: 13, fontWeight: 600, fontFamily: 'var(--mono)', margin: '0 0 4px' }}>
                  BUILDING NORMALIZED IR…
                </p>
                <p style={{ color: 'var(--muted)', fontSize: 11, margin: 0 }}>
                  Generating symbol tables and dependency graph projections
                </p>
              </div>
            </div>
          ) : active?.type === 'BMS' ? (
            <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
              <BmsMetadataTab screenName={active.name} bmsSource={activeAS?.source || ''} />
            </div>
          ) : active?.type === 'DATASET' ? (
            <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
              <DatasetMetadataTab datasetName={active.name} rawData={activeAS?.source || ''} />
            </div>
          ) : activeAS?.status === 'done' ? <>
            {/* Automatic Next Steps banner after IR generation */}
            <div style={{
              margin: '8px 10px 4px', padding: '10px 12px',
              background: 'linear-gradient(135deg, rgba(15,98,254,0.12), rgba(138,63,252,0.12))',
              border: '1px solid rgba(15,98,254,0.3)', borderRadius: 7,
              display: 'flex', flexDirection: 'column', gap: 6, flexShrink: 0,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent-light)', display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>🚀</span>
                  <span>IR Generated: Recommended Next Steps</span>
                </span>
                <span style={{ fontSize: 10, color: '#34d399', background: 'rgba(52,211,153,0.15)', padding: '2px 6px', borderRadius: 4, fontWeight: 600 }}>
                  READY
                </span>
              </div>
              <p style={{ margin: 0, fontSize: 11, color: 'var(--muted)', lineHeight: 1.4 }}>
                AST lowered into Normalized IR for <strong>{active?.name}</strong>. Choose next modernization action:
              </p>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 2 }}>
                <button
                  onClick={() => nav('/graph', { state: { asset: active?.name } })}
                  style={{
                    padding: '4px 9px', fontSize: 11, borderRadius: 5, border: '1px solid rgba(15,98,254,0.4)',
                    background: 'rgba(15,98,254,0.2)', color: '#a6c8ff', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
                  }}
                >
                  🕸️ Explore Graph
                </button>
                <button
                  onClick={() => nav('/wizard')}
                  style={{
                    padding: '4px 9px', fontSize: 11, borderRadius: 5, border: '1px solid rgba(138,63,252,0.4)',
                    background: 'rgba(138,63,252,0.2)', color: '#d4bbff', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
                  }}
                >
                  ⚙️ Configure (Granite)
                </button>
                <button
                  onClick={() => active && startMigrate(active.name)}
                  disabled={migrating}
                  style={{
                    padding: '4px 10px', fontSize: 11, borderRadius: 5, border: 'none',
                    background: '#34d399', color: '#000', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
                  }}
                >
                  ☕ Launch Migration
                </button>
              </div>
            </div>

            {/* IR tabs */}
            <div style={{
              display: 'flex', background: '#0a0c14',
              borderBottom: '1px solid var(--border)', flexShrink: 0,
            }}>
              {([
                { id: 'summary',   label: '📊 IR' },
                { id: 'functions', label: '⚙️ Fns' },
                { id: 'variables', label: '📦 Vars' },
                { id: 'graph',     label: '🕸️ Neo4j Graph' },
                { id: 'raw',       label: '{}' },
              ] as { id: IRTab; label: string }[]).map(t => (
                <button key={t.id} onClick={() => setIRTab(t.id)} style={{
                  padding: '6px 12px', fontSize: 11, border: 'none', cursor: 'pointer',
                  background: irTab === t.id ? 'var(--surface)' : 'transparent',
                  color: irTab === t.id ? 'var(--text)' : 'var(--muted)',
                  borderBottom: irTab === t.id ? '2px solid var(--accent)' : '2px solid transparent',
                  fontWeight: irTab === t.id ? 600 : 400,
                }}>{t.label}</button>
              ))}
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
              {irTab === 'summary'   && <IRSummaryTab summary={activeAS.summary!} refinements={activeAS.refinements} assetName={active?.name || ''} />}
              {irTab === 'functions' && <IRFunctionsTab irJson={activeAS.irJson} />}
              {irTab === 'variables' && <IRVariablesTab irJson={activeAS.irJson} />}
              {irTab === 'graph'     && <IRGraphTab graphData={activeAS.graphData} programName={active?.name || ''} onOpenNeo4j={() => nav('/graph', { state: { asset: active?.name } })} />}
              {irTab === 'raw'       && (
                <pre style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--muted)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                  {JSON.stringify(activeAS.irJson, null, 2)}
                </pre>
              )}
            </div>
            {/* migrate footer */}
            <div style={{
              padding: '8px 12px', background: '#0a0c14',
              borderTop: '1px solid var(--border)', flexShrink: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <span style={{ fontSize: 11, color: (activeAS.summary?.unsupported_ops ?? 0) > 0 ? '#fbbf24' : '#34d399' }}>
                {(activeAS.summary?.unsupported_ops ?? 0) > 0
                  ? `⚠️ ${activeAS.summary?.unsupported_ops} unsupported ops`
                  : '✅ Ready to migrate'}
              </span>
              <div style={{ display: 'flex', gap: 6 }}>
                <SmBtn onClick={() => setEditMode(true)} color="var(--accent2)" label="✏️ Refine" />
                <button
                  onClick={() => active && startMigrate(active.name)}
                  disabled={migrating}
                  style={{
                    padding: '4px 14px', fontSize: 11, borderRadius: 5, cursor: migrating ? 'wait' : 'pointer',
                    background: migrating ? 'var(--surface2)' : '#34d399', color: '#000', border: 'none',
                  }}
                >
                  {migrating && migratingProg === active?.name ? '⏳ Migrating…' : `☕ Migrate ${active?.name}`}
                </button>
              </div>
            </div>
          </> : (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 10, color: 'var(--muted)', textAlign: 'center', padding: 20 }}>
              <span style={{ fontSize: 32 }}>🔍</span>
              <p style={{ fontSize: 13, fontWeight: 600 }}>IR Inspector</p>
              <p style={{ fontSize: 11 }}>Select a COBOL member and click<br /><strong style={{ color: 'var(--accent)' }}>Parse → IR</strong> to inspect the<br />Normalized Intermediate Representation</p>
              {activeAS?.status === 'error' && (
                <div style={{ background: 'rgba(248,113,113,.1)', border: '1px solid var(--red)', borderRadius: 6, padding: 8, fontSize: 11, color: '#f87171', maxWidth: '100%' }}>
                  {activeAS.error}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Panel D: Agent Status (bottom, spans cols 2+3) ────────── */}
        <div style={{
          gridColumn: '2 / 4',
          background: '#080a12', border: '1px solid var(--border)',
          borderRadius: 8, overflow: 'hidden', display: 'flex', flexDirection: 'column',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '6px 12px', background: '#0a0c14',
            borderBottom: '1px solid var(--border)', flexShrink: 0,
          }}>
            <span style={{ fontSize: 14 }}>🤖</span>
            <span style={{ fontSize: 12, fontWeight: 600, fontFamily: 'var(--mono)' }}>
              AGENT STATUS
            </span>
            {migrating && (
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 10,
                background: 'rgba(251,191,36,.15)', color: '#fbbf24',
                animation: 'pulse 1.5s infinite',
              }}>
                ● RUNNING — {migratingProg}
              </span>
            )}
            {!migrating && agentSteps.length > 0 && (
              <span style={{ fontSize: 10, color: '#34d399' }}>● IDLE</span>
            )}
            {agentSteps.length === 0 && (
              <span style={{ fontSize: 10, color: 'var(--muted)' }}>
                Parse a program above, then click Migrate to see live agent pipeline
              </span>
            )}
            <div style={{ flex: 1 }} />
            {agentSteps.some(e => e.event === 'done') && (
              <button
                onClick={() => nav('/result')}
                style={{
                  padding: '3px 12px', fontSize: 11, borderRadius: 5, cursor: 'pointer',
                  background: '#34d399', color: '#000', border: 'none',
                }}
              >
                View Results →
              </button>
            )}
          </div>

          {/* agent timeline */}
          <div style={{
            flex: 1, overflowY: 'auto', padding: '6px 12px',
            display: 'flex', flexDirection: 'column', gap: 2,
            fontFamily: 'var(--mono)', fontSize: 11,
          }}>
            {agentSteps.length === 0 ? (
              <div style={{ color: 'var(--border)', textAlign: 'center', paddingTop: 16, fontSize: 11 }}>
                — pipeline will appear here —
              </div>
            ) : agentSteps.map((step, i) => {
              const meta = AGENT_LABEL[step.event] || { icon: '▸', label: step.event, color: 'var(--muted)' }
              const detail = step.function ? ` · fn:${step.function}` : ''
                + (step.round ? ` · round ${step.round}` : '')
                + (step.strategy ? ` · strategy:${step.strategy}` : '')
                + (step.effort ? ` · effort:${step.effort}` : '')
                + (step.completeness != null ? ` · ${step.completeness}% coverage` : '')
                + (step.issues?.length ? ` · issues:[${step.issues.slice(0,2).join(', ')}]` : '')
                + (step.rounds != null ? ` · ${step.rounds} total rounds` : '')
                + (step.error ? ` · ERROR: ${step.error}` : '')
              return (
                <div key={i} style={{
                  display: 'flex', gap: 8, alignItems: 'flex-start', padding: '2px 0',
                  borderBottom: '1px solid rgba(255,255,255,.03)',
                  opacity: meta.label === 'keepalive' ? 0 : 1,
                }}>
                  <span style={{ color: 'var(--muted)', minWidth: 72, flexShrink: 0 }}>{step.ts}</span>
                  <span style={{ minWidth: 18 }}>{meta.icon}</span>
                  <span style={{ color: meta.color, fontWeight: 600, minWidth: 140 }}>{meta.label}</span>
                  <span style={{ color: 'var(--muted)' }}>{detail}</span>
                  {step.notes && <span style={{ color: '#4f9cf9', fontStyle: 'italic', marginLeft: 4 }}>"{step.notes.slice(0, 60)}"</span>}
                </div>
              )
            })}
            <div ref={agentEndRef} />
          </div>

          {/* agent pipeline legend */}
          {!migrating && agentSteps.length === 0 && (
            <div style={{
              display: 'flex', gap: 0, borderTop: '1px solid var(--border)',
              flexShrink: 0, overflow: 'hidden',
            }}>
              {[
                { icon: '📋', label: 'Planner',  desc: 'Reads IR → MigrationPlan', color: '#4f9cf9' },
                { icon: '⚙️', label: 'Executor', desc: 'IR + scaffold → Java code', color: '#fbbf24' },
                { icon: '🔎', label: 'Critic',   desc: 'Validates IR coverage',     color: '#a78bfa' },
                { icon: '☕', label: 'Emitter',  desc: 'Deterministic Java output', color: '#34d399' },
              ].map((s, i) => (
                <div key={i} style={{
                  flex: 1, padding: '6px 10px', borderLeft: i > 0 ? '1px solid var(--border)' : 'none',
                  display: 'flex', gap: 6, alignItems: 'center',
                }}>
                  <span style={{ fontSize: 14 }}>{s.icon}</span>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: s.color }}>{s.label}</div>
                    <div style={{ fontSize: 10, color: 'var(--muted)' }}>{s.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }`}</style>
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════════
   SMALL HELPER COMPONENTS
═══════════════════════════════════════════════════════════════════════════ */

function ToolBtn({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button onClick={onClick} style={{
      padding: '5px 12px', fontSize: 11, borderRadius: 5, cursor: 'pointer',
      background: 'var(--surface2)', color: 'var(--muted)',
      border: '1px solid var(--border)',
    }}>{label}</button>
  )
}

function SmBtn({ onClick, label, color, disabled }: {
  onClick: () => void; label: string; color: string; disabled?: boolean
}) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      padding: '3px 10px', fontSize: 11, borderRadius: 5, cursor: disabled ? 'wait' : 'pointer',
      background: 'transparent', color, border: `1px solid ${color}`,
      opacity: disabled ? 0.5 : 1,
    }}>{label}</button>
  )
}

function AssetRow({ asset, as, isActive, isSelected, onCheck, onClick }: {
  asset: Asset; as: AssetState; isActive: boolean; isSelected: boolean
  onCheck: () => void; onClick: () => void
}) {
  const DOT: Record<ParseStatus, string> = {
    idle: '#4b5563', parsing: '#f1c21b', done: '#24a148', error: '#f1c21b',
  }
  return (
    <div onClick={onClick} style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '6px 10px', cursor: 'pointer', userSelect: 'none',
      background: isActive ? 'rgba(15,98,254,.12)' : 'transparent',
      borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
      transition: 'var(--transition-smooth)',
    }}>
      <input
        type="checkbox" checked={isSelected}
        onChange={onCheck} onClick={e => e.stopPropagation()}
        style={{ accentColor: 'var(--accent)', cursor: 'pointer', flexShrink: 0 }}
      />
      <span style={{
        width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
        background: DOT[as.status],
        boxShadow: as.status === 'parsing' ? '0 0 6px #f1c21b' : 'none',
      }} />
      <span style={{ fontSize: 13, flexShrink: 0 }}>{TYPE_ICONS[asset.type] || '📄'}</span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{
          fontSize: 12, fontWeight: 500, fontFamily: 'var(--mono)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          color: as.status === 'done' ? 'var(--text)' : 'var(--text-secondary)',
        }}>
          {asset.name}
        </div>
        <div style={{ fontSize: 10, color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span>
            {as.status === 'idle' ? asset.type
              : as.status === 'parsing' ? '⏳ Parsing…'
              : as.status === 'done' ? `IR Ready · ${as.summary?.functions ?? 0} fns`
              : `Ready to parse`}
          </span>
          {as.refinements > 0 && <span style={{ color: 'var(--accent2)' }}>· ✏️×{as.refinements}</span>}
        </div>
      </div>
    </div>
  )
}

/* ─── Syntax-highlighted COBOL source ──────────────────────────────────── */
function CobolSourceView({ source }: { source: string }) {
  return (
    <div style={{ height: '100%', overflow: 'auto', padding: '10px 14px', background: '#080a12' }}>
      <pre style={{ fontFamily: 'var(--mono)', fontSize: 12, lineHeight: 1.65, margin: 0 }}>
        {source.split('\n').map((line, i) => {
          const u = line.trim().toUpperCase()
          let c = '#c9d1d9'
          if (line.trim().startsWith('*') || u.startsWith('*>'))                       c = '#484f58'
          else if (/^\s*(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION/.test(u)) c = '#e879f9'
          else if (/^\s*(WORKING-STORAGE|FILE|LINKAGE|LOCAL-STORAGE)\s+SECTION/.test(u)) c = '#c084fc'
          else if (/^\s*\d{2}\s+/.test(line))                                            c = '#7dd3fc'
          else if (/\b(PERFORM|CALL|IF|ELSE|END-IF|EVALUATE|WHEN|SEARCH)\b/.test(u))    c = '#60a5fa'
          else if (/\b(MOVE|COMPUTE|ADD|SUBTRACT|MULTIPLY|DIVIDE)\b/.test(u))            c = '#93c5fd'
          else if (/\b(DISPLAY|ACCEPT|OPEN|CLOSE|READ|WRITE|REWRITE)\b/.test(u))        c = '#67e8f9'
          else if (/\b(PIC|PICTURE|VALUE|COMP|BINARY|USAGE|PACKED-DECIMAL)\b/.test(u))  c = '#86efac'
          else if (/\b(STOP RUN|GOBACK|EXIT PROGRAM)\b/.test(u))                         c = '#fca5a5'
          return (
            <div key={i} style={{ display: 'flex', gap: 12 }}>
              <span style={{ color: '#2d3148', minWidth: 28, textAlign: 'right', flexShrink: 0, userSelect: 'none' }}>
                {i + 1}
              </span>
              <span style={{ color: c }}>{line || '\u00a0'}</span>
            </div>
          )
        })}
      </pre>
    </div>
  )
}

/* ─── IR Summary ───────────────────────────────────────────────────────── */
function IRSummaryTab({ summary, refinements, assetName }: {
  summary: IrSummary; refinements: number; assetName: string
}) {
  const risk = summary.unsupported_ops > 5 ? 'HIGH' : summary.unsupported_ops > 0 ? 'MEDIUM' : 'LOW'
  const rc = { HIGH: '#f87171', MEDIUM: '#fbbf24', LOW: '#34d399' }[risk]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 12, color: '#7dd3fc' }}>
        IR :: {assetName}{refinements > 0 ? ` (${refinements}× refined)` : ''}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        {[
          { l: 'Source Lines', v: summary.source_lines, i: '📄', w: false },
          { l: 'Functions',    v: summary.functions,    i: '⚙️', w: false },
          { l: 'Variables',    v: summary.variables,    i: '📦', w: false },
          { l: 'Unsupported',  v: summary.unsupported_ops, i: '⚠️', w: summary.unsupported_ops > 0 },
        ].map(m => (
          <div key={m.l} style={{
            background: '#0d0f1a', borderRadius: 6, padding: '8px 10px',
            border: m.w ? '1px solid rgba(251,191,36,.3)' : '1px solid #1e2235',
          }}>
            <div style={{ fontSize: 14 }}>{m.i}</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: m.w ? '#fbbf24' : '#60a5fa' }}>{m.v}</div>
            <div style={{ fontSize: 10, color: 'var(--muted)' }}>{m.l}</div>
          </div>
        ))}
      </div>
      <div style={{ background: '#0d0f1a', borderRadius: 6, padding: '8px 10px', fontSize: 11 }}>
        {[
          ['Dialect', summary.dialect],
          ['Uses Files', summary.uses_files ? 'Yes' : 'No'],
          ['Risk', risk],
        ].map(([k, v]) => (
          <div key={k} style={{ display: 'flex', gap: 8, padding: '3px 0' }}>
            <span style={{ color: 'var(--muted)', minWidth: 80, fontFamily: 'var(--mono)' }}>{k}</span>
            <span style={{ color: k === 'Risk' ? rc : 'var(--text)', fontWeight: k === 'Risk' ? 700 : 400 }}>{String(v)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ─── IR Functions ─────────────────────────────────────────────────────── */
function IRFunctionsTab({ irJson }: { irJson: unknown }) {
  const fns: any[] = (irJson as any)?.functions ?? []
  if (!fns.length) return <p style={{ color: 'var(--muted)', fontSize: 12 }}>No functions.</p>
  return (
    <div>
      {[...fns].sort((a, b) => (b.complexity ?? 0) - (a.complexity ?? 0)).map((fn: any) => (
        <div key={fn.name} style={{
          background: '#0d0f1a', borderRadius: 5, padding: '8px 10px', marginBottom: 6,
          borderLeft: `2px solid ${fn.kind === 'main' ? '#60a5fa' : fn.is_io ? '#fbbf24' : '#1e2235'}`,
        }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 2 }}>
            <code style={{ color: fn.kind === 'main' ? '#60a5fa' : 'var(--text)', fontSize: 12, fontWeight: 600 }}>{fn.name}</code>
            <span style={{ fontSize: 9, color: 'var(--muted)', padding: '1px 5px', background: 'rgba(255,255,255,.05)', borderRadius: 4 }}>{fn.kind}</span>
            {fn.is_io && <span style={{ fontSize: 10, color: '#fbbf24' }}>I/O</span>}
            {fn.unsupported_count > 0 && <span style={{ fontSize: 10, color: '#fbbf24' }}>⚠️{fn.unsupported_count}</span>}
          </div>
          <div style={{ fontSize: 10, color: 'var(--muted)', display: 'flex', gap: 12 }}>
            <span>cx:<strong style={{ color: fn.complexity > 5 ? '#f87171' : fn.complexity > 2 ? '#fbbf24' : '#34d399' }}>{fn.complexity}</strong></span>
            <span>in:{fn.fan_in}</span><span>out:{fn.fan_out}</span>
            {fn.callees?.length > 0 && <span>calls: {fn.callees.map((c: string) => (
              <code key={c} style={{ color: '#60a5fa', marginLeft: 3, fontSize: 10 }}>{c}</code>
            ))}</span>}
          </div>
        </div>
      ))}
    </div>
  )
}

/* ─── IR Variables ─────────────────────────────────────────────────────── */
function IRVariablesTab({ irJson }: { irJson: unknown }) {
  const vars = Object.values((irJson as any)?.vars ?? {}).filter((v: any) => !v.is_temp)
  if (!vars.length) return <p style={{ color: 'var(--muted)', fontSize: 12 }}>No vars.</p>
  const TC: Record<string, string> = { int: '#60a5fa', dec: '#fbbf24', str: '#86efac', bool: '#c084fc', unknown: 'var(--muted)' }
  return (
    <div>
      {vars.map((v: any) => (
        <div key={v.vid} style={{ display: 'flex', gap: 6, padding: '4px 0', borderBottom: '1px solid #0d0f1a', fontSize: 11, alignItems: 'center' }}>
          <code style={{ color: 'var(--text)', minWidth: 110, fontFamily: 'var(--mono)', fontSize: 11 }}>{v.name}</code>
          <span style={{ fontSize: 10, padding: '1px 5px', background: 'rgba(255,255,255,.04)', borderRadius: 4, color: TC[v.type] || 'var(--muted)' }}>{v.type}</span>
          {v.picture && <code style={{ fontSize: 10, color: 'var(--muted)' }}>{v.picture}</code>}
          {v.occurs > 1 && <span style={{ fontSize: 10, color: '#c084fc' }}>×{v.occurs}</span>}
          {v.is_condition && <span style={{ fontSize: 9, color: '#fbbf24' }}>88</span>}
          {v.initial != null && <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 'auto' }}>={JSON.stringify(v.initial)}</span>}
        </div>
      ))}
    </div>
  )
}

/* ─── IR Graph (force canvas) ──────────────────────────────────────────── */
function IRGraphTab({ graphData, programName, onOpenNeo4j }: {
  graphData: GraphResponse | null; programName: string; onOpenNeo4j?: () => void
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const posRef    = useRef<Record<string | number, { x: number; y: number; vx: number; vy: number }>>({})
  const rafRef    = useRef<number>(0)
  const divRef    = useRef<HTMLDivElement>(null)
  const nodes = graphData?.nodes ?? []
  const links = graphData?.links ?? []
  const NC: Record<string, string> = {
    Program: '#0f62fe', Function: '#8a3ffc', Variable: '#24a148',
    Dataset: '#f1c21b', Job: '#da1e28', Screen: '#ff7eb6', Field: '#1192e8'
  }

  useEffect(() => {
    if (!nodes.length || !canvasRef.current || !divRef.current) return
    const W = divRef.current.clientWidth || 340, H = 260
    canvasRef.current.width = W; canvasRef.current.height = H
    const ctx = canvasRef.current.getContext('2d')!
    nodes.forEach(n => { if (!posRef.current[n.id]) posRef.current[n.id] = { x: Math.random() * W, y: Math.random() * H, vx: 0, vy: 0 } })
    const sim = () => {
      const p = posRef.current
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const a = p[nodes[i].id], b = p[nodes[j].id]; if (!a || !b) continue
        const dx = a.x - b.x, dy = a.y - b.y, d = Math.sqrt(dx*dx+dy*dy)||1, f = 2200/(d*d)
        a.vx+=dx/d*f; a.vy+=dy/d*f; b.vx-=dx/d*f; b.vy-=dy/d*f
      }
      links.forEach(l => {
        const a = p[l.source], b = p[l.target]; if (!a || !b) return
        const dx = b.x-a.x, dy = b.y-a.y, d = Math.sqrt(dx*dx+dy*dy)||1, f = (d-80)*.012
        a.vx+=dx/d*f; a.vy+=dy/d*f; b.vx-=dx/d*f; b.vy-=dy/d*f
      })
      nodes.forEach(n => {
        const q = p[n.id]; if (!q) return
        q.vx+=(W/2-q.x)*.003; q.vy+=(H/2-q.y)*.003; q.vx*=.82; q.vy*=.82
        q.x=Math.max(14,Math.min(W-14,q.x+q.vx)); q.y=Math.max(14,Math.min(H-14,q.y+q.vy))
      })
      ctx.clearRect(0,0,W,H)
      ctx.strokeStyle='#1e2235'; ctx.lineWidth=1
      links.forEach(l => {
        const a=p[l.source],b=p[l.target]; if(!a||!b) return
        ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke()
        const ang=Math.atan2(b.y-a.y,b.x-a.x), ex=b.x-Math.cos(ang)*10, ey=b.y-Math.sin(ang)*10
        ctx.beginPath(); ctx.moveTo(ex,ey)
        ctx.lineTo(ex-5*Math.cos(ang-.4),ey-5*Math.sin(ang-.4))
        ctx.lineTo(ex-5*Math.cos(ang+.4),ey-5*Math.sin(ang+.4))
        ctx.closePath(); ctx.fillStyle='#2d3148'; ctx.fill()
      })
      nodes.forEach(n => {
        const q=p[n.id]; if(!q) return
        const col=NC[n.label]||'#888', r=(n.label==='Program'||n.label==='Screen'||n.label==='Job')?11:(n.label==='Function'||n.label==='Dataset')?8:6
        ctx.beginPath(); ctx.arc(q.x,q.y,r,0,Math.PI*2); ctx.fillStyle=col+'22'; ctx.fill()
        ctx.strokeStyle=col; ctx.lineWidth=2; ctx.stroke()
        ctx.fillStyle=col; ctx.font=`${r>8?11:10}px monospace`
        ctx.fillText((n.name||'').slice(0,12),q.x+r+3,q.y+4)
      })
      rafRef.current=requestAnimationFrame(sim)
    }
    rafRef.current=requestAnimationFrame(sim)
    return () => cancelAnimationFrame(rafRef.current)
  }, [nodes, links])

  return (
    <div ref={divRef}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <div style={{ fontSize: 11, color: 'var(--muted)' }}>
          {nodes.length} nodes · {links.length} edges
        </div>
        {onOpenNeo4j && (
          <button
            onClick={onOpenNeo4j}
            style={{
              padding: '3px 10px', fontSize: 11, borderRadius: 5, cursor: 'pointer',
              background: 'rgba(15,98,254,0.15)', color: '#4589ff', border: '1px solid rgba(15,98,254,0.3)',
              fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4, transition: 'var(--transition-smooth)'
            }}
          >
            ⚡ Open in Neo4j Studio ↗
          </button>
        )}
      </div>
      {nodes.length > 0
        ? <canvas ref={canvasRef} style={{ display: 'block', borderRadius: 6, background: '#040508', width: '100%' }} />
        : <div style={{ height: 180, background: '#040508', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', fontSize: 12 }}>
            Parse to generate dependency graph
          </div>
      }
      <div style={{ display: 'flex', gap: 10, marginTop: 6, flexWrap: 'wrap' }}>
        {Object.entries(NC).map(([label, color]) => (
          <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: 'var(--muted)' }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: color, display: 'inline-block' }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  )
}

/* ─── IBM 3270 Green-Screen Terminal Simulator ─────────────────────────── */
function Terminal3270View({ screenName }: { screenName: string; bmsSource?: string }) {
  const isPay = screenName.toUpperCase().includes('PAY')
  const [empId, setEmpId] = useState('1001')
  const [orderNo, setOrderNo] = useState('ORD10001')
  const [statusMsg, setStatusMsg] = useState('DFH3270I: READY FOR TRANSACTION INPUT')
  const [recordData, setRecordData] = useState({
    name: 'SMITH, JOHN',
    dept: 'IT - SYSTEMS',
    rate: '$85,000 / YR',
    status: 'ACTIVE (FULL-TIME)',
    hours: '40.0',
    gross: '$7,083.33',
    tax: '$1,558.33',
    net: '$5,525.00'
  })
  const [orderData, setOrderData] = useState({
    cust: 'CUST99201',
    amt: '$12,500.00',
    discount: '5% VIP DISCOUNT',
    netAmt: '$11,875.00',
    stat: 'CONFIRMED / DISPATCHED',
    date: '2024-01-10'
  })

  const handleQuery = () => {
    if (isPay) {
      if (empId === '1001') {
        setRecordData({ name: 'SMITH, JOHN', dept: 'IT - SYSTEMS', rate: '$85,000 / YR', status: 'ACTIVE (FULL-TIME)', hours: '40.0', gross: '$7,083.33', tax: '$1,558.33', net: '$5,525.00' })
        setStatusMsg('DFH3270I: RECORD RETRIEVED SUCCESSFULLY FOR EMPID: 1001')
      } else if (empId === '1002') {
        setRecordData({ name: 'JOHNSON, ALICE', dept: 'FINANCE & ACCT', rate: '$92,000 / YR', status: 'ACTIVE (FULL-TIME)', hours: '40.0', gross: '$7,666.67', tax: '$1,686.67', net: '$5,980.00' })
        setStatusMsg('DFH3270I: RECORD RETRIEVED SUCCESSFULLY FOR EMPID: 1002')
      } else if (empId === '1003') {
        setRecordData({ name: 'WILLIAMS, ROBERT', dept: 'ENGINEERING', rate: '$105,000 / YR', status: 'ACTIVE (FULL-TIME)', hours: '45.0', gross: '$9,843.75', tax: '$2,264.06', net: '$7,579.69' })
        setStatusMsg('DFH3270I: RECORD RETRIEVED SUCCESSFULLY FOR EMPID: 1003')
      } else {
        setRecordData({ name: `EMPLOYEE #${empId}`, dept: 'OPERATIONS', rate: '$78,500 / YR', status: 'ACTIVE', hours: '40.0', gross: '$6,541.67', tax: '$1,439.17', net: '$5,102.50' })
        setStatusMsg(`DFH3270I: RECORD FOUND IN VSAM KSDS (KEY=${empId})`)
      }
    } else {
      if (orderNo.toUpperCase().includes('10002')) {
        setOrderData({ cust: 'CUST48112', amt: '$4,500.00', discount: '0% STD', netAmt: '$4,500.00', stat: 'PENDING MANUAL REVIEW', date: '2024-01-10' })
        setStatusMsg('DFH3270I: ORDER RECORD IN PENDING STATE. CICS COMM-AREA OK.')
      } else if (orderNo.toUpperCase().includes('10003')) {
        setOrderData({ cust: 'CUST11049', amt: '$89,200.00', discount: '5% VIP DISCOUNT', netAmt: '$84,740.00', stat: 'APPROVED & ROUTED', date: '2024-01-10' })
        setStatusMsg('DFH3270I: LARGE BATCH ORDER RETRIEVED (CREDIT VERIFIED).')
      } else {
        setOrderData({ cust: 'CUST99201', amt: '$12,500.00', discount: '5% VIP DISCOUNT', netAmt: '$11,875.00', stat: 'CONFIRMED / DISPATCHED', date: '2024-01-10' })
        setStatusMsg(`DFH3270I: ORDER RECORD RETRIEVED FROM DB2/VSAM FOR ${orderNo}`)
      }
    }
  }

  const handleClear = () => {
    if (isPay) {
      setEmpId('')
      setRecordData({ name: '', dept: '', rate: '', status: '', hours: '', gross: '', tax: '', net: '' })
    } else {
      setOrderNo('')
      setOrderData({ cust: '', amt: '', discount: '', netAmt: '', stat: '', date: '' })
    }
    setStatusMsg('DFH3270I: BUFFER CLEARED (PA1 SIGNAL)')
  }

  return (
    <div style={{
      height: '100%', display: 'flex', flexDirection: 'column',
      background: '#040d07', color: '#22c55e', fontFamily: '"Courier New", Courier, monospace',
      position: 'relative', overflow: 'hidden', padding: 12, userSelect: 'none'
    }}>
      {/* CRT Scanline overlay effect */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
        background: 'linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%)',
        backgroundSize: '100% 4px', pointerEvents: 'none', zIndex: 10, opacity: 0.7
      }} />

      {/* Top Mainframe Session Bar */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(34, 197, 94, 0.3)',
        paddingBottom: 6, marginBottom: 8, fontSize: 11, color: '#4ade80'
      }}>
        <span>SYS: IBM z/OS V2.5</span>
        <span>APPLID: CICS01</span>
        <span>TRAN: {isPay ? 'PAY1' : 'ORD1'}</span>
        <span>TERM: 3270-2 (24x80)</span>
        <span style={{ color: '#86efac' }}>● CONNECTED</span>
      </div>

      {/* Screen Title */}
      <div style={{ textAlign: 'center', marginBottom: 12, borderBottom: '1px dashed rgba(34, 197, 94, 0.2)', paddingBottom: 6 }}>
        <div style={{ fontSize: 14, fontWeight: 'bold', letterSpacing: 2, color: '#86efac', textShadow: '0 0 8px rgba(34,197,94,0.6)' }}>
          {isPay ? '*** EMPLOYEE PAYROLL INQUIRY SYSTEM ***' : '*** CUSTOMER ORDER INQUIRY SYSTEM ***'}
        </div>
        <div style={{ fontSize: 10, color: 'rgba(34, 197, 94, 0.6)', marginTop: 2 }}>
          MAPSET: {screenName}M &nbsp;|&nbsp; MAP: {screenName} &nbsp;|&nbsp; PROG: {screenName}PRG
        </div>
      </div>

      {/* Screen Form Content */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
        {isPay ? (
          <>
            {/* Input Row */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, background: 'rgba(34, 197, 94, 0.05)', padding: '6px 10px', borderRadius: 4 }}>
              <span style={{ color: '#86efac', fontWeight: 'bold' }}>EMPLOYEE ID :</span>
              <div style={{ display: 'flex', alignItems: 'center', background: '#021808', border: '1px solid #22c55e', padding: '2px 8px', borderRadius: 3 }}>
                <input
                  type="text"
                  value={empId}
                  onChange={e => setEmpId(e.target.value.toUpperCase())}
                  onKeyDown={e => { if (e.key === 'Enter') handleQuery() }}
                  maxLength={6}
                  placeholder="1001"
                  style={{
                    background: 'transparent', border: 'none', color: '#86efac',
                    fontFamily: '"Courier New", Courier, monospace', fontSize: 14, fontWeight: 'bold',
                    width: 70, outline: 'none'
                  }}
                />
                <span className="blinking-cursor" style={{ color: '#22c55e', fontWeight: 'bold' }}>_</span>
              </div>
              <button
                onClick={handleQuery}
                style={{
                  padding: '3px 10px', background: '#15803d', color: '#fff', border: 'none',
                  borderRadius: 3, cursor: 'pointer', fontSize: 11, fontWeight: 'bold'
                }}
              >
                [ENTER] Inquire
              </button>
              <div style={{ display: 'flex', gap: 4, marginLeft: 'auto' }}>
                <span style={{ fontSize: 10, color: 'rgba(34,197,94,0.6)', alignSelf: 'center' }}>Samples:</span>
                {['1001', '1002', '1003'].map(id => (
                  <button
                    key={id}
                    onClick={() => { setEmpId(id); setTimeout(handleQuery, 50) }}
                    style={{
                      padding: '2px 6px', fontSize: 10, background: 'rgba(34,197,94,0.1)',
                      border: '1px solid rgba(34,197,94,0.3)', color: '#86efac', borderRadius: 2, cursor: 'pointer'
                    }}
                  >
                    {id}
                  </button>
                ))}
              </div>
            </div>

            {/* Display Fields */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, padding: '4px 8px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div><span style={{ color: 'rgba(34, 197, 94, 0.7)' }}>EMP NAME   : </span><span style={{ color: '#4ade80', fontWeight: 'bold', textShadow: '0 0 4px rgba(74,222,128,0.5)' }}>{recordData.name || '────────────────────'}</span></div>
                <div><span style={{ color: 'rgba(34, 197, 94, 0.7)' }}>DEPARTMENT : </span><span style={{ color: '#4ade80' }}>{recordData.dept || '──────────'}</span></div>
                <div><span style={{ color: 'rgba(34, 197, 94, 0.7)' }}>STATUS     : </span><span style={{ color: '#4ade80' }}>{recordData.status || '──────────'}</span></div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div><span style={{ color: 'rgba(34, 197, 94, 0.7)' }}>PAY RATE   : </span><span style={{ color: '#4ade80', fontWeight: 'bold' }}>{recordData.rate || '──────────'}</span></div>
                <div><span style={{ color: 'rgba(34, 197, 94, 0.7)' }}>HOURS WRK  : </span><span style={{ color: '#4ade80' }}>{recordData.hours || '─────'}</span></div>
                <div><span style={{ color: 'rgba(34, 197, 94, 0.7)' }}>EST NET PAY: </span><span style={{ color: '#86efac', fontWeight: 'bold' }}>{recordData.net || '──────────'}</span></div>
              </div>
            </div>

            {/* Pay calculation box */}
            <div style={{
              marginTop: 6, border: '1px dashed rgba(34, 197, 94, 0.3)',
              padding: '6px 10px', borderRadius: 4, background: 'rgba(34, 197, 94, 0.02)',
              fontSize: 11, display: 'flex', justifyContent: 'space-around'
            }}>
              <span>GROSS PAY: <b style={{ color: '#86efac' }}>{recordData.gross}</b></span>
              <span>DEDUCTIONS / TAX: <b style={{ color: '#f87171' }}>{recordData.tax}</b></span>
              <span>NET PAY: <b style={{ color: '#4ade80' }}>{recordData.net}</b></span>
            </div>
          </>
        ) : (
          <>
            {/* Input Row for Order */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, background: 'rgba(34, 197, 94, 0.05)', padding: '6px 10px', borderRadius: 4 }}>
              <span style={{ color: '#86efac', fontWeight: 'bold' }}>ORDER NUM   :</span>
              <div style={{ display: 'flex', alignItems: 'center', background: '#021808', border: '1px solid #22c55e', padding: '2px 8px', borderRadius: 3 }}>
                <input
                  type="text"
                  value={orderNo}
                  onChange={e => setOrderNo(e.target.value.toUpperCase())}
                  onKeyDown={e => { if (e.key === 'Enter') handleQuery() }}
                  maxLength={10}
                  placeholder="ORD10001"
                  style={{
                    background: 'transparent', border: 'none', color: '#86efac',
                    fontFamily: '"Courier New", Courier, monospace', fontSize: 14, fontWeight: 'bold',
                    width: 90, outline: 'none'
                  }}
                />
                <span className="blinking-cursor" style={{ color: '#22c55e', fontWeight: 'bold' }}>_</span>
              </div>
              <button
                onClick={handleQuery}
                style={{
                  padding: '3px 10px', background: '#15803d', color: '#fff', border: 'none',
                  borderRadius: 3, cursor: 'pointer', fontSize: 11, fontWeight: 'bold'
                }}
              >
                [ENTER] Inquire
              </button>
              <div style={{ display: 'flex', gap: 4, marginLeft: 'auto' }}>
                <span style={{ fontSize: 10, color: 'rgba(34,197,94,0.6)', alignSelf: 'center' }}>Samples:</span>
                {['ORD10001', 'ORD10002', 'ORD10003'].map(id => (
                  <button
                    key={id}
                    onClick={() => { setOrderNo(id); setTimeout(handleQuery, 50) }}
                    style={{
                      padding: '2px 6px', fontSize: 10, background: 'rgba(34,197,94,0.1)',
                      border: '1px solid rgba(34,197,94,0.3)', color: '#86efac', borderRadius: 2, cursor: 'pointer'
                    }}
                  >
                    {id}
                  </button>
                ))}
              </div>
            </div>

            {/* Display Fields for Order */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, padding: '4px 8px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div><span style={{ color: 'rgba(34, 197, 94, 0.7)' }}>CUSTOMER ID : </span><span style={{ color: '#4ade80', fontWeight: 'bold' }}>{orderData.cust}</span></div>
                <div><span style={{ color: 'rgba(34, 197, 94, 0.7)' }}>ORDER DATE  : </span><span style={{ color: '#4ade80' }}>{orderData.date}</span></div>
                <div><span style={{ color: 'rgba(34, 197, 94, 0.7)' }}>DISPATCH    : </span><span style={{ color: orderData.stat.includes('PENDING') ? '#fbbf24' : '#4ade80', fontWeight: 'bold' }}>{orderData.stat}</span></div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div><span style={{ color: 'rgba(34, 197, 94, 0.7)' }}>ORDER AMOUNT: </span><span style={{ color: '#4ade80', fontWeight: 'bold' }}>{orderData.amt}</span></div>
                <div><span style={{ color: 'rgba(34, 197, 94, 0.7)' }}>DISCOUNT    : </span><span style={{ color: '#4ade80' }}>{orderData.discount}</span></div>
                <div><span style={{ color: 'rgba(34, 197, 94, 0.7)' }}>FINAL NET   : </span><span style={{ color: '#86efac', fontWeight: 'bold' }}>{orderData.netAmt}</span></div>
              </div>
            </div>
          </>
        )}
      </div>

      {/* CICS Status Message line */}
      <div style={{
        marginTop: 'auto', borderTop: '1px solid rgba(34, 197, 94, 0.3)',
        paddingTop: 6, fontSize: 11, color: '#86efac', display: 'flex', justifyContent: 'space-between'
      }}>
        <span>MSG: <span style={{ color: '#fbbf24' }}>{statusMsg}</span></span>
        <button
          onClick={handleClear}
          style={{
            padding: '1px 6px', background: 'transparent', border: '1px solid rgba(34,197,94,0.4)',
            color: '#86efac', fontSize: 10, cursor: 'pointer', borderRadius: 2
          }}
        >
          PA1 (Clear)
        </button>
      </div>

      {/* 3270 Function Keys Footer */}
      <div style={{
        marginTop: 6, background: '#021808', border: '1px solid rgba(34, 197, 94, 0.2)',
        padding: '4px 8px', fontSize: 10, color: 'rgba(34, 197, 94, 0.7)',
        display: 'flex', justifyContent: 'space-between', borderRadius: 3
      }}>
        <span>F1=Help</span>
        <span>F3=Exit</span>
        <span>F5=Refresh</span>
        <span>F7=Back</span>
        <span>F8=Forward</span>
        <span>F12=Cancel</span>
        <span style={{ color: '#86efac' }}>ENTER=Send</span>
      </div>

      <style>{`
        @keyframes blinkCursor { 0%,49%{opacity:1} 50%,100%{opacity:0} }
        .blinking-cursor { animation: blinkCursor 1s infinite; }
      `}</style>
    </div>
  )
}

/* ─── Fixed-Block Mainframe Dataset Viewer ──────────────────────────────── */
function DatasetView({ datasetName, rawData }: { datasetName: string; rawData: string }) {
  const [searchTerm, setSearchTerm] = useState('')
  const [viewMode, setViewMode] = useState<'table' | 'text'>('table')
  const [selectedRow, setSelectedRow] = useState<number | null>(null)

  const lines = useMemo(() => {
    if (!rawData || rawData.includes('Could not load') || rawData.includes('404')) return []
    return rawData.trim().split('\n').filter(l => l.trim().length > 0)
  }, [rawData])

  const filteredLines = useMemo(() => {
    if (!searchTerm) return lines
    const term = searchTerm.toLowerCase()
    return lines.filter(l => l.toLowerCase().includes(term))
  }, [lines, searchTerm])

  const isPayroll = datasetName.toUpperCase().includes('PAYROLL')
  const isOrder = datasetName.toUpperCase().includes('ORDER')

  return (
    <div style={{
      height: '100%', display: 'flex', flexDirection: 'column',
      background: '#090c15', color: 'var(--text)', overflow: 'hidden'
    }}>
      {/* Dataset Metadata Ribbon */}
      <div style={{
        padding: '6px 12px', background: '#0d111d', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, fontFamily: 'var(--mono)' }}>
          <span style={{ color: '#67e8f9', fontWeight: 600 }}>DSN: {datasetName}</span>
          <span style={{ color: 'var(--muted)' }}>•</span>
          <span style={{ color: '#34d399' }}>RECFM: FB</span>
          <span style={{ color: 'var(--muted)' }}>•</span>
          <span style={{ color: '#fbbf24' }}>LRECL: 80</span>
          <span style={{ color: 'var(--muted)' }}>•</span>
          <span style={{ color: '#a78bfa' }}>BLKSIZE: 27920</span>
          <span style={{ color: 'var(--muted)' }}>•</span>
          <span style={{ color: 'var(--muted)' }}>{lines.length} records</span>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <div style={{ display: 'flex', background: 'var(--surface2)', borderRadius: 4, padding: 2 }}>
            <button
              onClick={() => setViewMode('table')}
              style={{
                padding: '2px 8px', fontSize: 10, borderRadius: 3, border: 'none', cursor: 'pointer',
                background: viewMode === 'table' ? 'var(--accent)' : 'transparent',
                color: viewMode === 'table' ? '#fff' : 'var(--muted)'
              }}
            >
              📋 Table
            </button>
            <button
              onClick={() => setViewMode('text')}
              style={{
                padding: '2px 8px', fontSize: 10, borderRadius: 3, border: 'none', cursor: 'pointer',
                background: viewMode === 'text' ? 'var(--accent)' : 'transparent',
                color: viewMode === 'text' ? '#fff' : 'var(--muted)'
              }}
            >
              📏 Ruler
            </button>
          </div>
          <button
            onClick={() => {
              navigator.clipboard?.writeText(rawData)
              alert('Dataset copied to clipboard!')
            }}
            style={{
              padding: '2px 8px', fontSize: 10, borderRadius: 4, border: '1px solid var(--border)',
              background: 'transparent', color: 'var(--muted)', cursor: 'pointer'
            }}
          >
            📋 Copy
          </button>
        </div>
      </div>

      {/* Search Bar */}
      <div style={{ padding: '6px 12px', background: '#0a0d18', borderBottom: '1px solid var(--border)', display: 'flex', gap: 8 }}>
        <input
          type="text"
          value={searchTerm}
          onChange={e => setSearchTerm(e.target.value)}
          placeholder="Filter records by keyword..."
          style={{
            flex: 1, padding: '4px 8px', fontSize: 11, background: 'var(--surface2)',
            border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text)', outline: 'none'
          }}
        />
        {searchTerm && (
          <button
            onClick={() => setSearchTerm('')}
            style={{ padding: '2px 8px', fontSize: 10, background: 'transparent', border: '1px solid var(--border)', color: 'var(--muted)', borderRadius: 3, cursor: 'pointer' }}
          >
            Clear
          </button>
        )}
      </div>

      {/* Dataset Content View */}
      <div style={{ flex: 1, overflow: 'auto', padding: '8px 12px' }}>
        {viewMode === 'text' ? (
          <div>
            {/* Column Ruler Header */}
            <div style={{
              fontFamily: 'var(--mono)', fontSize: 11, color: '#fbbf24', background: '#121624',
              padding: '3px 6px', borderRadius: 3, marginBottom: 4, whiteSpace: 'pre', overflowX: 'auto'
            }}>
              {'LINE#  HEX   ----+----10----+----20----+----30----+----40----+----50----+----60----+----70----+----80'}
            </div>
            {filteredLines.map((line, idx) => {
              const hexOffset = (idx * 80).toString(16).padStart(4, '0').toUpperCase()
              return (
                <div
                  key={idx}
                  onClick={() => setSelectedRow(idx)}
                  style={{
                    fontFamily: 'var(--mono)', fontSize: 11, whiteSpace: 'pre',
                    padding: '2px 6px', cursor: 'pointer',
                    background: selectedRow === idx ? 'rgba(79,156,249,0.15)' : 'transparent',
                    borderLeft: selectedRow === idx ? '2px solid var(--accent)' : '2px solid transparent',
                    display: 'flex', gap: 8
                  }}
                >
                  <span style={{ color: 'var(--muted)', minWidth: 44 }}>{String(idx + 1).padStart(5, '0')}</span>
                  <span style={{ color: '#7dd3fc', minWidth: 40 }}>0x{hexOffset}</span>
                  <span style={{ color: '#e2e8f0' }}>{line}</span>
                </div>
              )
            })}
          </div>
        ) : (
          <div style={{ width: '100%', overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: 'var(--mono)' }}>
              <thead>
                <tr style={{ background: '#121624', borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                  <th style={{ padding: '6px 8px', color: 'var(--muted)' }}>#</th>
                  {isPayroll ? (
                    <>
                      <th style={{ padding: '6px 8px', color: '#67e8f9' }}>EMP ID (1-7)</th>
                      <th style={{ padding: '6px 8px', color: '#34d399' }}>NAME (8-24)</th>
                      <th style={{ padding: '6px 8px', color: '#fbbf24' }}>DEPT (25-28)</th>
                      <th style={{ padding: '6px 8px', color: '#a78bfa' }}>SALARY (29-38)</th>
                      <th style={{ padding: '6px 8px', color: '#60a5fa' }}>DATE (39-46)</th>
                    </>
                  ) : isOrder ? (
                    <>
                      <th style={{ padding: '6px 8px', color: '#67e8f9' }}>ORDER ID (1-8)</th>
                      <th style={{ padding: '6px 8px', color: '#34d399' }}>CUST ID (9-18)</th>
                      <th style={{ padding: '6px 8px', color: '#60a5fa' }}>DATE (19-26)</th>
                      <th style={{ padding: '6px 8px', color: '#fbbf24' }}>AMOUNT (27-36)</th>
                      <th style={{ padding: '6px 8px', color: '#a78bfa' }}>STATUS (40-48)</th>
                    </>
                  ) : (
                    <th style={{ padding: '6px 8px', color: '#67e8f9' }}>RECORD DATA</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {filteredLines.map((line, idx) => (
                  <tr
                    key={idx}
                    onClick={() => setSelectedRow(idx)}
                    style={{
                      borderBottom: '1px solid rgba(255,255,255,0.03)',
                      background: selectedRow === idx ? 'rgba(79,156,249,0.12)' : 'transparent',
                      cursor: 'pointer'
                    }}
                  >
                    <td style={{ padding: '4px 8px', color: 'var(--muted)' }}>{idx + 1}</td>
                    {isPayroll ? (
                      <>
                        <td style={{ padding: '4px 8px', color: '#67e8f9', fontWeight: 600 }}>{line.slice(0, 7)}</td>
                        <td style={{ padding: '4px 8px', color: '#e2e8f0' }}>{line.slice(7, 24).trim()}</td>
                        <td style={{ padding: '4px 8px', color: '#fbbf24' }}>{line.slice(24, 28).trim()}</td>
                        <td style={{ padding: '4px 8px', color: '#a78bfa' }}>${(Number(line.slice(28, 38)) / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
                        <td style={{ padding: '4px 8px', color: '#60a5fa' }}>{line.slice(38, 46)}</td>
                      </>
                    ) : isOrder ? (
                      <>
                        <td style={{ padding: '4px 8px', color: '#67e8f9', fontWeight: 600 }}>{line.slice(0, 8)}</td>
                        <td style={{ padding: '4px 8px', color: '#e2e8f0' }}>{line.slice(8, 18).trim()}</td>
                        <td style={{ padding: '4px 8px', color: '#60a5fa' }}>{line.slice(18, 26)}</td>
                        <td style={{ padding: '4px 8px', color: '#fbbf24' }}>${(Number(line.slice(26, 36)) / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
                        <td style={{ padding: '4px 8px', color: line.includes('APPROVED') ? '#34d399' : line.includes('REJECTED') ? '#f87171' : '#fbbf24' }}>
                          {line.slice(39).trim()}
                        </td>
                      </>
                    ) : (
                      <td style={{ padding: '4px 8px', color: '#e2e8f0' }}>{line}</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Selected Record Detail Footer */}
      {selectedRow !== null && filteredLines[selectedRow] && (
        <div style={{
          padding: '8px 12px', background: '#0a0d18', borderTop: '1px solid var(--border)',
          fontSize: 11, display: 'flex', justifyContent: 'space-between', alignItems: 'center'
        }}>
          <div>
            <span style={{ color: 'var(--muted)' }}>Selected Row #{selectedRow + 1}: </span>
            <span style={{ fontFamily: 'var(--mono)', color: '#67e8f9' }}>{filteredLines[selectedRow]}</span>
          </div>
          <button
            onClick={() => setSelectedRow(null)}
            style={{ padding: '1px 6px', fontSize: 10, background: 'transparent', border: '1px solid var(--border)', color: 'var(--muted)', borderRadius: 3, cursor: 'pointer' }}
          >
            ✕ Dismiss
          </button>
        </div>
      )}
    </div>
  )
}

/* ─── BMS Mapset Metadata Inspector ────────────────────────────────────── */
function BmsMetadataTab({ screenName, bmsSource }: { screenName: string; bmsSource: string }) {
  const fields = useMemo(() => {
    const list: { name: string; line: number; col: number; len: number; attr: string; initial: string }[] = []
    const lines = bmsSource.split('\n')
    lines.forEach(l => {
      const match = l.match(/^([A-Z0-9_]+)\s+DFHMDF\s+POS=\((\d+),(\d+)\),ATTRB=\(([^)]+)\),LENGTH=(\d+)(?:,.*INITIAL='([^']*)')?/i)
      if (match) {
        list.push({
          name: match[1],
          line: Number(match[2]),
          col: Number(match[3]),
          attr: match[4],
          len: Number(match[5]),
          initial: match[6] || ''
        })
      }
    })
    return list
  }, [bmsSource])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: 2 }}>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 12, color: '#34d399', fontWeight: 600 }}>
        🖥️ BMS Mapset :: {screenName}
      </div>

      {/* Screen specs grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        <div style={{ background: '#0d0f1a', borderRadius: 6, padding: '8px 10px', border: '1px solid #1e2235' }}>
          <div style={{ fontSize: 10, color: 'var(--muted)' }}>Terminal Type</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#67e8f9' }}>IBM 3270 Model 2</div>
          <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 2 }}>24 rows × 80 cols</div>
        </div>
        <div style={{ background: '#0d0f1a', borderRadius: 6, padding: '8px 10px', border: '1px solid #1e2235' }}>
          <div style={{ fontSize: 10, color: 'var(--muted)' }}>Defined Fields</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#34d399' }}>{fields.length} DFHMDF</div>
          <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 2 }}>CICS Map Definition</div>
        </div>
      </div>

      {/* Modernization Target */}
      <div style={{ background: '#0d0f1a', borderRadius: 6, padding: '8px 10px', border: '1px solid #1e2235', fontSize: 11 }}>
        <div style={{ fontWeight: 600, color: 'var(--accent2)', marginBottom: 4 }}>🚀 Modernization Target:</div>
        <div style={{ color: 'var(--muted)', lineHeight: 1.5 }}>
          Transforms CICS 3270 screen buffer into a reactive Spring Boot REST Controller & React Tailwind form.
        </div>
        <div style={{ marginTop: 6, background: '#080a12', padding: 6, borderRadius: 4, fontFamily: 'var(--mono)', fontSize: 10, color: '#60a5fa' }}>
          GET /api/{screenName.toLowerCase().replace('inq', '')}/query?id={'{id}'}
        </div>
      </div>

      {/* Fields List */}
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', marginTop: 4 }}>Field Catalog:</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 180, overflowY: 'auto' }}>
        {fields.map((f, i) => (
          <div key={i} style={{ background: '#0d0f1a', borderRadius: 4, padding: '4px 8px', fontSize: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontFamily: 'var(--mono)', color: '#fbbf24', fontWeight: 600 }}>{f.name}</span>
              <span style={{ color: 'var(--muted)', marginLeft: 6 }}>POS=({f.line},{f.col})</span>
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ color: 'var(--muted)' }}>len:{f.len}</span>
              <span style={{
                padding: '1px 4px', borderRadius: 3, fontSize: 9,
                background: f.attr.includes('UNPROT') ? 'rgba(52,211,153,0.15)' : 'rgba(255,255,255,0.05)',
                color: f.attr.includes('UNPROT') ? '#34d399' : 'var(--muted)'
              }}>
                {f.attr.includes('UNPROT') ? 'INPUT' : 'DISPLAY'}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ─── Dataset Metadata Inspector ───────────────────────────────────────── */
function DatasetMetadataTab({ datasetName, rawData }: { datasetName: string; rawData: string }) {
  const lineCount = rawData ? rawData.trim().split('\n').filter(Boolean).length : 0
  const isPayroll = datasetName.toUpperCase().includes('PAYROLL')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: 2 }}>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 12, color: '#fbbf24', fontWeight: 600 }}>
        🗄️ Dataset Catalog :: {datasetName}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        <div style={{ background: '#0d0f1a', borderRadius: 6, padding: '8px 10px', border: '1px solid #1e2235' }}>
          <div style={{ fontSize: 10, color: 'var(--muted)' }}>DSORG</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#67e8f9' }}>PS (Sequential)</div>
          <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 2 }}>Fixed Block</div>
        </div>
        <div style={{ background: '#0d0f1a', borderRadius: 6, padding: '8px 10px', border: '1px solid #1e2235' }}>
          <div style={{ fontSize: 10, color: 'var(--muted)' }}>Record Count</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#34d399' }}>{lineCount} rows</div>
          <div style={{ fontSize: 9, color: 'var(--muted)', marginTop: 2 }}>LRECL=80, BLK=27920</div>
        </div>
      </div>

      {/* Target Cloud Storage & Spring Batch */}
      <div style={{ background: '#0d0f1a', borderRadius: 6, padding: '8px 10px', border: '1px solid #1e2235', fontSize: 11 }}>
        <div style={{ fontWeight: 600, color: '#34d399', marginBottom: 4 }}>☁️ Cloud Target (Spring Batch):</div>
        <div style={{ color: 'var(--muted)', lineHeight: 1.5 }}>
          Maps sequential fixed-block records into Spring Batch <code>FlatFileItemReader</code> with <code>FixedLengthTokenizer</code>.
        </div>
        <div style={{ marginTop: 6, background: '#080a12', padding: 6, borderRadius: 4, fontFamily: 'var(--mono)', fontSize: 10, color: '#a78bfa' }}>
          s3://migration-bucket/datasets/{datasetName.toLowerCase().replace(/\./g, '/')}.dat
        </div>
      </div>

      {/* Associated JCL DD */}
      <div style={{ background: '#0d0f1a', borderRadius: 6, padding: '8px 10px', border: '1px solid #1e2235', fontSize: 11 }}>
        <div style={{ fontWeight: 600, color: '#60a5fa', marginBottom: 4 }}>⚙️ JCL Usage:</div>
        <div style={{ color: 'var(--text)', fontFamily: 'var(--mono)', fontSize: 10 }}>
          {isPayroll ? '//PAYIN  DD DSN=HLQ.PAYROLL.INPUT,DISP=SHR' : '//ORDIN  DD DSN=HLQ.ORDER.INPUT,DISP=SHR'}
        </div>
      </div>
    </div>
  )
}
