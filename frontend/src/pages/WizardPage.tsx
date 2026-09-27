import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { migrate, migrateAll } from '../api/client'
import type { AppState } from '../App'

interface Props { state: AppState; update: (p: Partial<AppState>) => void }

// ── Model catalogue per backend ──────────────────────────────────────────

const MODEL_CATALOGUE: Record<string, { id: string; label: string; note: string }[]> = {
  mock: [
    { id: 'mock',   label: '⚡ Local Deterministic AST Engine', note: 'No API call — sub-second, offline' },
  ],
  granite: [
    { id: 'ibm/granite-3-8b-instruct',         label: 'Granite 3.0 8B Instruct',          note: '8B · 128k ctx · Recommended default' },
    { id: 'ibm/granite-3-2b-instruct',         label: 'Granite 3.0 2B Instruct',          note: '2B · 128k ctx · Fastest inference' },
    { id: 'ibm/granite-34b-code-instruct',     label: 'Granite 34B Code Instruct',        note: '34B · 64k ctx · COBOL/JCL specialist' },
    { id: 'ibm/granite-20b-code-instruct',     label: 'Granite 20B Code Instruct',        note: '20B · 32k ctx · Batch throughput' },
    { id: 'ibm/granite-3.1-8b-instruct',       label: 'Granite 3.1 8B Instruct',          note: '8B · 128k ctx · Latest generation' },
    { id: 'ibm/granite-guardian-3.0-8b',       label: 'Granite Guardian 3.0 8B',          note: '8B · Safety & OWASP critic' },
  ],
  anthropic: [
    { id: 'claude-3-5-sonnet-20241022',  label: 'Claude 3.5 Sonnet (Oct 2024)',   note: 'Fastest, best for code (recommended)' },
    { id: 'claude-3-5-haiku-20241022',   label: 'Claude 3.5 Haiku (Oct 2024)',    note: 'Ultra-fast, cost-efficient' },
    { id: 'claude-3-opus-20240229',      label: 'Claude 3 Opus',                  note: 'Most capable, slower' },
    { id: 'claude-3-sonnet-20240229',    label: 'Claude 3 Sonnet',                note: 'Balanced performance' },
    { id: 'claude-3-haiku-20240307',     label: 'Claude 3 Haiku',                 note: 'Fastest 3.x model' },
  ],
  openai: [
    { id: 'gpt-4o',           label: 'GPT-4o',                   note: 'Latest flagship multimodal model' },
    { id: 'gpt-4o-mini',      label: 'GPT-4o Mini',              note: 'Fast, cost-efficient' },
    { id: 'gpt-4-turbo',      label: 'GPT-4 Turbo',              note: '128k context window' },
    { id: 'gpt-4',            label: 'GPT-4',                    note: 'Classic GPT-4' },
    { id: 'gpt-3.5-turbo',    label: 'GPT-3.5 Turbo',           note: 'Economy tier' },
    { id: 'o1-preview',       label: 'o1 Preview',               note: 'Extended thinking model' },
    { id: 'o1-mini',          label: 'o1 Mini',                  note: 'Fast reasoning model' },
  ],
  groq: [
    { id: 'llama-3.3-70b-versatile',                       label: 'Llama 3.3 70B Versatile',          note: '70B · 128k ctx · Recommended' },
    { id: 'llama-3.1-70b-versatile',                       label: 'Llama 3.1 70B Versatile',          note: '70B · 128k ctx' },
    { id: 'llama-3.1-8b-instant',                          label: 'Llama 3.1 8B Instant',             note: '8B · 128k ctx · Ultra-fast' },
    { id: 'llama3-70b-8192',                               label: 'Llama 3 70B',                      note: '70B · 8k ctx' },
    { id: 'llama3-8b-8192',                                label: 'Llama 3 8B',                       note: '8B · 8k ctx' },
    { id: 'mixtral-8x7b-32768',                            label: 'Mixtral 8x7B MoE',                 note: '8x7B · 32k ctx' },
    { id: 'openai/gpt-oss-120b',                           label: 'OpenAI GPT-OSS 120B',              note: 'Reasoning model · 128k ctx' },
    { id: 'openai/gpt-oss-20b',                            label: 'OpenAI GPT-OSS 20B',               note: 'Reasoning model · 128k ctx' },
    { id: 'llama3-groq-70b-8192-tool-use-preview',         label: 'Llama 3 70B Tool Use',             note: 'Function calling optimized' },
  ],
  gemini: [
    { id: 'gemini-3.8-flash',          label: 'Gemini 3.8 Flash',             note: 'Fastest multimodal · Recommended' },
    { id: 'gemini-3.1-pro-preview',    label: 'Gemini 3.1 Pro (Preview)',     note: 'High-end reasoning · Preview' },
    { id: 'gemini-3.7-flash',          label: 'Gemini 3.7 Flash',             note: 'Balanced speed and quality' },
    { id: 'gemini-3.6-flash',          label: 'Gemini 3.6 Flash',             note: 'High-throughput generation' },
    { id: 'gemini-3.5-flash',          label: 'Gemini 3.5 Flash',             note: 'Efficient general-purpose model' },
    { id: 'gemini-3.5-flash-lite',    label: 'Gemini 3.5 Flash-Lite',        note: 'Low-cost, lightweight' },
  ],
  grok: [
    { id: 'grok-2-1212',        label: 'Grok 2 (Dec 2024)',         note: 'Latest flagship, strong reasoning' },
    { id: 'grok-beta',          label: 'Grok Beta',                  note: 'General purpose' },
    { id: 'grok-2-vision-1212', label: 'Grok 2 Vision (Dec 2024)',  note: 'Multimodal with vision' },
    { id: 'grok-vision-beta',   label: 'Grok Vision Beta',          note: 'Vision capabilities' },
  ],
  ollama: [
    { id: 'granite3.1-dense:8b',    label: 'Granite 3.1 Dense 8B (local)',  note: 'IBM Granite local via Ollama' },
    { id: 'granite3.1-dense:2b',    label: 'Granite 3.1 Dense 2B (local)',  note: 'Compact IBM Granite local' },
    { id: 'granite-code:34b',       label: 'Granite Code 34B (local)',      note: 'Large code model local' },
    { id: 'llama3.1:70b',           label: 'Llama 3.1 70B (local)',         note: 'Meta Llama 3.1 local' },
    { id: 'llama3.1:8b',            label: 'Llama 3.1 8B (local)',          note: 'Fast Llama 3.1 local' },
    { id: 'codellama:34b',          label: 'Code Llama 34B (local)',        note: 'Code specialist local' },
    { id: 'mistral:7b',             label: 'Mistral 7B (local)',            note: 'Efficient 7B local' },
    { id: 'gemma2:9b',              label: 'Gemma 2 9B (local)',            note: 'Google Gemma 2 local' },
  ],
}

