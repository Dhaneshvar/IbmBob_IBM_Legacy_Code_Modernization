import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { getGraph, queryGraph, listAssets } from '../api/client'
import type { AppState } from '../App'
import type { GraphNode, GraphLink } from '../api/client'

interface Props { state: AppState; update: (p: Partial<AppState>) => void }

const NODE_CONFIG: Record<string, { color: string; glow: string; icon: string; radius: number }> = {
  Program:  { color: '#0f62fe', glow: 'rgba(15, 98, 254, 0.35)', icon: '📄', radius: 14 },
  Function: { color: '#8a3ffc', glow: 'rgba(138, 63, 252, 0.35)', icon: '⚙️', radius: 9 },
  Variable: { color: '#24a148', glow: 'rgba(36, 161, 72, 0.35)', icon: '📦', radius: 7 },
  Dataset:  { color: '#f1c21b', glow: 'rgba(241, 194, 27, 0.35)', icon: '🗄️', radius: 11 },
  Job:      { color: '#da1e28', glow: 'rgba(218, 30, 40, 0.35)', icon: '⚡', radius: 13 },
  Screen:   { color: '#ff7eb6', glow: 'rgba(255, 126, 182, 0.35)', icon: '🖥️', radius: 13 },
  Field:    { color: '#1192e8', glow: 'rgba(17, 146, 232, 0.35)', icon: '🏷️', radius: 7 },
}

const PRESET_QUERIES = [
  {
    label: '1. All Enterprise Nodes',
    desc: 'Inspect all cataloged programs, jobs, screens, and datasets',
    cypher: 'MATCH (n) RETURN n LIMIT 100',
  },
  {
    label: '2. Function Call Tree',
    desc: 'Trace procedural calls between paragraphs and subroutines',
    cypher: 'MATCH (caller:Function)-[:CALLS]->(callee:Function) RETURN caller, callee',
  },
  {
    label: '3. JCL Batch Data Lineage',
    desc: 'Trace jobs executing programs and binding input/output datasets',
    cypher: 'MATCH (j:Job)-[:RUNS]->(p:Program), (j)-[:USES_DATASET]->(d:Dataset) RETURN j, p, d',
  },
  {
    label: '4. BMS 3270 Screens & Fields',
    desc: 'Inspect CICS 3270 screen layouts and input/output field mappings',
    cypher: 'MATCH (s:Screen)-[:HAS_FIELD]->(f:Field) RETURN s, f',
  },
  {
    label: '5. Screen-to-Program User Flows',
    desc: 'Discover which COBOL programs display interactive BMS screens',
    cypher: 'MATCH (p:Program)-[:DISPLAYS_SCREEN]->(s:Screen) RETURN p, s',
  },
]

