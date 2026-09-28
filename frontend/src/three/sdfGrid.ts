import type { Bounds, Sdf } from './bodySdf'

// The body's distance field sampled once on a regular grid, so the cloth
// solver's many collision queries are cheap trilinear lookups instead of full
// field evaluations. Only a band around the surface is sampled exactly; far
// blocks just carry their centre's (large) value, which is all collision needs.

const BLOCK = 4
const BAND_SAFETY = 2.5

export class SdfGrid {
  private readonly nx: number
  private readonly ny: number
  private readonly nz: number
  private readonly x0: number
  private readonly y0: number
  private readonly z0: number
  private readonly data: Float32Array

  constructor(sdf: Sdf, bounds: Bounds, private readonly h = 1.0, pad = 6) {
    this.x0 = bounds.min[0] - pad
    this.y0 = bounds.min[1] - pad
    this.z0 = bounds.min[2] - pad
    this.nx = Math.ceil((bounds.max[0] + pad - this.x0) / h) + 1
    this.ny = Math.ceil((bounds.max[1] + pad - this.y0) / h) + 1
    this.nz = Math.ceil((bounds.max[2] + pad - this.z0) / h) + 1
    const { nx, ny, nz } = this
    this.data = new Float32Array(nx * ny * nz)
    const exact = new Uint8Array(nx * ny * nz)
    const skip = BAND_SAFETY * (BLOCK * h * Math.sqrt(3)) / 2
    for (let bk = 0; bk < nz - 1; bk += BLOCK) {
      for (let bj = 0; bj < ny - 1; bj += BLOCK) {
        for (let bi = 0; bi < nx - 1; bi += BLOCK) {
          const i1 = Math.min(bi + BLOCK, nx - 1)
          const j1 = Math.min(bj + BLOCK, ny - 1)
          const k1 = Math.min(bk + BLOCK, nz - 1)
          const probe = sdf(this.x0 + ((bi + i1) / 2) * h, this.y0 + ((bj + j1) / 2) * h, this.z0 + ((bk + k1) / 2) * h)
          const far = Math.abs(probe) > skip
          for (let k = bk; k <= k1; k++) {
            for (let j = bj; j <= j1; j++) {
              for (let i = bi; i <= i1; i++) {
                const p = i + nx * (j + ny * k)
                if (exact[p]) continue
                if (far) this.data[p] = probe
                else {
                  this.data[p] = sdf(this.x0 + i * h, this.y0 + j * h, this.z0 + k * h)
                  exact[p] = 1
                }
              }
            }
          }
        }
      }
    }
  }

  // Trilinear sample; far outside the grid everything is "outside the body".
  sample(x: number, y: number, z: number): number {
    const fx = (x - this.x0) / this.h
    const fy = (y - this.y0) / this.h
    const fz = (z - this.z0) / this.h
    const { nx, ny, nz, data } = this
    if (fx < 0 || fy < 0 || fz < 0 || fx >= nx - 1 || fy >= ny - 1 || fz >= nz - 1) return 1e3
    const i = Math.floor(fx)
    const j = Math.floor(fy)
    const k = Math.floor(fz)
    const u = fx - i
    const v = fy - j
    const w = fz - k
    const p = i + nx * (j + ny * k)
    const sx = 1
    const sy = nx
    const sz = nx * ny
    const c00 = data[p] * (1 - u) + data[p + sx] * u
    const c10 = data[p + sy] * (1 - u) + data[p + sy + sx] * u
    const c01 = data[p + sz] * (1 - u) + data[p + sz + sx] * u
    const c11 = data[p + sz + sy] * (1 - u) + data[p + sz + sy + sx] * u
    const c0 = c00 * (1 - v) + c10 * v
    const c1 = c01 * (1 - v) + c11 * v
    return c0 * (1 - w) + c1 * w
  }

  // Unit outward normal (field gradient); zero where the field is flat.
  normal(x: number, y: number, z: number, out: Float32Array): void {
    const e = this.h * 0.5
    const gx = this.sample(x + e, y, z) - this.sample(x - e, y, z)
    const gy = this.sample(x, y + e, z) - this.sample(x, y - e, z)
    const gz = this.sample(x, y, z + e) - this.sample(x, y, z - e)
    const g = Math.hypot(gx, gy, gz)
    if (g < 1e-9) {
      out[0] = out[1] = out[2] = 0
      return
    }
    out[0] = gx / g
    out[1] = gy / g
    out[2] = gz / g
  }
}
