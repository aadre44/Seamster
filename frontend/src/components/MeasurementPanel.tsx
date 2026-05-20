import { useState, useEffect } from 'react'
import { useEditor } from '../context/EditorContext'
import { toDisplay, fromDisplay, convertBounds, unitLabel } from '../utils/units'

// Field definitions — bounds are always in cm; display converts on the fly
const FIELDS: { name: string; label: string; minCm: number; maxCm: number }[] = [
  { name: 'bust',          label: 'Bust',           minCm: 50,  maxCm: 200 },
  { name: 'waist',         label: 'Waist',          minCm: 40,  maxCm: 180 },
  { name: 'hip',           label: 'Hip',            minCm: 50,  maxCm: 200 },
  { name: 'waistToHip',    label: 'Waist to Hip',   minCm: 10,  maxCm: 40  },
  { name: 'garmentLength', label: 'Length',         minCm: 10,  maxCm: 160 },
  { name: 'inseam',        label: 'Inseam',         minCm: 20,  maxCm: 100 },
  { name: 'shoulder',      label: 'Shoulder Width', minCm: 20,  maxCm: 60  },
  { name: 'sleeveLength',  label: 'Sleeve Length',  minCm: 10,  maxCm: 70  },
]

function MeasurementField({
  name,
  label,
  minCm,
  maxCm,
}: {
  name: string
  label: string
  minCm: number
  maxCm: number
}) {
  const { state, dispatch } = useEditor()
  const unit = state.unitSystem
  const stateValCm = state.measurements[name]

  // raw input string — reset when the stored cm value or unit changes
  const [raw, setRaw] = useState(
    stateValCm != null ? String(toDisplay(stateValCm, unit)) : '',
  )
  const [error, setError] = useState('')

  useEffect(() => {
    setRaw(stateValCm != null ? String(toDisplay(stateValCm, unit)) : '')
    setError('')
  }, [stateValCm, unit])

  const { min, max } = convertBounds(minCm, maxCm, unit)
  const ul = unitLabel(unit)

  const handleChange = (value: string) => {
    setRaw(value)
    const num = parseFloat(value)
    if (value === '' || isNaN(num)) { setError('Enter a number'); return }
    if (num < min || num > max) { setError(`${min}–${max} ${ul}`); return }
    setError('')
    dispatch({ type: 'SET_MEASUREMENT', name, value: fromDisplay(num, unit) })
  }

  return (
    <div>
      <label className="block text-[10px] text-gray-500 mb-0.5">
        {label} ({ul})
      </label>
      <input
        type="number"
        value={raw}
        onChange={e => handleChange(e.target.value)}
        className={`w-full border rounded px-2 py-1 text-xs font-mono
          ${error ? 'border-red-400 bg-red-50' : 'border-gray-300'}`}
        placeholder="—"
        step={unit === 'imperial' ? '0.25' : '1'}
      />
      {error && <p className="text-[10px] text-red-500 mt-0.5">{error}</p>}
    </div>
  )
}

export default function MeasurementPanel() {
  const { state, dispatch } = useEditor()
  const [collapsed, setCollapsed] = useState(false)
  const unit = state.unitSystem

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
          {/* Unit toggle */}
          <div className="flex items-center gap-1 mb-1">
            <span className="text-[10px] text-gray-500">Units:</span>
            <button
              onClick={() => dispatch({ type: 'SET_UNIT_SYSTEM', unit: 'metric' })}
              className={`px-2 py-0.5 text-[10px] rounded ${
                unit === 'metric'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              cm
            </button>
            <button
              onClick={() => dispatch({ type: 'SET_UNIT_SYSTEM', unit: 'imperial' })}
              className={`px-2 py-0.5 text-[10px] rounded ${
                unit === 'imperial'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              in
            </button>
          </div>

          {FIELDS.map(f => (
            <MeasurementField
              key={f.name}
              name={f.name}
              label={f.label}
              minCm={f.minCm}
              maxCm={f.maxCm}
            />
          ))}
        </div>
      )}
    </section>
  )
}
