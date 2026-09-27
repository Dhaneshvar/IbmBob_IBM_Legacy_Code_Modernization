import { useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from 'react-router-dom'
import ConnectPage from './pages/ConnectPage'
import AssetBrowserPage from './pages/AssetBrowserPage'
import GraphPage from './pages/GraphPage'
import WizardPage from './pages/WizardPage'
import LiveOpsPage from './pages/LiveOpsPage'
import ResultPage from './pages/ResultPage'
import './App.css'

export interface AppState {
  connected: boolean
  sysinfo: Record<string, string>
  selectedAssets: string[]
  selectedProgram: string
  migrateResult: unknown
  targetLang: string
  llmBackend: string
  llmModel: string
  llmApiKey: string
  watsonxProjectId: string
  watsonxRegion: string
  executionMode: 'accelerated' | 'live'
  ollamaUrl: string
}

export default function App() {
  const [state, setState] = useState<AppState>({
    connected: false,
    sysinfo: {},
    selectedAssets: [],
    selectedProgram: '',
    migrateResult: null,
    targetLang: 'java',
    llmBackend: 'gemini',
    llmModel: 'gemini-3.8-flash',
    llmApiKey: '',
    watsonxProjectId: '',
    watsonxRegion: 'us-south',
    executionMode: 'accelerated',
    ollamaUrl: 'http://localhost:11434',
  })

  const update = (patch: Partial<AppState>) =>
    setState(prev => ({ ...prev, ...patch }))

  return (
    <BrowserRouter>
      <div className="app-shell">
        <Header state={state} />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<ConnectPage state={state} update={update} />} />
            <Route
              path="/assets"
              element={
                state.connected ? <AssetBrowserPage state={state} update={update} /> : <Navigate to="/" />
              }
            />
            <Route
              path="/graph"
              element={
                state.connected ? <GraphPage state={state} update={update} /> : <Navigate to="/" />
              }
            />
            <Route
              path="/wizard"
              element={
                state.connected ? <WizardPage state={state} update={update} /> : <Navigate to="/" />
              }
            />
            <Route
              path="/live"
              element={
                state.connected ? <LiveOpsPage state={state} update={update} /> : <Navigate to="/" />
              }
            />
            <Route
              path="/result"
              element={
                state.migrateResult ? <ResultPage state={state} update={update} /> : <Navigate to="/assets" />
              }
            />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

function Header({ state }: { state: AppState }) {
  const location = useLocation()
  const steps = [
    { path: '/',        num: '1', label: 'Connect',      active: true },
    { path: '/assets',  num: '2', label: 'Browse',       active: state.connected },
    { path: '/graph',   num: '3', label: 'Neo4j Graph',  active: state.connected },
    { path: '/wizard',  num: '4', label: 'Configure',    active: state.connected && state.selectedAssets.length > 0 },
    { path: '/live',    num: '5', label: 'AI-Ops',       active: state.connected },
    { path: '/result',  num: '6', label: 'Results',      active: !!state.migrateResult },
  ]

  return (
    <header className="app-header">
      <div className="header-brand">
        <div className="brand-icon-wrap">
          <span className="brand-icon">⚡</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span className="brand-name">IBM Legacy Modernizer</span>
        </div>
        <span className="version-pill">v0.1.0</span>
        {state.connected && (
          <span className="conn-badge">
            <span className="live-dot" />
            {state.sysinfo.hostname || 'z/OS 2.5'}
          </span>
        )}
      </div>

      <nav className="header-steps">
        {steps.map((s, i) => {
          const isCurrent = location.pathname === s.path
          return (
            <Link
              key={i}
              to={s.active ? s.path : '#'}
              className={`step-item ${isCurrent ? 'active' : ''} ${s.active ? '' : 'disabled'}`}
              onClick={e => !s.active && e.preventDefault()}
            >
              <span className="step-num">{s.num}</span>
              <span>{s.label}</span>
            </Link>
          )
        })}
      </nav>
    </header>
  )
}
