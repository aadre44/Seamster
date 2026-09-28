import { useRef, useEffect, useState, useCallback } from 'react'
import { useEditor } from '../context/EditorContext'
import { snap, SNAP_COLORS, screenToCm } from '../snapping/snapEngine'
import type { SnapResult, SnapResult as SR } from '../snapping/snapEngine'
import type { CanvasElement, PatternPiece, Point } from '../types'
import { transformPieceElements } from '../utils/pieceTransforms'

let _idSeq = 0
function genId() { return `el-${++_idSeq}-${Date.now()}` }

let _pieceSeq = 0
function genPieceId() { return `piece-${++_pieceSeq}-${Date.now()}` }

function buildPiecePath(elementIds: string[], elMap: Map<string, CanvasElement>): string {
  const ordered = elementIds.map(id => elMap.get(id)).filter(Boolean) as CanvasElement[]
  if (ordered.length === 0) return ''
  const first = ordered[0]
  if (first.type !== 'line' && first.type !== 'curve') return ''
  let d = `M ${first.start.x} ${first.start.y}`
  for (const el of ordered) {
    if (el.type === 'line') d += ` L ${el.end.x} ${el.end.y}`
    else if (el.type === 'curve') d += ` C ${el.cp1.x} ${el.cp1.y} ${el.cp2.x} ${el.cp2.y} ${el.end.x} ${el.end.y}`
  }
  return d + ' Z'
}

function pieceCentroid(elementIds: string[], elMap: Map<string, CanvasElement>): Point {
  const pts: Point[] = []
  for (const id of elementIds) {
    const el = elMap.get(id)
    if (!el) continue
    if (el.type === 'line' || el.type === 'curve') pts.push(el.start, el.end)
  }
  if (pts.length === 0) return { x: 0, y: 0 }
  return { x: pts.reduce((s, p) => s + p.x, 0) / pts.length, y: pts.reduce((s, p) => s + p.y, 0) / pts.length }
}

// Returns the shared endpoint (node) at the end of each segment in order.
// For a closed piece with N segments, node[i] is seg[i].end === seg[(i+1)%N].start
function getPieceNodes(elementIds: string[], elMap: Map<string, CanvasElement>): Point[] {
  return elementIds
    .map(id => {
      const el = elMap.get(id)
      if (!el || (el.type !== 'line' && el.type !== 'curve')) return null
      return { ...el.end }
    })
    .filter((p): p is Point => p !== null)
}

// ── Seam-allowance geometry ───────────────────────────────────────────────────

function flattenPieceVertices(elementIds: string[], elMap: Map<string, CanvasElement>): { pts: Point[]; foldEdge: boolean[] } {
  const pts: Point[] = []
  const foldEdge: boolean[] = []
  for (const id of elementIds) {
    const el = elMap.get(id)
    if (!el) continue
    if (el.type === 'line') {
      pts.push({ ...el.start })
      foldEdge.push(el.isFold)
    } else if (el.type === 'curve') {
      // Sample curve (excluding endpoint — next element starts there)
      const S = 16
      for (let i = 0; i < S; i++) {
        pts.push(sampleBezier(el.start, el.cp1, el.cp2, el.end, i / S))
        foldEdge.push(false)
      }
    }
  }
  return { pts, foldEdge }
}

function lineLineIntersect(a1: Point, a2: Point, b1: Point, b2: Point): Point | null {
  const dx1 = a2.x - a1.x, dy1 = a2.y - a1.y
  const dx2 = b2.x - b1.x, dy2 = b2.y - b1.y
  const denom = dx1 * dy2 - dy1 * dx2
  if (Math.abs(denom) < 1e-10) return null
  const t = ((b1.x - a1.x) * dy2 - (b1.y - a1.y) * dx2) / denom
  return { x: a1.x + t * dx1, y: a1.y + t * dy1 }
}

function offsetPolygon(pts: Point[], foldEdge: boolean[], d: number): Point[] {
  const n = pts.length
  if (n < 3) return []
  // Shoelace signed area — positive = CW on screen (SVG Y-down)
  let area = 0
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n
    area += pts[i].x * pts[j].y - pts[j].x * pts[i].y
  }
  const sign = area > 0 ? 1 : -1 // CW on screen → right-perp is outward

  const offEdges: { a: Point; b: Point }[] = []
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n
    const dx = pts[j].x - pts[i].x, dy = pts[j].y - pts[i].y
    const len = Math.hypot(dx, dy)
    if (foldEdge[i] || len < 1e-10) {
      offEdges.push({ a: pts[i], b: pts[j] })
    } else {
      const nx = sign * dy / len, ny = sign * (-dx) / len
      offEdges.push({
        a: { x: pts[i].x + nx * d, y: pts[i].y + ny * d },
        b: { x: pts[j].x + nx * d, y: pts[j].y + ny * d },
      })
    }
  }

  return offEdges.map((_, i) => {
    const prev = (i - 1 + n) % n
    return lineLineIntersect(offEdges[prev].a, offEdges[prev].b, offEdges[i].a, offEdges[i].b)
      ?? offEdges[i].a
  })
}

function computeSeamAllowancePath(piece: PatternPiece, elMap: Map<string, CanvasElement>): string {
  const { pts, foldEdge } = flattenPieceVertices(piece.elementIds, elMap)
  if (pts.length < 3) return ''
  const off = offsetPolygon(pts, foldEdge, piece.seamAllowance)
  if (off.length < 3) return ''
  return 'M ' + off.map(p => `${p.x.toFixed(3)} ${p.y.toFixed(3)}`).join(' L ') + ' Z'
}

function distPointToSegment(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x, dy = b.y - a.y
  const lenSq = dx * dx + dy * dy
  if (lenSq < 1e-10) return Math.hypot(p.x - a.x, p.y - a.y)
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq))
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))
}

function sampleBezier(s: Point, c1: Point, c2: Point, e: Point, t: number): Point {
  const u = 1 - t
  return {
    x: u * u * u * s.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * e.x,
    y: u * u * u * s.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * e.y,
  }
}

function bezierArcLength(s: Point, c1: Point, c2: Point, e: Point, samples = 40): number {
  let len = 0
  let prev = s
  for (let i = 1; i <= samples; i++) {
    const curr = sampleBezier(s, c1, c2, e, i / samples)
    len += Math.hypot(curr.x - prev.x, curr.y - prev.y)
    prev = curr
  }
  return len
}

function rotatePoint(p: Point, center: Point, angle: number): Point {
  const cos = Math.cos(angle), sin = Math.sin(angle)
  const dx = p.x - center.x, dy = p.y - center.y
  return { x: center.x + dx * cos - dy * sin, y: center.y + dx * sin + dy * cos }
}

// Given start S, end E, and a through-point T at t=0.5, compute cubic Bezier control points.
// Derivation: B(0.5) = midpoint(S,E) + (3/4)*delta, so delta = (T - mid) * 4/3
// CP1 = S + (E-S)/3 + delta, CP2 = S + 2*(E-S)/3 + delta
export function throughPointToCP(S: Point, E: Point, T: Point): { cp1: Point; cp2: Point } {
  const mx = (S.x + E.x) / 2, my = (S.y + E.y) / 2
  const dx = (T.x - mx) * (4 / 3), dy = (T.y - my) * (4 / 3)
  return {
    cp1: { x: S.x + (E.x - S.x) / 3 + dx, y: S.y + (E.y - S.y) / 3 + dy },
    cp2: { x: S.x + 2 * (E.x - S.x) / 3 + dx, y: S.y + 2 * (E.y - S.y) / 3 + dy },
  }
}

// 1 SVG unit = 1 cm. BASE_SCALE converts cm → screen px at zoom=1.
export const BASE_SCALE = 20 // px/cm at zoom=1.0

const RULER_SIZE = 20 // px
const ZOOM_STEP = 1.15
const MIN_ZOOM = 0.25
const MAX_ZOOM = 4.0

// ── Ruler helpers ────────────────────────────────────────────────────────────

/** Returns the best labelled-tick interval (cm) for the current scale (px/cm). */
function rulerInterval(scale: number): { major: number; minor: number } {
  const niceValues = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100]
  const TARGET_MAJOR_PX = 80
  const major = niceValues.find(v => v * scale >= TARGET_MAJOR_PX) ?? 100
  return { major, minor: major / 5 }
}

interface RulerProps {
  horizontal: boolean
  length: number
  scale: number  // px/cm
  offset: number // pan offset in px
}

function Ruler({ horizontal, length, scale, offset }: RulerProps) {
  const { major, minor } = rulerInterval(scale)
  const FULL = RULER_SIZE

  // First visible minor tick
  const start = Math.floor(-offset / scale / minor) * minor - minor
  const end = start + length / scale + minor * 2

  const ticks: React.ReactNode[] = []

  for (let v = start; v <= end; v += minor) {
    const px = offset + v * scale
    if (px < 0 || px > length) continue
    const isMajor = Math.round(v / major) * major === Math.round(v * 1e6) / 1e6
    const tickLen = isMajor ? FULL * 0.6 : FULL * 0.35

    if (horizontal) {
      ticks.push(
        <line key={v} x1={px} y1={FULL - tickLen} x2={px} y2={FULL} stroke="#999" strokeWidth={0.5} />,
      )
      if (isMajor) {
        ticks.push(
          <text key={`t${v}`} x={px + 2} y={FULL - tickLen - 1}
            fontSize={8} fill="#666" dominantBaseline="auto">
            {Number(v.toFixed(4))}
          </text>,
        )
      }
    } else {
      ticks.push(
        <line key={v} x1={FULL - tickLen} y1={px} x2={FULL} y2={px} stroke="#999" strokeWidth={0.5} />,
      )
      if (isMajor) {
        ticks.push(
          <text key={`t${v}`}
            transform={`rotate(-90, ${FULL - tickLen - 1}, ${px})`}
            x={FULL - tickLen - 1} y={px - 2}
            fontSize={8} fill="#666" textAnchor="end">
            {Number(v.toFixed(4))}
          </text>,
        )
      }
    }
  }

  return (
    <svg
      style={{
        position: 'absolute',
        ...(horizontal
          ? { top: 0, left: RULER_SIZE, width: length, height: RULER_SIZE }
          : { top: RULER_SIZE, left: 0, width: RULER_SIZE, height: length }),
      }}
      className="select-none pointer-events-none"
    >
      <rect width={horizontal ? length : RULER_SIZE} height={horizontal ? RULER_SIZE : length}
        fill="#f5f5f5" />
      {ticks}
      {/* border line */}
      {horizontal
        ? <line x1={0} y1={RULER_SIZE - 0.5} x2={length} y2={RULER_SIZE - 0.5} stroke="#ccc" strokeWidth={1} />
        : <line x1={RULER_SIZE - 0.5} y1={0} x2={RULER_SIZE - 0.5} y2={length} stroke="#ccc" strokeWidth={1} />}
    </svg>
  )
}

