// Which part of the body a pattern piece covers, inferred from its seam
// labels (reliable for engine pieces) and its name (for user/AI pieces).
// PatternPiece has no explicit body-region field yet.

export type Region = 'torso-upper' | 'torso-lower' | 'leg' | 'sleeve' | 'skip'

export interface Classification {
  region: Region
  back: boolean
  reason?: string
}

// Trims and small pieces have no clean place on the body in the static
// preview; they stay 2D-only for now.
const TRIM = /\b(facing|facings|binding|pocket|pockets|welt|flap|collar|cuff|cuffs|loop|loops|strap|straps|tie|ties|fly|shield|gusset|placket|belt|bag|lining|interfacing|casing|epaulet|epaulette|hood|yoke|waistband|band|ruffle|frill|bow|tab)\b/

export function classifyPiece(name: string, labels: Set<string>): Classification {
  const n = name.toLowerCase()
  const back = labels.has('center_back') || (!labels.has('center_front') && /\bback\b/.test(n))
  if (TRIM.test(n)) return { region: 'skip', back, reason: 'trim or detail piece' }
  if (labels.has('sleeve_seam') || labels.has('center_sleeve') || /\bsleeve\b/.test(n)) return { region: 'sleeve', back }
  if (labels.has('inseam') || labels.has('crotch') || /\bleg\b/.test(n)) return { region: 'leg', back }
  if (labels.has('shoulder') || labels.has('armhole')) return { region: 'torso-upper', back }
  if (labels.has('side_seam') && (labels.has('waist') || labels.has('waist_seam'))) return { region: 'torso-lower', back }
  if (labels.has('side_seam') && /\b(skirt|bodice|front|back|panel)\b/.test(n)) return { region: 'torso-lower', back }
  return { region: 'skip', back, reason: 'no body region recognised' }
}
