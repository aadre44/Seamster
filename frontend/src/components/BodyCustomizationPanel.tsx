import { useMemo, useState } from 'react'
import { useEditor } from '../context/EditorContext'
import { BODY_FIELDS, resolveBody } from '../three/bodyRegions'
import type { BodyField, BodySex, BodyShapePreset } from '../three/types'
import { convertBounds, fromDisplay, toDisplay, unitLabel } from '../utils/units'

const groups = (sex: BodySex): { title: string; keys: BodyField[] }[] => [
  { title: 'Frame', keys: ['height', 'shoulder', 'neck'] },
  // A man's chest has no underbust measurement.
  { title: 'Torso', keys: sex === 'male' ? ['bust', 'waist', 'waistToHip', 'hip'] : ['bust', 'underbust', 'waist', 'waistToHip', 'hip'] },
  { title: 'Arms', keys: ['armLength', 'upperArm', 'wrist'] },
  { title: 'Legs', keys: ['inseam', 'thigh', 'knee', 'calf', 'ankle'] },
]

const SHAPES: { key: BodyShapePreset; female: string; male: string }[] = [
  { key: 'hourglass', female: 'Hourglass', male: 'Athletic' },
  { key: 'rectangle', female: 'Rectangle', male: 'Rectangle' },
  { key: 'pear', female: 'Pear', male: 'Triangle' },
  { key: 'apple', female: 'Apple', male: 'Oval' },
]

const SEXES: { key: BodySex; label: string }[] = [
  { key: 'female', label: 'Female' },
  { key: 'male', label: 'Male' },
]

const META = new Map(BODY_FIELDS.map(f => [f.key, f]))

export default function BodyCustomizationPanel() {
  const { state, dispatch } = useEditor()
  const [collapsed, setCollapsed] = useState(false)
  const unit = state.unitSystem
  const ul = unitLabel(unit)
  const { overrides, shape } = state.bodyProfile
  const sex = state.bodyProfile.sex ?? 'female'
  const label = (key: BodyField) => (key === 'bust' && sex === 'male' ? 'Chest' : META.get(key)!.label)
  const body = useMemo(
    () => resolveBody(state.bodyProfile, state.measurements),
    [state.bodyProfile, state.measurements],
  )

  const source = (key: BodyField) => {
    if (overrides[key] !== undefined) return 'custom'
    const mk = META.get(key)?.measurementKey
    return mk && state.measurements[mk] !== undefined ? 'measured' : ''
  }

  return (
    <section className="border-b border-gray-200">
      <button
        onClick={() => setCollapsed(c => !c)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50"
      >
        <span>Body</span>
        <span>{collapsed ? '▸' : '▾'}</span>
      </button>

      {!collapsed && (
        <div className="px-3 pb-3 space-y-3">
          <div>
            <div className="text-[10px] text-gray-500 mb-1">Body</div>
            <div className="grid grid-cols-2 gap-1" role="radiogroup" aria-label="Body">
              {SEXES.map(s => (
                <button
                  key={s.key}
                  role="radio"
                  aria-checked={sex === s.key}
                  onClick={() => dispatch({ type: 'SET_BODY_SEX', sex: s.key })}
                  className={`px-2 py-0.5 text-[10px] rounded ${
                    sex === s.key ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="text-[10px] text-gray-500 mb-1">Shape</div>
            <div className="grid grid-cols-2 gap-1">
              {SHAPES.map(s => (
                <button
                  key={s.key}
                  onClick={() => dispatch({ type: 'SET_BODY_SHAPE', shape: s.key })}
                  className={`px-2 py-0.5 text-[10px] rounded ${
                    shape === s.key ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {sex === 'male' ? s.male : s.female}
                </button>
              ))}
            </div>
          </div>

          {groups(sex).map(group => (
            <div key={group.title} className="space-y-1.5">
              <div className="text-[10px] font-semibold text-gray-600 uppercase tracking-wide">{group.title}</div>
              {group.keys.map(key => {
                const meta = META.get(key)!
                const { min, max } = convertBounds(meta.minCm, meta.maxCm, unit)
                const src = source(key)
                return (
                  <div key={key}>
                    <div className="flex items-baseline justify-between text-[10px] text-gray-500">
                      <span>
                        {label(key)}
                        {src && <span className="ml-1 text-[9px] text-indigo-400">{src}</span>}
                      </span>
                      <span className="font-mono text-gray-700">{toDisplay(body[key], unit)} {ul}</span>
                    </div>
                    <input
                      type="range"
                      aria-label={label(key)}
                      min={min}
                      max={max}
                      step={unit === 'imperial' ? 0.25 : 0.5}
                      value={toDisplay(body[key], unit)}
                      onChange={e => dispatch({
                        type: 'SET_BODY_PROFILE_FIELD',
                        field: key,
                        value: fromDisplay(parseFloat(e.target.value), unit),
                      })}
                      className="w-full h-1 accent-indigo-600"
                    />
                  </div>
                )
              })}
            </div>
          ))}

          <button
            onClick={() => dispatch({ type: 'RESET_BODY_PROFILE' })}
            disabled={Object.keys(overrides).length === 0}
            className="w-full text-[10px] px-2 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-40"
          >
            Reset to measurements
          </button>
        </div>
      )}
    </section>
  )
}
