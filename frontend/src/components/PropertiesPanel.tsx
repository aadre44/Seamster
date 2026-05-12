import { useState, useEffect } from 'react'
import { useEditor } from '../context/EditorContext'
import { evaluateFormula } from '../utils/formulaEval'
import { transformPieceElements } from '../utils/pieceTransforms'
import { throughPointToCP } from './Canvas'
import type { LineElement, CurveElement, PatternPiece, Point } from '../types'

export default function PropertiesPanel() {
  const { state, dispatch } = useEditor()

  if (state.selectedPieceId) {
    const piece = state.pieces.find(p => p.id === state.selectedPieceId)
    if (piece) return <PieceProps piece={piece} />
  }

  const selected = state.elements.filter(el => state.selectedIds.includes(el.id))
  if (selected.length === 0) {
    return (
      <div className="p-3 text-xs text-gray-400 italic">
        Select an element to edit its properties.
      </div>
    )
  }

  const el = selected[0]

  return (
    <div className="p-3 text-xs text-gray-700 space-y-2">
      <div className="font-semibold text-gray-900 capitalize">{el.type}</div>

      {el.type === 'line' && (
        <LineProps el={el} measurements={state.measurements} dispatch={dispatch} />
      )}

      {el.type === 'curve' && (
        <CurveProps el={el} dispatch={dispatch} />
      )}

      {el.type === 'grain-line' && (
        <>
          <Row label="Start" value={`(${el.start.x.toFixed(2)}, ${el.start.y.toFixed(2)}) cm`} />
          <Row label="End" value={`(${el.end.x.toFixed(2)}, ${el.end.y.toFixed(2)}) cm`} />
        </>
      )}

      {el.type === 'notch' && (
        <>
          <Row label="Position" value={`(${el.position.x.toFixed(2)}, ${el.position.y.toFixed(2)}) cm`} />
          <Row label="Angle" value={`${el.angle.toFixed(1)}°`} />
        </>
      )}
    </div>
  )
}

// ── Editable number coordinate row ────────────────────────────────────────────

function CoordRow({ label, value, onCommit }: {
  label: string
  value: number
  onCommit: (v: number) => void
}) {
  const [raw, setRaw] = useState(value.toFixed(3))
  const [active, setActive] = useState(false)

  useEffect(() => {
    if (!active) setRaw(value.toFixed(3))
  }, [value, active])

  const commit = () => {
    const v = parseFloat(raw)
    if (!isNaN(v)) onCommit(v)
    setActive(false)
  }

  return (
    <div className="flex items-center justify-between gap-1">
      <span className="text-gray-500 shrink-0">{label}</span>
      <input
        type="number"
        step={0.1}
        value={raw}
        onChange={e => { setActive(true); setRaw(e.target.value) }}
        onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') commit() }}
        className="w-20 border border-gray-300 rounded px-1.5 py-0.5 text-[10px] font-mono text-right"
      />
    </div>
  )
}

// ── Line properties ───────────────────────────────────────────────────────────

