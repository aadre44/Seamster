import type { CanvasElement, PatternPiece, Point } from '../types'

// ── Geometry helpers (mirrors Canvas.tsx — keep in sync) ─────────────────────

function sampleBezier(s: Point, c1: Point, c2: Point, e: Point, t: number): Point {
  const u = 1 - t
  return {
    x: u*u*u*s.x + 3*u*u*t*c1.x + 3*u*t*t*c2.x + t*t*t*e.x,
    y: u*u*u*s.y + 3*u*u*t*c1.y + 3*u*t*t*c2.y + t*t*t*e.y,
  }
}

function lineLineIntersect(a1: Point, a2: Point, b1: Point, b2: Point): Point | null {
  const dx1 = a2.x - a1.x, dy1 = a2.y - a1.y
  const dx2 = b2.x - b1.x, dy2 = b2.y - b1.y
  const denom = dx1 * dy2 - dy1 * dx2
  if (Math.abs(denom) < 1e-10) return null
  const t = ((b1.x - a1.x) * dy2 - (b1.y - a1.y) * dx2) / denom
  return { x: a1.x + t * dx1, y: a1.y + t * dy1 }
}

function flattenPieceVertices(elementIds: string[], elMap: Map<string, CanvasElement>) {
  const pts: Point[] = [], foldEdge: boolean[] = []
  for (const id of elementIds) {
    const el = elMap.get(id)
    if (!el) continue
    if (el.type === 'line') {
      pts.push({ ...el.start })
      foldEdge.push(el.isFold)
    } else if (el.type === 'curve') {
      for (let i = 0; i < 16; i++) {
        pts.push(sampleBezier(el.start, el.cp1, el.cp2, el.end, i / 16))
        foldEdge.push(false)
      }
    }
  }
  return { pts, foldEdge }
}

function offsetPolygon(pts: Point[], foldEdge: boolean[], d: number): Point[] {
  const n = pts.length
  if (n < 3) return []
  let area = 0
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n
    area += pts[i].x * pts[j].y - pts[j].x * pts[i].y
  }
  const sign = area > 0 ? 1 : -1
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

// ── Main export function ──────────────────────────────────────────────────────

