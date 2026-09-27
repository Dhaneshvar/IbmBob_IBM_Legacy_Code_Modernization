import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { connect } from '../api/client'
import type { AppState } from '../App'

interface Props {
  state: AppState
  update: (p: Partial<AppState>) => void
}

export default function ConnectPage({ state, update }: Props) {
  const nav = useNavigate()
  const [form, setForm] = useState({
    host: 'MVS.MAINFRAME.EXAMPLE.COM',
    port: 23,
    user: 'IBMUSER',
    password: 'SYS1',
  })
  const [loading, setLoading] = useState(false)

  const handleConnect = async () => {
    setLoading(true)
    // Always navigate — credentials are dummy for hackathon demo
    // API call is best-effort; failure falls back to local sysinfo
    try {
      const res = await connect({ ...form, session_id: 'default' })
      update({
        connected: true,
        sysinfo: res.sysinfo as Record<string, string>,
      })
    } catch {
      // API down or unreachable — still proceed with dummy sysinfo
      update({
        connected: true,
        sysinfo: {
          hostname: form.host,
          platform: 'IBM z/OS 2.5',
          zos_version: 'z/OS 2.5',
          user: form.user,
          sysplex: 'PLEX01',
        },
      })
    } finally {
      setLoading(false)
    }
    // Navigate regardless of API outcome
    nav('/assets')
  }

  const stages = [
    {
      num: '01',
      icon: '⚡',
      title: 'Deterministic Parsing',
      tech: 'ANTLR4 / Recursive Descent',
      desc: 'Parses COBOL-85 & JCL card syntax without LLM hallucinations. Preserves unknown constructs.',
    },
    {
      num: '02',
      icon: '🔄',
      title: 'Normalized IR Lowering',
      tech: 'Language-Agnostic IR',
      desc: 'Translates PIC clauses, OCCURS tables, and paragraphs into explicit types, blocks, and CFG edges.',
    },
    {
      num: '03',
      icon: '🗄️',
      title: 'Dual-Store Persistence',
      tech: 'SQLite + Neo4j Graph',
      desc: 'Indexes programs, variables, and cross-job dataset dependencies into graph relationships.',
    },
    {
      num: '04',
      icon: '🤖',
      title: 'Agentic Migration Loop',
      tech: 'Planner → Executor → Critic',
      desc: 'Multi-agent refinement loop. LLM operates strictly on IR & Java scaffolding, not raw COBOL.',
    },
    {
      num: '05',
      icon: '☕',
      title: 'Clean Java 17 Emission',
      tech: 'Spring Boot & BigDecimal',
      desc: 'Deterministic skeleton with financial BigDecimal arithmetic, modular methods, and TODO markers.',
    },
    {
      num: '06',
      icon: '📊',
      title: 'Live AI-Ops Observability',
      tech: 'Prometheus & Loki Spans',
      desc: 'Real-time telemetry, WebSocket streaming spans, force-directed graph, and Markdown reports.',
    },
  ]

  return (
    <div className="page" style={{ paddingTop: 20 }}>
      {/* Hero Header */}
      <div style={{ textAlign: 'center', marginBottom: 36 }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '4px 14px', borderRadius: 'var(--radius-full)', background: 'rgba(99, 102, 241, 0.1)', border: '1px solid rgba(99, 102, 241, 0.25)', marginBottom: 16 }}>
          <span style={{ fontSize: 13 }}>⚡</span>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent-light)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
            Enterprise Mainframe Modernization Platform
          </span>
        </div>
        
        <h1 className="page-title gradient-text" style={{ fontSize: 34, marginBottom: 10 }}>
          Deterministic COBOL/JCL to Java 17
        </h1>
        
        <p className="page-subtitle" style={{ maxWidth: 620, margin: '0 auto' }}>
          Connect to your IBM z/OS environment to browse assets, inspect normalized IR,
          and continue into the migration workflow.
        </p>
      </div>

      {/* Main Connection Card */}
      <div className="card card-interactive" style={{ maxWidth: 540, margin: '0 auto', backdropFilter: 'blur(20px)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
          <div className="card-title" style={{ margin: 0 }}>
            <span>🖥️</span> z/OS Mainframe Connection
          </div>
          <span className="badge badge-yellow">Z/OSMF</span>
        </div>

        <div className="form-grid" style={{ marginBottom: 18 }}>
          <div className="form-field" style={{ gridColumn: '1/-1' }}>
            <label>Host / IP Address</label>
            <input
              value={form.host}
              onChange={e => setForm(f => ({ ...f, host: e.target.value }))}
              placeholder="MVS.MAINFRAME.EXAMPLE.COM"
            />
          </div>
          
          <div className="form-field">
            <label>Port (TN3270 / REST)</label>
            <input
              type="number"
              value={form.port}
              onChange={e => setForm(f => ({ ...f, port: +e.target.value }))}
            />
          </div>
          
          <div className="form-field">
            <label>RACF User ID</label>
            <input
              value={form.user}
              onChange={e => setForm(f => ({ ...f, user: e.target.value }))}
            />
          </div>
          
          <div className="form-field" style={{ gridColumn: '1/-1' }}>
            <label>Password</label>
            <input
              type="password"
              value={form.password}
              onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
            />
          </div>
        </div>

        <button
          className="btn btn-primary"
          onClick={handleConnect}
          disabled={loading}
          style={{ width: '100%', height: 44, fontSize: 14 }}
        >
          {loading ? (
            <>
              <span className="spinner" />
              <span>Establishing z/OS Session...</span>
            </>
          ) : (
            <>
              <span>⚡</span>
              <span>Connect to z/OS Mainframe</span>
            </>
          )}
        </button>

        {/* Available Assets Pill Bar */}
        <div style={{ marginTop: 22, paddingTop: 18, borderTop: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Available Assets
            </span>
            <span style={{ fontSize: 11, color: 'var(--muted-dark)' }}>Ready to migrate</span>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {[
              { name: 'PAYROLL.cbl', type: 'COBOL' },
              { name: 'ORDPRCS.cbl', type: 'COBOL' },
              { name: 'INVNTRY.cbl', type: 'COBOL' },
              { name: 'PAYJOB.jcl',  type: 'JCL' },
              { name: 'ORDJOB.jcl',  type: 'JCL' },
              { name: 'PAYINQ', type: 'BMS' },
              { name: 'ORDINQ', type: 'BMS' },
              { name: 'HLQ.PAYROLL.INPUT', type: 'DATASET' },
              { name: 'HLQ.PAYROLL.OUTPUT', type: 'DATASET' },
              { name: 'HLQ.ORDER.INPUT', type: 'DATASET' },
            ].map(f => (
              <span key={f.name} className="badge badge-blue" style={{ fontSize: 11 }}>
                <span>{f.type === 'COBOL' ? '📄' : f.type === 'JCL' ? '⚙️' : f.type === 'BMS' ? '🖥️' : '🗄️'}</span>
                <span>{f.name}</span>
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Pipeline Architecture Grid */}
      <div style={{ maxWidth: 860, margin: '40px auto 20px' }}>
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text)' }}>
            Automated Migration Pipeline
          </h2>
          <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4 }}>
            Deterministic AST lowering into language-agnostic IR, verified by multi-agent critics.
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 14 }}>
          {stages.map(s => (
            <div
              key={s.num}
              className="card card-interactive"
              style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 8 }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 16 }}>{s.icon}</span>
                  <span style={{ fontWeight: 700, fontSize: 13.5, color: '#ffffff' }}>{s.title}</span>
                </div>
                <span style={{ fontSize: 10, fontWeight: 800, color: 'var(--accent-light)', fontFamily: 'var(--font-mono)' }}>
                  {s.num}
                </span>
              </div>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent2)', fontFamily: 'var(--font-mono)' }}>
                {s.tech}
              </div>
              <p style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.5, margin: 0 }}>
                {s.desc}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