function LineProps({ el, measurements, dispatch }: {
  el: LineElement
  measurements: Record<string, number>
  dispatch: React.Dispatch<any>
}) {
  const [formulaInput, setFormulaInput] = useState(el.formula ?? '')
  const [formulaError, setFormulaError] = useState<string | null>(null)

  useEffect(() => { setFormulaInput(el.formula ?? ''); setFormulaError(null) }, [el.id, el.formula])

  const length = Math.hypot(el.end.x - el.start.x, el.end.y - el.start.y)

  const applyFormula = (f: string) => {
    if (!f.trim()) {
      dispatch({ type: 'UPDATE_ELEMENT', element: { ...el, formula: undefined } })
      setFormulaError(null)
      return
    }
    const result = evaluateFormula(f, measurements)
    if (result.error) { setFormulaError(result.error); return }
    setFormulaError(null)
    if (result.value === null) {
      dispatch({ type: 'UPDATE_ELEMENT', element: { ...el, formula: f } })
      return
    }
    const dx = el.end.x - el.start.x, dy = el.end.y - el.start.y
    const currentLen = Math.hypot(dx, dy)
    if (currentLen < 0.001) return
    const factor = result.value / currentLen
    dispatch({
      type: 'UPDATE_ELEMENT',
      element: { ...el, formula: f, end: { x: el.start.x + dx * factor, y: el.start.y + dy * factor } },
    })
  }

  useEffect(() => {
    if (el.formula) applyFormula(el.formula)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [measurements])

  const evalPreview = formulaInput ? evaluateFormula(formulaInput, measurements) : null

  const moveStart = (field: 'x' | 'y', v: number) => {
    const newStart: Point = { ...el.start, [field]: v }
    dispatch({ type: 'UPDATE_ELEMENT', element: { ...el, start: newStart } })
  }
  const moveEnd = (field: 'x' | 'y', v: number) => {
    const newEnd: Point = { ...el.end, [field]: v }
    dispatch({ type: 'UPDATE_ELEMENT', element: { ...el, end: newEnd } })
  }

  return (
    <>
      <CoordRow label="Start X" value={el.start.x} onCommit={v => moveStart('x', v)} />
      <CoordRow label="Start Y" value={el.start.y} onCommit={v => moveStart('y', v)} />
      <CoordRow label="End X"   value={el.end.x}   onCommit={v => moveEnd('x', v)} />
      <CoordRow label="End Y"   value={el.end.y}   onCommit={v => moveEnd('y', v)} />
      <Row label="Length" value={`${length.toFixed(2)} cm`} />

      <div className="flex items-center justify-between pt-0.5">
        <span className="text-gray-500">Fold line</span>
        <input
          type="checkbox"
          checked={el.isFold}
          onChange={e => dispatch({ type: 'UPDATE_ELEMENT', element: { ...el, isFold: e.target.checked } })}
          className="w-4 h-4 accent-indigo-600"
        />
      </div>

      <div className="pt-1">
        <label className="block text-[10px] text-gray-500 mb-0.5">Formula (e.g. hip / 2 + 1)</label>
        <input
          type="text"
          value={formulaInput}
          onChange={e => setFormulaInput(e.target.value)}
          onBlur={e => applyFormula(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') applyFormula(formulaInput) }}
          className={`w-full border rounded px-2 py-1 text-xs font-mono
            ${formulaError ? 'border-red-400 bg-red-50' : 'border-gray-300'}`}
          placeholder="e.g. hip / 2 + 1"
        />
        {evalPreview && evalPreview.value !== null && !formulaError && (
          <p className="text-[10px] text-indigo-600 mt-0.5">= {evalPreview.value} cm</p>
        )}
        {formulaError && (
          <p className="text-[10px] text-red-500 mt-0.5">{formulaError}</p>
        )}
      </div>
    </>
  )
}

// ── Curve properties ──────────────────────────────────────────────────────────

function sampleBezier(s: Point, c1: Point, c2: Point, e: Point, t: number): Point {
  const u = 1 - t
  return {
    x: u*u*u*s.x + 3*u*u*t*c1.x + 3*u*t*t*c2.x + t*t*t*e.x,
    y: u*u*u*s.y + 3*u*u*t*c1.y + 3*u*t*t*c2.y + t*t*t*e.y,
  }
}

function curveLength(el: CurveElement): number {
  let len = 0, prev = el.start
  for (let i = 1; i <= 20; i++) {
    const p = sampleBezier(el.start, el.cp1, el.cp2, el.end, i / 20)
    len += Math.hypot(p.x - prev.x, p.y - prev.y)
    prev = p
  }
  return len
}

function CurveProps({ el, dispatch }: { el: CurveElement; dispatch: React.Dispatch<any> }) {
  const len = curveLength(el)

  // Through-point at t=0.5 (what the curve passes through at its midpoint)
  const throughPt = sampleBezier(el.start, el.cp1, el.cp2, el.end, 0.5)

  // Chord geometry
  const chordX = el.end.x - el.start.x
  const chordY = el.end.y - el.start.y
  const chordLen = Math.hypot(chordX, chordY)

  // Perpendicular unit vector (90° CCW from chord direction)
  const perpX = chordLen > 0.001 ? -chordY / chordLen : 0
  const perpY = chordLen > 0.001 ?  chordX / chordLen : 0

  // Midpoint of chord
  const mx = (el.start.x + el.end.x) / 2
  const my = (el.start.y + el.end.y) / 2

  // Arc height: signed perpendicular offset from chord midpoint to through-point
  const archHeight = (throughPt.x - mx) * perpX + (throughPt.y - my) * perpY

  const setArchHeight = (h: number) => {
    const newThrough = { x: mx + h * perpX, y: my + h * perpY }
    const { cp1, cp2 } = throughPointToCP(el.start, el.end, newThrough)
    dispatch({ type: 'UPDATE_ELEMENT', element: { ...el, cp1, cp2 } })
  }

  const moveStart = (field: 'x' | 'y', v: number) => {
    const delta: Point = field === 'x' ? { x: v - el.start.x, y: 0 } : { x: 0, y: v - el.start.y }
    dispatch({
      type: 'UPDATE_ELEMENT',
      element: {
        ...el,
        start: { ...el.start, [field]: v },
        cp1: { x: el.cp1.x + delta.x, y: el.cp1.y + delta.y },
      },
    })
  }

  const moveEnd = (field: 'x' | 'y', v: number) => {
    const delta: Point = field === 'x' ? { x: v - el.end.x, y: 0 } : { x: 0, y: v - el.end.y }
    dispatch({
      type: 'UPDATE_ELEMENT',
      element: {
        ...el,
        end: { ...el.end, [field]: v },
        cp2: { x: el.cp2.x + delta.x, y: el.cp2.y + delta.y },
      },
    })
  }

  return (
    <>
      <CoordRow label="Start X" value={el.start.x} onCommit={v => moveStart('x', v)} />
      <CoordRow label="Start Y" value={el.start.y} onCommit={v => moveStart('y', v)} />
      <CoordRow label="End X"   value={el.end.x}   onCommit={v => moveEnd('x', v)} />
      <CoordRow label="End Y"   value={el.end.y}   onCommit={v => moveEnd('y', v)} />
      <Row label="Chord" value={`${chordLen.toFixed(2)} cm`} />
      <Row label="Arc length" value={`${len.toFixed(2)} cm`} />
      {chordLen > 0.001 && (
        <>
          <CoordRow label="Arc height" value={archHeight} onCommit={setArchHeight} />
          <p className="text-[10px] text-gray-400 leading-snug">
            Arc height: perpendicular offset from the chord midpoint.
            Positive = left of chord direction.
          </p>
        </>
      )}
    </>
  )
}

// ── Piece properties ──────────────────────────────────────────────────────────

function PieceProps({ piece }: { piece: PatternPiece }) {
  const { state, dispatch } = useEditor()
  const [name, setName] = useState(piece.name)
  const [seamInput, setSeamInput] = useState(String(piece.seamAllowance))
  const [customAngle, setCustomAngle] = useState('0')

  useEffect(() => { setName(piece.name) }, [piece.id, piece.name])
  useEffect(() => { setSeamInput(String(piece.seamAllowance)) }, [piece.id, piece.seamAllowance])

  const commitSeam = () => {
    const v = parseFloat(seamInput)
    if (!isNaN(v) && v >= 0) dispatch({ type: 'UPDATE_PIECE', piece: { ...piece, seamAllowance: v } })
  }
  const commitName = () => {
    if (name.trim()) dispatch({ type: 'UPDATE_PIECE', piece: { ...piece, name: name.trim() } })
  }
  const applyTransform = (op: 'flipH' | 'flipV' | 'rotate', angle = 0) => {
    const updated = transformPieceElements(piece, state.elements, op, angle)
    dispatch({ type: 'BATCH_UPDATE_ELEMENTS', elements: updated })
  }

  return (
    <div className="p-3 text-xs text-gray-700 space-y-3">
      <div className="font-semibold text-gray-900">Pattern Piece</div>

      <div>
        <label className="block text-[10px] text-gray-500 mb-0.5">Name</label>
        <input type="text" value={name}
          onChange={e => setName(e.target.value)}
          onBlur={commitName}
          onKeyDown={e => { if (e.key === 'Enter') commitName() }}
          className="w-full border border-gray-300 rounded px-2 py-1 text-xs" />
      </div>

      <div className="flex items-center justify-between">
        <span className="text-gray-500">Cut quantity</span>
        <input type="number" min={1} max={20} value={piece.cutQty}
          onChange={e => dispatch({ type: 'UPDATE_PIECE', piece: { ...piece, cutQty: Math.max(1, parseInt(e.target.value) || 1) } })}
          className="w-14 border border-gray-300 rounded px-2 py-1 text-xs text-right" />
      </div>

      <div className="flex items-center justify-between">
        <span className="text-gray-500">On fold</span>
        <input type="checkbox" checked={piece.onFold}
          onChange={e => dispatch({ type: 'UPDATE_PIECE', piece: { ...piece, onFold: e.target.checked } })}
          className="w-4 h-4 accent-indigo-600" />
      </div>

      <div>
        <label className="block text-[10px] text-gray-500 mb-0.5">Seam allowance (cm)</label>
        <input type="number" min={0} step={0.25} value={seamInput}
          onChange={e => setSeamInput(e.target.value)}
          onBlur={commitSeam}
          onKeyDown={e => { if (e.key === 'Enter') commitSeam() }}
          className="w-full border border-gray-300 rounded px-2 py-1 text-xs text-right font-mono" />
      </div>

      <div className="border-t border-gray-100 pt-2 space-y-2">
        <div className="text-[10px] text-gray-500 font-medium uppercase tracking-wide">Transform</div>
        <div className="flex gap-1">
          <button onClick={() => applyTransform('flipH')}
            className="flex-1 border border-gray-300 rounded px-1 py-1 text-[10px] hover:bg-gray-50 active:bg-gray-100">
            Flip H
          </button>
          <button onClick={() => applyTransform('flipV')}
            className="flex-1 border border-gray-300 rounded px-1 py-1 text-[10px] hover:bg-gray-50 active:bg-gray-100">
            Flip V
          </button>
        </div>
        <div className="flex gap-1">
          <button onClick={() => applyTransform('rotate',  90)}
            className="flex-1 border border-gray-300 rounded px-1 py-1 text-[10px] hover:bg-gray-50 active:bg-gray-100">
            90° CW
          </button>
          <button onClick={() => applyTransform('rotate', -90)}
            className="flex-1 border border-gray-300 rounded px-1 py-1 text-[10px] hover:bg-gray-50 active:bg-gray-100">
            90° CCW
          </button>
          <button onClick={() => applyTransform('rotate', 180)}
            className="flex-1 border border-gray-300 rounded px-1 py-1 text-[10px] hover:bg-gray-50 active:bg-gray-100">
            180°
          </button>
        </div>
        <div className="flex items-center gap-1">
          <input type="number" step={1} value={customAngle}
            onChange={e => setCustomAngle(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') applyTransform('rotate', parseFloat(customAngle) || 0) }}
            className="w-16 border border-gray-300 rounded px-2 py-1 text-xs text-right font-mono"
            placeholder="0" />
          <span className="text-gray-400 text-[10px]">deg</span>
          <button onClick={() => applyTransform('rotate', parseFloat(customAngle) || 0)}
            className="flex-1 border border-gray-300 rounded px-1 py-1 text-[10px] hover:bg-gray-50 active:bg-gray-100">
            Rotate
          </button>
        </div>
      </div>

      <div className="border-t border-gray-100 pt-2 space-y-2">
        <div className="text-[10px] text-gray-500 font-medium uppercase tracking-wide">Mirror (new copy)</div>
        <div className="flex gap-1">
          <button onClick={() => dispatch({ type: 'MIRROR_PIECE', pieceId: piece.id, op: 'flipH' })}
            className="flex-1 border border-gray-300 rounded px-1 py-1 text-[10px] hover:bg-blue-50 active:bg-blue-100">
            Mirror H
          </button>
          <button onClick={() => dispatch({ type: 'MIRROR_PIECE', pieceId: piece.id, op: 'flipV' })}
            className="flex-1 border border-gray-300 rounded px-1 py-1 text-[10px] hover:bg-blue-50 active:bg-blue-100">
            Mirror V
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between text-gray-400">
        <span>Segments</span>
        <span className="font-mono">{piece.elementIds.length}</span>
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-gray-500 shrink-0">{label}</span>
      <span className="font-mono text-right">{value}</span>
    </div>
  )
}