export default function GraphPage({ state, update }: Props) {
  const nav = useNavigate()
  const location = useLocation()
  const [nodes, setNodes] = useState<GraphNode[]>([])
  const [links, setLinks] = useState<GraphLink[]>([])
  const [neo4jConnected, setNeo4jConnected] = useState<boolean>(false)
  const [backendMode, setBackendMode] = useState<string>('sqlite_fallback')
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [filterType, setFilterType] = useState<Record<string, boolean>>({
    Program: true, Function: true, Variable: true, Dataset: true, Job: true, Screen: true, Field: true,
  })
  const [programFilter, setProgramFilter] = useState<string>('ALL')
  const [availableAssets, setAvailableAssets] = useState<{ name: string; type: string }[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [cypherInput, setCypherInput] = useState('')
  const [cypherOutput, setCypherOutput] = useState<string>('')
  const [cypherRecords, setCypherRecords] = useState<unknown[]>([])
  const [isQuerying, setIsQuerying] = useState(false)
  const [showCypherPanel, setShowCypherPanel] = useState(true)

  // Canvas physics
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const posRef = useRef<Record<string | number, { x: number; y: number; vx: number; vy: number }>>({})
  const draggedNodeRef = useRef<string | number | null>(null)
  const [dimensions, setDimensions] = useState({ w: 1000, h: 620 })
  const containerRef = useRef<HTMLDivElement>(null)

  // Fetch initial graph data
  const loadGraphData = useCallback(async (prog?: string) => {
    try {
      const p = prog === 'ALL' ? undefined : prog
      const res = await getGraph(p)
      setNodes(res.nodes || [])
      setLinks(res.links || [])
      setNeo4jConnected(!!res.neo4j_connected)
      setBackendMode(res.backend || 'sqlite_fallback')
    } catch (e) {
      console.error('Failed to load graph:', e)
    }
  }, [])

  useEffect(() => {
    listAssets().then(r => {
      setAvailableAssets(r.assets.map(a => ({ name: a.name, type: a.type })))
    }).catch(console.error)

    const initial = (location.state as { asset?: string })?.asset
    if (initial) {
      setProgramFilter(initial)
      loadGraphData(initial)
    } else {
      loadGraphData()
    }
  }, [loadGraphData, location.state])

  // Resize listener
  useEffect(() => {
    const handleResize = () => {
      if (containerRef.current) {
        setDimensions({
          w: containerRef.current.clientWidth || 1000,
          h: Math.max(560, window.innerHeight - 300)
        })
      }
    }
    handleResize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // Execute Cypher
  const runCypher = async (queryText?: string) => {
    const q = queryText ?? cypherInput
    if (!q.trim()) return
    setIsQuerying(true)
    try {
      const res = await queryGraph(q)
      if (res.ok) {
        if (res.nodes) setNodes(res.nodes)
        if (res.links) setLinks(res.links)
        if (res.records) setCypherRecords(res.records)
        setCypherOutput(res.summary || `Success: ${res.records?.length ?? res.nodes?.length ?? 0} results returned.`)
      } else {
        setCypherOutput(`Error: ${res.error || 'Query failed'}`)
        setCypherRecords([])
      }
    } catch (e) {
      setCypherOutput(`Error: ${e instanceof Error ? e.message : String(e)}`)
      setCypherRecords([])
    } finally {
      setIsQuerying(false)
    }
  }

  // Filtered nodes & links
  const visibleNodes = nodes.filter(n => {
    if (!filterType[n.label]) return false
    if (searchQuery.trim() && !n.name.toLowerCase().includes(searchQuery.toLowerCase())) return false
    return true
  })

  const visibleNodeIds = new Set(visibleNodes.map(n => n.id))
  const visibleLinks = links.filter(l => visibleNodeIds.has(l.source) && visibleNodeIds.has(l.target))

  // Inbound & outbound for selected node
  const inboundLinks = selectedNode ? links.filter(l => l.target === selectedNode.id) : []
  const outboundLinks = selectedNode ? links.filter(l => l.source === selectedNode.id) : []

  // Canvas Force Simulation
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const { w, h } = dimensions
    canvas.width = w
    canvas.height = h

    // Initialize positions
    visibleNodes.forEach(n => {
      if (!posRef.current[n.id]) {
        posRef.current[n.id] = {
          x: w / 2 + (Math.random() - 0.5) * (w * 0.65),
          y: h / 2 + (Math.random() - 0.5) * (h * 0.65),
          vx: 0,
          vy: 0,
        }
      }
    })

    let animId: number
    const simulate = () => {
      const pos = posRef.current

      // Repulsion between nodes
      for (let i = 0; i < visibleNodes.length; i++) {
        for (let j = i + 1; j < visibleNodes.length; j++) {
          const a = pos[visibleNodes[i].id]
          const b = pos[visibleNodes[j].id]
          if (!a || !b) continue
          const dx = a.x - b.x
          const dy = a.y - b.y
          const dist = Math.sqrt(dx * dx + dy * dy) || 1
          const force = 3200 / (dist * dist)
          a.vx += (dx / dist) * force
          a.vy += (dy / dist) * force
          b.vx -= (dx / dist) * force
          b.vy -= (dy / dist) * force
        }
      }

      // Spring attraction along links
      visibleLinks.forEach(l => {
        const a = pos[l.source]
        const b = pos[l.target]
        if (!a || !b) return
        const dx = b.x - a.x
        const dy = b.y - a.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const force = (dist - 110) * 0.015
        a.vx += (dx / dist) * force
        a.vy += (dy / dist) * force
        b.vx -= (dx / dist) * force
        b.vy -= (dy / dist) * force
      })

      // Center gravity & damping
      visibleNodes.forEach(n => {
        const p = pos[n.id]
        if (!p) return
        if (draggedNodeRef.current === n.id) return // Don't apply physics while dragging
        p.vx += (w / 2 - p.x) * 0.002
        p.vy += (h / 2 - p.y) * 0.002
        p.vx *= 0.86
        p.vy *= 0.86
        p.x = Math.max(25, Math.min(w - 25, p.x + p.vx))
        p.y = Math.max(25, Math.min(h - 25, p.y + p.vy))
      })

      // Draw frame
      ctx.clearRect(0, 0, w, h)

      // Draw background grid lines
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.02)'
      ctx.lineWidth = 1
      for (let x = 0; x < w; x += 40) {
        ctx.beginPath()
        ctx.moveTo(x, 0)
        ctx.lineTo(x, h)
        ctx.stroke()
      }
      for (let y = 0; y < h; y += 40) {
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(w, y)
        ctx.stroke()
      }

      // Draw links
      visibleLinks.forEach(l => {
        const a = pos[l.source]
        const b = pos[l.target]
        if (!a || !b) return

        const isHighlighted = selectedNode && (selectedNode.id === l.source || selectedNode.id === l.target)
        ctx.strokeStyle = isHighlighted ? 'rgba(99, 102, 241, 0.85)' : 'rgba(255, 255, 255, 0.12)'
        ctx.lineWidth = isHighlighted ? 2 : 1

        ctx.beginPath()
        ctx.moveTo(a.x, a.y)
        ctx.lineTo(b.x, b.y)
        ctx.stroke()

        // Direction arrow
        const angle = Math.atan2(b.y - a.y, b.x - a.x)
        const targetRadius = (NODE_CONFIG[nodes.find(n => n.id === l.target)?.label || '']?.radius || 10) + 4
        const arrowX = b.x - Math.cos(angle) * targetRadius
        const arrowY = b.y - Math.sin(angle) * targetRadius

        ctx.fillStyle = isHighlighted ? '#818cf8' : 'rgba(255, 255, 255, 0.35)'
        ctx.beginPath()
        ctx.moveTo(arrowX, arrowY)
        ctx.lineTo(arrowX - 8 * Math.cos(angle - 0.4), arrowY - 8 * Math.sin(angle - 0.4))
        ctx.lineTo(arrowX - 8 * Math.cos(angle + 0.4), arrowY - 8 * Math.sin(angle + 0.4))
        ctx.closePath()
        ctx.fill()

        // Relationship label on link (if highlighted)
        if (isHighlighted && l.type) {
          ctx.fillStyle = 'var(--text-secondary)'
          ctx.font = '10px JetBrains Mono'
          const midX = (a.x + b.x) / 2
          const midY = (a.y + b.y) / 2
          ctx.fillText(l.type, midX + 4, midY - 4)
        }
      })

      // Draw nodes
      visibleNodes.forEach(n => {
        const p = pos[n.id]
        if (!p) return

        const cfg = NODE_CONFIG[n.label] || { color: '#cbd5e1', glow: 'rgba(203, 213, 225, 0.3)', radius: 9 }
        const isSelected = selectedNode?.id === n.id
        const radius = isSelected ? cfg.radius + 4 : cfg.radius

        // Outer glow
        ctx.beginPath()
        ctx.arc(p.x, p.y, radius + 4, 0, Math.PI * 2)
        ctx.fillStyle = isSelected ? 'rgba(99, 102, 241, 0.5)' : cfg.glow
        ctx.fill()

        // Node circle
        ctx.beginPath()
        ctx.arc(p.x, p.y, radius, 0, Math.PI * 2)
        ctx.fillStyle = isSelected ? '#ffffff' : cfg.color
        ctx.fill()
        ctx.strokeStyle = isSelected ? 'var(--accent)' : 'rgba(0, 0, 0, 0.4)'
        ctx.lineWidth = isSelected ? 3 : 1.5
        ctx.stroke()

        // Text label
        ctx.font = `${isSelected ? 'bold 12px' : '11px'} Plus Jakarta Sans, sans-serif`
        ctx.fillStyle = isSelected ? '#ffffff' : 'var(--text-secondary)'
        ctx.fillText(n.name.length > 16 ? n.name.slice(0, 15) + '…' : n.name, p.x + radius + 6, p.y + 4)
      })

      animId = requestAnimationFrame(simulate)
    }

    animId = requestAnimationFrame(simulate)
    return () => cancelAnimationFrame(animId)
  }, [visibleNodes, visibleLinks, dimensions, selectedNode])

  // Mouse interaction for drag & click
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top

    // Find clicked node
    for (const n of visibleNodes) {
      const p = posRef.current[n.id]
      if (!p) continue
      const dist = Math.hypot(mx - p.x, my - p.y)
      const rad = (NODE_CONFIG[n.label]?.radius || 10) + 6
      if (dist <= rad) {
        draggedNodeRef.current = n.id
        setSelectedNode(n)
        return
      }
    }
  }

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!draggedNodeRef.current) return
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const p = posRef.current[draggedNodeRef.current]
    if (p) {
      p.x = Math.max(20, Math.min(dimensions.w - 20, e.clientX - rect.left))
      p.y = Math.max(20, Math.min(dimensions.h - 20, e.clientY - rect.top))
      p.vx = 0
      p.vy = 0
    }
  }

  const handleMouseUp = () => {
    draggedNodeRef.current = null
  }

  return (
    <div className="page" style={{ maxWidth: 1400, margin: '0 auto', paddingBottom: 60 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <span style={{
              fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 999,
              background: neo4jConnected ? 'rgba(16, 185, 129, 0.15)' : 'rgba(99, 102, 241, 0.15)',
              color: neo4jConnected ? 'var(--green)' : 'var(--accent)',
              border: `1px solid ${neo4jConnected ? 'rgba(16, 185, 129, 0.3)' : 'rgba(99, 102, 241, 0.3)'}`,
              textTransform: 'uppercase', letterSpacing: '0.06em'
            }}>
              {neo4jConnected ? '● Neo4j Live Bolt Server' : '● Dual-Store Graph (Neo4j Ready)'}
            </span>
            <span style={{ fontSize: 13, color: 'var(--muted)' }}>
              Protocol: <strong style={{ color: 'var(--text)' }}>bolt://localhost:7687</strong>
            </span>
          </div>
          <h1 className="page-title" style={{ margin: 0, fontSize: 24 }}>Neo4j Knowledge Graph Explorer</h1>
          <p className="page-subtitle" style={{ margin: '4px 0 0' }}>
            Interactive property graph visualizer — explore call trees, data lineage, and cross-system JCL datasets.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button className="btn btn-ghost" onClick={() => loadGraphData(programFilter)}>
            🔄 Refresh Graph
          </button>
          <button className="btn btn-ghost" onClick={() => setShowCypherPanel(!showCypherPanel)}>
            {showCypherPanel ? 'Hide Cypher Console' : '⌨️ Cypher Console'}
          </button>
          <button className="btn btn-primary" onClick={() => nav('/assets')}>
            Back to Asset Browser →
          </button>
        </div>
      </div>

      {/* Interactive Cypher Console */}
      {showCypherPanel && (
        <div className="card" style={{ marginBottom: 16, padding: '16px 20px', background: 'var(--surface-solid)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 14 }}>⚡</span>
              <div className="card-title" style={{ margin: 0, fontSize: 13 }}>Cypher Query Engine</div>
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {PRESET_QUERIES.map((p, idx) => (
                <button
                  key={idx}
                  onClick={() => { setCypherInput(p.cypher); runCypher(p.cypher) }}
                  style={{
                    padding: '3px 10px', fontSize: 11, borderRadius: 6,
                    background: 'var(--surface2)', border: '1px solid var(--border)',
                    color: 'var(--text-secondary)', cursor: 'pointer'
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <div style={{ display: 'flex', gap: 10 }}>
            <div style={{ flex: 1, position: 'relative' }}>
              <input
                value={cypherInput}
                onChange={e => setCypherInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && runCypher()}
                placeholder="MATCH (n) RETURN n LIMIT 50..."
                style={{
                  width: '100%', padding: '10px 14px', fontFamily: 'var(--font-mono)',
                  fontSize: 12, background: 'var(--bg)', borderRadius: 'var(--radius)',
                  border: '1px solid var(--border)', color: 'var(--text)',
                  WebkitTextFillColor: 'var(--text)'
                }}
              />
            </div>
            <button
              className="btn btn-primary"
              disabled={isQuerying}
              onClick={() => runCypher()}
              style={{ padding: '0 20px', fontSize: 12 }}
            >
              {isQuerying ? 'Executing...' : 'Run Cypher'}
            </button>
          </div>

          <div style={{ marginTop: 8, fontSize: 11, color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
            <span>💡 <strong>Quick Cypher Samples:</strong></span>
            <span>Click any preset above to visualize call trees, JCL datasets, or CICS screens. Works with both Neo4j and Dual-Store SQLite!</span>
          </div>

          {cypherOutput && (
            <div style={{
              marginTop: 10, padding: '8px 12px', background: 'rgba(99, 102, 241, 0.08)',
              border: '1px solid rgba(99, 102, 241, 0.2)', borderRadius: 6,
              fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text)',
              WebkitTextFillColor: 'var(--text)'
            }}>
              {cypherOutput}
            </div>
          )}

          {cypherRecords.length > 0 && (
            <div style={{ marginTop: 10, maxHeight: 150, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 6 }}>
              <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse', fontFamily: 'var(--font-mono)' }}>
                <thead>
                  <tr style={{ background: 'var(--surface2)', textAlign: 'left', color: 'var(--text-secondary)' }}>
                    {Object.keys(cypherRecords[0] as object).map((k) => (
                      <th key={k} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)' }}>{k}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {cypherRecords.slice(0, 15).map((row, rIdx) => (
                    <tr key={rIdx} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                      {Object.values(row as object).map((v, cIdx) => (
                        <td key={cIdx} style={{ padding: '4px 8px', color: 'var(--text)' }}>
                          {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Filter and Control Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 16px', background: 'var(--surface)', borderRadius: 'var(--radius)',
        border: '1px solid var(--border)', marginBottom: 12, flexWrap: 'wrap', gap: 12
      }}>
        {/* Node Type Toggles */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase' }}>Filter:</span>
          {Object.entries(NODE_CONFIG).map(([label, cfg]) => (
            <label key={label} style={{
              display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
              fontSize: 12, padding: '4px 10px', borderRadius: 6,
              background: filterType[label] ? 'var(--surface2)' : 'transparent',
              border: `1px solid ${filterType[label] ? cfg.color : 'transparent'}`
            }}>
              <input
                type="checkbox"
                checked={filterType[label]}
                onChange={() => setFilterType(prev => ({ ...prev, [label]: !prev[label] }))}
                style={{ accentColor: cfg.color }}
              />
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: cfg.color }} />
              <span style={{ color: filterType[label] ? 'var(--text)' : 'var(--muted)' }}>{label}</span>
            </label>
          ))}
        </div>

        {/* Program Subgraph Dropdown & Search */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <select
            value={programFilter}
            onChange={e => {
              setProgramFilter(e.target.value)
              loadGraphData(e.target.value)
            }}
            style={{
              padding: '6px 12px', fontSize: 12, borderRadius: 6,
              background: 'var(--surface2)', color: 'var(--text)', border: '1px solid var(--border)'
            }}
          >
            <option value="ALL">🌐 All Enterprise Assets</option>
            <optgroup label="COBOL Programs">
              {availableAssets.filter(a => a.type === 'COBOL').map(a => (
                <option key={a.name} value={a.name}>📄 {a.name}</option>
              ))}
            </optgroup>
            <optgroup label="JCL Batch Jobs">
              {availableAssets.filter(a => a.type === 'JCL').map(a => (
                <option key={a.name} value={a.name}>⚡ {a.name}</option>
              ))}
            </optgroup>
            <optgroup label="CICS / BMS Screens">
              {availableAssets.filter(a => a.type === 'BMS').map(a => (
                <option key={a.name} value={a.name}>🖥️ {a.name}</option>
              ))}
            </optgroup>
            <optgroup label="QSAM Datasets">
              {availableAssets.filter(a => a.type === 'DATASET').map(a => (
                <option key={a.name} value={a.name}>🗄️ {a.name}</option>
              ))}
            </optgroup>
          </select>

          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search nodes..."
            style={{
              padding: '6px 12px', fontSize: 12, borderRadius: 6, width: 160,
              background: 'var(--surface2)', color: 'var(--text)', border: '1px solid var(--border)'
            }}
          />
        </div>
      </div>

      {/* Main Graph Viewport + Inspector Layout */}
      <div style={{ display: 'grid', gridTemplateColumns: selectedNode ? '1fr 340px' : '1fr', gap: 12 }}>
        {/* Force Directed Graph Canvas */}
        <div ref={containerRef} className="card" style={{ padding: 0, overflow: 'hidden', position: 'relative' }}>
          <canvas
            ref={canvasRef}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            style={{ display: 'block', cursor: 'grab', background: '#07090e' }}
          />

          {/* Canvas Floating Legend */}
          <div style={{
            position: 'absolute', bottom: 12, left: 14, display: 'flex', gap: 14,
            padding: '6px 14px', background: 'rgba(15, 23, 42, 0.85)',
            backdropFilter: 'blur(8px)', borderRadius: 999, border: '1px solid var(--border)',
            fontSize: 11
          }}>
            <span style={{ color: 'var(--muted)' }}>Nodes: <strong style={{ color: 'var(--text)' }}>{visibleNodes.length}</strong></span>
            <span style={{ color: 'var(--muted)' }}>Edges: <strong style={{ color: 'var(--text)' }}>{visibleLinks.length}</strong></span>
            <span style={{ color: 'var(--muted)' }}>Click node to inspect</span>
          </div>
        </div>

        {/* Node Inspector Drawer */}
        {selectedNode && (
          <div className="card" style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 20 }}>{NODE_CONFIG[selectedNode.label]?.icon || '📦'}</span>
                <div>
                  <span style={{
                    fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
                    background: `${NODE_CONFIG[selectedNode.label]?.color}22`,
                    color: NODE_CONFIG[selectedNode.label]?.color
                  }}>
                    {selectedNode.label}
                  </span>
                  <div style={{ fontSize: 14, fontWeight: 700, marginTop: 2 }}>{selectedNode.name}</div>
                </div>
              </div>
              <button
                className="btn btn-ghost"
                onClick={() => setSelectedNode(null)}
                style={{ padding: '2px 8px', fontSize: 12 }}
              >
                ✕
              </button>
            </div>

            {/* Properties */}
            <div style={{ background: 'var(--surface2)', borderRadius: 8, padding: 10, fontSize: 11, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--muted)' }}>Node ID:</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-light)' }}>{String(selectedNode.id)}</span>
              </div>
              {selectedNode.prog && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--muted)' }}>Program:</span>
                  <strong style={{ color: 'var(--text)' }}>{selectedNode.prog}</strong>
                </div>
              )}
              {selectedNode.complexity != null && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--muted)' }}>Cyclomatic CX:</span>
                  <span style={{
                    color: selectedNode.complexity > 5 ? 'var(--red)' : selectedNode.complexity > 2 ? 'var(--yellow)' : 'var(--green)',
                    fontWeight: 700
                  }}>
                    {selectedNode.complexity}
                  </span>
                </div>
              )}
              {selectedNode.type && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--muted)' }}>Data Type:</span>
                  <span style={{ fontFamily: 'var(--font-mono)' }}>{selectedNode.type}</span>
                </div>
              )}
              {selectedNode.is_io != null && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--muted)' }}>I/O Procedure:</span>
                  <span>{selectedNode.is_io ? 'Yes (File Read/Write)' : 'No'}</span>
                </div>
              )}
            </div>

            {/* Relationships */}
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}>
                Connected Relationships
              </div>

              {/* Inbound */}
              <div style={{ marginBottom: 8 }}>
                <span style={{ fontSize: 10, color: 'var(--muted-dark)' }}>INBOUND ({inboundLinks.length}):</span>
                {inboundLinks.length === 0 ? (
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>None (Root node)</div>
                ) : (
                  inboundLinks.slice(0, 5).map((l, i) => (
                    <div key={i} style={{ fontSize: 11, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                      <span style={{ color: 'var(--accent)' }}>← {l.type}</span> from <span style={{ fontFamily: 'var(--font-mono)' }}>{String(l.source)}</span>
                    </div>
                  ))
                )}
              </div>

              {/* Outbound */}
              <div>
                <span style={{ fontSize: 10, color: 'var(--muted-dark)' }}>OUTBOUND ({outboundLinks.length}):</span>
                {outboundLinks.length === 0 ? (
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>None (Leaf node)</div>
                ) : (
                  outboundLinks.slice(0, 5).map((l, i) => (
                    <div key={i} style={{ fontSize: 11, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                      <span style={{ color: 'var(--green)' }}>→ {l.type}</span> to <span style={{ fontFamily: 'var(--font-mono)' }}>{String(l.target)}</span>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Quick Actions */}
            <div style={{ marginTop: 'auto', paddingTop: 10, borderTop: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 6 }}>
              {selectedNode.label === 'Program' && (
                <button
                  className="btn btn-primary"
                  onClick={() => {
                    update({ selectedAssets: [selectedNode.name] })
                    nav('/wizard')
                  }}
                  style={{ width: '100%', fontSize: 12 }}
                >
                  🚀 Migrate {selectedNode.name}
                </button>
              )}
              <button
                className="btn btn-ghost"
                onClick={() => nav('/assets')}
                style={{ width: '100%', fontSize: 12 }}
              >
                Inspect in Asset Browser
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
