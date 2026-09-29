import type { SeamConnection, SeamEnd } from '../types'
import type { PlacedPiece } from './garmentWrap'
import type { SdfGrid } from './sdfGrid'
import { seamParts } from './pieceGeometry'

// Drape: position-based dynamics cloth ("small steps": many substeps, one
// constraint pass each — Macklin et al. 2019), seeded from the static wrap.
//
//  - stretch: every mesh edge keeps its FLAT pattern length (woven fabric
//    barely stretches; it may compress, which lets it buckle into folds);
//  - bending: soft constraints between the far corners of neighbouring
//    triangles, so the fabric has some body;
//  - stitching: every seam in the engine's stitch map, plus each piece's own
//    fold / centre / underarm seams between its mirrored copies, pulls matching
//    points (by arc-length fraction along the two edges) together;
//  - body collision against a sampled distance grid, with friction so fabric
//    rests on shoulders and hips; the floor at y = 0.
//
// All cloth lives in one particle array; each placed copy is a slice of it.

export const CLOTH_THICKNESS = 0.35 // cm kept between fabric and skin
const GRAVITY = 981 // cm/s²
const STRETCH = 1.0
const COMPRESS = 0.4
const BEND = 0.12
const STITCH = 1.0
// Cotton on skin: fairly grippy.
const STATIC_FRICTION = 0.9
const KINETIC_FRICTION = 0.6
const DAMPING_PER_SECOND = 0.3 // fraction of velocity kept after 1 s of free motion
// Tethers only catch gross sag (local shape is the edge constraints' job):
// 10% slack, and none for particles within TETHER_MIN of their anchor.
const TETHER_SLACK = 1.1
const TETHER_MIN = 15

export interface CopyRange { piece: number; copy: number; start: number; count: number }

interface EdgeRef { range: CopyRange; verts: number[]; t: number[] }

export class Cloth {
  readonly x: Float32Array
  readonly prev: Float32Array
  readonly v: Float32Array
  readonly n: number
  readonly ranges: CopyRange[] = []
  // Distance constraints: pairs (i, j), rest length, stiffness.
  private readonly di: Int32Array
  private readonly dr: Float32Array
  private readonly dk: Float32Array
  // Stitches: particle a to the point b0·(1−w) + b1·w.
  private readonly sa: Int32Array
  private readonly sb: Int32Array
  private readonly sw: Float32Array
  // Long-range attachments (Kim et al. 2012): particle i may be at most tr
  // from anchor ti (a vertex on the edge the piece hangs from), tr being their
  // flat pattern distance. Carries the garment's weight to where it hangs in
  // one constraint, which plain edge constraints can't at a usable cost.
  private readonly ti: Int32Array
  private readonly ta: Int32Array
  private readonly tr: Float32Array
  // alias[i] = the particle i is welded to (itself when not welded).
  private readonly alias: Int32Array
  // Seams between pieces that were welded (the rest fell back to stitches).
  weldedSeams = 0
  private readonly normal = new Float32Array(3)