const BACKEND_META: Record<string, { icon: string; label: string; color: string; desc: string; keyLabel: string; keyPlaceholder: string; keyNote: string }> = {
  mock:      { icon: '⚡', label: 'Local (Mock)',       color: '#f1c21b', desc: 'Zero-latency deterministic engine — no API needed', keyLabel: '', keyPlaceholder: '', keyNote: '' },
  granite:   { icon: '🔷', label: 'IBM Granite',        color: '#0f62fe', desc: 'IBM Granite 3.x models via watsonx.ai enterprise platform', keyLabel: 'IBM Cloud API Key', keyPlaceholder: 'IBM Cloud IAM API key', keyNote: 'Requires watsonx.ai project ID' },
  anthropic: { icon: '🤖', label: 'Anthropic Claude',   color: '#c084fc', desc: 'Claude 3.5 Sonnet and family — advanced reasoning', keyLabel: 'Anthropic API Key', keyPlaceholder: 'sk-ant-...', keyNote: 'Get at console.anthropic.com' },
  openai:    { icon: '✨', label: 'OpenAI GPT',         color: '#34d399', desc: 'GPT-4o and family — multimodal code synthesis', keyLabel: 'OpenAI API Key', keyPlaceholder: 'sk-...', keyNote: 'Get at platform.openai.com' },
  groq:      { icon: '⚡', label: 'Groq Cloud',         color: '#f87171', desc: 'Ultra-fast inference for Llama 3, Mixtral, Gemma2', keyLabel: 'Groq API Key', keyPlaceholder: 'gsk_...', keyNote: 'Get at console.groq.com' },
  gemini:    { icon: '💎', label: 'Google Gemini',      color: '#60a5fa', desc: 'Gemini 3.x generation — Flash, Flash-Lite, and Pro preview models', keyLabel: 'Google AI Key', keyPlaceholder: 'AIza...', keyNote: 'Get at aistudio.google.com' },
  grok:      { icon: '𝕏',  label: 'xAI Grok',           color: '#e5e7eb', desc: 'xAI Grok 2 — strong reasoning & coding capabilities', keyLabel: 'xAI API Key', keyPlaceholder: 'xai-...', keyNote: 'Get at console.x.ai' },
  ollama:    { icon: '🦙', label: 'Ollama (Local)',     color: '#fb923c', desc: 'Local Ollama server — Granite, Llama, Mistral, Gemma2', keyLabel: 'Ollama URL', keyPlaceholder: 'http://localhost:11434', keyNote: 'Run: ollama pull granite3.1-dense:8b' },
}

