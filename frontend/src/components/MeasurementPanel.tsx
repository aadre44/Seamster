import { useState, useEffect } from 'react'
import { useEditor } from '../context/EditorContext'

const FIELDS: { name: string; label: string; min: number; max: number }[] = [
  { name: 'bust',        label: 'Bust',              min: 50, max: 200 },
  { name: 'waist',       label: 'Waist',             min: 40, max: 180 },
  { name: 'hip',         label: 'Hip',               min: 50, max: 200 },
  { name: 'waistToHip',  label: 'Waist to Hip',      min: 10, max: 40 },
  { name: 'skirtLength', label: 'Skirt Length',      min: 10, max: 160 },
  { name: 'inseam',      label: 'Inseam',            min: 20, max: 100 },
  { name: 'shoulder',    label: 'Shoulder Width',    min: 20, max: 60 },
  { name: 'sleeveLength',label: 'Sleeve Length',     min: 10, max: 70 },
]

function MeasurementField({ name, label, min, max }: { name: string; label: string; min: number; max: number }) {
  const { state, dispatch } = useEditor()
  const stateVal = state.measurements[name]
  const [raw, setRaw] = useState(stateVal != null ? String(stateVal) : '')
  const [error, setError] = useState('')

  // Sync when external load (LOAD_STATE) changes the measurement value
  useEffect(() => {
    setRaw(stateVal != null ? String(stateVal) : '')
    setError('')
  }, [stateVal])

  const handleChange = (value: string) => {
    setRaw(value)
    const num = parseFloat(value)
    if (value === '' || isNaN(num)) { setError('Enter a number'); return }
    if (num < min || num > max) { setError(`${min}–${max} cm`); return }
    setError('')
    dispatch({ type: 'SET_MEASUREMENT', name, value: num })
  }

  return (
    <div>
      <label className="block text-[10px] text-gray-500 mb-0.5">{label} (cm)</label>
      <input
        type="number"
        value={raw}
        onChange={e => handleChange(e.target.value)}
        className={`w-full border rounded px-2 py-1 text-xs font-mono
          ${error ? 'border-red-400 bg-red-50' : 'border-gray-300'}`}
        placeholder="—"
      />
      {error && <p className="text-[10px] text-red-500 mt-0.5">{error}</p>}
    </div>
  )
}

export default function MeasurementPanel() {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <section className="border-t border-gray-200">
      <button
        onClick={() => setCollapsed(c => !c)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50"
      >
        <span>Measurements</span>
        <span>{collapsed ? '▸' : '▾'}</span>
      </button>

      {!collapsed && (
        <div className="px-3 pb-3 space-y-2">
          {FIELDS.map(f => (
            <MeasurementField key={f.name} name={f.name} label={f.label} min={f.min} max={f.max} />
          ))}
        </div>
      )}
    </section>
  )
}
