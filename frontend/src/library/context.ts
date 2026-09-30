import type { CanvasElement, PatternPiece } from '../types'
import { isTrimName } from '../three/pieceClassifier'
import type { PresetContext } from './presets'

// What the library sizes collars, cuffs and waistbands to: the current
// pattern's whole neckline, waist and one sleeve's wrist. Pieces cut in two or
// on the fold are halves, so their edges count twice. Trims (a collar has a
// "neckline" edge too) are left out.

function edgeLength(e: CanvasElement): number {
  if (e.type === 'line') return Math.hypot(e.end.x - e.start.x, e.end.y - e.start.y)
  if (e.type !== 'curve') return 0
  let len = 0
  let prev = e.start
  for (let i = 1; i <= 32; i++) {
    const t = i / 32, u = 1 - t
    const p = {
      x: u * u * u * e.start.x + 3 * u * u * t * e.cp1.x + 3 * u * t * t * e.cp2.x + t * t * t * e.end.x,
      y: u * u * u * e.start.y + 3 * u * u * t * e.cp1.y + 3 * u * t * t * e.cp2.y + t * t * t * e.end.y,
    }
    len += Math.hypot(p.x - prev.x, p.y - prev.y)
    prev = p
  }
  return len
}

export function presetContext(pieces: PatternPiece[], elements: CanvasElement[], measurements: Record<string, number>): PresetContext {
  const byId = new Map(elements.map(e => [e.id, e]))
  const shell = pieces.filter(p => !isTrimName(p.name))
  // Whole-garment length of the edges with `label`; `perSleeve` counts each
  // piece once unless it is a half on the fold (one sleeve, not the pair).
  const total = (label: string, only?: (p: PatternPiece) => boolean, perSleeve = false) => {
    let sum = 0
    for (const p of shell) {
      if (only && !only(p)) continue
      const len = p.elementIds.map(id => byId.get(id)).filter(e => e && (e as { seamLabel?: string }).seamLabel === label)
        .reduce((s, e) => s + edgeLength(e!), 0)
      sum += len * (p.onFold || (!perSleeve && p.cutQty >= 2) ? 2 : 1)
    }
    return sum > 0 ? Math.round(sum * 10) / 10 : null
  }
  return { neck: total('neckline'), waist: total('waist'), wrist: total('wrist', p => /sleeve/i.test(p.name), true), measurements }
}
