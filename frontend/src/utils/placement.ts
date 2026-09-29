import type { CanvasElement, PatternPiece, Placement } from '../types'

// Where a placed piece (pocket, flap, appliqué) sits on its host, in the
// host's canvas coordinates. Shared by the Assembly view and the 3D drape so
// both put it in the same spot: mirror in x (optional), then rotate by
// `rotation` degrees (canvas axes, y down) about the piece's bbox centre, then
// translate by (dx, dy).

export interface Matrix { a: number; b: number; c: number; d: number; tx: number; ty: number }

export function pieceCenter(piece: PatternPiece, byId: Map<string, CanvasElement>): { x: number; y: number } {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const id of piece.elementIds) {
    const el = byId.get(id)
    if (!el || (el.type !== 'line' && el.type !== 'curve')) continue
    for (const p of el.type === 'curve' ? [el.start, el.end, el.cp1, el.cp2] : [el.start, el.end]) {
      minX = Math.min(minX, p.x); minY = Math.min(minY, p.y)
      maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y)
    }
  }
  return isFinite(minX) ? { x: (minX + maxX) / 2, y: (minY + maxY) / 2 } : { x: 0, y: 0 }
}

export function placementMatrix(pl: Placement, center: { x: number; y: number }): Matrix {
  const th = (pl.transform.rotation * Math.PI) / 180
  const cos = Math.cos(th), sin = Math.sin(th)
  const f = pl.transform.flip ? -1 : 1
  // p' = R · F · (p − c) + c + d
  const a = cos * f, b = -sin, c = sin * f, d = cos
  return {
    a, b, c, d,
    tx: center.x + pl.transform.dx - (a * center.x + b * center.y),
    ty: center.y + pl.transform.dy - (c * center.x + d * center.y),
  }
}

export function applyMatrix(m: Matrix, x: number, y: number): [number, number] {
  return [m.a * x + m.b * y + m.tx, m.c * x + m.d * y + m.ty]
}