  constructor(placed: PlacedPiece[], connections: SeamConnection[], private readonly body: SdfGrid) {
    let n = 0
    placed.forEach((p, pi) => p.copies.forEach((c, ci) => {
      this.ranges.push({ piece: pi, copy: ci, start: n, count: c.positions.length / 3 })
      n += c.positions.length / 3
    }))
    this.n = n
    this.x = new Float32Array(n * 3)
    for (const r of this.ranges) this.x.set(placed[r.piece].copies[r.copy].positions, r.start * 3)
    this.prev = new Float32Array(this.x)
    this.v = new Float32Array(n * 3)

    const pairs: number[] = []
    const rest: number[] = []
    const stiff: number[] = []
    placed.forEach((p, pi) => {
      const { pts, tris } = p.mesh
      const flat = (a: number, b: number) => Math.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1])
      const edgeTris = new Map<string, number[]>()
      tris.forEach(([a, b, c]) => {
        for (const [u, w, o] of [[a, b, c], [b, c, a], [c, a, b]]) {
          const key = u < w ? `${u},${w}` : `${w},${u}`
          const list = edgeTris.get(key) ?? []
          list.push(o)
          edgeTris.set(key, list)
        }
      })
      for (const r of this.ranges.filter(r => r.piece === pi)) {
        for (const [key, opposite] of edgeTris) {
          const [u, w] = key.split(',').map(Number)
          pairs.push(r.start + u, r.start + w)
          rest.push(flat(u, w))
          stiff.push(STRETCH)
          if (opposite.length === 2) {
            pairs.push(r.start + opposite[0], r.start + opposite[1])
            rest.push(flat(opposite[0], opposite[1]))
            stiff.push(BEND)
            }
        }
      }
    })
    this.dr = new Float32Array(rest)
    this.dk = new Float32Array(stiff)

    const sa: number[] = []
    const sb: number[] = []
    const sw: number[] = []
    // Do two sewn edges run in opposite directions? (From where the wrap put them.)
    const reversedPair = (A: EdgeRef, B: EdgeRef) => {
      const pos = (r: CopyRange, v: number) => [this.x[(r.start + v) * 3], this.x[(r.start + v) * 3 + 1], this.x[(r.start + v) * 3 + 2]]
      const d = (p: number[], q: number[]) => Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2])
      const a0 = pos(A.range, A.verts[0])
      const a1 = pos(A.range, A.verts[A.verts.length - 1])
      const b0 = pos(B.range, B.verts[0])
      const b1 = pos(B.range, B.verts[B.verts.length - 1])
      return d(a0, b1) + d(a1, b0) < d(a0, b0) + d(a1, b1)
    }

    // Welded particles share one simulated particle (alias → root).
    const alias = Int32Array.from({ length: n }, (_, i) => i)
    const root = (i: number): number => {
      while (alias[i] !== i) i = alias[i]
      return i
    }
    const weldPair = (a: number, b: number) => {
      const ra = root(a)
      const rb = root(b)
      if (ra !== rb) alias[rb] = ra
    }

    const stitch = (A: EdgeRef, B: EdgeRef) => {
      const reversed = reversedPair(A, B)
      const link = (from: EdgeRef, to: EdgeRef, flip: boolean) => {
        from.verts.forEach((va, i) => {
          const t = flip ? 1 - from.t[i] : from.t[i]
          let j = 0
          while (j < to.t.length - 2 && to.t[j + 1] < t) j++
          const w = Math.min(1, Math.max(0, (t - to.t[j]) / Math.max(to.t[j + 1] - to.t[j], 1e-9)))
          sa.push(from.range.start + va)
          sb.push(to.range.start + to.verts[j], to.range.start + to.verts[j + 1])
          sw.push(w)
        })
      }
      link(A, B, reversed)
      link(B, A, reversed)
    }

    const edgeRef = (pi: number, ci: number, ei: number): EdgeRef => {
      const range = this.ranges.find(r => r.piece === pi && r.copy === ci)!
      return { range, verts: placed[pi].mesh.edgeVerts[ei], t: placed[pi].mesh.edgeT[ei] }
    }

    // A seam end can be several outline edges: an edge darts were cut into
    // (sewn, the darts close — each segment's first vertex lands on the previous
    // one's last, the dart legs being welded), or split where other seams' ranges
    // end (consecutive parts share their end vertex). As a seam it is the parts
    // chained with those duplicates dropped; t runs along the sewn length.
    const seamRef = (pi: number, ci: number, end: SeamEnd): EdgeRef | null => {
      const p = placed[pi]
      const parts = seamParts(p.edges, end).map(ei => ({ e: p.edges[ei], ei }))
      if (!parts.length) return null
      if (parts.length === 1) return edgeRef(pi, ci, parts[0].ei)
      const range = this.ranges.find(r => r.piece === pi && r.copy === ci)!
      const { pts, edgeVerts } = p.mesh
      const verts: number[] = []
      const len: number[] = []
      let total = 0
      parts.forEach(({ ei }, s) => {
        edgeVerts[ei].forEach((v, k) => {
          if (s > 0 && k === 0) return
          if (verts.length && k > 0) total += Math.hypot(pts[v][0] - pts[edgeVerts[ei][k - 1]][0], pts[v][1] - pts[edgeVerts[ei][k - 1]][1])
          verts.push(v)
          len.push(total)
        })
      })
      return { range, verts, t: len.map(l => (total > 0 ? l / total : 0)) }
    }

    // Seams between pieces, copy by copy on the same side of the body; a
    // sleeve's front half is sewn to the front bodice, its back half to the
    // back. Placement samples both sides of a seam identically, so the seam is
    // welded vertex to vertex and cannot open; stitched only if the sampling
    // somehow differs.
    // Which side of the body (the wearer's left is +x) a copy was placed on.
    const sideOf = (r: CopyRange): 'left' | 'right' => {
      let sx = 0
      for (let i = r.start; i < r.start + r.count; i++) sx += this.x[i * 3]
      return sx >= 0 ? 'left' : 'right'
    }
    // Is a seam end's chain (in loop order) running against its element?
    const runsBackwards = (pi: number, end: SeamEnd) => {
      const parts = seamParts(placed[pi].edges, end)
      return parts.length > 0 && placed[pi].edges[parts[0]].flipped
    }
    for (const c of connections) {
      const pa = placed.findIndex(p => p.id === c.from.pieceId)
      const pb = placed.findIndex(p => p.id === c.to.pieceId)
      if (pa < 0 || pb < 0) continue
      placed[pa].copySpecs.forEach((sA, ia) => placed[pb].copySpecs.forEach((sB, ib) => {
        if (sA.mirrorWorld !== sB.mirrorWorld) return
        if (placed[pa].region === 'sleeve' && sA.frontHalf === placed[pb].back) return
        if (placed[pb].region === 'sleeve' && sB.frontHalf === placed[pa].back) return
        const A = seamRef(pa, ia, c.from)
        const B = seamRef(pb, ib, c.to)
        if (!A || !B) return
        if (c.from.side && sideOf(A.range) !== c.from.side) return
        if (c.to.side && sideOf(B.range) !== c.to.side) return
        if (A.verts.length !== B.verts.length) {
          stitch(A, B)
          return
        }
        // By default the direction comes from where the wrap put the two edges;
        // `reversed` (set in Assembly) says how the elements themselves pair up.
        const flip = c.reversed === undefined
          ? reversedPair(A, B)
          : c.reversed !== (runsBackwards(pa, c.from) !== runsBackwards(pb, c.to))
        const last = B.verts.length - 1
        A.verts.forEach((v, k) => weldPair(A.range.start + v, B.range.start + B.verts[flip ? last - k : k]))
        this.weldedSeams++
      }))
    }

    // A piece's own seams between its mirrored copies (fold, centre front/back,
    // crotch, sleeve underarm) join identical vertices one-to-one, so they are
    // welded — both copies share the particles — rather than stitched: a fold is
    // continuous fabric, and a stitch would leave a visible hairline.
    placed.forEach((p, pi) => {
      p.edges.forEach((e, ei) => {
        const sleeveSeam = p.region === 'sleeve' && (e.isFold || e.label === 'sleeve_seam')
        const centre = p.region !== 'sleeve' && (e.isFold || ['center_front', 'center_back', 'crotch'].includes(e.label))
        if (!sleeveSeam && !centre) return
        p.copySpecs.forEach((sA, ia) => p.copySpecs.forEach((sB, ib) => {
          if (ib <= ia) return
          const partner = sleeveSeam
            ? sA.mirrorWorld === sB.mirrorWorld && sA.frontHalf !== sB.frontHalf // front/back half of one sleeve
            : sA.mirrorWorld !== sB.mirrorWorld // right/left of the body
          if (!partner) return
          const A = edgeRef(pi, ia, ei)
          const B = edgeRef(pi, ib, ei)
          for (const v of A.verts) {
            const ra = root(A.range.start + v)
            const rb = root(B.range.start + v)
            if (ra !== rb) alias[rb] = ra
          }
        }))
      })
    })
    // Darts: the two legs of each dart (cut out of the mesh) are sewn together
    // on every copy, which is what takes the dart intake out of the waist. The
    // legs are mirror images, so they are welded vertex to vertex (leg a runs
    // base→apex, leg b apex→base); stitched if their sampling ever differs.
    placed.forEach((p, pi) => {
      p.edges.forEach((e, ei) => {
        if (e.label !== 'dart' || !e.id.endsWith(':a')) return
        const eb = p.edges.findIndex(o => o.id === `${e.id.slice(0, -2)}:b`)
        if (eb < 0) return
        p.copySpecs.forEach((_, ci) => {
          const A = edgeRef(pi, ci, ei)
          const B = edgeRef(pi, ci, eb)
          if (A.verts.length !== B.verts.length) {
            stitch(A, B)
            return
          }
          A.verts.forEach((v, k) => {
            const ra = root(A.range.start + v)
            const rb = root(B.range.start + B.verts[B.verts.length - 1 - k])
            if (ra !== rb) alias[rb] = ra
          })
        })
      })
    })

    for (let i = 0; i < n; i++) alias[i] = root(i)
    this.alias = alias
    const remap = (arr: number[]) => Int32Array.from(arr, i => alias[i])
    this.di = remap(pairs)
    this.sa = remap(sa)
    this.sb = remap(sb)
    this.sw = new Float32Array(sw)

    // Tethers: each particle to its nearest (in the flat pattern) vertex on
    // the edge its piece hangs from.
    const ti: number[] = []
    const ta: number[] = []
    const tr: number[] = []
    placed.forEach((p, pi) => {
      const hangs = p.region === 'sleeve' ? ['armhole'] : p.region === 'torso-upper' ? ['shoulder'] : ['waist', 'waist_seam']
      const anchors = new Set<number>()
      p.edges.forEach((e, ei) => { if (hangs.includes(e.label)) p.mesh.edgeVerts[ei].forEach(v => anchors.add(v)) })
      if (!anchors.size) return
      const list = [...anchors]
      const { pts } = p.mesh
      const nearest = pts.map((q, i) => {
        let best = list[0]
        let bd = Infinity
        for (const a of list) {
          const d = Math.hypot(pts[a][0] - q[0], pts[a][1] - q[1])
          if (d < bd) { bd = d; best = a }
        }
        return anchors.has(i) || bd < TETHER_MIN ? null : { a: best, d: bd }
      })
      for (const r of this.ranges.filter(r => r.piece === pi)) {
        nearest.forEach((m, i) => {
          if (!m) return
          ti.push(r.start + i)
          ta.push(r.start + m.a)
          tr.push(m.d * TETHER_SLACK)
        })
      }
    })
    this.ti = Int32Array.from(ti, i => this.alias[i])
    this.ta = Int32Array.from(ta, i => this.alias[i])
    this.tr = new Float32Array(tr)
  }

  step(dt: number, substeps: number): void {
    const h = dt / substeps
    const damp = Math.pow(DAMPING_PER_SECOND, h)
    const { x, prev, v, n } = this
    for (let s = 0; s < substeps; s++) {
      for (let i = 0; i < n; i++) {
        const k = i * 3
        v[k + 1] -= GRAVITY * h
        v[k] *= damp
        v[k + 1] *= damp
        v[k + 2] *= damp
        prev[k] = x[k]
        prev[k + 1] = x[k + 1]
        prev[k + 2] = x[k + 2]
        x[k] += v[k] * h
        x[k + 1] += v[k + 1] * h
        x[k + 2] += v[k + 2] * h
      }
      this.solveDistances(false)
      this.solveStitches()
      this.solveTethers()
      this.solveDistances(true)
      // Two passes: where contacts meet (foot and floor) one push can undo another.
      this.collide()
      this.collide()
      this.syncWelds()
      for (let k = 0; k < n * 3; k++) v[k] = (x[k] - prev[k]) / h
    }
  }

  // All distance constraints; or, with strainLimitOnly, just a pass that pulls
  // over-stretched fabric edges back (fabric may buckle, but barely stretches).
  private solveDistances(strainLimitOnly: boolean): void {
    const { x, di, dr, dk } = this
    for (let c = 0; c < dr.length; c++) {
      if (strainLimitOnly && dk[c] !== STRETCH) continue
      const a = di[c * 2] * 3
      const b = di[c * 2 + 1] * 3
      const dx = x[b] - x[a]
      const dy = x[b + 1] - x[a + 1]
      const dz = x[b + 2] - x[a + 2]
      const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
      if (len < 1e-9) continue
      const err = len - dr[c]
      if (strainLimitOnly && err <= 0) continue
      const k = err < 0 && dk[c] === STRETCH ? COMPRESS : dk[c]
      const f = (k * err) / len / 2
      x[a] += dx * f
      x[a + 1] += dy * f
      x[a + 2] += dz * f
      x[b] -= dx * f
      x[b + 1] -= dy * f
      x[b + 2] -= dz * f
    }
  }

  private solveStitches(): void {
    const { x, sa, sb, sw } = this
    for (let c = 0; c < sw.length; c++) {
      const a = sa[c] * 3
      const b0 = sb[c * 2] * 3
      const b1 = sb[c * 2 + 1] * 3
      const w = sw[c]
      for (let d = 0; d < 3; d++) {
        const target = x[b0 + d] * (1 - w) + x[b1 + d] * w
        const err = (target - x[a + d]) * STITCH
        // Split the correction between the particle and the edge point.
        x[a + d] += err * 0.5
        x[b0 + d] -= err * 0.5 * (1 - w)
        x[b1 + d] -= err * 0.5 * w
      }
    }
  }

  // Unilateral: only a particle farther than its tether length moves (toward
  // its anchor); the anchor is supported by the body and stays put.
  // Welded particles follow the particle they are welded to.
  private syncWelds(): void {
    const { x, prev, alias } = this
    for (let i = 0; i < alias.length; i++) {
      const r = alias[i]
      if (r === i) continue
      for (let d = 0; d < 3; d++) {
        x[i * 3 + d] = x[r * 3 + d]
        prev[i * 3 + d] = prev[r * 3 + d]
      }
    }
  }

  private solveTethers(): void {
    const { x, ti, ta, tr } = this
    for (let c = 0; c < tr.length; c++) {
      const i = ti[c] * 3
      const a = ta[c] * 3
      const dx = x[i] - x[a]
      const dy = x[i + 1] - x[a + 1]
      const dz = x[i + 2] - x[a + 2]
      const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
      if (len <= tr[c]) continue
      const f = (len - tr[c]) / len
      x[i] -= dx * f
      x[i + 1] -= dy * f
      x[i + 2] -= dz * f
    }
  }

  private collide(): void {
    const { x, body, normal, n } = this
    for (let i = 0; i < n; i++) {
      const k = i * 3
      if (x[k + 1] < CLOTH_THICKNESS) {
        const push = CLOTH_THICKNESS - x[k + 1]
        x[k + 1] = CLOTH_THICKNESS
        normal[0] = 0
        normal[1] = 1
        normal[2] = 0
        this.friction(k, push)
      }
      const d = body.sample(x[k], x[k + 1], x[k + 2])
      if (d >= CLOTH_THICKNESS) continue
      body.normal(x[k], x[k + 1], x[k + 2], normal)
      const push = CLOTH_THICKNESS - d
      x[k] += normal[0] * push
      x[k + 1] += normal[1] * push
      x[k + 2] += normal[2] * push
      this.friction(k, push)
    }
  }

  // Coulomb friction on this substep's sliding along the contact (Macklin et
  // al.): slip smaller than μs × the normal push is cancelled entirely (static
  // friction — fabric rests on shoulders and hips instead of being ratcheted
  // down by the push-out), larger slip is reduced by μk × the push.
  private friction(k: number, push: number): void {
    const { x, prev, normal } = this
    const mx = x[k] - prev[k]
    const my = x[k + 1] - prev[k + 1]
    const mz = x[k + 2] - prev[k + 2]
    const mn = mx * normal[0] + my * normal[1] + mz * normal[2]
    const tx = mx - mn * normal[0]
    const ty = my - mn * normal[1]
    const tz = mz - mn * normal[2]
    const slip = Math.sqrt(tx * tx + ty * ty + tz * tz)
    if (slip < 1e-12) return
    const f = slip < STATIC_FRICTION * push ? 1 : Math.min(1, (KINETIC_FRICTION * push) / slip)
    x[k] -= tx * f
    x[k + 1] -= ty * f
    x[k + 2] -= tz * f
  }

  // Do two particles share one simulated particle (welded)?
  welded(a: number, b: number): boolean {
    const root = (i: number) => {
      while (this.alias[i] !== i) i = this.alias[i]
      return i
    }
    return root(a) === root(b)
  }

  kineticEnergy(): number {
    let e = 0
    for (let k = 0; k < this.v.length; k++) e += this.v[k] * this.v[k]
    return 0.5 * e / Math.max(this.n, 1)
  }

  // Distance between each stitched particle and its target on the other edge (cm).
  stitchGaps(): number[] {
    const { x, sa, sb, sw } = this
    const out: number[] = []
    for (let c = 0; c < sw.length; c++) {
      const a = sa[c] * 3
      const b0 = sb[c * 2] * 3
      const b1 = sb[c * 2 + 1] * 3
      const w = sw[c]
      out.push(Math.hypot(
        x[b0] * (1 - w) + x[b1] * w - x[a],
        x[b0 + 1] * (1 - w) + x[b1 + 1] * w - x[a + 1],
        x[b0 + 2] * (1 - w) + x[b1 + 2] * w - x[a + 2],
      ))
    }
    return out
  }

  // Stretch (current ÷ flat length − 1) of every fabric edge whose particles
  // both have a per-particle value ≥ min (e.g. fit-map ease: only where the
  // pattern fits the body).
  edgeStretch(perParticle: Float32Array, min: number): number[] {
    const { x, di, dr, dk } = this
    const out: number[] = []
    for (let c = 0; c < dr.length; c++) {
      if (dk[c] !== STRETCH || dr[c] < 1e-6) continue
      const i = di[c * 2]
      const j = di[c * 2 + 1]
      if (perParticle[i] < min || perParticle[j] < min) continue
      out.push(Math.hypot(x[j * 3] - x[i * 3], x[j * 3 + 1] - x[i * 3 + 1], x[j * 3 + 2] - x[i * 3 + 2]) / dr[c] - 1)
    }
    return out
  }

  positionsOf(r: CopyRange): Float32Array {
    return this.x.slice(r.start * 3, (r.start + r.count) * 3)
  }
}

export const DRAPE = { dt: 1 / 60, substeps: 16, steps: 150 }
