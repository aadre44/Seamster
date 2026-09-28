import type { MeshData } from './types'
import type { Bounds, Sdf } from './bodySdf'

// Naive surface nets: one vertex per grid cell the surface passes through (the
// mean of its edge crossings, then snapped onto the surface with one Newton
// step), and one quad per sign-changing grid edge.
//
// The field is evaluated only in a narrow band: each 4³ block is probed at its
// centre and skipped when the surface can't be inside it. The x grid is
// symmetric about x = 0, so a symmetric field gives a symmetric mesh.

const BLOCK = 4
// Our distance fields can over-estimate slope (blend, lobes), so blocks are
// only skipped when the probe is this many half-diagonals away.
const BAND_SAFETY = 2.5

export function meshSdf(sdf: Sdf, bounds: Bounds, h: number, name = 'body'): MeshData {
  const pad = 2 * h
  const halfX = Math.max(-bounds.min[0], bounds.max[0]) + pad
  const nx = 2 * Math.ceil(halfX / h) + 1
  const x0 = -((nx - 1) / 2) * h
  const y0 = bounds.min[1] - pad
  const z0 = bounds.min[2] - pad
  const ny = Math.ceil((bounds.max[1] + pad - y0) / h) + 1
  const nz = Math.ceil((bounds.max[2] + pad - z0) / h) + 1
  const idx = (i: number, j: number, k: number) => i + nx * (j + ny * k)

  const field = new Float32Array(nx * ny * nz)
  const exact = new Uint8Array(nx * ny * nz)
  const skipDistance = BAND_SAFETY * (BLOCK * h * Math.sqrt(3)) / 2
  for (let bk = 0; bk < nz - 1; bk += BLOCK) {
    for (let bj = 0; bj < ny - 1; bj += BLOCK) {
      for (let bi = 0; bi < nx - 1; bi += BLOCK) {
        const i1 = Math.min(bi + BLOCK, nx - 1)
        const j1 = Math.min(bj + BLOCK, ny - 1)
        const k1 = Math.min(bk + BLOCK, nz - 1)
        const probe = sdf(x0 + ((bi + i1) / 2) * h, y0 + ((bj + j1) / 2) * h, z0 + ((bk + k1) / 2) * h)
        const skip = Math.abs(probe) > skipDistance
        for (let k = bk; k <= k1; k++) {
          for (let j = bj; j <= j1; j++) {
            for (let i = bi; i <= i1; i++) {
              const p = idx(i, j, k)
              if (exact[p]) continue
              if (skip) {
                field[p] = probe
              } else {
                field[p] = sdf(x0 + i * h, y0 + j * h, z0 + k * h)
                exact[p] = 1
              }
            }
          }
        }
      }
    }
  }

  const cellIndex = new Int32Array((nx - 1) * (ny - 1) * (nz - 1)).fill(-1)
  const cidx = (i: number, j: number, k: number) => i + (nx - 1) * (j + (ny - 1) * k)
  const positions: number[] = []
  const corners = [
    [0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1],
  ]
  const edges = [
    [0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7],
  ]
  const values = new Float64Array(8)
  const eps = h * 0.05

  for (let k = 0; k < nz - 1; k++) {
    for (let j = 0; j < ny - 1; j++) {
      for (let i = 0; i < nx - 1; i++) {
        let inside = 0
        for (let c = 0; c < 8; c++) {
          const v = field[idx(i + corners[c][0], j + corners[c][1], k + corners[c][2])]
          values[c] = v
          if (v < 0) inside++
        }
        if (inside === 0 || inside === 8) continue
        let sx = 0
        let sy = 0
        let sz = 0
        let count = 0
        for (const [a, b] of edges) {
          const va = values[a]
          const vb = values[b]
          if ((va < 0) === (vb < 0)) continue
          const t = va / (va - vb)
          sx += corners[a][0] + (corners[b][0] - corners[a][0]) * t
          sy += corners[a][1] + (corners[b][1] - corners[a][1]) * t
          sz += corners[a][2] + (corners[b][2] - corners[a][2]) * t
          count++
        }
        let px = x0 + (i + sx / count) * h
        let py = y0 + (j + sy / count) * h
        let pz = z0 + (k + sz / count) * h
        // One Newton step onto the zero set, limited to the cell size.
        const f = sdf(px, py, pz)
        const gx = (sdf(px + eps, py, pz) - sdf(px - eps, py, pz)) / (2 * eps)
        const gy = (sdf(px, py + eps, pz) - sdf(px, py - eps, pz)) / (2 * eps)
        const gz = (sdf(px, py, pz + eps) - sdf(px, py, pz - eps)) / (2 * eps)
        const g2 = gx * gx + gy * gy + gz * gz
        if (g2 > 1e-8) {
          let step = f / g2
          const len = Math.abs(step) * Math.sqrt(g2)
          if (len > h) step *= h / len
          px -= step * gx
          py -= step * gy
          pz -= step * gz
        }
        cellIndex[cidx(i, j, k)] = positions.length / 3
        positions.push(px, py, pz)
      }
    }
  }

  const indices: number[] = []
  const quad = (a: number, b: number, c: number, d: number, keep: boolean) => {
    if (a < 0 || b < 0 || c < 0 || d < 0) return
    if (keep) indices.push(a, b, c, a, c, d)
    else indices.push(a, d, c, a, c, b)
  }
  for (let k = 0; k < nz; k++) {
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        const v0 = field[idx(i, j, k)]
        const in0 = v0 < 0
        // Faces are wound counter-clockwise around +axis, i.e. facing +axis,
        // which is outward when the inside is at the lower end of the edge.
        if (i < nx - 1 && j > 0 && k > 0 && j < ny - 1 && k < nz - 1 && in0 !== (field[idx(i + 1, j, k)] < 0)) {
          quad(cellIndex[cidx(i, j - 1, k - 1)], cellIndex[cidx(i, j, k - 1)], cellIndex[cidx(i, j, k)], cellIndex[cidx(i, j - 1, k)], in0)
        }
        if (j < ny - 1 && i > 0 && k > 0 && i < nx - 1 && k < nz - 1 && in0 !== (field[idx(i, j + 1, k)] < 0)) {
          quad(cellIndex[cidx(i - 1, j, k - 1)], cellIndex[cidx(i - 1, j, k)], cellIndex[cidx(i, j, k)], cellIndex[cidx(i, j, k - 1)], in0)
        }
        if (k < nz - 1 && i > 0 && j > 0 && i < nx - 1 && j < ny - 1 && in0 !== (field[idx(i, j, k + 1)] < 0)) {
          quad(cellIndex[cidx(i - 1, j - 1, k)], cellIndex[cidx(i, j - 1, k)], cellIndex[cidx(i, j, k)], cellIndex[cidx(i - 1, j, k)], in0)
        }
      }
    }
  }

  return { name, positions: new Float32Array(positions), indices: new Uint32Array(indices) }
}
