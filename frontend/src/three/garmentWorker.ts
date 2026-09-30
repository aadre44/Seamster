import { proceduralBodyQuery } from './bodyQuery'
import { buildBodySdf } from './bodySdf'
import { Cloth, DRAPE } from './clothSim'
import { placeGarment } from './garmentWrap'
import type { PlacedPiece } from './garmentWrap'
import { SdfGrid } from './sdfGrid'
import type { CanvasElement, PatternPiece, Placement, SeamConnection } from '../types'
import type { ResolvedBody } from './types'
import { seamParts } from './pieceGeometry'

export interface GarmentJob {
  id: number
  body: ResolvedBody
  pieces: PatternPiece[]
  elements: CanvasElement[]
  connections: SeamConnection[]
  placements: Placement[]
  drape: boolean
}

export interface GarmentCopyData { positions: Float32Array; indices: Uint32Array; ease: Float32Array }

// seams: the piece's sewn edges (vertex indices along each, same for every copy),
// drawn as stitch lines so you can see they stay joined.
export interface GarmentPieceData { id: string; name: string; layer: 'outer' | 'inside'; copies: GarmentCopyData[]; seams: number[][] }

// A piece edge is drawn as a seam when it is sewn: to another piece (a
// connection — including the parts an edge was split into by darts), a dart
// leg, or the piece's own centre / crotch / underarm seam. Folds are not seams.
function seamEdges(p: PlacedPiece, connections: SeamConnection[]): number[][] {
  const sewn = new Set<number>(p.stitchedEdges ?? []) // a placed piece's stitched edges
  for (const c of connections) {
    for (const end of [c.from, c.to]) {
      if (end.pieceId === p.id) seamParts(p.edges, end).forEach(i => sewn.add(i))
    }
  }
  const out: number[][] = []
  p.edges.forEach((e, i) => {
    if (e.isFold) return
    const own = e.label === 'dart' || e.label === 'sleeve_seam' || ['center_front', 'center_back', 'crotch'].includes(e.label)
    if (sewn.has(i) || own) out.push(p.mesh.edgeVerts[i])
  })
  return out
}

// 'placed': the static wrap (topology + ease); 'frame': new cloth positions
// for the same copies while draping; `done` marks the last message of a job.
export type GarmentMessage =
  | {
      kind: 'placed'
      id: number
      pieces: GarmentPieceData[]
      skipped: { id: string; name: string; reason: string }[]
      done: boolean
    }
  | { kind: 'frame'; id: number; step: number; positions: Float32Array[][]; done: boolean }
  | { kind: 'error'; id: number; error: string; done: true }

const FRAME_EVERY = 6
let latest = 0
let gridCache: { key: string; grid: SdfGrid } | null = null

function gridFor(body: ResolvedBody): SdfGrid {
  const key = JSON.stringify(body)
  if (gridCache?.key !== key) {
    const { sdf, bounds } = buildBodySdf(body)
    gridCache = { key, grid: new SdfGrid(sdf, bounds) }
  }
  return gridCache.grid
}

const post = (m: GarmentMessage, transfer: Transferable[] = []) => (self as unknown as Worker).postMessage(m, transfer)
const yieldToMessages = () => new Promise(resolve => setTimeout(resolve, 0))

// Placement then (optionally) draping, off the UI thread. A drape runs in
// slices and is abandoned as soon as a newer job arrives.
self.onmessage = async (e: MessageEvent<GarmentJob>) => {
  const job = e.data
  latest = job.id
  try {
    const { placed, skipped } = placeGarment(job.pieces, job.elements, proceduralBodyQuery(job.body), job.connections, job.placements)
    const pieces: GarmentPieceData[] = placed.map(p => ({
      id: p.id,
      name: p.name,
      layer: p.layer,
      copies: p.copies.map(c => ({ ...c, positions: c.positions.slice() })),
      seams: seamEdges(p, job.connections),
    }))
    post({ kind: 'placed', id: job.id, pieces, skipped, done: !job.drape || placed.length === 0 },
      pieces.flatMap(p => p.copies.flatMap(c => [c.positions.buffer, c.indices.buffer, c.ease.buffer])))
    if (!job.drape || placed.length === 0) return

    await yieldToMessages()
    if (job.id !== latest) return
    const cloth = new Cloth(placed, job.connections, gridFor(job.body))
    for (let step = 1; step <= DRAPE.steps; step++) {
      cloth.step(DRAPE.dt, DRAPE.substeps)
      const done = step === DRAPE.steps
      if (step % FRAME_EVERY === 0 || done) {
        const positions = placed.map((_, pi) => cloth.ranges.filter(r => r.piece === pi).map(r => cloth.positionsOf(r)))
        post({ kind: 'frame', id: job.id, step, positions, done }, positions.flatMap(p => p.map(a => a.buffer)))
        await yieldToMessages()
        if (job.id !== latest) return
      }
    }
  } catch (err) {
    post({ kind: 'error', id: job.id, error: err instanceof Error ? err.message : String(err), done: true })
  }
}