// ── Grid ─────────────────────────────────────────────────────────────────────

interface GridProps {
  scale: number
  pan: { x: number; y: number }
  canvasW: number
  canvasH: number
}

function Grid({ scale, pan, canvasW, canvasH }: GridProps) {
  // Visible cm range (add a 1cm buffer each side)
  const x0 = Math.floor(-pan.x / scale) - 1
  const x1 = Math.ceil((canvasW - pan.x) / scale) + 1
  const y0 = Math.floor(-pan.y / scale) - 1
  const y1 = Math.ceil((canvasH - pan.y) / scale) + 1

  const minorW = 0.4 / scale   // ~0.4 screen px
  const majorW = 0.8 / scale   // ~0.8 screen px

  const minor: React.ReactNode[] = []
  const majorLines: React.ReactNode[] = []

  for (let x = x0; x <= x1; x++) {
    const isMajor = x % 5 === 0
    const line = (
      <line key={`vx${x}`} x1={x} y1={y0} x2={x} y2={y1}
        stroke={isMajor ? '#c8c8c8' : '#e4e4e4'}
        strokeWidth={isMajor ? majorW : minorW} />
    )
    ;(isMajor ? majorLines : minor).push(line)
  }
  for (let y = y0; y <= y1; y++) {
    const isMajor = y % 5 === 0
    const line = (
      <line key={`hy${y}`} x1={x0} y1={y} x2={x1} y2={y}
        stroke={isMajor ? '#c8c8c8' : '#e4e4e4'}
        strokeWidth={isMajor ? majorW : minorW} />
    )
    ;(isMajor ? majorLines : minor).push(line)
  }

  return <g>{minor}{majorLines}</g>
}

// ── Context menu item ─────────────────────────────────────────────────────────

function ContextMenuItem({
  label, onClick, danger = false,
}: { label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button
      className={`block w-full text-left px-3 py-1.5 text-xs ${danger ? 'text-red-600 hover:bg-red-50' : 'text-gray-700 hover:bg-gray-100'}`}
      onMouseDown={e => e.stopPropagation()}
      onClick={onClick}
    >
      {label}
    </button>
  )
}

// ── Dimension edit input ──────────────────────────────────────────────────────

function DimEditInput({
  id, initialValue, onApply, onCancel,
}: {
  id: string; initialValue: string
  onApply: (id: string, val: string) => void; onCancel: () => void
}) {
  const [value, setValue] = useState(initialValue)
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => { ref.current?.focus(); ref.current?.select() }, [])
  return (
    <input
      ref={ref}
      type="number" min="0.1" step="0.1"
      value={value}
      onChange={e => setValue(e.target.value)}
      onKeyDown={e => {
        if (e.key === 'Enter') { e.preventDefault(); onApply(id, value) }
        if (e.key === 'Escape') { e.preventDefault(); onCancel() }
      }}
      onBlur={() => onApply(id, value)}
      className="w-20 text-center text-xs border-2 border-blue-500 rounded-full px-2 py-1 shadow-lg bg-white font-mono outline-none"
      onClick={e => e.stopPropagation()}
    />
  )
}

// ── Canvas ───────────────────────────────────────────────────────────────────