const DEFAULT_MODEL: Record<string, string> = {
  mock: 'mock',
  granite: 'ibm/granite-3-8b-instruct',
  anthropic: 'claude-3-5-sonnet-20241022',
  openai: 'gpt-4o',
  groq: 'openai/gpt-oss-20b',
  gemini: 'gemini-3.8-flash',
  grok: 'grok-2-1212',
  ollama: 'granite3.1-dense:8b',
}

export default function WizardPage({ state, update }: Props) {
  const nav = useNavigate()
  const [loading, setLoading] = useState(false)
  const [errorModal, setErrorModal] = useState<{ title: string; message: string } | null>(null)
  const [batchResults, setBatchResults] = useState<Array<{ program: string; ok: boolean; status?: string; files?: string[]; error?: string }>>([])

  const targetLang = state.targetLang
  const llmBackend = state.llmBackend
  const llmModel = state.llmModel
  const llmApiKey = state.llmApiKey
  const watsonxProjectId = state.watsonxProjectId
  const watsonxRegion = state.watsonxRegion
  const executionMode = state.executionMode
  const ollamaUrl = state.ollamaUrl
  const selectedProgram = state.selectedProgram
  const COBOL_PROGRAMS = ['PAYROLL', 'ORDPRCS', 'INVNTRY']
  const COBOL_SELECTED = state.selectedAssets.filter(a => COBOL_PROGRAMS.includes(a))

  const setTargetLang = (v: string) => update({ targetLang: v })
  const setLlmBackend = (v: string) => update({ llmBackend: v, llmModel: DEFAULT_MODEL[v] || '' })
  const setLlmModel = (v: string) => update({ llmModel: v })
  const setLlmApiKey = (v: string) => update({ llmApiKey: v })
  const setWatsonxProjectId = (v: string) => update({ watsonxProjectId: v })
  const setWatsonxRegion = (v: string) => update({ watsonxRegion: v })
  const setExecutionMode = (v: 'accelerated' | 'live') => update({ executionMode: v })
  const setOllamaUrl = (v: string) => update({ ollamaUrl: v })
  const setSelectedProgram = (v: string) => update({ selectedProgram: v })

  const handleBackendChange = (b: string) => {
    update({
      llmBackend: b,
      llmModel: DEFAULT_MODEL[b] || '',
      ...(b === 'granite' ? { executionMode: 'live' } : {}),
    })
  }

  const [showKey, setShowKey] = useState(false)

  const validateMigrationConfig = () => {
    if (llmBackend === 'mock') {
      return {
        title: 'Mock engine selected',
        message: 'The Local Mock backend is deterministic and does not call an AI model. Choose Gemini, OpenAI, Anthropic, Groq, Grok, Ollama, or Granite Live for AI-generated output.'
      }
    }

    if (llmBackend === 'granite' && executionMode === 'accelerated') {
      return {
        title: 'AI mode not enabled',
        message: 'Granite Accelerated uses the local deterministic AST engine, so the result is not AI-generated. Switch Granite to watsonx.ai Live to use a real AI model.'
      }
    }

    if (llmBackend === 'granite' && executionMode === 'live') {
      if (!llmApiKey.trim()) {
        return { title: 'Missing IBM Cloud API key', message: 'Enter your IBM Cloud API key to run Granite with watsonx.ai Live.' }
      }
      if (!watsonxProjectId.trim()) {
        return { title: 'Missing watsonx project ID', message: 'Enter your watsonx.ai project ID so Granite Live can send the migration IR to IBM watsonx.ai.' }
      }
    }

    if (llmBackend === 'ollama') {
      if (!ollamaUrl.trim()) {
        return { title: 'Missing Ollama URL', message: 'Enter the Ollama server URL before starting an AI-backed migration.' }
      }
    } else if (!llmApiKey.trim()) {
      return {
        title: 'Missing API key',
        message: `Enter the ${meta.label} API key before starting an AI-generated migration.`
      }
    }

    return null
  }

  const buildMigrationOptions = () => {
    const extras: Record<string, string> = {}
    if (llmBackend === 'granite' && executionMode === 'live') {
      extras.watsonx_project_id = watsonxProjectId
      extras.watsonx_url = `https://${watsonxRegion}.ml.cloud.ibm.com`
    }
    if (llmBackend === 'ollama') {
      extras.ollama_url = ollamaUrl
    }
    return {
      llm_backend: llmBackend,
      llm_model: llmModel,
      llm_api_key: llmBackend === 'ollama' ? undefined : (llmApiKey || undefined),
      llm_extra: Object.keys(extras).length ? extras : undefined,
    }
  }

  const runBatchMigration = async () => {
    const selected = state.selectedAssets.filter(a => COBOL_PROGRAMS.includes(a))
    if (selected.length === 0) {
      setErrorModal({ title: 'No programs selected', message: 'Select at least one COBOL program to migrate.' })
      return
    }

    const configError = validateMigrationConfig()
    if (configError) {
      setErrorModal(configError)
      return
    }

    setLoading(true)
    setBatchResults([])
    try {
      const res = await migrateAll({ program_names: selected, target_lang: targetLang, ...buildMigrationOptions() })
      setBatchResults(res.results || [])

      if (res.succeeded > 0) {
        update({
          migrateResult: {
            ok: true,
            status: 'done',
            program: selected[0],
            target_lang: targetLang,
            files: Object.fromEntries((res.results || []).filter(r => r.ok && r.files).map(r => [r.program, r.files?.[0] || ''])),
            agent_rounds: 1,
            explanations: Object.fromEntries((res.results || []).filter(r => r.ok).map(r => [r.program, `Batch migration completed for ${r.program}`])),
            file_contents: {},
            events: [],
            metrics: { total_programs: res.total, succeeded: res.succeeded, failed: res.failed }
          },
          selectedAssets: selected,
        })
        nav('/live')
      } else {
        setErrorModal({ title: 'Batch migration failed', message: 'None of the selected programs completed successfully. Please review the logs and try again.' })
      }
    } catch (e: unknown) {
      setErrorModal(friendlyError(e))
    } finally {
      setLoading(false)
    }
  }

  const startMigration = async (progName: string) => {
    const configError = validateMigrationConfig()
    if (configError) {
      setErrorModal(configError)
      return
    }

    setLoading(true)
    try {
      const result = await migrate({
        program_name: progName,
        target_lang: targetLang,
        run_id: progName,
        ...buildMigrationOptions(),
      })
      update({ migrateResult: result, selectedAssets: [progName] })
      nav('/result')
    } catch (e: unknown) {
      setErrorModal(friendlyError(e))
    } finally {
      setLoading(false)
    }
  }

  const models = MODEL_CATALOGUE[llmBackend] || []
  const meta = BACKEND_META[llmBackend] || BACKEND_META['mock']
  const needsKey = llmBackend !== 'mock' && llmBackend !== 'ollama' && !(llmBackend === 'granite' && executionMode === 'accelerated')

  return (
    <div className="page" style={{ maxWidth: 980, margin: '0 auto' }}>
      {errorModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(2, 6, 23, 0.7)', display: 'flex',
          alignItems: 'center', justifyContent: 'center', zIndex: 2000, padding: 20
        }} onClick={() => setErrorModal(null)}>
          <div
            onClick={e => e.stopPropagation()}
            style={{
              width: '100%', maxWidth: 440, background: 'rgba(15, 23, 42, 0.96)',
              border: '1px solid rgba(148, 163, 184, 0.25)', borderRadius: 16,
              boxShadow: '0 24px 60px rgba(2, 6, 23, 0.7)', overflow: 'hidden'
            }}
          >
            <div style={{ padding: '18px 20px 8px', borderBottom: '1px solid rgba(148, 163, 184, 0.12)' }}>
              <div style={{ fontSize: 12, color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>
                Migration status
              </div>
              <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)' }}>{errorModal.title}</div>
            </div>
            <div style={{ padding: '16px 20px 20px', color: 'var(--text-secondary)', fontSize: 14, lineHeight: 1.6 }}>
              {errorModal.message}
            </div>
            <div style={{ padding: '0 20px 20px', display: 'flex', justifyContent: 'flex-end' }}>
              <button
                className="btn btn-primary"
                onClick={() => setErrorModal(null)}
                style={{ minWidth: 100, fontSize: 13 }}
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
          <span style={{
            fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 999,
            background: 'rgba(99,102,241,0.12)', color: 'var(--accent)', border: '1px solid rgba(99,102,241,0.25)',
            textTransform: 'uppercase', letterSpacing: '0.06em',
          }}>Step 3 of 4</span>
          <span style={{ fontSize: 13, color: 'var(--muted)' }}>Configuration & Execution</span>
        </div>
        <h1 className="page-title">Migration Wizard</h1>
        <p className="page-subtitle">Configure target language, LLM backend and model, then launch the multi-agent pipeline.</p>
      </div>

      {/* Selected Programs */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16 }}>📦</span>
            <div className="card-title" style={{ margin: 0 }}>Selected Mainframe Modules</div>
          </div>
          <button className="btn btn-ghost" style={{ padding: '4px 10px', fontSize: 12 }} onClick={() => nav('/assets')}>Change Selection</button>
        </div>
        {state.selectedAssets.length === 0 ? (
          <div style={{ padding: '24px 16px', textAlign: 'center', background: 'var(--surface2)', borderRadius: 'var(--radius)', border: '1px dashed var(--border)' }}>
            <p style={{ color: 'var(--muted)', fontSize: 13, margin: '0 0 12px 0' }}>No assets selected.</p>
            <button className="btn btn-primary" onClick={() => nav('/assets')}>Browse & Select Assets</button>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {state.selectedAssets.map(a => (
              <span key={a} className="badge badge-blue" style={{ fontSize: 12, padding: '6px 12px', display: 'flex', alignItems: 'center', gap: 6 }}>
                <span>{a.toLowerCase().endsWith('.jcl') ? '⚙️' : '📄'}</span>
                <span>{a}</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Target Language */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
          <span style={{ fontSize: 16 }}>🎯</span>
          <div className="card-title" style={{ margin: 0 }}>Target Language</div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14 }}>
          {[
            { id: 'java',   icon: '☕', title: 'Java 17 / 21',         sub: 'Spring Boot 3 · Jakarta EE · BigDecimal', tag: 'Recommended' },
            { id: 'python', icon: '🐍', title: 'Python 3.11+',          sub: 'FastAPI · Pydantic V2 · Decimal',          tag: 'ETL & Data' },
          ].map(opt => {
            const sel = targetLang === opt.id
            return (
              <div key={opt.id} onClick={() => setTargetLang(opt.id)} style={{
                padding: '18px 20px', borderRadius: 'var(--radius-lg)', cursor: 'pointer',
                border: sel ? '2px solid var(--accent)' : '1px solid var(--border)',
                background: sel ? 'rgba(99,102,241,0.08)' : 'var(--surface2)',
                position: 'relative', transition: 'all var(--transition-normal)',
              }}>
                {sel && <div style={{ position: 'absolute', top: 12, right: 12, background: 'var(--accent)', color: '#fff', borderRadius: '50%', width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11 }}>✓</div>}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                  <span style={{ fontSize: 28 }}>{opt.icon}</span>
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 700, color: sel ? 'var(--accent)' : 'var(--muted)', textTransform: 'uppercase', marginBottom: 3 }}>{opt.tag}</div>
                    <div style={{ fontWeight: 600, fontSize: 15 }}>{opt.title}</div>
                  </div>
                </div>
                <div style={{ fontSize: 12, color: 'var(--muted)' }}>{opt.sub}</div>
              </div>
            )
          })}
        </div>
      </div>

      {/* LLM Backend Selection */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16 }}>🧠</span>
            <div className="card-title" style={{ margin: 0 }}>Agent Intelligence Backend</div>
          </div>
          <span style={{ fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 999, background: 'rgba(15,98,254,0.15)', color: '#4589ff', border: '1px solid rgba(15,98,254,0.3)' }}>
            🏆 IBM BOB 2.0
          </span>
        </div>

        {/* Backend tiles — 4 per row on desktop */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10, marginBottom: 20 }}>
          {Object.entries(BACKEND_META).map(([id, m]) => {
            const active = llmBackend === id
            return (
              <div key={id} onClick={() => handleBackendChange(id)} style={{
                padding: '12px 14px', borderRadius: 'var(--radius)', cursor: 'pointer',
                border: active ? `2px solid ${m.color}` : '1px solid var(--border)',
                background: active ? `${m.color}18` : 'var(--surface2)',
                boxShadow: active ? `0 0 16px ${m.color}28` : 'none',
                transition: 'all 0.18s ease',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 5 }}>
                  <span style={{ fontSize: 18 }}>{m.icon}</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: active ? '#fff' : 'var(--text)' }}>{m.label}</span>
                  {active && <span style={{ marginLeft: 'auto', color: m.color, fontSize: 13 }}>✓</span>}
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.4 }}>{m.desc}</div>
              </div>
            )
          })}
        </div>

        {/* ── IBM Granite extra controls ─────────────────────────── */}
        {llmBackend === 'granite' && (
          <div style={{ background: 'rgba(15,98,254,0.05)', border: '1px solid rgba(15,98,254,0.2)', borderRadius: 'var(--radius)', padding: '16px 18px', marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: '#4589ff', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Execution Mode
              </span>
              <div style={{ display: 'flex', background: 'var(--surface2)', borderRadius: 4, padding: 2, border: '1px solid var(--border)', gap: 2 }}>
                {(['accelerated', 'live'] as const).map(mode => (
                  <button key={mode} type="button" onClick={() => setExecutionMode(mode)} style={{
                    padding: '3px 10px', fontSize: 10, borderRadius: 3, border: 'none', cursor: 'pointer', fontWeight: 600,
                    background: executionMode === mode ? 'var(--accent)' : 'transparent',
                    color: executionMode === mode ? '#fff' : 'var(--muted)',
                  }}>
                    {mode === 'accelerated' ? '⚡ Local AST' : '☁️ watsonx.ai Live'}
                  </button>
                ))}
              </div>
            </div>
            {executionMode === 'live' ? (
              <div className="form-grid">
                <div className="form-field">
                  <label>watsonx.ai Region</label>
                  <select value={watsonxRegion} onChange={e => setWatsonxRegion(e.target.value)}>
                    {[['us-south','US South (Dallas)'],['eu-de','EU Germany (Frankfurt)'],['eu-gb','EU UK (London)'],['jp-tok','Japan (Tokyo)'],['au-syd','Australia (Sydney)']].map(([v,l]) => (
                      <option key={v} value={v}>{l}</option>
                    ))}
                  </select>
                </div>
                <div className="form-field">
                  <label>watsonx Project ID</label>
                  <input value={watsonxProjectId} onChange={e => setWatsonxProjectId(e.target.value)} placeholder="e.g. 7a82b9c1-4321-..." />
                </div>
                <div className="form-field" style={{ gridColumn: '1/-1' }}>
                  <label>IBM Cloud API Key</label>
                  <ApiKeyInput value={llmApiKey} onChange={setLlmApiKey} show={showKey} onToggle={() => setShowKey(v => !v)} placeholder="IBM Cloud IAM API key" />
                </div>
              </div>
            ) : (
              <div style={{ fontSize: 11, color: '#4589ff', display: 'flex', alignItems: 'center', gap: 8, background: 'rgba(15,98,254,0.08)', padding: '8px 12px', borderRadius: 6 }}>
                <span>💡</span>
                <span><strong>Hackathon Demo:</strong> Accelerated AST transforms COBOL to Java in sub-seconds — no cloud credits needed.</span>
              </div>
            )}
          </div>
        )}

        {/* ── Ollama URL input ───────────────────────────────────── */}
        {llmBackend === 'ollama' && (
          <div style={{ marginBottom: 16 }}>
            <div className="form-field">
              <label>Ollama Server URL</label>
              <input value={ollamaUrl} onChange={e => setOllamaUrl(e.target.value)} placeholder="http://localhost:11434" style={{ fontFamily: 'var(--mono)' }} />
            </div>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6, padding: '8px 10px', background: 'var(--surface2)', borderRadius: 6 }}>
              💡 Pull a model first: <code style={{ color: 'var(--accent)' }}>ollama pull granite3.1-dense:8b</code>
            </div>
          </div>
        )}

        {/* ── API key for non-mock non-ollama (unless granite in accelerated) ─── */}
        {needsKey && (
          <div className="form-field" style={{ marginBottom: 16 }}>
            <label>{meta.keyLabel || 'API Key'}</label>
            <ApiKeyInput value={llmApiKey} onChange={setLlmApiKey} show={showKey} onToggle={() => setShowKey(v => !v)} placeholder={meta.keyPlaceholder} note={meta.keyNote} />
          </div>
        )}

        {/* ── Model dropdown ────────────────────────────────────── */}
        {llmBackend !== 'mock' && (
          <div className="form-field">
            <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>Model Identifier</span>
              <span style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 400 }}>— select from dropdown or type a custom ID</span>
            </label>
            <div style={{ display: 'flex', gap: 8 }}>
              <select
                value={llmModel}
                onChange={e => setLlmModel(e.target.value)}
                style={{
                  flex: 1, padding: '8px 12px', borderRadius: 'var(--radius)',
                  background: 'var(--surface2)', border: '1px solid var(--border)',
                  color: 'var(--text)', fontSize: 13, fontFamily: 'var(--mono)',
                }}
              >
                {models.map(m => (
                  <option key={m.id} value={m.id}>{m.label} — {m.note}</option>
                ))}
                <option value="__custom__">── Custom model ID ──</option>
              </select>
            </div>
            {/* Custom model input */}
            {llmModel === '__custom__' && (
              <input
                autoFocus
                placeholder="Enter exact model ID..."
                style={{ marginTop: 8, fontFamily: 'var(--mono)', fontSize: 12 }}
                onChange={e => setLlmModel(e.target.value)}
              />
            )}
            {/* Model details strip */}
            {llmModel && llmModel !== '__custom__' && (() => {
              const found = models.find(m => m.id === llmModel)
              return found ? (
                <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--muted)', padding: '6px 10px', background: 'var(--surface2)', borderRadius: 6 }}>
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: meta.color, flexShrink: 0 }} />
                  <code style={{ color: meta.color, fontSize: 11 }}>{found.id}</code>
                  <span>·</span>
                  <span>{found.note}</span>
                </div>
              ) : null
            })()}
          </div>
        )}

        {/* Mock note */}
        {llmBackend === 'mock' && (
          <div style={{ padding: '12px 16px', background: 'rgba(241,194,27,0.08)', border: '1px solid rgba(241,194,27,0.2)', borderRadius: 'var(--radius)', fontSize: 12, color: 'var(--yellow)', display: 'flex', gap: 10 }}>
            <span style={{ fontSize: 18 }}>💡</span>
            <span><strong>Zero-Latency Offline Mode:</strong> Uses deterministic IR lowering with AST pattern analysis — no API key, no internet, production-ready Java in sub-seconds.</span>
          </div>
        )}

        {llmBackend === 'granite' && executionMode === 'accelerated' && (
          <div style={{ marginTop: 12, padding: '12px 16px', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.22)', borderRadius: 'var(--radius)', fontSize: 12, color: 'var(--yellow)', display: 'flex', gap: 10 }}>
            <span style={{ fontSize: 18 }}>⚠️</span>
            <span><strong>Deterministic mode:</strong> Granite Accelerated is a local scaffold engine for demo speed. It will not send your migration IR to a live AI model.</span>
          </div>
        )}
      </div>

      {/* Pipeline Stages */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
          <span style={{ fontSize: 16 }}>🔄</span>
          <div className="card-title" style={{ margin: 0 }}>Automated 4-Stage Agent Loop</div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }}>
          {[
            { step: '01', name: 'Planner Agent',   desc: 'Analyses IR dependencies & produces risk-aware migration plan.', color: '#38bdf8' },
            { step: '02', name: 'Executor Agent',  desc: 'Translates each function with verified type-safe mappings.', color: '#818cf8' },
            { step: '03', name: 'Critic Agent',    desc: 'Verifies 100% IR op coverage and requests refinements.', color: '#c084fc' },
            { step: '04', name: 'Synthesizer',     desc: 'Emits structured source with records, annotations & docs.', color: '#34d399' },
          ].map((s, i) => (
            <div key={i} style={{ padding: 14, borderRadius: 'var(--radius)', background: 'var(--surface2)', border: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                <span style={{ fontSize: 10, fontWeight: 700, color: s.color, fontFamily: 'var(--mono)' }}>STAGE {s.step}</span>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: s.color }} />
              </div>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{s.name}</div>
              <div style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.4 }}>{s.desc}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Action Footer */}
      <div style={{ display: 'flex', gap: 12, justifyContent: 'space-between', alignItems: 'center', padding: '16px 20px', background: 'var(--surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border)' }}>
        <button className="btn btn-ghost" onClick={() => nav('/assets')}>← Back to Assets</button>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {COBOL_SELECTED.length === 0 ? (
            <button className="btn btn-primary" disabled style={{ opacity: 0.5 }}>Select COBOL Programs First</button>
          ) : (
            <>
              {COBOL_SELECTED.length > 1 && (
                <select
                  value={selectedProgram}
                  onChange={e => setSelectedProgram(e.target.value)}
                  style={{ padding: '8px 12px', borderRadius: 'var(--radius)', background: 'var(--surface2)', border: '1px solid var(--border)', color: 'var(--text)', fontSize: 13, fontFamily: 'var(--mono)', minWidth: 160 }}
                >
                  {COBOL_SELECTED.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              )}
              {/* Backend summary pill */}
              <div style={{ fontSize: 11, color: meta.color, display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: `${meta.color}12`, borderRadius: 999, border: `1px solid ${meta.color}30` }}>
                <span>{meta.icon}</span>
                <span>{meta.label}</span>
                {llmModel && llmModel !== 'mock' && <span style={{ color: 'var(--muted)' }}>·</span>}
                {llmModel && llmModel !== 'mock' && <span style={{ fontFamily: 'var(--mono)', fontSize: 10 }}>{llmModel.split('/').pop()}</span>}
              </div>
              <button
                className="btn btn-primary"
                disabled={loading || !( selectedProgram || COBOL_SELECTED[0])}
                onClick={() => startMigration(selectedProgram || COBOL_SELECTED[0])}
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 24px', fontSize: 14 }}
              >
                {loading ? <><span className="spinner" /><span>Migrating...</span></> : <span>Launch Migration →</span>}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Batch Migration Controls */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 16 }}>
        <button
          className="btn btn-primary"
          disabled={loading || state.selectedAssets.length === 0}
          onClick={() => runBatchMigration()}
          style={{ minWidth: 220 }}
        >
          {loading ? 'Running Batch Migration...' : 'Run One Migration Job for Selected Programs'}
        </button>
        <button
          className="btn btn-ghost"
          disabled={loading || !state.selectedAssets.length}
          onClick={() => {
            const selected = state.selectedAssets.filter(a => COBOL_PROGRAMS.includes(a))
            if (selected.length) startMigration(selected[0])
          }}
        >
          Run Single Program
        </button>
      </div>

      {/* Batch Migration Results */}
      {batchResults.length > 0 && (
        <div className="card" style={{ marginTop: 20, padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <strong style={{ fontSize: 14 }}>Batch Validation Summary</strong>
            <span className="badge badge-green">{batchResults.filter(r => r.ok).length}/{batchResults.length} passed</span>
          </div>
          <div style={{ display: 'grid', gap: 8 }}>
            {batchResults.map((r, idx) => (
              <div key={idx} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)',
                background: r.ok ? 'rgba(16,185,129,0.06)' : 'rgba(239,68,68,0.06)',
              }}>
                <span style={{ fontWeight: 600 }}>{r.program}</span>
                <span style={{ color: r.ok ? 'var(--green)' : 'var(--red)', fontSize: 12 }}>
                  {r.ok ? `✓ ${r.status || 'done'}` : `✕ ${r.error || 'failed'}`}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── reusable API key input ──────────────────────────────────────────────────

function ApiKeyInput({
  value, onChange, show, onToggle, placeholder, note,
}: {
  value: string; onChange: (v: string) => void
  show: boolean; onToggle: () => void
  placeholder?: string; note?: string
}) {
  return (
    <div>
      <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
        <input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder || 'API key...'}
          style={{ width: '100%', paddingRight: 64 }}
        />
        <button
          type="button"
          onClick={onToggle}
          style={{ position: 'absolute', right: 8, background: 'none', border: 'none', color: 'var(--muted)', cursor: 'pointer', fontSize: 11, padding: '2px 6px' }}
        >
          {show ? '🙈 Hide' : '👁 Show'}
        </button>
      </div>
      {note && (
        <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4, paddingLeft: 4 }}>ℹ️ {note}</div>
      )}
    </div>
  )
}

const friendlyError = (error: unknown) => {
  const raw = error instanceof Error ? error.message : String(error)
  const text = raw.toLowerCase()

  if (text.includes('quota') || text.includes('rate limit') || text.includes('429') || text.includes('exceeded your quota')) {
    return {
      title: 'Quota limit reached',
      message: 'The selected AI model has reached its usage limit. Please wait a bit, switch to another model, or verify your billing/quota in the provider dashboard.'
    }
  }

  if (text.includes('api key') || text.includes('unauthorized') || text.includes('401') || text.includes('403') || text.includes('forbidden')) {
    return {
      title: 'API key issue',
      message: `The provider rejected the request as an auth/key problem. This can mean the key is wrong, belongs to a different provider, or the selected model is not available to that account. Original error: ${raw}`
    }
  }

  if (text.includes('network') || text.includes('fetch') || text.includes('failed to fetch') || text.includes('connection')) {
    return {
      title: 'Connection problem',
      message: 'The AI service could not be reached. Please check your internet connection and try again.'
    }
  }

  if (text.includes('timeout')) {
    return {
      title: 'Request timed out',
      message: 'The AI request took too long. Please retry with a smaller model or check the service status.'
    }
  }

  return {
    title: 'Migration could not start',
    message: 'Something went wrong while starting the migration. Please review the backend settings and try again.'
  }
}
