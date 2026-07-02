/**
 * Header control to switch the backend LLM provider at runtime — toggles between
 * Claude (Anthropic, cloud) and a local open-source model (Ollama).
 *
 * Reads/writes GET|POST /api/provider. The choice lives in the backend process
 * memory, so every AI action (analyse, generate, instructions, piece fallback)
 * uses whichever provider is selected here without a server restart.
 */
import { useEffect, useState } from 'react'
import { getProvider, setProvider } from '../api'
import type { ProviderState } from '../api'

export default function ModelToggle() {
  const [state, setState] = useState<ProviderState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getProvider()
      .then(setState)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const select = async (key: string) => {
    if (busy || !state || key === state.active) return
    setBusy(true); setError('')
    try {
      setState(await setProvider(key))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!state) {
    return (
      <span className="text-xs text-gray-400">
        {error ? 'AI offline' : 'Loading model…'}
      </span>
    )
  }

  return (
    <div
      className="flex items-center gap-1.5"
      title={error || (state.model ? `Model: ${state.model}` : undefined)}
    >
      <span className="text-xs text-gray-400">Model:</span>
      <div className="flex rounded-full border border-gray-200 overflow-hidden text-xs">
        {state.providers.map(p => {
          const isActive = p.key === state.active
          return (
            <button
              key={p.key}
              onClick={() => select(p.key)}
              disabled={busy}
              className={`px-2.5 py-0.5 font-medium transition-colors disabled:cursor-not-allowed ${
                isActive
                  ? 'bg-violet-600 text-white'
                  : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              {p.label}
            </button>
          )
        })}
      </div>
      {busy && (
        <span className="inline-block w-3 h-3 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
      )}
    </div>
  )
}