export default function Canvas() {
  const { state, dispatch } = useEditor()
  const { zoom, pan, showGrid, elements, activeTool, pieces, selectedPieceId, showSeamAllowance } = state

  const containerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const [size, setSize] = useState({ w: 800, h: 600 })

  // Derived scale: px per cm on screen
  const scale = zoom * BASE_SCALE

  // Track pan drag
  const isPanning = useRef(false)
  const panStart = useRef({ x: 0, y: 0 })
  const panOrigin = useRef({ x: 0, y: 0 })

  // Track space-key for space+drag pan
  const spaceDown = useRef(false)

  // Chain-tracking (shared across line + curve tools)
  const chainStart = useRef<Point | null>(null)
  const currentChainIds = useRef<string[]>([])
  // Refs for stale-closure-safe access inside keyboard useEffect
  const piecesRef = useRef(pieces)
  useEffect(() => { piecesRef.current = pieces }, [pieces])
  const selectedPieceIdRef = useRef(selectedPieceId)
  useEffect(() => { selectedPieceIdRef.current = selectedPieceId }, [selectedPieceId])
  const measurementsRef = useRef(state.measurements)
  useEffect(() => { measurementsRef.current = state.measurements }, [state.measurements])

  // Save / load helpers
  const savePattern = useCallback(() => {
    const data = {
      version: 1,
      elements: elementsRef.current,
      pieces: piecesRef.current,
      measurements: measurementsRef.current,
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'pattern.psnap'
    a.click()
    URL.revokeObjectURL(url)
  }, [])

  const loadPattern = useCallback((json: string) => {
    try {
      const data = JSON.parse(json)
      if (!data.elements || !Array.isArray(data.elements)) throw new Error('Invalid .psnap file')
      dispatch({
        type: 'LOAD_STATE',
        elements: data.elements,
        pieces: data.pieces ?? [],
        measurements: data.measurements ?? {},
        connections: data.connections ?? [],
        instructions: data.instructions ?? null,
        lastFeatures: data.lastFeatures ?? null,
        lastMeasurements: data.lastMeasurements ?? null,
      })
    } catch {
      alert('Failed to load pattern file.')
    }
  }, [dispatch])

  const handleFileDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const file = Array.from(e.dataTransfer.files).find(f => f.name.endsWith('.psnap'))
    if (!file) return
    const hasContent = elementsRef.current.length > 0 || piecesRef.current.length > 0
    if (hasContent && !window.confirm('Loading a file will replace the current pattern. Continue?')) return
    file.text().then(loadPattern)
  }, [loadPattern])

  // Dimension label inline editor
  const [editingDim, setEditingDim] = useState<{ id: string; value: string } | null>(null)

  // Seam-allowance dialog
  const [seamDialog, setSeamDialog] = useState<{ pieceId: string; amount: string } | null>(null)
  const applySeamAllowance = () => {
    if (!seamDialog) return
    const amount = parseFloat(seamDialog.amount)
    if (!isNaN(amount) && amount >= 0) {
      const piece = state.pieces.find(p => p.id === seamDialog.pieceId)
      if (piece) dispatch({ type: 'UPDATE_PIECE', piece: { ...piece, seamAllowance: amount } })
    }
    setSeamDialog(null)
  }

  const applyDimension = useCallback((id: string, valueStr: string) => {
    setEditingDim(null)
    const newLen = parseFloat(valueStr)
    if (isNaN(newLen) || newLen <= 0) return
    const el = elementsRef.current.find(e => e.id === id)
    if (!el) return
    if (el.type === 'line') {
      const dx = el.end.x - el.start.x, dy = el.end.y - el.start.y
      const oldLen = Math.hypot(dx, dy)
      if (oldLen < 0.001) return
      const ratio = newLen / oldLen
      dispatch({ type: 'UPDATE_ELEMENT', element: { ...el, end: { x: el.start.x + dx * ratio, y: el.start.y + dy * ratio } } })
    } else if (el.type === 'curve') {
      const oldLen = bezierArcLength(el.start, el.cp1, el.cp2, el.end)
      if (oldLen < 0.001) return
      const ratio = newLen / oldLen
      dispatch({ type: 'UPDATE_ELEMENT', element: { ...el,
        cp1: { x: el.start.x + (el.cp1.x - el.start.x) * ratio, y: el.start.y + (el.cp1.y - el.start.y) * ratio },
        cp2: { x: el.start.x + (el.cp2.x - el.start.x) * ratio, y: el.start.y + (el.cp2.y - el.start.y) * ratio },
        end: { x: el.start.x + (el.end.x - el.start.x) * ratio, y: el.start.y + (el.end.y - el.start.y) * ratio },
      } })
    }
  }, [dispatch])

  // Piece transform helpers
  const flipPiece = useCallback((pieceId: string, op: 'flipH' | 'flipV') => {
    const piece = piecesRef.current.find(p => p.id === pieceId)
    if (!piece) return
    const updated = transformPieceElements(piece, elementsRef.current, op)
    dispatch({ type: 'BATCH_UPDATE_ELEMENTS', elements: updated })
  }, [dispatch])

  const rotatePiece = useCallback((pieceId: string, degrees: number) => {
    const piece = piecesRef.current.find(p => p.id === pieceId)
    if (!piece) return
    const updated = transformPieceElements(piece, elementsRef.current, 'rotate', degrees)
    dispatch({ type: 'BATCH_UPDATE_ELEMENTS', elements: updated })
  }, [dispatch])

  // Line-tool state
  const lineStart = useRef<Point | null>(null)
  const shiftDown = useRef(false)
  const [cursorPoint, setCursorPoint] = useState<Point | null>(null)
  const [snapInfo, setSnapInfo] = useState<SnapResult | null>(null)

  // Curve-tool state: idle → placing-end → shaping → (back to placing-end for chain)
  // idle: click sets start → placing-end
  // placing-end: click sets end → shaping
  // shaping: cursor = through-point; click commits curve → back to placing-end (auto-chain)
  type CurvePhase = 'idle' | 'placing-end' | 'shaping'
  const curvePhase = useRef<CurvePhase>('idle')
  const curveStart = useRef<Point | null>(null)
  const curveEnd = useRef<Point | null>(null)

  // Ref to avoid stale closures in keyboard handler
  const selectedIdsRef = useRef(state.selectedIds)
  useEffect(() => { selectedIdsRef.current = state.selectedIds }, [state.selectedIds])
  const elementsRef = useRef(elements)
  useEffect(() => { elementsRef.current = elements }, [elements])

  // Rotation state
  const isRotating = useRef(false)
  const rotateCenter = useRef<Point | null>(null)
  const rotateStartAngle = useRef(0)
  const rotateSnapshot = useRef<Map<string, CanvasElement>>(new Map())

  // Grain-line tool state
  const grainLineStart = useRef<Point | null>(null)

  // Piece drag-to-move
  const isDraggingPiece = useRef(false)
  const pieceDragStart = useRef<{ cmX: number; cmY: number } | null>(null)
  const pieceElementsSnapshot = useRef<Map<string, CanvasElement>>(new Map())

  // Node drag — reshape a closed piece by moving a shared endpoint between two segments
  const isDraggingNode = useRef(false)
  const nodeDragStart = useRef<{ cmX: number; cmY: number } | null>(null)
  const nodeDragPieceId = useRef<string | null>(null)
  const nodeDragNodeIdx = useRef<number>(-1)
  // Snapshot of the two segments that share the dragged node
  const nodeDragSnapshot = useRef<Map<string, CanvasElement>>(new Map())

  // Context menu
  type ContextMenuState =
    | { type: 'piece'; id: string; x: number; y: number }
    | { type: 'element'; id: string; x: number; y: number }
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)

  // Select-tool state (all screen coords are SVG-element-relative, not clientX/Y)
  const selectDragStart = useRef<{ screenX: number; screenY: number; cmX: number; cmY: number } | null>(null)
  const isDraggingElements = useRef(false)
  const draggedElementsOrigin = useRef<Map<string, { x: number; y: number }>>(new Map())
  const [boxSelect, setBoxSelect] = useState<{ x: number; y: number; w: number; h: number } | null>(null)

  // Endpoint drag — drag just the start or end of a selected free segment
  const isDraggingEndpoint = useRef(false)
  const endpointDragId = useRef<string | null>(null)
  const endpointDragWhich = useRef<'start' | 'end' | null>(null)

  // ── Resize observer ────────────────────────────────────────────────────────
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      setSize({ w: width, h: height })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // ── Canvas dimensions (excluding rulers) ──────────────────────────────────
  const canvasW = size.w - RULER_SIZE
  const canvasH = size.h - RULER_SIZE

  // ── Keyboard handlers ─────────────────────────────────────────────────────
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      // Ignore when typing in inputs
      if ((e.target as HTMLElement).tagName === 'INPUT' || (e.target as HTMLElement).tagName === 'TEXTAREA') return

      if (e.key === 'Shift') shiftDown.current = true

      if (e.key === ' ') {
        e.preventDefault()
        spaceDown.current = true
      }

      if (e.key === 'Escape') {
        setContextMenu(null)
        lineStart.current = null
        chainStart.current = null
        currentChainIds.current = []
        curvePhase.current = 'idle'
        curveStart.current = null
        curveEnd.current = null
        grainLineStart.current = null
        setCursorPoint(null)
        setSnapInfo(null)
        dispatch({ type: 'DESELECT_ALL' })
      }

      if (e.key === 'Enter') {
        // Close outline: need ≥ 2 chain elements so adding closing segment gives ≥ 3 sides
        const cs = chainStart.current
        const lastPt = lineStart.current
        if (cs && lastPt && currentChainIds.current.length >= 2) {
          const closeDist = Math.hypot(lastPt.x - cs.x, lastPt.y - cs.y)
          let closingId: string | undefined
          if (closeDist > 0.1) {
            closingId = genId()
            dispatch({ type: 'ADD_ELEMENT', element: { id: closingId, type: 'line', start: { ...lastPt }, end: { ...cs }, isFold: false } })
          }
          const allIds = closingId ? [...currentChainIds.current, closingId] : [...currentChainIds.current]
          dispatch({
            type: 'ADD_PIECE',
            piece: { id: genPieceId(), name: `Piece ${piecesRef.current.length + 1}`, elementIds: allIds, cutQty: 2, onFold: false, seamAllowance: 1.5, closed: true },
          })
          chainStart.current = null
          currentChainIds.current = []
          lineStart.current = null
          setCursorPoint(null)
          setSnapInfo(null)
        }
      }

      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedIdsRef.current.length > 0) {
          // If any selected element belongs to a piece, revert the whole piece to standalone segments
          const pieceSideId = selectedIdsRef.current.find(id => {
            const el = elementsRef.current.find(e => e.id === id)
            return el && 'pieceId' in el && (el as any).pieceId
          })
          if (pieceSideId) {
            const el = elementsRef.current.find(e => e.id === pieceSideId) as any
            dispatch({ type: 'REMOVE_SIDE_FROM_PIECE', pieceId: el.pieceId, elementId: pieceSideId })
          } else {
            dispatch({ type: 'DELETE_ELEMENTS', ids: selectedIdsRef.current })
          }
        } else if (selectedPieceIdRef.current) {
          // Delete the whole piece — the reducer removes its outline elements,
          // interior markings and connections in one undoable step
          dispatch({ type: 'DELETE_PIECE', id: selectedPieceIdRef.current })
        }
      }

      if (e.ctrlKey && e.key === 'g') {
        e.preventDefault()
        dispatch({ type: 'TOGGLE_GRID' })
      }

      if (e.ctrlKey && e.key === '0') {
        e.preventDefault()
        fitToScreen()
      }

      if (e.ctrlKey && (e.key === '=' || e.key === '+')) {
        e.preventDefault()
        zoomAt(canvasW / 2, canvasH / 2, ZOOM_STEP)
      }

      if (e.ctrlKey && e.key === '-') {
        e.preventDefault()
        zoomAt(canvasW / 2, canvasH / 2, 1 / ZOOM_STEP)
      }

      if (e.ctrlKey && !e.shiftKey && e.key.toLowerCase() === 's') {
        e.preventDefault()
        savePattern()
      }

      if (e.ctrlKey && !e.shiftKey && e.key.toLowerCase() === 'n') {
        e.preventDefault()
        // Start a new piece: switch to line tool and reset chain state
        lineStart.current = null
        chainStart.current = null
        currentChainIds.current = []
        dispatch({ type: 'SET_ACTIVE_TOOL', tool: 'line' })
      }

      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 's') {
        e.preventDefault()
        dispatch({ type: 'TOGGLE_SNAP' })
      }

      if (e.ctrlKey && e.key === 'z') {
        e.preventDefault()
        dispatch({ type: 'UNDO' })
      }

      if (e.ctrlKey && (e.key === 'y' || (e.shiftKey && e.key === 'z'))) {
        e.preventDefault()
        dispatch({ type: 'REDO' })
      }

      if (!e.ctrlKey && !e.shiftKey && !e.altKey) {
        const switchTool = (t: import('../types').ToolType) => {
          lineStart.current = null
          chainStart.current = null
          currentChainIds.current = []
          curvePhase.current = 'idle'; curveStart.current = null; curveEnd.current = null
          grainLineStart.current = null
          setCursorPoint(null); setSnapInfo(null)
          dispatch({ type: 'SET_ACTIVE_TOOL', tool: t })
        }
        switch (e.key.toLowerCase()) {
          case 's': switchTool('select'); break
          case 'l': switchTool('line'); break
          case 'c': switchTool('curve'); break
          case 'a':
            if (selectedPieceIdRef.current) {
              const p = piecesRef.current.find(pp => pp.id === selectedPieceIdRef.current)
              setSeamDialog({ pieceId: selectedPieceIdRef.current, amount: String(p?.seamAllowance ?? 1.5) })
            } else {
              switchTool('seam-allowance')
            }
            break
          case 'g': switchTool('grain-line'); break
          case 'n': switchTool('notch'); break
          case 'p': switchTool('point'); break
          case 'e': switchTool('eraser'); break
        }
      }
    }
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key === 'Shift') shiftDown.current = false
      if (e.key === ' ') {
        spaceDown.current = false
        if (isPanning.current) stopPan()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoom, pan, canvasW, canvasH, dispatch])

  // ── Zoom helpers ──────────────────────────────────────────────────────────
  const zoomAt = useCallback((cx: number, cy: number, factor: number) => {
    const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom * factor))
    const newScale = newZoom * BASE_SCALE
    const oldScale = zoom * BASE_SCALE
    const newPanX = cx - (cx - pan.x) * (newScale / oldScale)
    const newPanY = cy - (cy - pan.y) * (newScale / oldScale)
    dispatch({ type: 'SET_ZOOM', zoom: newZoom })
    dispatch({ type: 'SET_PAN', pan: { x: newPanX, y: newPanY } })
  }, [zoom, pan, dispatch])

  const fitToScreen = useCallback(() => {
    if (elements.length === 0) {
      // Default view: 80cm × 100cm workspace centred
      const fitZoom = Math.min(canvasW / (80 * BASE_SCALE), canvasH / (100 * BASE_SCALE))
      const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, fitZoom))
      dispatch({ type: 'SET_ZOOM', zoom: newZoom })
      dispatch({ type: 'SET_PAN', pan: { x: canvasW / 2 - 40 * newZoom * BASE_SCALE, y: canvasH / 2 - 50 * newZoom * BASE_SCALE } })
      return
    }
    // Compute bounding box of all elements
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const el of elements) {
      const pts = el.type === 'line' ? [el.start, el.end]
        : el.type === 'curve' ? [el.start, el.cp1, el.cp2, el.end]
        : el.type === 'grain-line' ? [el.start, el.end]
        : [el.position]
      for (const p of pts) {
        minX = Math.min(minX, p.x); minY = Math.min(minY, p.y)
        maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y)
      }
    }
    const pad = 5 // cm padding
    const bw = (maxX - minX + pad * 2) * BASE_SCALE
    const bh = (maxY - minY + pad * 2) * BASE_SCALE
    const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.min(canvasW / bw, canvasH / bh)))
    dispatch({ type: 'SET_ZOOM', zoom: newZoom })
    dispatch({ type: 'SET_PAN', pan: {
      x: -((minX - pad) * newZoom * BASE_SCALE) + (canvasW - (maxX - minX + pad * 2) * newZoom * BASE_SCALE) / 2,
      y: -((minY - pad) * newZoom * BASE_SCALE) + (canvasH - (maxY - minY + pad * 2) * newZoom * BASE_SCALE) / 2,
    } })
  }, [elements, canvasW, canvasH, dispatch])

  // ── Wheel zoom ────────────────────────────────────────────────────────────
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const handleWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = svg.getBoundingClientRect()
      const cx = e.clientX - rect.left
      const cy = e.clientY - rect.top
      const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP
      zoomAt(cx, cy, factor)
    }
    svg.addEventListener('wheel', handleWheel, { passive: false })
    return () => svg.removeEventListener('wheel', handleWheel)
  }, [zoomAt])

  // ── Pan helpers ───────────────────────────────────────────────────────────
  const startPan = (screenX: number, screenY: number) => {
    isPanning.current = true
    panStart.current = { x: screenX, y: screenY }
    panOrigin.current = { x: pan.x, y: pan.y }
  }
  const movePan = useCallback((screenX: number, screenY: number) => {
    if (!isPanning.current) return
    const dx = screenX - panStart.current.x
    const dy = screenY - panStart.current.y
    dispatch({ type: 'SET_PAN', pan: { x: panOrigin.current.x + dx, y: panOrigin.current.y + dy } })
  }, [dispatch])
  const stopPan = () => { isPanning.current = false }

  // ── Snap helper ───────────────────────────────────────────────────────────
  const getSnap = useCallback((clientX: number, clientY: number): SR => {
    const rect = svgRef.current!.getBoundingClientRect()
    const sx = clientX - rect.left
    const sy = clientY - rect.top
    return snap(sx, sy, pan, scale, elements, state.snapEnabled, shiftDown.current, lineStart.current ?? undefined)
  }, [pan, scale, elements, state.snapEnabled])

  // ── Hit testing ──────────────────────────────────────────────────────────
  const HIT_PX = 8 // screen pixels
  const hitTest = useCallback((clickPt: Point): string | null => {
    const HIT_CM = HIT_PX / scale
    for (let i = elements.length - 1; i >= 0; i--) {
      const el = elements[i]
      if (el.type === 'line') {
        if (distPointToSegment(clickPt, el.start, el.end) <= HIT_CM) return el.id
      } else if (el.type === 'curve') {
        // Sample bezier
        for (let t = 0; t <= 1; t += 0.05) {
          const p = sampleBezier(el.start, el.cp1, el.cp2, el.end, t)
          if (Math.hypot(clickPt.x - p.x, clickPt.y - p.y) <= HIT_CM) return el.id
        }
      } else if (el.type === 'grain-line') {
        if (distPointToSegment(clickPt, el.start, el.end) <= HIT_CM) return el.id
      } else if (el.type === 'notch' || el.type === 'anchor-point') {
        const pos = el.type === 'notch' ? el.position : el.position
        if (Math.hypot(clickPt.x - pos.x, clickPt.y - pos.y) <= HIT_CM) return el.id
      }
    }
    return null
  }, [elements, scale])

  // ── Mouse events on SVG ───────────────────────────────────────────────────
  const handleMouseDown = (e: React.MouseEvent<SVGSVGElement>) => {
    const isMiddle = e.button === 1
    const isSpacePan = spaceDown.current && e.button === 0

    if (isMiddle || isSpacePan) {
      e.preventDefault()
      startPan(e.clientX, e.clientY)
      return
    }

    if (e.button !== 0) return

    // ── Line tool ──────────────────────────────────────────────────────────
    if (activeTool === 'line') {
      const sr = getSnap(e.clientX, e.clientY)
      const pt = sr.point

      if (!lineStart.current) {
        lineStart.current = pt
        if (!chainStart.current) chainStart.current = pt
        setCursorPoint(pt)
      } else {
        const dx = pt.x - lineStart.current.x
        const dy = pt.y - lineStart.current.y
        if (Math.hypot(dx, dy) > 0.01) {
          const newId = genId()
          dispatch({
            type: 'ADD_ELEMENT',
            element: { id: newId, type: 'line', start: { ...lineStart.current }, end: pt, isFold: false },
          })
          const cs = chainStart.current
          const closeDist = cs ? Math.hypot(pt.x - cs.x, pt.y - cs.y) : Infinity
          if (cs && closeDist < 0.1 && currentChainIds.current.length >= 2) {
            // Outline closed → create piece
            dispatch({
              type: 'ADD_PIECE',
              piece: { id: genPieceId(), name: `Piece ${pieces.length + 1}`, elementIds: [...currentChainIds.current, newId], cutQty: 2, onFold: false, seamAllowance: 1.5, closed: true },
            })
            chainStart.current = null
            currentChainIds.current = []
            lineStart.current = null
            setCursorPoint(null)
            setSnapInfo(null)
          } else {
            currentChainIds.current.push(newId)
            lineStart.current = pt
          }
        }
      }
    }

    // ── Curve tool — three-click arc control ─────────────────────────────
    // Phase idle → placing-end: first click sets start point
    if (activeTool === 'curve' && curvePhase.current === 'idle') {
      const sr = getSnap(e.clientX, e.clientY)
      curveStart.current = sr.point
      if (!chainStart.current) chainStart.current = sr.point
      curvePhase.current = 'placing-end'
      setCursorPoint(sr.point)
    // Phase placing-end → shaping: second click sets end point
    } else if (activeTool === 'curve' && curvePhase.current === 'placing-end') {
      const sr = getSnap(e.clientX, e.clientY)
      const end = sr.point
      const start = curveStart.current!
      if (Math.hypot(end.x - start.x, end.y - start.y) > 0.01) {
        curveEnd.current = end
        curvePhase.current = 'shaping'
        setCursorPoint(end)
      }
    // Phase shaping → commit: third click — cursor is the through-point
    } else if (activeTool === 'curve' && curvePhase.current === 'shaping') {
      const sr = getSnap(e.clientX, e.clientY)
      const throughPt = sr.point
      const start = curveStart.current!
      const end = curveEnd.current!
      const { cp1, cp2 } = throughPointToCP(start, end, throughPt)
      const newId = genId()
      dispatch({ type: 'ADD_ELEMENT', element: { id: newId, type: 'curve', start, cp1, cp2, end } })
      const cs = chainStart.current
      const closeDist = cs ? Math.hypot(end.x - cs.x, end.y - cs.y) : Infinity
      if (cs && closeDist < 0.1 && currentChainIds.current.length >= 2) {
        dispatch({
          type: 'ADD_PIECE',
          piece: { id: genPieceId(), name: `Piece ${pieces.length + 1}`, elementIds: [...currentChainIds.current, newId], cutQty: 2, onFold: false, seamAllowance: 1.5, closed: true },
        })
        chainStart.current = null
        currentChainIds.current = []
        curvePhase.current = 'idle'
        curveStart.current = null
        curveEnd.current = null
      } else {
        currentChainIds.current.push(newId)
        // Auto-chain: next segment starts from current end
        curveStart.current = end
        curveEnd.current = null
        lineStart.current = end  // keep Enter-to-close in sync
        curvePhase.current = 'placing-end'
      }
      setCursorPoint(null)
      setSnapInfo(null)
    }

    // ── Grain-line tool ───────────────────────────────────────────────────
    if (activeTool === 'grain-line') {
      const sr = getSnap(e.clientX, e.clientY)
      grainLineStart.current = sr.point
      setCursorPoint(sr.point)
      setSnapInfo(sr)
    }

    // ── Notch tool ────────────────────────────────────────────────────────
    if (activeTool === 'notch') {
      const rect = svgRef.current!.getBoundingClientRect()
      const sx = e.clientX - rect.left
      const sy = e.clientY - rect.top
      const cmPt = screenToCm(sx, sy, pan, scale)
      const HIT_CM = HIT_PX / scale
      let bestDist = Infinity
      let bestEl: typeof elements[number] | null = null
      let bestT = 0
      for (const el of elements) {
        if (el.type === 'line') {
          const dist = distPointToSegment(cmPt, el.start, el.end)
          if (dist < bestDist && dist <= HIT_CM * 2) {
            bestDist = dist
            bestEl = el
            const dx = el.end.x - el.start.x, dy = el.end.y - el.start.y
            const lenSq = dx * dx + dy * dy
            bestT = lenSq < 1e-10 ? 0 : Math.max(0, Math.min(1, ((cmPt.x - el.start.x) * dx + (cmPt.y - el.start.y) * dy) / lenSq))
          }
        } else if (el.type === 'curve') {
          for (let i = 0; i <= 20; i++) {
            const t = i / 20
            const p = sampleBezier(el.start, el.cp1, el.cp2, el.end, t)
            const dist = Math.hypot(cmPt.x - p.x, cmPt.y - p.y)
            if (dist < bestDist && dist <= HIT_CM * 2) {
              bestDist = dist
              bestEl = el
              bestT = t
            }
          }
        }
      }
      if (bestEl) {
        let pos: Point, angleDeg: number
        if (bestEl.type === 'line') {
          const t = bestT
          pos = {
            x: bestEl.start.x + t * (bestEl.end.x - bestEl.start.x),
            y: bestEl.start.y + t * (bestEl.end.y - bestEl.start.y),
          }
          const dx = bestEl.end.x - bestEl.start.x, dy = bestEl.end.y - bestEl.start.y
          angleDeg = Math.atan2(dy, dx) * (180 / Math.PI) + 90
        } else if (bestEl.type === 'curve') {
          const t = bestT
          pos = sampleBezier(bestEl.start, bestEl.cp1, bestEl.cp2, bestEl.end, t)
          // Tangent via finite difference
          const dt = 0.01
          const t2 = Math.min(1, t + dt)
          const p2 = sampleBezier(bestEl.start, bestEl.cp1, bestEl.cp2, bestEl.end, t2)
          angleDeg = Math.atan2(p2.y - pos.y, p2.x - pos.x) * (180 / Math.PI) + 90
        } else {
          return
        }
        const notchPieceId = 'pieceId' in bestEl ? (bestEl as any).pieceId as string | undefined : undefined
        dispatch({
          type: 'ADD_ELEMENT',
          element: { id: genId(), type: 'notch', position: pos, angle: angleDeg, pieceId: notchPieceId },
        })
      }
    }

    // ── Point tool — place anchor point as snap target ────────────────────
    if (activeTool === 'point') {
      const sr = getSnap(e.clientX, e.clientY)
      dispatch({ type: 'ADD_ELEMENT', element: { id: genId(), type: 'anchor-point', position: sr.point } })
    }

    // ── Eraser tool — click element to delete it ──────────────────────────
    if (activeTool === 'eraser') {
      const rect = svgRef.current!.getBoundingClientRect()
      const cmPt = screenToCm(e.clientX - rect.left, e.clientY - rect.top, pan, scale)
      const hitId = hitTest(cmPt)
      if (hitId) {
        dispatch({ type: 'DELETE_ELEMENTS', ids: [hitId] })
      }
    }

    // ── Select tool ───────────────────────────────────────────────────────
    if (activeTool === 'select') {
      const rect = svgRef.current!.getBoundingClientRect()
      const sx = e.clientX - rect.left
      const sy = e.clientY - rect.top
      const cmPt = screenToCm(sx, sy, pan, scale)

      const hitId = hitTest(cmPt)

      if (hitId) {
        // If this element belongs to a closed piece, redirect to a whole-piece drag
        const hitEl = elements.find(el => el.id === hitId)
        const hitPieceId = hitEl && 'pieceId' in hitEl ? (hitEl as any).pieceId as string | undefined : undefined
        const hitPiece = hitPieceId ? pieces.find(p => p.id === hitPieceId && p.closed) : undefined

        if (hitPiece) {
          dispatch({ type: 'SELECT_PIECE', id: hitPiece.id })
          isDraggingPiece.current = true
          pieceDragStart.current = { cmX: cmPt.x, cmY: cmPt.y }
          const pieceSnap = new Map<string, CanvasElement>()
          for (const id of hitPiece.elementIds) {
            const el = elements.find(el => el.id === id)
            if (el) pieceSnap.set(id, el)
          }
          pieceElementsSnapshot.current = pieceSnap
        } else {
          // Free element: select it (add to selection if Shift held)
          if (e.shiftKey) {
            const already = state.selectedIds.includes(hitId)
            dispatch({ type: 'SET_SELECTED', ids: already
              ? state.selectedIds.filter(id => id !== hitId)
              : [...state.selectedIds, hitId]
            })
          } else {
            if (!state.selectedIds.includes(hitId)) {
              dispatch({ type: 'SET_SELECTED', ids: [hitId] })
            }
          }
          // Begin drag-to-move (use SVG-relative coords for consistency)
          isDraggingElements.current = true
          selectDragStart.current = { screenX: sx, screenY: sy, cmX: cmPt.x, cmY: cmPt.y }
          // Snapshot origins of all currently selected (including just-selected)
          const idsToMove = e.shiftKey ? state.selectedIds : [hitId]
          draggedElementsOrigin.current = new Map(
            elements
              .filter(el => idsToMove.includes(el.id))
              .map(el => {
                const cx = (el.type === 'notch' || el.type === 'anchor-point') ? el.position.x : (el as any).start.x
                const cy = (el.type === 'notch' || el.type === 'anchor-point') ? el.position.y : (el as any).start.y
                return [el.id, { x: cx, y: cy }]
              })
          )
        }
      } else {
        // Click on empty space: start box-select
        dispatch({ type: 'DESELECT_ALL' })
        // Store SVG-relative screen coordinates (not clientX/Y)
        selectDragStart.current = { screenX: sx, screenY: sy, cmX: cmPt.x, cmY: cmPt.y }
        isDraggingElements.current = false
        setBoxSelect({ x: sx, y: sy, w: 0, h: 0 })
      }
    }
  }

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (isRotating.current && rotateCenter.current) {
      const rect = svgRef.current!.getBoundingClientRect()
      const cmX = (e.clientX - rect.left - pan.x) / scale
      const cmY = (e.clientY - rect.top  - pan.y) / scale
      const delta = Math.atan2(cmY - rotateCenter.current.y, cmX - rotateCenter.current.x) - rotateStartAngle.current
      const center = rotateCenter.current
      const rotated: CanvasElement[] = []
      for (const [, origEl] of rotateSnapshot.current) {
        if (origEl.type === 'line') {
          rotated.push({ ...origEl, start: rotatePoint(origEl.start, center, delta), end: rotatePoint(origEl.end, center, delta) })
        } else if (origEl.type === 'curve') {
          rotated.push({ ...origEl, start: rotatePoint(origEl.start, center, delta), cp1: rotatePoint(origEl.cp1, center, delta), cp2: rotatePoint(origEl.cp2, center, delta), end: rotatePoint(origEl.end, center, delta) })
        } else if (origEl.type === 'grain-line') {
          rotated.push({ ...origEl, start: rotatePoint(origEl.start, center, delta), end: rotatePoint(origEl.end, center, delta) })
        } else {
          rotated.push({ ...origEl, position: rotatePoint((origEl as any).position, center, delta) } as CanvasElement)
        }
      }
      dispatch({ type: 'LIVE_UPDATE_ELEMENTS', elements: rotated })
      return
    }

    if (isPanning.current) {
      movePan(e.clientX, e.clientY)
      return
    }

    // Node drag — reshape a closed piece by moving a shared endpoint
    if (isDraggingNode.current && nodeDragStart.current) {
      const rect = svgRef.current!.getBoundingClientRect()
      const cmPt = screenToCm(e.clientX - rect.left, e.clientY - rect.top, pan, scale)
      const dcm = { x: cmPt.x - nodeDragStart.current.cmX, y: cmPt.y - nodeDragStart.current.cmY }
      const piece = piecesRef.current.find(p => p.id === nodeDragPieceId.current)
      if (piece) {
        const n = piece.elementIds.length
        const nodeIdx = nodeDragNodeIdx.current
        // prevEl owns the .end that is this node; nextEl owns the .start
        const prevId = piece.elementIds[nodeIdx]
        const nextId = piece.elementIds[(nodeIdx + 1) % n]
        const prevOrig = nodeDragSnapshot.current.get(prevId)
        const nextOrig = nodeDragSnapshot.current.get(nextId)
        const reshaped: CanvasElement[] = []
        if (prevOrig && (prevOrig.type === 'line' || prevOrig.type === 'curve')) {
          reshaped.push({ ...prevOrig, end: { x: prevOrig.end.x + dcm.x, y: prevOrig.end.y + dcm.y } } as CanvasElement)
        }
        if (nextOrig && (nextOrig.type === 'line' || nextOrig.type === 'curve')) {
          reshaped.push({ ...nextOrig, start: { x: nextOrig.start.x + dcm.x, y: nextOrig.start.y + dcm.y } } as CanvasElement)
        }
        if (reshaped.length > 0) dispatch({ type: 'LIVE_UPDATE_ELEMENTS', elements: reshaped })
      }
      return
    }

    // Piece drag-to-move (piece fill mousedown sets isDraggingPiece and stopPropagation,
    // so selectDragStart is null during a piece drag — handle it separately)
    if (isDraggingPiece.current && pieceDragStart.current) {
      const rect = svgRef.current!.getBoundingClientRect()
      const cmPt = screenToCm(e.clientX - rect.left, e.clientY - rect.top, pan, scale)
      const dcm = { x: cmPt.x - pieceDragStart.current.cmX, y: cmPt.y - pieceDragStart.current.cmY }
      const moved: CanvasElement[] = []
      for (const [, origEl] of pieceElementsSnapshot.current) {
        let updated: CanvasElement
        if (origEl.type === 'line') {
          updated = { ...origEl,
            start: { x: origEl.start.x + dcm.x, y: origEl.start.y + dcm.y },
            end:   { x: origEl.end.x   + dcm.x, y: origEl.end.y   + dcm.y },
          }
        } else if (origEl.type === 'curve') {
          updated = { ...origEl,
            start: { x: origEl.start.x + dcm.x, y: origEl.start.y + dcm.y },
            cp1:   { x: origEl.cp1.x   + dcm.x, y: origEl.cp1.y   + dcm.y },
            cp2:   { x: origEl.cp2.x   + dcm.x, y: origEl.cp2.y   + dcm.y },
            end:   { x: origEl.end.x   + dcm.x, y: origEl.end.y   + dcm.y },
          }
        } else if (origEl.type === 'grain-line') {
          updated = { ...origEl,
            start: { x: origEl.start.x + dcm.x, y: origEl.start.y + dcm.y },
            end:   { x: origEl.end.x   + dcm.x, y: origEl.end.y   + dcm.y },
          }
        } else {
          updated = { ...origEl, position: { x: (origEl as any).position.x + dcm.x, y: (origEl as any).position.y + dcm.y } }
        }
        moved.push(updated)
      }
      dispatch({ type: 'LIVE_UPDATE_ELEMENTS', elements: moved })
      return
    }

    // Endpoint drag — move just the start or end point of a selected segment
    if (isDraggingEndpoint.current && endpointDragId.current) {
      const sr = getSnap(e.clientX, e.clientY)
      const pt = sr.point
      const el = elementsRef.current.find(e => e.id === endpointDragId.current!)
      if (el && (el.type === 'line' || el.type === 'curve')) {
        let updated: CanvasElement
        if (endpointDragWhich.current === 'start') {
          if (el.type === 'line') {
            updated = { ...el, start: pt }
          } else {
            const dx = pt.x - el.start.x, dy = pt.y - el.start.y
            updated = { ...el, start: pt, cp1: { x: el.cp1.x + dx, y: el.cp1.y + dy } }
          }
        } else {
          if (el.type === 'line') {
            updated = { ...el, end: pt }
          } else {
            const dx = pt.x - el.end.x, dy = pt.y - el.end.y
            updated = { ...el, end: pt, cp2: { x: el.cp2.x + dx, y: el.cp2.y + dy } }
          }
        }
        dispatch({ type: 'LIVE_UPDATE_ELEMENTS', elements: [updated] })
        setSnapInfo(sr)
        setCursorPoint(pt)
      }
      return
    }

    if (activeTool === 'line') {
      const sr = getSnap(e.clientX, e.clientY)
      setCursorPoint(sr.point)
      setSnapInfo(sr)
    } else if (activeTool === 'curve') {
      const sr = getSnap(e.clientX, e.clientY)
      setCursorPoint(sr.point)
      setSnapInfo(sr)
    } else if (activeTool === 'select' && selectDragStart.current) {
      const rect = svgRef.current!.getBoundingClientRect()
      const sx = e.clientX - rect.left
      const sy = e.clientY - rect.top
      const cmPt = screenToCm(sx, sy, pan, scale)

      if (isDraggingElements.current && selectDragStart.current) {
        // Move all selected elements
        const dcm = {
          x: cmPt.x - selectDragStart.current.cmX,
          y: cmPt.y - selectDragStart.current.cmY,
        }
        const moved: CanvasElement[] = []
        for (const el of elements) {
          if (!state.selectedIds.includes(el.id)) continue
          const origin = draggedElementsOrigin.current.get(el.id)
          if (!origin) continue
          const dx = dcm.x
          const dy = dcm.y
          let updated: typeof el
          if (el.type === 'line') {
            const ox = el.start.x - origin.x
            const oy = el.start.y - origin.y
            updated = { ...el,
              start: { x: origin.x + dx, y: origin.y + dy },
              end: { x: el.end.x - ox + dx, y: el.end.y - oy + dy },
            }
          } else if (el.type === 'curve') {
            const ox = el.start.x - origin.x
            const oy = el.start.y - origin.y
            updated = { ...el,
              start: { x: origin.x + dx, y: origin.y + dy },
              cp1: { x: el.cp1.x - ox + dx, y: el.cp1.y - oy + dy },
              cp2: { x: el.cp2.x - ox + dx, y: el.cp2.y - oy + dy },
              end: { x: el.end.x - ox + dx, y: el.end.y - oy + dy },
            }
          } else if (el.type === 'grain-line') {
            const ox = el.start.x - origin.x
            const oy = el.start.y - origin.y
            updated = { ...el,
              start: { x: origin.x + dx, y: origin.y + dy },
              end: { x: el.end.x - ox + dx, y: el.end.y - oy + dy },
            }
          } else {
            updated = { ...el, position: { x: origin.x + dx, y: origin.y + dy } }
          }
          moved.push(updated)
        }
        if (moved.length > 0) dispatch({ type: 'LIVE_UPDATE_ELEMENTS', elements: moved })
      } else {
        // Update box-select rect (screen coords)
        const ds = selectDragStart.current
        const bx = Math.min(ds.screenX, sx)
        const by = Math.min(ds.screenY, sy)
        setBoxSelect({ x: bx, y: by, w: Math.abs(sx - ds.screenX), h: Math.abs(sy - ds.screenY) })
      }
    } else {
      const rect = svgRef.current?.getBoundingClientRect()
      if (rect) {
        const p = screenToCm(e.clientX - rect.left, e.clientY - rect.top, pan, scale)
        setCursorPoint(p)
      }
    }
  }

  const handleMouseUp = (e: React.MouseEvent<SVGSVGElement>) => {
    if (isPanning.current) { stopPan(); return }

    if (isRotating.current) {
      isRotating.current = false
      rotateCenter.current = null
      rotateSnapshot.current = new Map()
      dispatch({ type: 'PUSH_UNDO' })
      return
    }

    if (isDraggingNode.current) {
      isDraggingNode.current = false
      nodeDragStart.current = null
      nodeDragPieceId.current = null
      nodeDragNodeIdx.current = -1
      nodeDragSnapshot.current = new Map()
      dispatch({ type: 'PUSH_UNDO' })
      return
    }

    if (isDraggingPiece.current) {
      isDraggingPiece.current = false
      pieceDragStart.current = null
      pieceElementsSnapshot.current = new Map()
      dispatch({ type: 'PUSH_UNDO' })
      return
    }

    if (isDraggingEndpoint.current) {
      isDraggingEndpoint.current = false
      endpointDragId.current = null
      endpointDragWhich.current = null
      dispatch({ type: 'PUSH_UNDO' })
      return
    }

    // Grain-line: mouseup commits the grain line
    if (activeTool === 'grain-line' && grainLineStart.current) {
      const sr = getSnap(e.clientX, e.clientY)
      const end = sr.point
      const start = grainLineStart.current
      if (Math.hypot(end.x - start.x, end.y - start.y) > 0.1) {
        const glPieceId = selectedPieceIdRef.current ?? undefined
        dispatch({
          type: 'ADD_ELEMENT',
          element: { id: genId(), type: 'grain-line', start, end, pieceId: glPieceId },
        })
      }
      grainLineStart.current = null
      setCursorPoint(null)
      setSnapInfo(null)
    }

    // Select: commit box-select or end element drag
    if (activeTool === 'select' && selectDragStart.current) {
      if (isDraggingElements.current) {
        isDraggingElements.current = false
        // Push undo snapshot after move
        dispatch({ type: 'PUSH_UNDO' })
      } else if (boxSelect) {
        // Find all elements whose start point falls within box (canvas coords)
        const b = boxSelect
        if (b.w > 5 || b.h > 5) {
          const bx0 = (b.x - pan.x) / scale
          const bx1 = (b.x + b.w - pan.x) / scale
          const by0 = (b.y - pan.y) / scale
          const by1 = (b.y + b.h - pan.y) / scale
          const inBox = elements
            .filter(el => {
              const pt = (el.type === 'notch' || el.type === 'anchor-point') ? el.position : (el as any).start as Point
              return pt.x >= bx0 && pt.x <= bx1 && pt.y >= by0 && pt.y <= by1
            })
            .map(el => el.id)
          dispatch({ type: 'SET_SELECTED', ids: inBox })
        }
        setBoxSelect(null)
      }
      selectDragStart.current = null
    }
  }

  // ── Cursor style ──────────────────────────────────────────────────────────
  const cursor = isRotating.current ? 'grabbing'
    : isPanning.current ? 'grabbing'
    : spaceDown.current ? 'grab'
    : activeTool === 'select' ? 'default'
    : 'crosshair'

  // ── Render elements ───────────────────────────────────────────────────────
  function renderElements() {
    return elements.map(el => {
      const isSelected = state.selectedIds.includes(el.id)
      const stroke = isSelected ? '#2563eb' : '#1a1a1a'
      const sw = (isSelected ? 2 : 1.5) / scale

      const elPieceId = 'pieceId' in el ? (el as any).pieceId as string | undefined : undefined
      const onElContextMenu = (e: React.MouseEvent) => {
        e.preventDefault()
        e.stopPropagation()
        const containerRect = containerRef.current!.getBoundingClientRect()
        setContextMenu({ type: 'element', id: el.id, x: e.clientX - containerRect.left, y: e.clientY - containerRect.top })
      }

      if (el.type === 'line') {
        return (
          <line key={el.id}
            x1={el.start.x} y1={el.start.y} x2={el.end.x} y2={el.end.y}
            stroke={stroke} strokeWidth={sw} strokeLinecap="round"
            onContextMenu={onElContextMenu}
            style={{ cursor: elPieceId ? 'pointer' : undefined }}
          />
        )
      }
      if (el.type === 'curve') {
        const d = `M ${el.start.x} ${el.start.y} C ${el.cp1.x} ${el.cp1.y} ${el.cp2.x} ${el.cp2.y} ${el.end.x} ${el.end.y}`
        return (
          <path key={el.id} d={d} fill="none" stroke={stroke} strokeWidth={sw} strokeLinecap="round"
            onContextMenu={onElContextMenu}
            style={{ cursor: elPieceId ? 'pointer' : undefined }}
          />
        )
      }
      if (el.type === 'grain-line') {
        const dx = el.end.x - el.start.x, dy = el.end.y - el.start.y
        const len = Math.hypot(dx, dy)
        if (len < 0.001) return null
        const nx = dx / len, ny = dy / len
        const AW = 0.5 / scale   // arrowhead arm length in cm
        const AF = 0.22 / scale  // arrowhead flare in cm
        // Grain lines are always green — distinct from seam lines regardless of selection
        const grainColor = isSelected ? '#15803d' : '#16a34a'
        const grainSw = (isSelected ? 2.5 : 2) / scale
        // Arrowhead at end
        const ae = [
          { x: el.end.x - nx * AW + ny * AF, y: el.end.y - ny * AW - nx * AF },
          { x: el.end.x - nx * AW - ny * AF, y: el.end.y - ny * AW + nx * AF },
        ]
        // Arrowhead at start
        const as_ = [
          { x: el.start.x + nx * AW + ny * AF, y: el.start.y + ny * AW - nx * AF },
          { x: el.start.x + nx * AW - ny * AF, y: el.start.y + ny * AW + nx * AF },
        ]
        const mid = { x: (el.start.x + el.end.x) / 2, y: (el.start.y + el.end.y) / 2 }
        return (
          <g key={el.id} onContextMenu={onElContextMenu} style={{ cursor: elPieceId ? 'pointer' : undefined }}>
            <line x1={el.start.x} y1={el.start.y} x2={el.end.x} y2={el.end.y}
              stroke={grainColor} strokeWidth={grainSw} strokeDasharray={`${0.6 / scale} ${0.3 / scale}`} />
            <line x1={ae[0].x} y1={ae[0].y} x2={el.end.x} y2={el.end.y} stroke={grainColor} strokeWidth={grainSw} />
            <line x1={ae[1].x} y1={ae[1].y} x2={el.end.x} y2={el.end.y} stroke={grainColor} strokeWidth={grainSw} />
            <line x1={as_[0].x} y1={as_[0].y} x2={el.start.x} y2={el.start.y} stroke={grainColor} strokeWidth={grainSw} />
            <line x1={as_[1].x} y1={as_[1].y} x2={el.start.x} y2={el.start.y} stroke={grainColor} strokeWidth={grainSw} />
            <text x={mid.x} y={mid.y - 0.3 / scale}
              textAnchor="middle" dominantBaseline="auto"
              fontSize={0.45 / scale}
              fill={grainColor}
              style={{ pointerEvents: 'none', userSelect: 'none' }}
            >Grain</text>
          </g>
        )
      }
      if (el.type === 'notch') {
        const len = 0.5 // cm
        const rad = (el.angle * Math.PI) / 180
        return (
          <line key={el.id}
            x1={el.position.x - Math.cos(rad) * len / 2}
            y1={el.position.y - Math.sin(rad) * len / 2}
            x2={el.position.x + Math.cos(rad) * len / 2}
            y2={el.position.y + Math.sin(rad) * len / 2}
            stroke={stroke} strokeWidth={sw} />
        )
      }
      if (el.type === 'anchor-point') {
        const r = 0.2 / scale
        return (
          <circle key={el.id}
            cx={el.position.x} cy={el.position.y} r={r}
            fill={isSelected ? '#2563eb' : '#f59e0b'}
            stroke={isSelected ? '#1d4ed8' : '#d97706'}
            strokeWidth={0.5 / scale}
            onContextMenu={onElContextMenu}
          />
        )
      }
      return null
    })
  }

  return (
    <div ref={containerRef} className="relative flex-1 overflow-hidden bg-white select-none"
      onClick={() => setContextMenu(null)}
      onDragOver={e => e.preventDefault()}
      onDrop={handleFileDrop}
    >
      {/* Corner square where rulers meet */}
      <div style={{ position: 'absolute', top: 0, left: 0, width: RULER_SIZE, height: RULER_SIZE }}
        className="bg-gray-200 z-10 border-b border-r border-gray-300" />

      {/* Rulers */}
      <Ruler horizontal length={canvasW} scale={scale} offset={pan.x} />
      <Ruler horizontal={false} length={canvasH} scale={scale} offset={pan.y} />

      {/* Main SVG */}
      <svg
        ref={svgRef}
        style={{
          position: 'absolute',
          top: RULER_SIZE,
          left: RULER_SIZE,
          width: canvasW,
          height: canvasH,
          cursor,
          userSelect: 'none',
        }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onContextMenu={(e) => { e.preventDefault(); setContextMenu(null) }}
      >
        {/* Checkerboard / white background */}
        <rect width={canvasW} height={canvasH} fill="#fafafa" />

        <g transform={`translate(${pan.x} ${pan.y}) scale(${scale})`}>
          {/* Grid */}
          {showGrid && (
            <Grid scale={scale} pan={pan} canvasW={canvasW} canvasH={canvasH} />
          )}

          {/* Closed pattern pieces (rendered below elements) */}
          {(() => {
            const elMap = new Map(elements.map(e => [e.id, e]))
            return pieces.map(piece => {
              const d = buildPiecePath(piece.elementIds, elMap)
              if (!d) return null
              const center = pieceCentroid(piece.elementIds, elMap)
              const isSel = selectedPieceId === piece.id
              const isSeamTool = activeTool === 'seam-allowance'
              const saPath = piece.seamAllowance > 0 ? computeSeamAllowancePath(piece, elMap) : ''
              // AI-draft pieces (LLM-guessed or traced from the photo) render amber
              // so the user knows to verify them before cutting fabric.
              const isDraft = piece.source === 'llm' || piece.source === 'vision'
              return (
                <g key={piece.id}>
                  {/* Seam allowance offset outline (dashed red, behind fill) */}
                  {saPath && showSeamAllowance && (
                    <path
                      d={saPath}
                      fill="none"
                      stroke="#ef4444"
                      strokeWidth={1.5 / scale}
                      strokeDasharray={`${4 / scale} ${2.5 / scale}`}
                      style={{ pointerEvents: 'none' }}
                    />
                  )}
                  {/* Piece fill */}
                  <path
                    d={d}
                    fill={isSel ? 'rgba(99,102,241,0.18)' : isDraft ? 'rgba(251,191,36,0.20)' : 'rgba(186,230,253,0.25)'}
                    stroke={isSel ? '#6366f1' : isDraft ? '#f59e0b' : '#93c5fd'}
                    strokeWidth={1.5 / scale}
                    strokeDasharray={isSel ? undefined : `${3 / scale} ${2 / scale}`}
                    onMouseDown={(e) => {
                      if (spaceDown.current || e.button !== 0) return
                      if (activeTool === 'select') {
                        e.stopPropagation()
                        dispatch({ type: 'SELECT_PIECE', id: piece.id })
                        // Snapshot piece elements for drag-to-move
                        const rect = svgRef.current!.getBoundingClientRect()
                        const cmPt = screenToCm(e.clientX - rect.left, e.clientY - rect.top, pan, scale)
                        isDraggingPiece.current = true
                        pieceDragStart.current = { cmX: cmPt.x, cmY: cmPt.y }
                        const snap = new Map<string, CanvasElement>()
                        for (const id of piece.elementIds) {
                          const el = elements.find(el => el.id === id)
                          if (el) snap.set(id, el)
                        }
                        // Also include grain lines, notches etc. linked to this piece via pieceId
                        for (const el of elements) {
                          if (!snap.has(el.id) && 'pieceId' in el && (el as any).pieceId === piece.id) {
                            snap.set(el.id, el)
                          }
                        }
                        pieceElementsSnapshot.current = snap
                      } else if (isSeamTool) {
                        e.stopPropagation()
                        setSeamDialog({ pieceId: piece.id, amount: String(piece.seamAllowance) })
                      }
                    }}
                    onContextMenu={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      const containerRect = containerRef.current!.getBoundingClientRect()
                      setContextMenu({ type: 'piece', id: piece.id, x: e.clientX - containerRect.left, y: e.clientY - containerRect.top })
                    }}
                    style={{ cursor: (activeTool === 'select' || isSeamTool) ? 'pointer' : 'default' }}
                  />
                  <text
                    x={center.x} y={center.y - 0.45}
                    textAnchor="middle" dominantBaseline="middle"
                    fontSize={0.65}
                    fill={isSel ? '#3730a3' : isDraft ? '#b45309' : '#1e40af'}
                    style={{ pointerEvents: 'none', userSelect: 'none' }}
                  >
                    {isDraft ? `${piece.name} (AI draft)` : piece.name}
                  </text>
                  <text
                    x={center.x} y={center.y + 0.45}
                    textAnchor="middle" dominantBaseline="middle"
                    fontSize={0.45}
                    fill={isSel ? '#4338ca' : '#3b82f6'}
                    style={{ pointerEvents: 'none', userSelect: 'none' }}
                  >
                    {piece.onFold ? 'Cut 1 (on fold)' : `Cut ${piece.cutQty}`}
                  </text>

                  {/* Node handles — drag to reshape the piece without disconnecting it */}
                  {isSel && activeTool === 'select' && (() => {
                    const nodes = getPieceNodes(piece.elementIds, elMap)
                    return nodes.map((node, i) => (
                      <circle
                        key={`node-${i}`}
                        cx={node.x} cy={node.y}
                        r={5 / scale}
                        fill="white"
                        stroke="#0ea5e9"
                        strokeWidth={1.5 / scale}
                        style={{ cursor: 'move' }}
                        onMouseDown={(e) => {
                          if (e.button !== 0) return
                          e.stopPropagation()
                          const rect = svgRef.current!.getBoundingClientRect()
                          const cmPt = screenToCm(e.clientX - rect.left, e.clientY - rect.top, pan, scale)
                          isDraggingNode.current = true
                          nodeDragStart.current = { cmX: cmPt.x, cmY: cmPt.y }
                          nodeDragPieceId.current = piece.id
                          nodeDragNodeIdx.current = i
                          const snap = new Map<string, CanvasElement>()
                          const n = piece.elementIds.length
                          const prevEl = elements.find(el => el.id === piece.elementIds[i])
                          const nextEl = elements.find(el => el.id === piece.elementIds[(i + 1) % n])
                          if (prevEl) snap.set(prevEl.id, prevEl)
                          if (nextEl) snap.set(nextEl.id, nextEl)
                          nodeDragSnapshot.current = snap
                        }}
                      />
                    ))
                  })()}

                  {/* Rotation handle — visible only when piece is selected in select mode */}
                  {isSel && activeTool === 'select' && (() => {
                    let minY = Infinity
                    for (const id of piece.elementIds) {
                      const el = elMap.get(id)
                      if (!el) continue
                      const pts: Point[] = el.type === 'line' ? [el.start, el.end]
                        : el.type === 'curve' ? [el.start, el.end]
                        : el.type === 'grain-line' ? [el.start, el.end]
                        : 'position' in el ? [(el as any).position as Point] : []
                      for (const p of pts) minY = Math.min(minY, p.y)
                    }
                    const hx = center.x
                    const hy = (isFinite(minY) ? minY : center.y) - 28 / scale
                    const hr = 6 / scale
                    return (
                      <>
                        <line
                          x1={center.x} y1={center.y} x2={hx} y2={hy}
                          stroke="#818cf8" strokeWidth={0.8 / scale}
                          strokeDasharray={`${3 / scale} ${2 / scale}`}
                          style={{ pointerEvents: 'none' }}
                        />
                        <circle
                          cx={hx} cy={hy} r={hr}
                          fill="#6366f1" stroke="white" strokeWidth={1.5 / scale}
                          style={{ cursor: 'grab' }}
                          onMouseDown={(e) => {
                            if (e.button !== 0) return
                            e.stopPropagation()
                            const rect = svgRef.current!.getBoundingClientRect()
                            const cmX = (e.clientX - rect.left - pan.x) / scale
                            const cmY = (e.clientY - rect.top  - pan.y) / scale
                            isRotating.current = true
                            rotateCenter.current = { ...center }
                            rotateStartAngle.current = Math.atan2(cmY - center.y, cmX - center.x)
                            const snap = new Map<string, CanvasElement>()
                            for (const id of piece.elementIds) {
                              const found = elements.find(e => e.id === id)
                              if (found) snap.set(id, found)
                            }
                            rotateSnapshot.current = snap
                          }}
                        />
                        <text
                          x={hx} y={hy}
                          textAnchor="middle" dominantBaseline="middle"
                          fontSize={5 / scale} fill="white"
                          style={{ pointerEvents: 'none', userSelect: 'none' }}
                        >↻</text>
                      </>
                    )
                  })()}
                </g>
              )
            })
          })()}

          {/* Pattern elements */}
          {renderElements()}

          {/* Endpoint handles for selected line/curve segments (select tool only) */}
          {activeTool === 'select' && state.selectedIds.map(id => {
            const el = elements.find(e => e.id === id)
            if (!el || (el.type !== 'line' && el.type !== 'curve')) return null
            return (
              <g key={`ep-${id}`}>
                <circle cx={el.start.x} cy={el.start.y} r={5 / scale}
                  fill="white" stroke="#6366f1" strokeWidth={1.5 / scale}
                  style={{ cursor: 'crosshair' }}
                  onMouseDown={e => {
                    if (e.button !== 0 || spaceDown.current) return
                    e.stopPropagation()
                    isDraggingEndpoint.current = true
                    endpointDragId.current = id
                    endpointDragWhich.current = 'start'
                  }}
                />
                <circle cx={el.end.x} cy={el.end.y} r={5 / scale}
                  fill="white" stroke="#6366f1" strokeWidth={1.5 / scale}
                  style={{ cursor: 'crosshair' }}
                  onMouseDown={e => {
                    if (e.button !== 0 || spaceDown.current) return
                    e.stopPropagation()
                    isDraggingEndpoint.current = true
                    endpointDragId.current = id
                    endpointDragWhich.current = 'end'
                  }}
                />
              </g>
            )
          })}

          {/* Curve-tool: phase placing-end — line from start to cursor */}
          {activeTool === 'curve' && curvePhase.current === 'placing-end' && curveStart.current && cursorPoint && (
            <line
              x1={curveStart.current.x} y1={curveStart.current.y}
              x2={cursorPoint.x} y2={cursorPoint.y}
              stroke="#a855f7" strokeWidth={1.5 / scale}
              strokeDasharray={`${4 / scale} ${2.5 / scale}`}
              strokeLinecap="round"
              style={{ pointerEvents: 'none' }}
            />
          )}

          {/* Curve-tool: phase shaping — live bezier through cursor as through-point */}
          {activeTool === 'curve' && curvePhase.current === 'shaping' && curveStart.current && curveEnd.current && cursorPoint && (() => {
            const s = curveStart.current!
            const e = curveEnd.current!
            const { cp1, cp2 } = throughPointToCP(s, e, cursorPoint)
            const mx = (s.x + e.x) / 2, my = (s.y + e.y) / 2
            return (
              <>
                <path
                  d={`M ${s.x} ${s.y} C ${cp1.x} ${cp1.y} ${cp2.x} ${cp2.y} ${e.x} ${e.y}`}
                  fill="none" stroke="#a855f7" strokeWidth={1.5 / scale}
                  strokeDasharray={`${4 / scale} ${2.5 / scale}`}
                  style={{ pointerEvents: 'none' }}
                />
                {/* Through-point guide: dashed line from midpoint chord to cursor */}
                <line x1={mx} y1={my} x2={cursorPoint.x} y2={cursorPoint.y}
                  stroke="#a855f7" strokeWidth={0.8 / scale} strokeOpacity={0.5}
                  strokeDasharray={`${2 / scale} ${1.5 / scale}`}
                  style={{ pointerEvents: 'none' }} />
                {/* Through-point diamond */}
                <g transform={`translate(${cursorPoint.x},${cursorPoint.y}) rotate(45)`}
                  style={{ pointerEvents: 'none' }}>
                  <rect x={-3 / scale} y={-3 / scale} width={6 / scale} height={6 / scale}
                    fill="white" stroke="#a855f7" strokeWidth={1 / scale} />
                </g>
                {/* End-point anchor */}
                <circle cx={e.x} cy={e.y} r={3 / scale} fill="#a855f7"
                  style={{ pointerEvents: 'none' }} />
              </>
            )
          })()}

          {/* Curve-tool: start anchor dot */}
          {activeTool === 'curve' && curveStart.current && (
            <circle cx={curveStart.current.x} cy={curveStart.current.y}
              r={3 / scale} fill="#a855f7" style={{ pointerEvents: 'none' }} />
          )}

          {/* Grain-line tool: in-progress preview */}
          {activeTool === 'grain-line' && grainLineStart.current && cursorPoint && (
            <line
              x1={grainLineStart.current.x} y1={grainLineStart.current.y}
              x2={cursorPoint.x} y2={cursorPoint.y}
              stroke="#16a34a" strokeWidth={1.5 / scale}
              strokeDasharray={`${4 / scale} ${2.5 / scale}`}
              style={{ pointerEvents: 'none' }}
            />
          )}

          {/* Line-tool: in-progress preview */}
          {activeTool === 'line' && lineStart.current && cursorPoint && (
            <line
              x1={lineStart.current.x} y1={lineStart.current.y}
              x2={cursorPoint.x} y2={cursorPoint.y}
              stroke="#6366f1" strokeWidth={1.5 / scale}
              strokeDasharray={`${4 / scale} ${2.5 / scale}`}
              strokeLinecap="round"
              style={{ pointerEvents: 'none' }}
            />
          )}

          {/* Line-tool: start anchor dot */}
          {activeTool === 'line' && lineStart.current && (
            <circle
              cx={lineStart.current.x} cy={lineStart.current.y}
              r={3 / scale}
              fill="#6366f1"
              style={{ pointerEvents: 'none' }}
            />
          )}

            {/* Snap indicator */}
          {snapInfo && cursorPoint && snapInfo.kind !== 'none' && snapInfo.kind !== 'grid' && (
            <circle
              cx={cursorPoint.x} cy={cursorPoint.y}
              r={5 / scale}
              fill="none"
              stroke={SNAP_COLORS[snapInfo.kind]}
              strokeWidth={1.5 / scale}
              style={{ pointerEvents: 'none' }}
            />
          )}
        </g>

        {/* Box-select rectangle (screen coords, outside the transform group) */}
        {boxSelect && (
          <rect
            x={boxSelect.x} y={boxSelect.y}
            width={boxSelect.w} height={boxSelect.h}
            fill="rgba(99,102,241,0.08)"
            stroke="#6366f1"
            strokeWidth={1}
            strokeDasharray="4 2"
            style={{ pointerEvents: 'none' }}
          />
        )}
      </svg>

      {/* Context menu */}
      {contextMenu && (
        <div
          className="absolute z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[170px]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={e => e.stopPropagation()}
          onContextMenu={e => e.preventDefault()}
        >
          {contextMenu.type === 'piece' && (() => {
            const pid = contextMenu.id
            return (
              <>
                <ContextMenuItem label="Flip Horizontal"   onClick={() => { flipPiece(pid, 'flipH'); setContextMenu(null) }} />
                <ContextMenuItem label="Flip Vertical"     onClick={() => { flipPiece(pid, 'flipV'); setContextMenu(null) }} />
                <div className="my-1 border-t border-gray-100" />
                <ContextMenuItem label="Rotate 90° CW"    onClick={() => { rotatePiece(pid,  90); setContextMenu(null) }} />
                <ContextMenuItem label="Rotate 90° CCW"   onClick={() => { rotatePiece(pid, -90); setContextMenu(null) }} />
                <ContextMenuItem label="Rotate 180°"      onClick={() => { rotatePiece(pid, 180); setContextMenu(null) }} />
              </>
            )
          })()}
          {contextMenu.type === 'element' && (() => {
            const el = elements.find(e => e.id === contextMenu.id)
            const elPieceId = el && 'pieceId' in el ? (el as any).pieceId as string | undefined : undefined
            return (
              <>
                {elPieceId && (
                  <ContextMenuItem
                    label="Remove from piece"
                    onClick={() => {
                      dispatch({ type: 'REMOVE_SIDE_FROM_PIECE', pieceId: elPieceId, elementId: contextMenu.id })
                      setContextMenu(null)
                    }}
                  />
                )}
                <ContextMenuItem
                  label="Delete"
                  danger
                  onClick={() => {
                    dispatch({ type: 'DELETE_ELEMENTS', ids: [contextMenu.id] })
                    setContextMenu(null)
                  }}
                />
              </>
            )
          })()}
        </div>
      )}

      {/* ── Dimension labels (HTML overlay — reliable click, no SVG event issues) */}
      {elements.map(el => {
        if (el.type !== 'line' && el.type !== 'curve') return null

        let dimVal: number, labelX: number, labelY: number

        if (el.type === 'line') {
          const dx = el.end.x - el.start.x, dy = el.end.y - el.start.y
          dimVal = Math.hypot(dx, dy)
          if (dimVal < 0.3) return null
          const midX = (el.start.x + el.end.x) / 2
          const midY = (el.start.y + el.end.y) / 2
          const nx = -dy / dimVal, ny = dx / dimVal
          const off = 10 / scale
          labelX = midX + nx * off
          labelY = midY + ny * off
        } else {
          dimVal = bezierArcLength(el.start, el.cp1, el.cp2, el.end)
          if (dimVal < 0.3) return null
          const mid = sampleBezier(el.start, el.cp1, el.cp2, el.end, 0.5)
          const pA = sampleBezier(el.start, el.cp1, el.cp2, el.end, 0.48)
          const pB = sampleBezier(el.start, el.cp1, el.cp2, el.end, 0.52)
          const tx = pB.x - pA.x, ty = pB.y - pA.y
          const tl = Math.hypot(tx, ty)
          const nx = tl > 0.001 ? -ty / tl : 0
          const ny = tl > 0.001 ?  tx / tl : -1
          const off = 10 / scale
          labelX = mid.x + nx * off
          labelY = mid.y + ny * off
        }

        const sx = labelX * scale + pan.x + RULER_SIZE
        const sy = labelY * scale + pan.y + RULER_SIZE
        const isEditing = editingDim?.id === el.id

        if (isEditing) {
          return (
            <div
              key={`dim-${el.id}`}
              style={{ position: 'absolute', left: sx, top: sy, transform: 'translate(-50%,-50%)', zIndex: 110 }}
              onMouseDown={e => e.stopPropagation()}
            >
              <DimEditInput
                id={el.id}
                initialValue={editingDim!.value}
                onApply={applyDimension}
                onCancel={() => setEditingDim(null)}
              />
            </div>
          )
        }

        return (
          <div
            key={`dim-${el.id}`}
            style={{ position: 'absolute', left: sx, top: sy, transform: 'translate(-50%,-50%)', zIndex: 20, cursor: 'pointer' }}
            onMouseDown={e => {
              e.stopPropagation()
              if (e.button !== 0) return
              setEditingDim({ id: el.id, value: dimVal.toFixed(2) })
            }}
          >
            <div className="px-1.5 py-0.5 rounded-full text-[10px] leading-none font-mono whitespace-nowrap select-none bg-white/90 text-gray-500 border border-gray-200 hover:border-blue-400 hover:text-blue-500 shadow-sm">
              {dimVal.toFixed(1)}
            </div>
          </div>
        )
      })}

      {/* Seam allowance amount dialog */}
      {seamDialog && (
        <div
          className="absolute inset-0 flex items-center justify-center z-50"
          style={{ backgroundColor: 'rgba(0,0,0,0.15)' }}
          onClick={() => setSeamDialog(null)}
        >
          <div
            className="bg-white rounded-lg shadow-xl p-4 w-64 border border-gray-200"
            onClick={e => e.stopPropagation()}
          >
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Seam Allowance</h3>
            <label className="text-xs text-gray-600 block mb-1">Amount (cm)</label>
            <input
              type="number"
              min={0}
              step={0.25}
              value={seamDialog.amount}
              onChange={e => setSeamDialog({ ...seamDialog, amount: e.target.value })}
              onKeyDown={e => {
                if (e.key === 'Enter') applySeamAllowance()
                if (e.key === 'Escape') setSeamDialog(null)
              }}
              className="w-full border border-gray-300 rounded px-2 py-1 text-sm mb-3"
              autoFocus
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setSeamDialog(null)}
                className="text-xs px-3 py-1.5 border border-gray-200 rounded hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={applySeamAllowance}
                className="text-xs px-3 py-1.5 bg-indigo-600 text-white rounded hover:bg-indigo-700"
              >
                Apply
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