export function exportSVG(elements: CanvasElement[], pieces: PatternPiece[]): string {
  const PAD = 2 // cm padding around content
  const elMap = new Map(elements.map(e => [e.id, e]))

  // Compute bounding box
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  const expand = (p: Point) => {
    minX = Math.min(minX, p.x); minY = Math.min(minY, p.y)
    maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y)
  }

  for (const el of elements) {
    if (el.type === 'line') { expand(el.start); expand(el.end) }
    else if (el.type === 'curve') {
      expand(el.start); expand(el.end); expand(el.cp1); expand(el.cp2)
    }
    else if (el.type === 'grain-line') { expand(el.start); expand(el.end) }
    else if (el.type === 'notch' || el.type === 'anchor-point') { expand(el.position) }
  }

  if (!isFinite(minX)) { minX = 0; minY = 0; maxX = 20; maxY = 20 }

  // Reserve space for 5cm test square at bottom-left
  const TEST_SQ = 5
  minX = Math.min(minX, 0)
  minY = Math.min(minY, 0)
  maxX = Math.max(maxX, TEST_SQ + 1)
  maxY = Math.max(maxY, TEST_SQ + 1)

  const vx = minX - PAD, vy = minY - PAD
  const vw = maxX - minX + PAD * 2, vh = maxY - minY + PAD * 2

  const lines: string[] = []
  lines.push(`<?xml version="1.0" encoding="UTF-8"?>`)
  lines.push(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vx.toFixed(2)} ${vy.toFixed(2)} ${vw.toFixed(2)} ${vh.toFixed(2)}" width="${vw}cm" height="${vh}cm">`)
  lines.push(`<style>text { font-family: Arial, sans-serif; }</style>`)

  // ── Piece fills + seam allowances ──────────────────────────────────────────
  for (const piece of pieces) {
    const { pts, foldEdge } = flattenPieceVertices(piece.elementIds, elMap)
    if (pts.length < 3) continue
    const polyPts = pts.map(p => `${p.x.toFixed(3)},${p.y.toFixed(3)}`).join(' ')
    lines.push(`<polygon points="${polyPts}" fill="rgba(186,230,253,0.4)" stroke="#1a1a1a" stroke-width="0.05"/>`)

    // Seam allowance
    if (piece.seamAllowance > 0) {
      const off = offsetPolygon(pts, foldEdge, piece.seamAllowance)
      if (off.length >= 3) {
        const offPts = off.map(p => `${p.x.toFixed(3)},${p.y.toFixed(3)}`).join(' ')
        lines.push(`<polygon points="${offPts}" fill="none" stroke="#ef4444" stroke-width="0.04" stroke-dasharray="0.3 0.15"/>`)
      }
    }

    // Piece label (centroid)
    const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length
    const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length
    lines.push(`<text x="${cx.toFixed(2)}" y="${cy.toFixed(2)}" font-size="0.45" text-anchor="middle" dominant-baseline="middle" fill="#1a1a1a">${escapeXml(piece.name)}</text>`)
    lines.push(`<text x="${cx.toFixed(2)}" y="${(cy + 0.6).toFixed(2)}" font-size="0.35" text-anchor="middle" dominant-baseline="middle" fill="#6b7280">Cut × ${piece.cutQty}</text>`)
  }

  // ── Drawing elements ────────────────────────────────────────────────────────
  for (const el of elements) {
    if (el.type === 'line') {
      const fold = el.isFold ? ' stroke-dasharray="0.5 0.25"' : ''
      lines.push(`<line x1="${el.start.x}" y1="${el.start.y}" x2="${el.end.x}" y2="${el.end.y}" stroke="#1a1a1a" stroke-width="0.05" stroke-linecap="round"${fold}/>`)
    }
    else if (el.type === 'curve') {
      lines.push(`<path d="M ${el.start.x} ${el.start.y} C ${el.cp1.x} ${el.cp1.y} ${el.cp2.x} ${el.cp2.y} ${el.end.x} ${el.end.y}" fill="none" stroke="#1a1a1a" stroke-width="0.05" stroke-linecap="round"/>`)
    }
    else if (el.type === 'grain-line') {
      const dx = el.end.x - el.start.x, dy = el.end.y - el.start.y
      const len = Math.hypot(dx, dy)
      if (len < 0.01) continue
      const nx = dx / len, ny = dy / len
      const AW = 0.4, AF = 0.18
      lines.push(`<line x1="${el.start.x}" y1="${el.start.y}" x2="${el.end.x}" y2="${el.end.y}" stroke="#2563eb" stroke-width="0.05"/>`)
      // Arrowheads at both ends
      for (const [px, py, dirX, dirY] of [
        [el.end.x, el.end.y, -nx, -ny],
        [el.start.x, el.start.y, nx, ny],
      ] as [number, number, number, number][]) {
        const ax1 = px + dirX * AW + ny * AF, ay1 = py + dirY * AW - nx * AF
        const ax2 = px + dirX * AW - ny * AF, ay2 = py + dirY * AW + nx * AF
        lines.push(`<line x1="${ax1.toFixed(3)}" y1="${ay1.toFixed(3)}" x2="${px}" y2="${py}" stroke="#2563eb" stroke-width="0.05"/>`)
        lines.push(`<line x1="${ax2.toFixed(3)}" y1="${ay2.toFixed(3)}" x2="${px}" y2="${py}" stroke="#2563eb" stroke-width="0.05"/>`)
      }
      const mid = { x: (el.start.x + el.end.x) / 2, y: (el.start.y + el.end.y) / 2 }
      lines.push(`<text x="${mid.x}" y="${(mid.y - 0.3).toFixed(2)}" font-size="0.4" text-anchor="middle" fill="#2563eb">Grain</text>`)
    }
    else if (el.type === 'notch') {
      const halfLen = 0.25
      const rad = (el.angle * Math.PI) / 180
      const x1 = el.position.x - Math.cos(rad) * halfLen
      const y1 = el.position.y - Math.sin(rad) * halfLen
      const x2 = el.position.x + Math.cos(rad) * halfLen
      const y2 = el.position.y + Math.sin(rad) * halfLen
      lines.push(`<line x1="${x1.toFixed(3)}" y1="${y1.toFixed(3)}" x2="${x2.toFixed(3)}" y2="${y2.toFixed(3)}" stroke="#1a1a1a" stroke-width="0.06"/>`)
    }
  }

  // ── 5 cm test square (at origin area) ──────────────────────────────────────
  const sx = vx + PAD / 2, sy = maxY + PAD / 2
  lines.push(`<rect x="${sx}" y="${sy}" width="5" height="5" fill="none" stroke="#999" stroke-width="0.04" stroke-dasharray="0.2 0.1"/>`)
  lines.push(`<text x="${(sx + 2.5).toFixed(2)}" y="${(sy + 2.5).toFixed(2)}" font-size="0.4" text-anchor="middle" dominant-baseline="middle" fill="#999">5 cm test square</text>`)

  lines.push(`</svg>`)
  return lines.join('\n')
}

function escapeXml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

export function downloadSVG(elements: CanvasElement[], pieces: PatternPiece[]): void {
  const svg = exportSVG(elements, pieces)
  const blob = new Blob([svg], { type: 'image/svg+xml' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'pattern.svg'
  a.click()
  URL.revokeObjectURL(url)
}
